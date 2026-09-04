"""PurrViewLivePreviewView: the HTTP surface the Lovelace card polls (WP-5 backend)."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.setup import async_setup_component

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
from custom_components.purrview.live_preview import PurrViewLivePreviewView


async def _register(hass, *, preview=None, side_effect=None):
    await async_setup_component(hass, "http", {})
    # spec=PurrViewClient, not a bare MagicMock: configured_clients() only returns
    # real PurrViewClient instances (it filters __init__.py's "_view_registered"
    # sentinel out of the same dict), so an un-spec'd mock would 404 here exactly
    # like an unconfigured entry would - a false negative this view's own logic
    # would never actually produce.
    client = MagicMock(spec=PurrViewClient)
    if side_effect is not None:
        client.get_live_preview = AsyncMock(side_effect=side_effect)
    else:
        client.get_live_preview = AsyncMock(return_value=preview)
    hass.data[DOMAIN] = {"entry-1": client}
    hass.http.register_view(PurrViewLivePreviewView(hass))
    return client


class TestHappyPath:
    async def test_returns_the_preview_as_json(self, hass, hass_client):
        await _register(hass, preview={"frameSeq": 3, "frame": "abc"})
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/live-preview?profile_uuid=p1")

        assert resp.status == 200
        assert (await resp.json())["preview"] == {"frameSeq": 3, "frame": "abc"}

    async def test_null_preview_is_not_an_error(self, hass, hass_client):
        """A profile with no running watcher is a normal answer, not a failure -
        the card has to tell "not running" apart from "PurrView unreachable"."""
        await _register(hass, preview=None)
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/live-preview?profile_uuid=p1")

        assert resp.status == 200
        assert (await resp.json())["preview"] is None

    async def test_optional_params_are_forwarded_to_the_client(self, hass, hass_client):
        stub = await _register(hass, preview={})
        client = await hass_client()

        await client.get(
            "/api/purrview/entry-1/live-preview?profile_uuid=p1&source_uuid=src-1&since_seq=7&quality=50&full=true"
        )

        stub.get_live_preview.assert_awaited_once_with(
            profile_uuid="p1", source_uuid="src-1", since_seq=7, quality=50, full=True
        )


class TestErrors:
    async def test_missing_profile_uuid_is_400(self, hass, hass_client):
        await _register(hass, preview={})
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/live-preview")

        assert resp.status == 400

    async def test_non_integer_since_seq_is_400_not_a_crash(self, hass, hass_client):
        await _register(hass, preview={})
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/live-preview?profile_uuid=p1&since_seq=not-a-number")

        assert resp.status == 400

    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass, preview={})
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/live-preview?profile_uuid=p1")

        assert resp.status == 404

    async def test_purrview_error_becomes_502(self, hass, hass_client):
        from custom_components.purrview.api import PurrViewApiError

        await _register(hass, side_effect=PurrViewApiError("db unavailable"))
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/live-preview?profile_uuid=p1")

        assert resp.status == 502


class TestRequiresAuth:
    async def test_a_client_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        await _register(hass, preview={})
        client = await hass_client_no_auth()

        resp = await client.get("/api/purrview/entry-1/live-preview?profile_uuid=p1")

        assert resp.status == 401
