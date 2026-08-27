"""The WhiskerWatcher integration.

Just config entry storage for now. Platforms (media_source, the proxy view, the
flag service) show up with WP-4 - see HA_INTEGRATION_PLAN.md in the whiskerwatcher
repo for the full build order.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
