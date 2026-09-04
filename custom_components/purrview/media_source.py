"""media_source platform for PurrView: browse and play recorded events (WP-4 step 3).

Tree, from HA_INTEGRATION_PLAN.md:
    By camera  -> <Camera>  -> <Rule>   -> <Day> -> event
    By subject -> <Subject> -> <Camera> -> <Day> -> event
    By type    -> <Rule>    -> <Camera> -> <Day> -> event
    Recent     -> event

Every "By X" grouping is the same shape below its first level - fix one
WatchEventQuery dimension, list the next one, then list days, then list events -
so one pair of helpers (_browse_dimension / _browse_days) serves all three rather
than tripling the logic. Only "Recent" skips straight to events.

Identifiers are "/"-joined: "<entry_id>/<grouping>/<value>/<next_value>/<day>".
Leaves are always "<entry_id>/event/<event_uuid>" regardless of which branch
reached them - async_resolve_media only ever needs the event uuid, and giving
every leaf the same shape means resolve doesn't have to re-parse the branch
that produced it.

Each browse call is independent - HA does not carry state from a parent node to
its children across separate calls - so a value's display name (e.g. a camera's
name for its source_uuid) has to be re-resolved from the identifier alone at
every level that needs it, not passed down from whoever listed it first.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.components.media_source.error import Unresolvable
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import PurrViewApiError, PurrViewClient, configured_clients
from .const import DOMAIN

#: How far back "Recent" and the Day-level history search look. PurrView's histogram
#: endpoint reports its own bucket resolution rather than truncating for a wide range
#: (see PurrViewClient.histogram), so a too-wide window costs an honest wide answer,
#: never a silently wrong one - this just keeps typical browsing fast.
_HISTORY_WINDOW = timedelta(days=90)
_RECENT_LIMIT = 100

#: grouping keyword -> (field fixed at level 2, field fixed at level 3).
_GROUPINGS: dict[str, tuple[str, str]] = {
    "by_camera": ("source_uuid", "rule_uuid"),
    "by_subject": ("subject_ref", "source_uuid"),
    "by_type": ("rule_uuid", "source_uuid"),
}
_GROUPING_TITLES = {"by_camera": "By camera", "by_subject": "By subject", "by_type": "By type"}
#: Which facets() list carries a field's {ref, name} pairs.
_FACET_KEY_FOR_FIELD = {"source_uuid": "sources", "rule_uuid": "rules", "subject_ref": "subjects"}
#: A field's own name is what PurrView's query params use (WatchEventQuery's __init__
#: params are read as literal, un-aliased FastAPI query params - snake_case, verified
#: against the real API). But WatchEventGroup/WatchEventHistogramBucket are Pydantic
#: response models with alias_generator=to_camel, so *reading a row back* needs the
#: camelCase wire name instead - confirmed live against real event data after an
#: all-camelCase assumption in the query-building code silently leaked into reading
#: responses too, and this repo's own mock-fixture tests didn't catch it because the
#: fixtures shared the same wrong assumption.
_RESPONSE_KEY_FOR_FIELD = {"source_uuid": "sourceUuid", "rule_uuid": "ruleUuid", "subject_ref": "subjectRef"}


async def async_get_media_source(hass: HomeAssistant) -> PurrViewMediaSource:
    return PurrViewMediaSource(hass)


class PurrViewMediaSource(MediaSource):
    """Exposes every configured PurrView instance's recorded events to HA's media browser."""

    name = "PurrView"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    def _client(self, entry_id: str) -> PurrViewClient:
        client = configured_clients(self.hass).get(entry_id)
        if client is None:
            raise Unresolvable(f"Unknown PurrView config entry '{entry_id}'")
        return client

    # ---- browsing ----------------------------------------------------------

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        parts = item.identifier.split("/") if item.identifier else []

        if not parts:
            entries = configured_clients(self.hass)
            if not entries:
                raise Unresolvable("No PurrView instance is configured")
            if len(entries) == 1:
                return await self._browse_root(next(iter(entries)))
            children = [self._folder(entry_id, client.host) for entry_id, client in entries.items()]
            return self._folder("", "PurrView", children=children)

        entry_id = parts[0]
        client = self._client(entry_id)

        if len(parts) == 1:
            return await self._browse_root(entry_id)

        grouping = parts[1]
        if grouping == "recent":
            if len(parts) != 2:
                raise Unresolvable(f"Malformed PurrView media identifier: {item.identifier}")
            return await self._browse_recent(entry_id, client)

        if grouping not in _GROUPINGS:
            raise Unresolvable(f"Unknown PurrView media grouping '{grouping}'")
        level2_field, level3_field = _GROUPINGS[grouping]

        if len(parts) == 2:
            return await self._browse_dimension(
                client, prefix=f"{entry_id}/{grouping}", title=_GROUPING_TITLES[grouping], field=level2_field
            )

        value = parts[2]
        if len(parts) == 3:
            title = await self._name_for(client, level2_field, value)
            return await self._browse_dimension(
                client,
                prefix=f"{entry_id}/{grouping}/{value}",
                title=title,
                field=level3_field,
                base_filters={level2_field: value},
            )

        next_value = parts[3]
        filters = {level2_field: value, level3_field: next_value}
        if len(parts) == 4:
            title = await self._name_for(client, level3_field, next_value)
            return await self._browse_days(
                client, prefix=f"{entry_id}/{grouping}/{value}/{next_value}", title=title, filters=filters
            )

        if len(parts) == 5:
            day = parts[4]
            return await self._browse_events(
                entry_id, client, prefix=f"{entry_id}/{grouping}/{value}/{next_value}/{day}", day=day, filters=filters
            )

        raise Unresolvable(f"PurrView media identifier too deep: {item.identifier}")

    async def _browse_root(self, entry_id: str) -> BrowseMediaSource:
        children = [self._folder(f"{entry_id}/{key}", title) for key, title in _GROUPING_TITLES.items()]
        children.append(self._folder(f"{entry_id}/recent", "Recent"))
        return self._folder(entry_id, "PurrView", children=children)

    async def _browse_dimension(
        self, client: PurrViewClient, *, prefix: str, title: str, field: str, base_filters: dict | None = None
    ) -> BrowseMediaSource:
        """One level of the tree below a grouping's root: distinct values of `field`
        among events matching `base_filters`, each becoming a child folder.

        Sourced from list_groups (history), not from every rule/camera/subject that
        exists in config - a rule that has never fired should not offer an empty
        folder, the same reasoning PurrView's own facets endpoint documents.
        """
        groups = await client.list_groups(**(base_filters or {}))
        response_key = _RESPONSE_KEY_FOR_FIELD[field]
        counts: dict[str, int] = defaultdict(int)
        for row in groups:
            value = row.get(response_key)
            if value:
                counts[value] += row.get("count", 0)

        names = await self._names_for(client, field)
        children = [
            self._folder(f"{prefix}/{value}", f"{names.get(value, value)} ({count})")
            for value, count in sorted(counts.items(), key=lambda kv: names.get(kv[0], kv[0]).lower())
        ]
        return self._folder(prefix, title, children=children)

    async def _browse_days(
        self, client: PurrViewClient, *, prefix: str, title: str, filters: dict
    ) -> BrowseMediaSource:
        """Distinct local calendar days with at least one matching event, newest first."""
        window_start = dt_util.utcnow() - _HISTORY_WINDOW
        _, buckets = await client.histogram(bucket="hour", start_from=window_start, **filters)

        counts: dict[str, int] = defaultdict(int)
        for bucket in buckets:
            started = dt_util.parse_datetime(bucket["bucketStart"])
            if started is None:
                continue
            # bucketStart carries no offset (PurrView stores it as UTC-naive) - told so
            # explicitly before as_local can mean anything. Composed from UTC *hour*
            # buckets rather than trusting PurrView's own day buckets: bucket resolution
            # can silently coarsen from hour to day server-side for a wide filter (see
            # PurrViewClient.histogram's docstring), and only hour buckets are exact
            # once re-aggregated into a local day.
            local_day = dt_util.as_local(started.replace(tzinfo=dt_util.UTC)).date()
            counts[local_day.isoformat()] += bucket.get("count", 0)

        children = [
            self._folder(f"{prefix}/{day}", f"{day} ({count})") for day, count in sorted(counts.items(), reverse=True)
        ]
        return self._folder(prefix, title, children=children)

    async def _browse_events(
        self, entry_id: str, client: PurrViewClient, *, prefix: str, day: str, filters: dict
    ) -> BrowseMediaSource:
        start_of_day = dt_util.start_of_local_day(dt_util.parse_date(day))
        events, _ = await client.list_events(
            start_from=dt_util.as_utc(start_of_day),
            start_to=dt_util.as_utc(start_of_day + timedelta(days=1)),
            limit=200,
            **filters,
        )
        children = [self._event_leaf(entry_id, e) for e in events if _has_playable_clip(e)]
        return self._folder(prefix, day, children=children)

    async def _browse_recent(self, entry_id: str, client: PurrViewClient) -> BrowseMediaSource:
        events, _ = await client.list_events(limit=_RECENT_LIMIT)
        children = [self._event_leaf(entry_id, e) for e in events if _has_playable_clip(e)]
        return self._folder(f"{entry_id}/recent", "Recent", children=children)

    async def _names_for(self, client: PurrViewClient, field: str) -> dict[str, str]:
        facets = await client.get_facets()
        return {f["ref"]: f["name"] for f in facets.get(_FACET_KEY_FOR_FIELD[field], [])}

    async def _name_for(self, client: PurrViewClient, field: str, value: str) -> str:
        return (await self._names_for(client, field)).get(value, value)

    # ---- node builders -------------------------------------------------------

    def _folder(
        self, identifier: str, title: str, *, children: list[BrowseMediaSource] | None = None
    ) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.VIDEO,
            title=title,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.VIDEO,
        )

    def _event_leaf(self, entry_id: str, event: dict) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{entry_id}/event/{event['uuid']}",
            media_class=MediaClass.VIDEO,
            media_content_type=MediaType.VIDEO,
            title=_event_title(event),
            can_play=True,
            can_expand=False,
            # Routed through our own proxy, not PurrView's raw URL - unauthenticated
            # and LAN-only otherwise, same reasoning as the recording itself (WP-4).
            thumbnail=f"/api/purrview/{entry_id}/snapshot/{event['uuid']}" if event.get("hasSnapshot") else None,
        )

    # ---- resolving -------------------------------------------------------

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        parts = item.identifier.split("/")
        if len(parts) != 3 or parts[1] != "event":
            raise Unresolvable(f"Not a playable PurrView media identifier: {item.identifier}")
        entry_id, _, event_uuid = parts
        client = self._client(entry_id)

        try:
            event = await client.get_event(event_uuid)
        except PurrViewApiError as err:
            raise Unresolvable(str(err)) from err
        if event is None:
            raise Unresolvable(f"PurrView event '{event_uuid}' no longer exists")

        recording_uuid = _clip_recording_uuid(event)
        if recording_uuid is None:
            raise Unresolvable(f"PurrView event '{event_uuid}' has no playable recording")

        # A plain relative path, deliberately unsigned here: HA's own media_source
        # websocket resolve handler runs every PlayMedia.url through
        # async_process_play_media_url before handing it to a player or cast device -
        # signing it again here would be redundant, not more correct.
        return PlayMedia(url=f"/api/purrview/{entry_id}/recording/{recording_uuid}", mime_type="video/mp4")


def _has_playable_clip(event: dict) -> bool:
    return _clip_recording_uuid(event) is not None


def _clip_recording_uuid(event: dict) -> str | None:
    for recording in event.get("recordings", []):
        if recording.get("kind") == "clip" and recording.get("status") == "complete":
            return recording.get("uuid")
    return None


def _event_title(event: dict) -> str:
    started = dt_util.parse_datetime(event.get("startedAt") or "")
    when = dt_util.as_local(started.replace(tzinfo=dt_util.UTC)).strftime("%H:%M") if started else "?"
    who = event.get("subjectName") or event.get("ruleName") or "Event"
    return f"{when} — {who}"
