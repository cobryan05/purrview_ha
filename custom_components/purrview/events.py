"""Lists and filters recorded events for the events grid Lovelace card (WP-5).

Thin passthrough onto `PurrViewClient.list_events`/`get_facets` - the card needs both
a filtered page of events and the facet options that populate its filter bar, and
neither is otherwise reachable from HA (same reasoning as proxy.py's own comment on
why a raw PurrView URL isn't an option: no auth, no LAN-independence).
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .api import PurrViewApiError, configured_clients

#: Multi-select filters the card's filter bar sends as repeated query keys
#: (`?source_uuids=a&source_uuids=b`), matching `WatchEventQuery`'s own
#: `Query(None)`-typed list params one-for-one - forwarded as-is rather than
#: collapsed to a single value, so the card can let a viewer pick more than one
#: camera/subject/event type at once.
_MULTI_FILTER_PARAMS = ("source_uuids", "rule_uuids", "subject_refs", "target_refs")

#: Everything else the card is allowed to forward. Both of these are allowlists, not
#: a passthrough of request.query - this view is reachable with only HA's own auth,
#: not PurrView's, so it must not become a way to smuggle arbitrary query params.
_SINGLE_FILTER_PARAMS = ("start_from", "start_to", "review_state")

_DEFAULT_LIMIT = 60


def _client_or_404(hass: HomeAssistant, entry_id: str):
    client = configured_clients(hass).get(entry_id)
    if client is None:
        raise web.HTTPNotFound(reason="Unknown PurrView config entry")
    return client


def _parse_filters(query) -> dict:
    filters: dict = {}
    for key in _MULTI_FILTER_PARAMS:
        values = [v for v in query.getall(key, []) if v]
        if values:
            filters[key] = values
    for key in _SINGLE_FILTER_PARAMS:
        if query.get(key):
            filters[key] = query[key]
    return filters


class PurrViewEventsView(HomeAssistantView):
    """`GET /api/purrview/{entry_id}/events` -> `{"events": [...], "total": N}`."""

    url = "/api/purrview/{entry_id}/events"
    name = "api:purrview:events"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        client = _client_or_404(self._hass, entry_id)

        filters = _parse_filters(request.query)
        try:
            limit = int(request.query.get("limit", _DEFAULT_LIMIT))
            offset = int(request.query.get("offset", 0))
        except ValueError as err:
            raise web.HTTPBadRequest(reason="limit/offset must be integers") from err

        try:
            events, total = await client.list_events(limit=limit, offset=offset, **filters)
        except PurrViewApiError as err:
            raise web.HTTPBadGateway(reason=str(err)) from err

        return self.json({"events": events, "total": total})


class PurrViewEventFacetsView(HomeAssistantView):
    """`GET /api/purrview/{entry_id}/event-facets` -> `{rules, subjects, targets, sources}`."""

    url = "/api/purrview/{entry_id}/event-facets"
    name = "api:purrview:event-facets"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        client = _client_or_404(self._hass, entry_id)

        try:
            facets = await client.get_facets()
        except PurrViewApiError as err:
            raise web.HTTPBadGateway(reason=str(err)) from err

        return self.json(facets)


class PurrViewEventGroupsView(HomeAssistantView):
    """`GET /api/purrview/{entry_id}/event-groups` -> `{"groups": [...]}`.

    Backs the timeline view's lanes: distinct (rule, subject, target, source)
    combinations actually present in history, each with its own count - the same
    grouping the app's own timeline swimlanes use to decide which lanes exist and how
    to label them, rather than a lane per every rule/subject that has ever been
    configured (see media_source.py's own `_browse_dimension` for the identical
    reasoning on the media-browser side).
    """

    url = "/api/purrview/{entry_id}/event-groups"
    name = "api:purrview:event-groups"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        client = _client_or_404(self._hass, entry_id)

        filters = _parse_filters(request.query)
        try:
            groups = await client.list_groups(**filters)
        except PurrViewApiError as err:
            raise web.HTTPBadGateway(reason=str(err)) from err

        return self.json({"groups": groups})


class PurrViewEventHistogramView(HomeAssistantView):
    """`GET /api/purrview/{entry_id}/event-histogram` -> `{"bucket": "hour"|"day", "buckets": [...]}`.

    Backs the timeline view's marks. `bucket` in the response is the resolution
    PurrView actually used, not necessarily the one requested - a wide date range
    gets coarsened server-side to day buckets rather than silently truncated (see
    PurrViewClient.histogram's own docstring), and the card has to know which
    resolution it got back to lay marks out correctly.
    """

    url = "/api/purrview/{entry_id}/event-histogram"
    name = "api:purrview:event-histogram"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        client = _client_or_404(self._hass, entry_id)

        filters = _parse_filters(request.query)
        bucket = request.query.get("bucket", "hour")

        try:
            resolved_bucket, buckets = await client.histogram(bucket=bucket, **filters)
        except PurrViewApiError as err:
            raise web.HTTPBadGateway(reason=str(err)) from err

        return self.json({"bucket": resolved_bucket, "buckets": buckets})
