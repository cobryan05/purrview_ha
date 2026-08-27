"""Config flow for WhiskerWatcher.

Just asks for host/port/token and checks something answers before saving the
entry. There's no WhiskerWatcher endpoint yet that's specifically meant for a
health check - WP-3's auth middleware and WP-4's proxy routes don't exist -
so a plain connection failure is the only thing worth catching here.
"""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_TOKEN, DEFAULT_PORT, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_TOKEN): str,
    }
)


class CannotConnect(HomeAssistantError):
    """Couldn't reach the WhiskerWatcher instance."""


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    session = async_get_clientsession(hass)
    url = f"http://{data[CONF_HOST]}:{data[CONF_PORT]}/"
    headers = {}
    if token := data.get(CONF_TOKEN):
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with asyncio.timeout(10):
            async with session.get(url, headers=headers):
                pass
    except (asyncio.TimeoutError, OSError) as err:
        raise CannotConnect from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WhiskerWatcher."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)
