"""PurrViewWatchProfilesView: backs the Lovelace card's config editor dropdown."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.setup import async_setup_component

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
from custom_components.purrview.watch_profiles import PurrViewWatchProfilesView


async def _register(hass, *, profiles=None, running=None, side_effect=None):
    await async_setup_component(hass, "http", {})
    # spec=PurrViewClient - configured_clients() only returns real PurrViewClient
    # instances, so a bare MagicMock would 404 here the same way an unconfigured
    # entry would (see the same note in test_live_preview_view.py).
    client = MagicMock(spec=PurrViewClient)
    if side_effect is not None:
        client.list_watch_profiles = AsyncMock(side_effect=side_effect)
    else:
        client.list_watch_profiles = AsyncMock(return_value=profiles or [])
    client.get_running_watcher_tasks = AsyncMock(return_value=running or [])
    hass.data[DOMAIN] = {"entry-1": client}
    hass.http.register_view(PurrViewWatchProfilesView(hass))
    return client


class TestHappyPath:
    async def test_returns_profiles_with_a_live_flag(self, hass, hass_client):
        await _register(
            hass,
            profiles=[
                {"uuid": "p1", "name": "Cat Room", "enabled": True},
                {"uuid": "p2", "name": "Laundry", "enabled": True},
            ],
            running=[{"taskUuid": "t1", "profileUuid": "p1"}],
        )
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/watch-profiles")

        assert resp.status == 200
        assert (await resp.json())["profiles"] == [
            {"uuid": "p1", "name": "Cat Room", "live": True},
            {"uuid": "p2", "name": "Laundry", "live": False},
        ]

    async def test_disabled_profiles_are_excluded(self, hass, hass_client):
        await _register(
            hass,
            profiles=[
                {"uuid": "p1", "name": "Cat Room", "enabled": True},
                {"uuid": "p2", "name": "Retired Cam", "enabled": False},
            ],
        )
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/watch-profiles")

        uuids = [p["uuid"] for p in (await resp.json())["profiles"]]
        assert uuids == ["p1"]

    async def test_live_profiles_sort_first_then_alphabetical(self, hass, hass_client):
        await _register(
            hass,
            profiles=[
                {"uuid": "p1", "name": "Zebra Cam", "enabled": True},
                {"uuid": "p2", "name": "Aardvark Cam", "enabled": True},
                {"uuid": "p3", "name": "Live Cam", "enabled": True},
            ],
            running=[{"taskUuid": "t1", "profileUuid": "p3"}],
        )
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/watch-profiles")

        names = [p["name"] for p in (await resp.json())["profiles"]]
        assert names == ["Live Cam", "Aardvark Cam", "Zebra Cam"]


class TestErrors:
    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/watch-profiles")

        assert resp.status == 404

    async def test_purrview_error_becomes_502(self, hass, hass_client):
        from custom_components.purrview.api import PurrViewApiError

        await _register(hass, side_effect=PurrViewApiError("db unavailable"))
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/watch-profiles")

        assert resp.status == 502


class TestRequiresAuth:
    async def test_a_client_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        await _register(hass)
        client = await hass_client_no_auth()

        resp = await client.get("/api/purrview/entry-1/watch-profiles")

        assert resp.status == 401
