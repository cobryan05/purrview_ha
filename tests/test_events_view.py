"""PurrViewEventsView/PurrViewEventFacetsView: back the events grid card's filter bar
and grid, the same way test_watch_profiles_view.py covers the live-view card's editor.
"""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.setup import async_setup_component

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
#: The overlay view's path. One place, so a route change cannot leave half these
#: tests passing against the old URL.
OVERLAY_URL = "/api/purrview/entry-1/recordings/rec-1/overlay"

from custom_components.purrview.events import (
    PurrViewEventFacetsView,
    PurrViewEventsView,
    PurrViewRecordingOverlayView,
)


async def _register(
    hass,
    *,
    events=None,
    total=None,
    facets=None,
    labels=None,
    list_events_side_effect=None,
    facets_side_effect=None,
    labels_side_effect=None,
    overlay=None,
    overlay_side_effect=None,
):
    await async_setup_component(hass, "http", {})
    # spec=PurrViewClient - same reasoning as test_watch_profiles_view.py: a bare
    # MagicMock would still 404 through configured_clients()'s isinstance check.
    client = MagicMock(spec=PurrViewClient)
    if list_events_side_effect is not None:
        client.list_events = AsyncMock(side_effect=list_events_side_effect)
    else:
        client.list_events = AsyncMock(return_value=(events or [], total if total is not None else len(events or [])))
    if facets_side_effect is not None:
        client.get_facets = AsyncMock(side_effect=facets_side_effect)
    else:
        client.get_facets = AsyncMock(return_value=facets or {"rules": [], "subjects": [], "targets": [], "sources": []})
    if labels_side_effect is not None:
        client.list_labels = AsyncMock(side_effect=labels_side_effect)
    else:
        client.list_labels = AsyncMock(return_value=labels or [])
    if overlay_side_effect is not None:
        client.get_recording_overlay = AsyncMock(side_effect=overlay_side_effect)
    else:
        client.get_recording_overlay = AsyncMock(return_value=overlay)
    hass.data[DOMAIN] = {"entry-1": client}
    hass.http.register_view(PurrViewEventsView(hass))
    hass.http.register_view(PurrViewEventFacetsView(hass))
    hass.http.register_view(PurrViewRecordingOverlayView(hass))
    return client


class TestEventsHappyPath:
    async def test_returns_events_and_total(self, hass, hass_client):
        await _register(
            hass,
            events=[{"uuid": "e1", "subjectName": "Bandit"}, {"uuid": "e2", "subjectName": "Whiskers"}],
            total=5,
        )
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/events")

        assert resp.status == 200
        body = await resp.json()
        assert body["total"] == 5
        assert [e["uuid"] for e in body["events"]] == ["e1", "e2"]

    async def test_forwards_only_allowlisted_filters(self, hass, hass_client):
        purrview_client = await _register(hass, events=[])
        client = await hass_client()

        await client.get(
            "/api/purrview/entry-1/events?source_uuids=s1&subject_refs=sub1&not_a_real_filter=x&limit=10&offset=20"
        )

        purrview_client.list_events.assert_awaited_once_with(
            limit=10, offset=20, source_uuids=["s1"], subject_refs=["sub1"]
        )

    async def test_repeated_keys_become_a_multi_select_list(self, hass, hass_client):
        """The card's multi-select filter bar sends one repeated key per choice
        (?source_uuids=a&source_uuids=b), matching WatchEventQuery's own list params."""
        purrview_client = await _register(hass, events=[])
        client = await hass_client()

        await client.get("/api/purrview/entry-1/events?source_uuids=s1&source_uuids=s2")

        purrview_client.list_events.assert_awaited_once_with(limit=60, offset=0, source_uuids=["s1", "s2"])

    async def test_blank_filter_values_are_dropped(self, hass, hass_client):
        purrview_client = await _register(hass, events=[])
        client = await hass_client()

        await client.get("/api/purrview/entry-1/events?source_uuids=&rule_uuids=r1")

        purrview_client.list_events.assert_awaited_once_with(limit=60, offset=0, rule_uuids=["r1"])

    async def test_pinned_is_forwarded(self, hass, hass_client):
        """The card's Pinned filter - `pinned` is on the single-value allowlist
        alongside review_state, forwarded verbatim for PurrView's query param to parse."""
        purrview_client = await _register(hass, events=[])
        client = await hass_client()

        await client.get("/api/purrview/entry-1/events?pinned=true")

        purrview_client.list_events.assert_awaited_once_with(limit=60, offset=0, pinned="true")


    async def test_present_refs_is_forwarded(self, hass, hass_client):
        """The "Present" filter - labels catalogued anywhere inside a clip, from the
        one-to-many watch_event_labels table rather than an actor slot on the event.
        Its own allowlist entry: an omission here is silent, leaving the card with a
        dropdown whose every click returns the unfiltered set."""
        purrview_client = await _register(hass, events=[])
        client = await hass_client()

        await client.get("/api/purrview/entry-1/events?present_refs=l1&present_refs=l2")

        purrview_client.list_events.assert_awaited_once_with(limit=60, offset=0, present_refs=["l1", "l2"])

    async def test_target_refs_is_forwarded(self, hass, hass_client):
        """The "Acted on" filter, for the same reason as present_refs above."""
        purrview_client = await _register(hass, events=[])
        client = await hass_client()

        await client.get("/api/purrview/entry-1/events?target_refs=t1")

        purrview_client.list_events.assert_awaited_once_with(limit=60, offset=0, target_refs=["t1"])


class TestEventsErrors:
    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/events")

        assert resp.status == 404

    async def test_non_integer_limit_is_400(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/events?limit=not-a-number")

        assert resp.status == 400

    async def test_purrview_error_becomes_502(self, hass, hass_client):
        from custom_components.purrview.api import PurrViewApiError

        await _register(hass, list_events_side_effect=PurrViewApiError("db unavailable"))
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/events")

        assert resp.status == 502


class TestFacetsHappyPath:
    async def test_returns_facets(self, hass, hass_client):
        await _register(hass, facets={"rules": [{"ref": "r1", "name": "Intruder"}], "subjects": [], "targets": [], "sources": []})
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-facets")

        assert resp.status == 200
        assert (await resp.json())["rules"] == [{"ref": "r1", "name": "Intruder"}]


class TestFacetsPresent:
    async def test_present_facet_is_returned(self, hass, hass_client):
        """get_facets reads a fixed key list off PurrView's response, so a facet missing
        from it is dropped on the floor rather than erroring - the card then draws an
        empty "Present" dropdown with nothing to say why."""
        await _register(
            hass,
            facets={"rules": [], "subjects": [], "targets": [], "sources": [], "present": [{"ref": "l1", "name": "Bowl"}]},
        )
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-facets")

        assert (await resp.json())["present"] == [{"ref": "l1", "name": "Bowl"}]


class TestFacetsLabels:
    """The label tree rides along with the facets so the card's Subject dropdown can
    draw its refs as a tree and roll a parent up to its children."""

    async def test_labels_are_returned_alongside_the_facets(self, hass, hass_client):
        await _register(hass, labels=[{"uuid": "l1", "name": "Bowl", "parentUuid": None}])
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-facets")

        assert (await resp.json())["labels"] == [{"uuid": "l1", "name": "Bowl", "parentUuid": None}]

    async def test_a_failed_label_fetch_still_serves_the_facets(self, hass, hass_client):
        """Deliberately not the 502 a failed *facet* fetch gets: without the tree the
        card falls back to a flat list of refs, which is a degraded filter bar rather
        than no filter bar."""
        from custom_components.purrview.api import PurrViewApiError

        await _register(
            hass,
            facets={"rules": [{"ref": "r1", "name": "Intruder"}], "subjects": [], "targets": [], "sources": []},
            labels_side_effect=PurrViewApiError("labels unavailable"),
        )
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-facets")

        assert resp.status == 200
        body = await resp.json()
        assert body["labels"] == []
        assert body["rules"] == [{"ref": "r1", "name": "Intruder"}]


class TestFacetsErrors:
    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/event-facets")

        assert resp.status == 404

    async def test_purrview_error_becomes_502(self, hass, hass_client):
        from custom_components.purrview.api import PurrViewApiError

        await _register(hass, facets_side_effect=PurrViewApiError("db unavailable"))
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-facets")

        assert resp.status == 502


class TestRequiresAuth:
    async def test_events_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        await _register(hass)
        client = await hass_client_no_auth()

        resp = await client.get("/api/purrview/entry-1/events")

        assert resp.status == 401

    async def test_facets_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        await _register(hass)
        client = await hass_client_no_auth()

        resp = await client.get("/api/purrview/entry-1/event-facets")

        assert resp.status == 401


class TestRecordingOverlay:
    """Backs the clip viewer's detection-box toggle. The sidecar is fetched as JSON
    through this view rather than streamed through proxy.py: nothing hands it to a
    `<video>`, so it needs no signed URL and no Range support."""

    async def test_returns_the_sidecar(self, hass, hass_client):
        doc = {"version": 2, "durationS": 27.0, "frames": [{"t": 0.0, "boxes": []}]}
        await _register(hass, overlay=doc)
        client = await hass_client()

        resp = await client.get(OVERLAY_URL)

        assert resp.status == 200
        assert await resp.json() == doc

    async def test_a_clip_with_no_overlay_is_404_not_502(self, hass, hass_client):
        """The ordinary case, not a failure: a clip recorded before overlays existed,
        or one whose recording action had the box off, simply has no sidecar. The card
        offers no toggle, which has to stay distinguishable from PurrView being down -
        it reports the latter on screen."""
        await _register(hass, overlay=None)
        client = await hass_client()

        resp = await client.get(OVERLAY_URL)

        assert resp.status == 404

    async def test_a_purrview_failure_is_502(self, hass, hass_client):
        from custom_components.purrview.api import PurrViewApiError

        await _register(hass, overlay_side_effect=PurrViewApiError("db unavailable"))
        client = await hass_client()

        resp = await client.get(OVERLAY_URL)

        assert resp.status == 502

    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/recordings/rec-1/overlay")

        assert resp.status == 404

    async def test_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        await _register(hass, overlay={"version": 2, "frames": []})
        client = await hass_client_no_auth()

        resp = await client.get(OVERLAY_URL)

        assert resp.status == 401

    async def test_the_media_proxy_does_not_swallow_this_route(self, hass, hass_client):
        """proxy.py owns `/api/purrview/{entry_id}/{kind}/{uuid}`, and aiohttp matches
        dynamic resources in registration order - so any three-segment overlay path
        would be claimed by the proxy as an unknown `kind` and 404 before this view ever
        ran. Registered here in the same order __init__.py uses, because every other
        test in this class registers the overlay view alone and cannot see the clash.
        """
        from custom_components.purrview.proxy import PurrViewMediaProxyView

        doc = {"version": 2, "frames": []}
        await async_setup_component(hass, "http", {})
        client_mock = MagicMock(spec=PurrViewClient)
        client_mock.get_recording_overlay = AsyncMock(return_value=doc)
        hass.data[DOMAIN] = {"entry-1": client_mock}
        hass.http.register_view(PurrViewMediaProxyView(hass))
        hass.http.register_view(PurrViewRecordingOverlayView(hass))
        client = await hass_client()

        resp = await client.get(OVERLAY_URL)

        assert resp.status == 200
        assert await resp.json() == doc
