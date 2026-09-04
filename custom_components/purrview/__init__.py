"""The PurrView integration.

WP-4: the proxy view (media streamed through HA, auth and all) and a `PurrViewClient`
per config entry. media_source and the flag service build on the client this stores.
See HA_INTEGRATION_PLAN.md in the main PurrView repo for the full build order.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .api import PurrViewClient
from .const import CONF_TOKEN, DOMAIN
from .proxy import PurrViewMediaProxyView

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

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
