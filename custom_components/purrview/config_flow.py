"""Config flow for PurrView.

Asks for host/port/token and checks the credential against the instance before
saving. The same check backs the reauth step, so a rotated token is re-entered
rather than requiring the entry to be deleted and rebuilt.
"""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SSL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import PurrViewAuthError, PurrViewClient
from .const import CONF_TOKEN, DEFAULT_PORT, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_TOKEN): str,
        vol.Optional(CONF_SSL, default=False): bool,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Optional(CONF_TOKEN): str})


class CannotConnect(HomeAssistantError):
    """Couldn't reach the PurrView instance."""


class InvalidAuth(HomeAssistantError):
    """Reached PurrView, but the token we hold does not open it."""


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    client = PurrViewClient(
        hass,
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        token=data.get(CONF_TOKEN),
        use_ssl=data.get(CONF_SSL, False),
        verify_ssl=data.get(CONF_VERIFY_SSL, True),
    )
    try:
        await client.async_check_credentials()
    except PurrViewAuthError as err:
        raise InvalidAuth from err
    except (asyncio.TimeoutError, OSError) as err:
        raise CannotConnect from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PurrView."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # host:port, not the token - the token is a credential for an instance,
            # not part of its identity, and a reauth that changes it must still match
            # the entry it is re-authenticating.
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            try:
                await _validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            else:
                return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Re-enter the token for an entry PurrView has started refusing.

        Only the token is asked for. Host and port are the entry's identity, so
        changing them here would re-point the entry at a different instance under
        the guise of a credential refresh.
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            candidate = {**entry.data, CONF_TOKEN: user_input.get(CONF_TOKEN)}
            try:
                await _validate_input(self.hass, candidate)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            else:
                return self.async_update_reload_and_abort(entry, data=candidate)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )
