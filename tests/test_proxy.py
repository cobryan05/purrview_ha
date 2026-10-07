"""PurrViewMediaProxyView: forwards recordings/snapshots/crops through HA.

Uses a MagicMock stand-in for PurrViewClient rather than a real config entry -
api.py's own tests (test_api.py) cover PurrViewClient itself; this file is only
about the view's routing, error mapping, and header forwarding.
"""

from unittest.mock import MagicMock

import aiohttp
from homeassistant.setup import async_setup_component

from custom_components.purrview.const import DOMAIN
from custom_components.purrview.proxy import PurrViewMediaProxyView

BASE = "http://192.168.1.50:7999"


async def _register(hass, *, token=None):
    # hass.http does not exist until the http component itself is set up - not
    # something __init__.py has to do in production (a running HA always has it),
    # but the test harness starts with none of core's components loaded.
    await async_setup_component(hass, "http", {})
    client = MagicMock()
    client.base_url = BASE
    client.auth_headers.return_value = {"Authorization": f"Bearer {token}"} if token else {}
    hass.data[DOMAIN] = {"entry-1": client}
    hass.http.register_view(PurrViewMediaProxyView(hass))
    return client


class TestUnknownRoutes:
    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/recording/r1")

        assert resp.status == 404

    async def test_unknown_kind_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/nonsense/r1")

        assert resp.status == 404


class TestForwarding:
    async def test_range_header_is_forwarded_upstream(self, hass, hass_client, aioclient_mock):
        """The scrubbing-critical path: a seek in the player becomes a byte-range
        request, and that has to reach PurrView's own Range-aware file endpoint
        unchanged, not get flattened into a full download."""
        await _register(hass)
        aioclient_mock.get(
            f"{BASE}/api/recordings/r1/file",
            status=206,
            content=b"partial",
            headers={"Content-Range": "bytes 0-6/100", "Content-Type": "video/mp4"},
        )
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/recording/r1", headers={"Range": "bytes=0-6"})

        assert resp.status == 206
        assert await resp.read() == b"partial"
        assert resp.headers["Content-Range"] == "bytes 0-6/100"
        _, _, _, sent_headers = aioclient_mock.mock_calls[-1]
        assert sent_headers["Range"] == "bytes=0-6"

    async def test_no_range_header_means_none_is_sent_upstream(self, hass, hass_client, aioclient_mock):
        await _register(hass)
        aioclient_mock.get(
            f"{BASE}/api/recordings/r1/file", content=b"all of it", headers={"Content-Type": "video/mp4"}
        )
        client = await hass_client()

        await client.get("/api/purrview/entry-1/recording/r1")

        _, _, _, sent_headers = aioclient_mock.mock_calls[-1]
        assert "Range" not in sent_headers

    async def test_upstream_404_becomes_404(self, hass, hass_client, aioclient_mock):
        await _register(hass)
        aioclient_mock.get(f"{BASE}/api/watch-events/e1/snapshot", status=404)
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/snapshot/e1")

        assert resp.status == 404

    async def test_unreachable_purrview_becomes_502_not_a_crash(self, hass, hass_client, aioclient_mock):
        aioclient_mock.get(f"{BASE}/api/watch-events/e1/crop", exc=aiohttp.ClientConnectionError())
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/crop/e1")

        assert resp.status == 502

    async def test_configured_token_is_forwarded_as_bearer(self, hass, hass_client, aioclient_mock):
        await _register(hass, token="s3cr3t")
        aioclient_mock.get(f"{BASE}/api/watch-events/e1/crop", content=b"img", headers={"Content-Type": "image/jpeg"})
        client = await hass_client()

        await client.get("/api/purrview/entry-1/crop/e1")

        _, _, _, sent_headers = aioclient_mock.mock_calls[-1]
        assert sent_headers["Authorization"] == "Bearer s3cr3t"


class TestRequiresAuth:
    async def test_a_client_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        """This view is reachable from outside the LAN (that is the point of routing
        through HA at all) - it must not be reachable without HA's own auth just because
        PurrView's own token check passed."""
        await _register(hass)
        client = await hass_client_no_auth()

        resp = await client.get("/api/purrview/entry-1/recording/r1")

        assert resp.status == 401


class TestRejectedCredential:
    """PurrView's auth gate answers a non-HTML request with 401 and a page request with
    a 303 to its login form. Neither is media, and the difference matters: a followed
    redirect would stream the login page's HTML into a <video> element."""

    async def test_a_login_redirect_is_not_followed_and_streamed_as_media(
        self, hass, hass_client, aioclient_mock
    ):
        await _register(hass)
        aioclient_mock.get(
            f"{BASE}/api/watch-events/e1/snapshot",
            status=303,
            headers={"location": "/login?next=%2F"},
            text="<html>login form</html>",
        )
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/snapshot/e1")

        assert resp.status == 502
        assert "login form" not in await resp.text()

    async def test_a_rejected_token_says_so_rather_than_naming_a_status(
        self, hass, hass_client, aioclient_mock
    ):
        """"PurrView returned HTTP 401" reads as "PurrView is broken". The operator
        needs to know it is the stored token that was refused."""
        await _register(hass, token="stale")
        aioclient_mock.get(f"{BASE}/api/recordings/e1/file", status=401)
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/recording/e1")

        assert resp.status == 502
        assert "token" in (resp.reason or "").lower()
