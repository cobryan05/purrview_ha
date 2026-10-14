"""Thin async client for one PurrView instance's HTTP API.

Every call goes through Home Assistant's shared aiohttp session
(async_get_clientsession) - this class owns no connection of its own, matching how
HA integrations are expected to behave. JSON calls only; the proxy view (proxy.py)
does its own raw request forwarding for recordings and images, since a `<video>`
element needs the response streamed and Range-aware, not decoded as JSON.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN


def _stringify(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _query_params(filters: dict[str, Any]) -> list[tuple[str, Any]]:
    """Drop unset filters, stringify datetimes, and repeat the key for a list value.

    aiohttp would otherwise str() a datetime as "2026-09-04 12:00:00+00:00" - valid to
    Python, but not the canonical isoformat FastAPI's own parsing is guaranteed to
    accept. None values are dropped rather than sent as the literal string "None",
    which is how an optional UI filter (e.g. "any camera") gets composed here.

    A list of tuples, not a dict - `WatchEventQuery`'s multi-select filters
    (`source_uuids`, `rule_uuids`, ...) are FastAPI `Query(None)` lists, which read
    off *repeated* query keys (`?source_uuids=a&source_uuids=b`), not one key holding
    a comma-joined string. A dict can only hold one value per key, so a list-valued
    filter here is expanded into one tuple per item instead.
    """
    params: list[tuple[str, Any]] = []
    for key, value in filters.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            params.extend((key, _stringify(item)) for item in value)
        else:
            params.append((key, _stringify(value)))
    return params


class PurrViewApiError(Exception):
    """PurrView was reached, but answered with status == "failure"."""


class PurrViewAuthError(PurrViewApiError):
    """PurrView refused the credential this client holds.

    A subclass, so the `except PurrViewApiError` handlers throughout this integration
    keep catching it; distinguishable, so a caller that wants to say "re-enter the
    token" can tell it apart from "PurrView rejected the request".
    """


#: Statuses PurrView's AuthGate answers a refused request with. A non-HTML caller gets
#: a 401; a page request gets a 303 to the login form, which is why redirects are not
#: followed below - following one hands `json()` a page of HTML.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

#: Redirects worth following. One is enough for the only kind PurrView issues on an
#: API route: FastAPI's 307 from a collection path to its trailing-slash form. The
#: login bounce is caught by rejected_credential before this is consulted, which is
#: why following a redirect at all is safe here.
_MAX_REDIRECTS = 1


def rejected_credential(resp: Any) -> bool:
    if resp.status in (401, 403):
        return True
    if resp.status not in _REDIRECT_STATUSES:
        return False
    return "/login" in (resp.headers.get("location") or "")


#: What get_running_watcher_tasks filters task-instance listings down to. Mirrors
#: the app's own NVR pane (see WATCHER_TYPENAME / LIVE_STATUSES in
#: apps/image_tagging_server/static/js/app/nvr/main.js) - a stopped watcher's
#: instance row is retained after it stops, so status has to be checked too, not
#: just typename.
_WATCHER_TYPENAME = "StreamWatcherTask"
_LIVE_STATUSES = frozenset({"running", "pending", "paused"})


class PurrViewClient:
    """Talks to one PurrView instance's HTTP API (image_tagging_server, port 7999 by default)."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        token: str | None = None,
        use_ssl: bool = False,
        verify_ssl: bool = True,
        entry: ConfigEntry | None = None,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self.host = host
        self.port = port
        self.token = token or None
        self.use_ssl = use_ssl
        self.verify_ssl = verify_ssl

    @property
    def base_url(self) -> str:
        return f"{'https' if self.use_ssl else 'http'}://{self.host}:{self.port}"

    @property
    def session(self) -> ClientSession:
        """The shared session matching this instance's certificate policy.

        `verify_ssl=False` returns a second shared session rather than disabling
        verification on HA's default one, so this entry's self-signed certificate
        cannot weaken any other integration's requests.
        """
        return async_get_clientsession(self._hass, verify_ssl=self.verify_ssl)

    async def async_check_credentials(self) -> None:
        """Raise if PurrView is unreachable, or refuses the token this client holds.

        Redirects are not followed: a refused page request is a 303 to PurrView's
        login form, and following it lands on a 200 that says nothing about the
        credential. Raises PurrViewAuthError on refusal; OSError/TimeoutError reach
        the caller unchanged, so "wrong token" and "no route to host" stay apart.
        """
        async with asyncio.timeout(10):
            async with self.session.get(
                f"{self.base_url}/", headers=self.auth_headers(), allow_redirects=False
            ) as resp:
                if rejected_credential(resp):
                    raise PurrViewAuthError(self._refused_message())

    def auth_headers(self) -> dict[str, str]:
        """Headers to attach to a request.

        Empty when no token is configured - matches AuthGate on the PurrView side
        treating an absent token as "auth is off", not as a credential to check.
        """
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _redirect_target(self, resp: Any) -> str:
        """The configured origin plus the path and query PurrView redirected to.

        Only the path is taken from the Location. A redirect can therefore never move
        a request - and the token it carries - to another host, and a PurrView behind
        a TLS proxy that answers with an http:// Location stays on https.
        """
        location = resp.headers.get("location") or ""
        split = urlsplit(location)
        target = split.path or "/"
        if split.query:
            target = f"{target}?{split.query}"
        return f"{self.base_url}{target}"

    def _refused_message(self) -> str:
        return (
            "PurrView refused the configured access token"
            if self.token
            else "PurrView requires an access token and none is configured"
        )

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {**self.auth_headers(), **kwargs.pop("headers", {})}
        kwargs.setdefault("allow_redirects", False)
        url = f"{self.base_url}{path}"

        for _ in range(_MAX_REDIRECTS + 1):
            async with self.session.request(method, url, headers=headers, **kwargs) as resp:
                if rejected_credential(resp):
                    # Nothing here polls PurrView, so a refused call is the only moment
                    # the integration learns a token has been rotated. HA drops repeat
                    # flows for an entry that already has one open, so this can fire per
                    # failed call.
                    if self._entry is not None:
                        self._entry.async_start_reauth(self._hass)
                    raise PurrViewAuthError(self._refused_message())
                if resp.status in _REDIRECT_STATUSES:
                    url = self._redirect_target(resp)
                    # The query survives in the Location; sending it again as well would
                    # duplicate every filter.
                    kwargs.pop("params", None)
                    continue
                resp.raise_for_status()
                data = await resp.json()
                break
        else:
            raise PurrViewApiError(f"PurrView kept redirecting {method} {path}")
        # PurrView's response envelope is {"status": "success"|"failure", "message": ...}
        # on top of a 200 - PurrView reports a validation error in the body, not the
        # status code, so a "failure" envelope has to fail the call the same way a
        # transport error does, or callers would treat a rejected request as a success.
        if data.get("status") == "failure":
            raise PurrViewApiError(data.get("message") or f"PurrView rejected {method} {path}")
        return data

    async def get_facets(self) -> dict[str, list[dict[str, str]]]:
        """`{rules, subjects, targets, sources}`, each a list of `{ref, name}`.

        Derived from event history, not config - a rule that has never fired will not
        appear here yet. Documented behaviour, not a bug.
        """
        data = await self._request_json("GET", "/api/watch-events/facets")
        return {key: data.get(key, []) for key in ("rules", "subjects", "targets", "sources")}

    async def list_labels(self) -> list[dict[str, Any]]:
        """The whole label tree, as `{uuid, name, color, parentUuid, ...}` rows.

        The facets above name a subject/target by ref, and (bar motion zones, which
        live in the watcher profile) every one of those refs is a label uuid. A ref on
        its own says nothing about where it sits in the tree, so a filter bar that
        wants to offer "any bowl" has to fetch the tree itself.
        """
        data = await self._request_json("GET", "/api/labels")
        return data.get("labels", [])

    async def list_events(self, *, limit: int = 200, offset: int = 0, **filters: Any) -> tuple[list[dict], int]:
        """One page of `list_watch_events`, plus the total for that filter set.

        `filters` are the `WatchEventQuery` names PurrView itself uses (`source_uuid`,
        `rule_uuid`, `start_from`, ...) - passed straight through as query params so
        this file does not have to know every filter PurrView adds in the future.
        """
        params = _query_params(filters)
        params.append(("limit", limit))
        params.append(("offset", offset))
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
        params.append(("bucket", bucket))
        data = await self._request_json("GET", "/api/watch-events/histogram", params=params)
        return data.get("bucket", bucket), data.get("buckets", [])

    async def get_event(self, event_uuid: str) -> dict[str, Any] | None:
        try:
            data = await self._request_json("GET", f"/api/watch-events/{event_uuid}")
        except PurrViewApiError:
            return None
        return data.get("event")

    async def flag_event(self, event_uuid: str, reason: str, note: str = "", flagged: bool = True) -> None:
        """Sets review_state to "flagged"; reason/note live under metadata_json.flag.

        `flagged=False` reverses an accidental flag: review_state goes back to
        "unreviewed" (there is no prior state to restore to - flagging already
        discards whatever review_state held before it) and metadata_json.flag is
        dropped so a re-flag doesn't inherit a stale reason/note.

        Read-modify-write, not a bare PATCH carrying only `metadataJson`: that field
        replaces the whole column server-side, and an event can already carry other
        metadata this call has no business erasing.
        """
        event = await self.get_event(event_uuid)
        metadata = dict((event or {}).get("metadataJson") or {})
        if flagged:
            metadata["flag"] = {"reason": reason, "note": note, "source": "home_assistant"}
            review_state = "flagged"
        else:
            metadata.pop("flag", None)
            review_state = "unreviewed"
        await self._request_json(
            "PATCH",
            f"/api/watch-events/{event_uuid}",
            json={"reviewState": review_state, "metadataJson": metadata},
        )

    async def set_event_pinned(self, event_uuid: str, pinned: bool) -> None:
        """Pin or unpin an event's video against PurrView's storage-quota/retention
        cleanup, and against delete (single or bulk) until it is unpinned again.

        Unlike `flag_event`, a plain PATCH is enough — `pinned` is a real top-level
        column on the PurrView side (`WatchEvent.pinned`), not something folded into
        `metadata_json`, so there is nothing else on the row this could clobber.
        """
        await self._request_json("PATCH", f"/api/watch-events/{event_uuid}", json={"pinned": pinned})

    async def list_watch_profiles(self) -> list[dict[str, Any]]:
        """Every configured watch profile, as `[{"uuid", "name", "enabled"}]`.

        Backs the Lovelace card's config editor, so a viewer picks a camera/watcher
        by name instead of hand-typing a profile uuid dug out of the API or HA's own
        storage files - the gap that made shipping the card as YAML-only impractical
        for anyone but its own author.
        """
        data = await self._request_json("GET", "/api/watch-profiles")
        return [{"uuid": p["uuid"], "name": p["name"], "enabled": p.get("enabled", True)} for p in data.get("profiles", [])]

    async def get_watch_profile_sources(self, profile_uuid: str) -> list[dict[str, str]]:
        """A profile's configured cameras, as `[{"uuid", "name"}]`, in configured order.

        Backs the live-view card editor's "default camera" picker - unlike
        get_running_watcher_tasks/get_live_preview's `sources` list, this comes
        straight from the profile's own config (`WatchProfileRead.sources`), so it's
        available whether or not the watcher happens to be running while someone is
        editing the card.
        """
        profile_data = await self._request_json("GET", f"/api/watch-profiles/{profile_uuid}")
        profile = profile_data.get("profile") or {}
        links = sorted(profile.get("sources", []), key=lambda s: s.get("order", 0))

        sources_data = await self._request_json("GET", "/api/sources/get")
        names = {uuid: source.get("name", uuid) for uuid, source in sources_data.get("sources", {}).items()}

        return [
            {"uuid": link["sourceUuid"], "name": names.get(link["sourceUuid"], link["sourceUuid"])}
            for link in links
            if link.get("enabled", True)
        ]

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
            params.append(("full", "true"))
        data = await self._request_json("GET", f"/api/tasks/instances/{match['taskUuid']}/live-preview", params=params)
        return data.get("preview")

    async def set_manual_recording(
        self,
        *,
        profile_uuid: str,
        source_uuid: str,
        recording: bool,
        max_duration_s: float | None = None,
    ) -> bool:
        """Start or stop a manual recording on one camera. False if nothing is watching it.

        Routed through the watcher's command endpoint rather than a REST resource of its
        own, because the recording is state held by the running task — there is nothing
        to address when no watcher holds that source, and `False` says exactly that
        rather than inventing an error for an idle camera.

        `max_duration_s` is optional and the watcher clamps it; omitting it takes the
        profile's own default, which is the common case and what the MQTT switch does.
        """
        tasks = await self.get_running_watcher_tasks()
        match = next((t for t in tasks if t["profileUuid"] == profile_uuid), None)
        if match is None:
            return False
        params: dict[str, Any] = {"sourceUuid": source_uuid}
        if recording and max_duration_s:
            params["maxDurationS"] = float(max_duration_s)
        await self._request_json(
            "POST",
            "/api/tasks/instances/command",
            json={
                "taskUuid": match["taskUuid"],
                "command": "start_recording" if recording else "stop_recording",
                "params": params,
            },
        )
        return True


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
