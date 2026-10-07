"""Streams PurrView media (recordings, snapshots, crops) through Home Assistant.

Why this exists at all, from HA_INTEGRATION_PLAN.md WP-4: resolving media straight to
`http://<purrview-host>:7999/...` fails for any client off the LAN and carries no auth.
Routing it through this view instead gives every consumer - the media browser, a cast
target, the future Lovelace card - one thing that is always reachable and always
authorized, regardless of where PurrView actually lives.

`requires_auth = True`, but nothing here hands the caller a login prompt: `media_source`
resolves URLs through `async_sign_path`, which appends a short-lived signature HA's own
auth middleware accepts in place of a session or a header. That signature is what makes
this playable from a `<video>` tag and a cast device, neither of which can attach an
`Authorization` header - the same problem PurrView's own `?token=` fallback solves one
layer down, for HA's own long-lived token instead of PurrView's (WP-3).
"""

from __future__ import annotations

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import rejected_credential
from .const import DOMAIN

#: Maps this view's `kind` segment to the PurrView endpoint it forwards to. Deliberately
#: an allowlist, not a passthrough of an arbitrary path - this view is reachable with a
#: time-limited signature but no further access control, and a passthrough would turn it
#: into an open proxy into whatever host:port the config entry happens to point at.
_UPSTREAM_PATHS = {
    "recording": "/api/recordings/{uuid}/file",
    "snapshot": "/api/watch-events/{uuid}/snapshot",
    "crop": "/api/watch-events/{uuid}/crop",
}

#: Headers worth forwarding from PurrView's response. Everything else (Date, Server, a
#: proxy's own hop-by-hop headers) is either meaningless for a range-seekable download
#: or actively wrong to repeat under aiohttp's own connection handling.
_FORWARD_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "content-range",
        "accept-ranges",
        "cache-control",
        "etag",
        "last-modified",
    }
)


class PurrViewMediaProxyView(HomeAssistantView):
    """`GET /api/purrview/{entry_id}/{kind}/{uuid}` - forwards to one PurrView instance."""

    url = "/api/purrview/{entry_id}/{kind}/{uuid}"
    name = "api:purrview:media"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, entry_id: str, kind: str, uuid: str) -> web.StreamResponse:
        client = self._hass.data.get(DOMAIN, {}).get(entry_id)
        if client is None:
            raise web.HTTPNotFound(reason="Unknown PurrView config entry")

        path_template = _UPSTREAM_PATHS.get(kind)
        if path_template is None:
            raise web.HTTPNotFound(reason=f"Unknown media kind '{kind}'")

        headers = client.auth_headers()
        # Forwarded verbatim, not re-derived: PurrView's own file endpoint (FileResponse)
        # does the actual byte-range math, and duplicating that logic here would be a
        # second place for an off-by-one to disagree with the one that matters.
        if range_header := request.headers.get("Range"):
            headers["Range"] = range_header

        session = async_get_clientsession(self._hass)
        try:
            # Redirects are not followed: PurrView's auth gate answers a page request
            # with a 303 to its login form, and following that would stream the form's
            # HTML into whatever <video> or <img> asked for this.
            upstream = await session.get(
                f"{client.base_url}{path_template.format(uuid=uuid)}",
                headers=headers,
                allow_redirects=False,
            )
        except aiohttp.ClientError as err:
            raise web.HTTPBadGateway(reason="Could not reach PurrView") from err

        if upstream.status == 404:
            upstream.release()
            raise web.HTTPNotFound()
        if rejected_credential(upstream):
            upstream.release()
            raise web.HTTPBadGateway(reason="PurrView refused the configured access token")
        if upstream.status not in (200, 206):
            upstream.release()
            raise web.HTTPBadGateway(reason=f"PurrView returned HTTP {upstream.status}")

        response = web.StreamResponse(
            status=upstream.status,
            headers={k: v for k, v in upstream.headers.items() if k.lower() in _FORWARD_RESPONSE_HEADERS},
        )
        await response.prepare(request)
        try:
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
        finally:
            upstream.release()
        return response
