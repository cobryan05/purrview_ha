"""The purrview.flag_event service (WP-4 step 4).

Registered once for the domain, not once per config entry - a call targets a
specific PurrView instance via config_entry_id, the same way any multi-instance
integration's services do. Optional when only one instance is configured, which
is the common case (one PurrView per household).
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import PurrViewApiError, PurrViewClient, configured_clients
from .const import DOMAIN

SERVICE_FLAG_EVENT = "flag_event"

ATTR_EVENT_UUID = "event_uuid"
ATTR_REASON = "reason"
ATTR_NOTE = "note"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

FLAG_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EVENT_UUID): cv.string,
        vol.Required(ATTR_REASON): cv.string,
        vol.Optional(ATTR_NOTE, default=""): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


def _resolve_client(hass: HomeAssistant, call_data: dict) -> PurrViewClient:
    entries = configured_clients(hass)
    if not entries:
        raise ServiceValidationError("No PurrView instance is configured")

    requested = call_data.get(ATTR_CONFIG_ENTRY_ID)
    if requested:
        client = entries.get(requested)
        if client is None:
            raise ServiceValidationError(f"Unknown PurrView config entry '{requested}'")
        return client

    if len(entries) > 1:
        # Ambiguous, not a guess-and-hope case: which instance's event history
        # "event_uuid" even refers to is meaningless to answer for the wrong one.
        raise ServiceValidationError("Multiple PurrView instances are configured - specify config_entry_id")
    return next(iter(entries.values()))


def async_register_services(hass: HomeAssistant) -> None:
    """Called from async_setup_entry on every entry. Re-registering the same
    (domain, service) pair just replaces the handler with an identical one - unlike
    the proxy view, there's no route-duplication hazard here, so no guard is needed."""

    async def _handle_flag_event(call: ServiceCall) -> None:
        client = _resolve_client(hass, call.data)
        try:
            await client.flag_event(
                call.data[ATTR_EVENT_UUID],
                reason=call.data[ATTR_REASON],
                note=call.data.get(ATTR_NOTE, ""),
            )
        except PurrViewApiError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_FLAG_EVENT, _handle_flag_event, schema=FLAG_EVENT_SCHEMA)
