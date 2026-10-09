"""Streams live-preview JSON through HA, for the Lovelace card.

Unlike proxy.py's recordings/snapshots/crops, a live-preview response is small
structured JSON with an embedded base64 frame - no Range semantics apply, and
there is no reason to stream it as raw bytes. That's why this is its own view
rather than a fourth entry in proxy.py's _UPSTREAM_PATHS: the two have nothing
in common but both living under /api/purrview/.
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .api import PurrViewApiError, configured_clients


class PurrViewLivePreviewView(HomeAssistantView):
    """`GET /api/purrview/{entry_id}/live-preview?profile_uuid=...` -> `{"preview": ...}`.

    `preview` is `null` when that profile has no watcher running right now - a
    normal answer (see PurrViewClient.get_live_preview), not something this view
    turns into an error status.
    """

    url = "/api/purrview/{entry_id}/live-preview"
    name = "api:purrview:live-preview"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        client = configured_clients(self._hass).get(entry_id)
        if client is None:
            raise web.HTTPNotFound(reason="Unknown PurrView config entry")

        profile_uuid = request.query.get("profile_uuid")
        if not profile_uuid:
            raise web.HTTPBadRequest(reason="profile_uuid is required")

        try:
            since_seq = request.query.get("since_seq")
            quality = request.query.get("quality")
            since_seq = int(since_seq) if since_seq is not None else None
            quality = int(quality) if quality is not None else None
        except ValueError as err:
            raise web.HTTPBadRequest(reason="since_seq and quality must be integers") from err

        try:
            preview = await client.get_live_preview(
                profile_uuid=profile_uuid,
                source_uuid=request.query.get("source_uuid"),
                since_seq=since_seq,
                quality=quality,
                full=request.query.get("full") == "true",
            )
        except PurrViewApiError as err:
            raise web.HTTPBadGateway(reason=str(err)) from err

        return self.json({"preview": preview})
