"""PurrViewProfileSourcesView: backs the live-view card editor's "default camera"
picker, the same way test_watch_profiles_view.py covers its profile dropdown.
"""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.setup import async_setup_component

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
from custom_components.purrview.watch_profiles import PurrViewProfileSourcesView


async def _register(hass, *, sources=None, side_effect=None):
    await async_setup_component(hass, "http", {})
    client = MagicMock(spec=PurrViewClient)
    if side_effect is not None:
        client.get_watch_profile_sources = AsyncMock(side_effect=side_effect)
    else:
        client.get_watch_profile_sources = AsyncMock(return_value=sources or [])
    hass.data[DOMAIN] = {"entry-1": client}
    hass.http.register_view(PurrViewProfileSourcesView(hass))
    return client


class TestHappyPath:
    async def test_returns_sources(self, hass, hass_client):
        await _register(hass, sources=[{"uuid": "s1", "name": "Laundry"}, {"uuid": "s2", "name": "Garage"}])
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/watch-profiles/p1/sources")

        assert resp.status == 200
        assert (await resp.json())["sources"] == [{"uuid": "s1", "name": "Laundry"}, {"uuid": "s2", "name": "Garage"}]

    async def test_forwards_the_profile_uuid(self, hass, hass_client):
        purrview_client = await _register(hass)
        client = await hass_client()

        await client.get("/api/purrview/entry-1/watch-profiles/p1/sources")

        purrview_client.get_watch_profile_sources.assert_awaited_once_with("p1")


class TestErrors:
    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/watch-profiles/p1/sources")

        assert resp.status == 404

    async def test_purrview_error_becomes_502(self, hass, hass_client):
        from custom_components.purrview.api import PurrViewApiError

        await _register(hass, side_effect=PurrViewApiError("db unavailable"))
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/watch-profiles/p1/sources")

        assert resp.status == 502


class TestRequiresAuth:
    async def test_a_client_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        await _register(hass)
        client = await hass_client_no_auth()

        resp = await client.get("/api/purrview/entry-1/watch-profiles/p1/sources")

        assert resp.status == 401
