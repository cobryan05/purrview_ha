"""Config flow for PurrView.

Just asks for host/port/token and checks something answers before saving the
entry. There's no PurrView endpoint yet that's specifically meant for a
health check - PurrView's auth middleware and the proxy routes don't exist -
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

from .api import rejected_credential
from .const import CONF_TOKEN, DEFAULT_PORT, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_TOKEN): str,
    }
)


class CannotConnect(HomeAssistantError):
    """Couldn't reach the PurrView instance."""


class InvalidAuth(HomeAssistantError):
    """Reached PurrView, but the token we hold does not open it."""


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    session = async_get_clientsession(hass)
    url = f"http://{data[CONF_HOST]}:{data[CONF_PORT]}/"
    headers = {}
    if token := data.get(CONF_TOKEN):
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with asyncio.timeout(10):
            # Redirects are not followed, because a rejected page request is a 303 to
            # PurrView's login form and following it lands on a 200 that says nothing
            # about whether this token works. An API caller is not a browser.
            async with session.get(url, headers=headers, allow_redirects=False) as resp:
                if rejected_credential(resp):
                    raise InvalidAuth
    except (asyncio.TimeoutError, OSError) as err:
        raise CannotConnect from err



class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PurrView."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            else:
                return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)
