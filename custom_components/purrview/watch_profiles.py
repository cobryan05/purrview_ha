"""Lists watch profiles for the Lovelace card's config editor.

The card polls by profile_uuid (see live_preview.py), and until this existed the
only way to find one was digging through the PurrView API or HA's own storage files
by hand - fine for development, not something to ask a HACS viewer to do. This gives
the card's editor a name-based picker instead.
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .api import PurrViewApiError, configured_clients


class PurrViewWatchProfilesView(HomeAssistantView):
    """`GET /api/purrview/{entry_id}/watch-profiles` -> `{"profiles": [...]}`.

    Each profile carries a `live` flag (from get_running_watcher_tasks) so the
    editor can show which camera is actually watchable right now - a profile that
    exists but has no watcher running is still listed (the viewer may be setting up
    the card before starting the watcher), just not flagged live. Disabled profiles
    are left out entirely; there is nothing a live-view card could show for one.
    """

    url = "/api/purrview/{entry_id}/watch-profiles"
    name = "api:purrview:watch-profiles"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        client = configured_clients(self._hass).get(entry_id)
        if client is None:
            raise web.HTTPNotFound(reason="Unknown PurrView config entry")

        try:
            profiles = await client.list_watch_profiles()
            running = await client.get_running_watcher_tasks()
        except PurrViewApiError as err:
            raise web.HTTPBadGateway(reason=str(err)) from err

        live_uuids = {task["profileUuid"] for task in running}
        result = [
            {"uuid": p["uuid"], "name": p["name"], "live": p["uuid"] in live_uuids}
            for p in profiles
            if p["enabled"]
        ]
        result.sort(key=lambda p: (not p["live"], p["name"].lower()))
        return self.json({"profiles": result})
