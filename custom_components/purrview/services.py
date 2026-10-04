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
SERVICE_PIN_EVENT = "pin_event"
SERVICE_START_RECORDING = "start_recording"
SERVICE_STOP_RECORDING = "stop_recording"

ATTR_EVENT_UUID = "event_uuid"
ATTR_REASON = "reason"
ATTR_NOTE = "note"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PINNED = "pinned"
ATTR_FLAGGED = "flagged"
ATTR_PROFILE_UUID = "profile_uuid"
ATTR_SOURCE_UUID = "source_uuid"
ATTR_MAX_DURATION_S = "max_duration_s"

FLAG_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EVENT_UUID): cv.string,
        vol.Required(ATTR_REASON): cv.string,
        vol.Optional(ATTR_NOTE, default=""): cv.string,
        vol.Optional(ATTR_FLAGGED, default=True): cv.boolean,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

PIN_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EVENT_UUID): cv.string,
        vol.Optional(ATTR_PINNED, default=True): cv.boolean,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

# `max_duration_s` is optional, not defaulted here: the cap belongs to the watch
# profile, and defaulting it in the integration would pin a second number that silently
# disagreed the moment the profile's own was changed.
START_RECORDING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROFILE_UUID): cv.string,
        vol.Required(ATTR_SOURCE_UUID): cv.string,
        vol.Optional(ATTR_MAX_DURATION_S): vol.Coerce(float),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

STOP_RECORDING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROFILE_UUID): cv.string,
        vol.Required(ATTR_SOURCE_UUID): cv.string,
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
                flagged=call.data.get(ATTR_FLAGGED, True),
            )
        except PurrViewApiError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_FLAG_EVENT, _handle_flag_event, schema=FLAG_EVENT_SCHEMA)

    async def _handle_pin_event(call: ServiceCall) -> None:
        client = _resolve_client(hass, call.data)
        try:
            await client.set_event_pinned(call.data[ATTR_EVENT_UUID], call.data[ATTR_PINNED])
        except PurrViewApiError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_PIN_EVENT, _handle_pin_event, schema=PIN_EVENT_SCHEMA)

    async def _set_recording(call: ServiceCall, recording: bool) -> None:
        client = _resolve_client(hass, call.data)
        try:
            started = await client.set_manual_recording(
                profile_uuid=call.data[ATTR_PROFILE_UUID],
                source_uuid=call.data[ATTR_SOURCE_UUID],
                recording=recording,
                max_duration_s=call.data.get(ATTR_MAX_DURATION_S),
            )
        except PurrViewApiError as err:
            raise ServiceValidationError(str(err)) from err
        if not started:
            # A watcher that is not running is a configuration problem the caller can
            # act on, not a transient one worth swallowing: the automation believes it
            # is recording and nothing would ever tell it otherwise.
            raise ServiceValidationError(
                f"No running watcher holds profile '{call.data[ATTR_PROFILE_UUID]}' — nothing to record"
            )

    async def _handle_start_recording(call: ServiceCall) -> None:
        await _set_recording(call, True)

    async def _handle_stop_recording(call: ServiceCall) -> None:
        await _set_recording(call, False)

    hass.services.async_register(
        DOMAIN, SERVICE_START_RECORDING, _handle_start_recording, schema=START_RECORDING_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_STOP_RECORDING, _handle_stop_recording, schema=STOP_RECORDING_SCHEMA)
