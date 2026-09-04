"""The PurrView integration.

WP-4: the proxy view (media streamed through HA, auth and all), a `PurrViewClient`
per config entry, and the `purrview.flag_event` service. media_source (media_source.py)
builds on the client this stores too, but is auto-discovered by HA's own platform
loader rather than wired in here. See HA_INTEGRATION_PLAN.md in the main PurrView
repo for the full build order.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .api import PurrViewClient, configured_clients
from .const import CONF_TOKEN, DOMAIN
from .proxy import PurrViewMediaProxyView
from .services import SERVICE_FLAG_EVENT, async_register_services

#: Not a real config entry id - HA generates those as opaque hex, never with a leading
#: underscore - so this can share `hass.data[DOMAIN]` with the entry_id -> client map
#: below instead of needing a second dict just to say "the view is registered".
_VIEW_REGISTERED_KEY = "_view_registered"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = PurrViewClient(
        hass,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        token=entry.data.get(CONF_TOKEN),
    )

    # Registered once, not per-entry: the view itself resolves which PurrView instance
    # to forward to from the entry_id in the URL, so a second entry needs a new client
    # in the dict above, not a second route.
    if not domain_data.get(_VIEW_REGISTERED_KEY):
        hass.http.register_view(PurrViewMediaProxyView(hass))
        domain_data[_VIEW_REGISTERED_KEY] = True

    # Re-registering on every entry is harmless (see async_register_services), so
    # this doesn't need the same once-only guard as the view above.
    async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].pop(entry.entry_id, None)

    # Only the service comes down when the last entry does - the view stays
    # registered (HA has no supported "unregister" for it, and a route with no
    # matching entry_id in hass.data just 404s, same as it would for a typo).
    if not configured_clients(hass):
        hass.services.async_remove(DOMAIN, SERVICE_FLAG_EVENT)

    return True
