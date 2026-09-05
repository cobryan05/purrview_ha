"""PurrViewEventsView/PurrViewEventFacetsView: back the events grid card's filter bar
and grid, the same way test_watch_profiles_view.py covers the live-view card's editor.
"""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.setup import async_setup_component

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
from custom_components.purrview.events import PurrViewEventFacetsView, PurrViewEventsView


async def _register(hass, *, events=None, total=None, facets=None, list_events_side_effect=None, facets_side_effect=None):
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
    hass.data[DOMAIN] = {"entry-1": client}
    hass.http.register_view(PurrViewEventsView(hass))
    hass.http.register_view(PurrViewEventFacetsView(hass))
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
