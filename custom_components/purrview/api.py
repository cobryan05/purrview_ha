"""Thin async client for one PurrView instance's HTTP API.

Every call goes through Home Assistant's shared aiohttp session
(async_get_clientsession) - this class owns no connection of its own, matching how
HA integrations are expected to behave. JSON calls only; the proxy view (proxy.py)
does its own raw request forwarding for recordings and images, since a `<video>`
element needs the response streamed and Range-aware, not decoded as JSON.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN


def _query_params(filters: dict[str, Any]) -> dict[str, Any]:
    """Drop unset filters and stringify datetimes.

    aiohttp would otherwise str() a datetime as "2026-09-04 12:00:00+00:00" - valid to
    Python, but not the canonical isoformat FastAPI's own parsing is guaranteed to
    accept. None values are dropped rather than sent as the literal string "None",
    which is how an optional UI filter (e.g. "any camera") gets composed here.
    """
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in filters.items() if v is not None}


class PurrViewApiError(Exception):
    """PurrView was reached, but answered with status == "failure"."""


#: What get_running_watcher_tasks filters task-instance listings down to. Mirrors
#: the app's own NVR pane (see WATCHER_TYPENAME / LIVE_STATUSES in
#: apps/image_tagging_server/static/js/app/nvr/main.js) - a stopped watcher's
#: instance row is retained after it stops, so status has to be checked too, not
#: just typename.
_WATCHER_TYPENAME = "StreamWatcherTask"
_LIVE_STATUSES = frozenset({"running", "pending", "paused"})


class PurrViewClient:
    """Talks to one PurrView instance's HTTP API (image_tagging_server, port 7999 by default)."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, token: str | None = None) -> None:
        self._hass = hass
        self.host = host
        self.port = port
        self.token = token or None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def auth_headers(self) -> dict[str, str]:
        """Headers to attach to a request.

        Empty when no token is configured - matches AuthGate on the PurrView side
        treating an absent token as "auth is off", not as a credential to check.
        """
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        session = async_get_clientsession(self._hass)
        headers = {**self.auth_headers(), **kwargs.pop("headers", {})}
        async with session.request(method, f"{self.base_url}{path}", headers=headers, **kwargs) as resp:
            resp.raise_for_status()
            data = await resp.json()
        # WP-1/2's response envelope is {"status": "success"|"failure", "message": ...}
        # on top of a 200 - PurrView reports a validation error in the body, not the
        # status code, so a "failure" envelope has to fail the call the same way a
        # transport error does, or callers would treat a rejected request as a success.
        if data.get("status") == "failure":
            raise PurrViewApiError(data.get("message") or f"PurrView rejected {method} {path}")
        return data

    async def get_facets(self) -> dict[str, list[dict[str, str]]]:
        """`{rules, subjects, targets, sources}`, each a list of `{ref, name}`.

        Derived from event history, not config - a rule that has never fired will not
        appear here yet. Documented behaviour, not a bug (HA_INTEGRATION_PLAN.md WP-5).
        """
        data = await self._request_json("GET", "/api/watch-events/facets")
        return {key: data.get(key, []) for key in ("rules", "subjects", "targets", "sources")}

    async def list_events(self, *, limit: int = 200, offset: int = 0, **filters: Any) -> tuple[list[dict], int]:
        """One page of `list_watch_events`, plus the total for that filter set.

        `filters` are the `WatchEventQuery` names PurrView itself uses (`source_uuid`,
        `rule_uuid`, `start_from`, ...) - passed straight through as query params so
        this file does not have to know every filter PurrView adds in the future.
        """
        params = _query_params(filters)
        params["limit"] = limit
        params["offset"] = offset
        data = await self._request_json("GET", "/api/watch-events", params=params)
        return data.get("events", []), data.get("total", 0)

    async def list_groups(self, **filters: Any) -> list[dict]:
        """Distinct (rule, subject, target, source) combinations matching `filters`,
        each with its own count - the building block for every intermediate level of
        the media_source tree (e.g. "which rules has this camera actually fired",
        derived from history, not from every rule that exists).
        """
        data = await self._request_json("GET", "/api/watch-events/groups", params=_query_params(filters))
        return data.get("groups", [])

    async def histogram(self, *, bucket: str = "hour", **filters: Any) -> tuple[str, list[dict]]:
        """Event counts per UTC time bucket, for rolling into local-day tree nodes.

        Returns the *actual* bucket resolution used, not necessarily the one asked for:
        PurrView coarsens `hour` to `day` itself for a very wide filter, rather than
        silently truncating - see WatchEventHistogramResponse.bucket. A caller doing its
        own local-day rollup has to know when that already happened UTC-day-aligned,
        rather than re-aggregating hours that were never returned.
        """
        params = _query_params(filters)
        params["bucket"] = bucket
        data = await self._request_json("GET", "/api/watch-events/histogram", params=params)
        return data.get("bucket", bucket), data.get("buckets", [])

    async def get_event(self, event_uuid: str) -> dict[str, Any] | None:
        try:
            data = await self._request_json("GET", f"/api/watch-events/{event_uuid}")
        except PurrViewApiError:
            return None
        return data.get("event")

    async def flag_event(self, event_uuid: str, reason: str, note: str = "") -> None:
        """WP-1: sets review_state to "flagged"; reason/note live under metadata_json.flag.

        Read-modify-write, not a bare PATCH carrying only `metadataJson`: that field
        replaces the whole column server-side, and an event can already carry other
        metadata this call has no business erasing.
        """
        event = await self.get_event(event_uuid)
        metadata = dict((event or {}).get("metadataJson") or {})
        metadata["flag"] = {"reason": reason, "note": note, "source": "home_assistant"}
        await self._request_json(
            "PATCH",
            f"/api/watch-events/{event_uuid}",
            json={"reviewState": "flagged", "metadataJson": metadata},
        )

    async def list_watch_profiles(self) -> list[dict[str, Any]]:
        """Every configured watch profile, as `[{"uuid", "name", "enabled"}]`.

        Backs the Lovelace card's config editor, so a viewer picks a camera/watcher
        by name instead of hand-typing a profile uuid dug out of the API or HA's own
        storage files - the gap that made shipping the card as YAML-only impractical
        for anyone but its own author.
        """
        data = await self._request_json("GET", "/api/watch-profiles")
        return [{"uuid": p["uuid"], "name": p["name"], "enabled": p.get("enabled", True)} for p in data.get("profiles", [])]

    async def get_running_watcher_tasks(self) -> list[dict[str, str]]:
        """Every running watcher, as `[{"taskUuid": ..., "profileUuid": ...}]`.

        There is no "list running watchers" endpoint - `POST /api/tasks/instances/get`
        with no `taskUuids` returns every task instance, and this filters it exactly
        the way the app's own NVR pane does client-side (fetchRunningWatchers in
        main.js): by typename, then by an in-progress instance status, since a
        stopped watcher's instance row is retained rather than deleted.

        A profile's uuid lives at `config.params.watch_profile_uuid` - snake_case,
        unlike every *declared* field on this response, because `params` is an
        opaque `Dict[str, Any]` on the PurrView side (whatever the task itself wrote),
        never run through the `to_camel` aliasing that field names above it get.
        """
        data = await self._request_json("POST", "/api/tasks/instances/get", json={})
        running: list[dict[str, str]] = []
        for task_uuid, info in data.get("tasks", {}).items():
            config = info.get("config") or {}
            instance = info.get("instance") or {}
            if config.get("typename") != _WATCHER_TYPENAME:
                continue
            if instance.get("status") not in _LIVE_STATUSES:
                continue
            profile_uuid = (config.get("params") or {}).get("watch_profile_uuid")
            if profile_uuid:
                running.append({"taskUuid": task_uuid, "profileUuid": profile_uuid})
        return running

    async def get_live_preview(
        self,
        *,
        profile_uuid: str,
        source_uuid: str | None = None,
        since_seq: int | None = None,
        quality: int | None = None,
        full: bool = False,
    ) -> dict[str, Any] | None:
        """The running watcher's current frame plus what it sees in it.

        None when that profile isn't currently running - a normal answer, not an
        error, mirroring `fetchTaskLivePreview`'s own contract on the PurrView side
        (a stopped watcher and a profile that was never a watcher look the same).
        """
        tasks = await self.get_running_watcher_tasks()
        match = next((t for t in tasks if t["profileUuid"] == profile_uuid), None)
        if match is None:
            return None

        params = _query_params({"source_uuid": source_uuid, "since_seq": since_seq, "quality": quality})
        if full:
            params["full"] = "true"
        data = await self._request_json("GET", f"/api/tasks/instances/{match['taskUuid']}/live-preview", params=params)
        return data.get("preview")


def configured_clients(hass: HomeAssistant) -> dict[str, PurrViewClient]:
    """Every configured PurrView instance, keyed by config entry id.

    Shared by __init__.py, services.py and media_source.py rather than each
    filtering hass.data[DOMAIN] itself - that dict also carries __init__.py's
    "_view_registered" sentinel (not a real entry_id, see its own comment), and
    only this one place should have to know that isinstance check is why.
    """
    return {
        entry_id: client for entry_id, client in hass.data.get(DOMAIN, {}).items() if isinstance(client, PurrViewClient)
    }
