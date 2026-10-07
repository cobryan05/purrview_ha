"""Config flow tests.

Covers the two outcomes that matter: a reachable host produces a saved entry,
an unreachable one re-shows the form with an error instead of blowing up.
"""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.purrview.const import DOMAIN


async def test_user_flow_creates_entry(hass, aioclient_mock):
    aioclient_mock.get("http://192.168.1.50:7999/", status=200)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.1.50", "port": 7999}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "192.168.1.50"
    assert result["data"] == {"host": "192.168.1.50", "port": 7999}


async def test_user_flow_cannot_connect(hass, aioclient_mock):
    aioclient_mock.get("http://192.168.1.50:7999/", exc=OSError())

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.1.50", "port": 7999}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_rejects_a_bad_token(hass, aioclient_mock):
    """A wrong token used to save happily and then fail every call at runtime, which
    reads as "the integration is broken" rather than "the token is wrong"."""
    aioclient_mock.get("http://192.168.1.50:7999/", status=401)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.1.50", "port": 7999, "token": "wrong"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_rejects_an_omitted_token_when_purrview_wants_one(hass, aioclient_mock):
    """PurrView sends an HTML request to the login page rather than a 401, so a browser
    gets a form. The config flow is not a browser: a redirect to /login means the
    credential it holds (here, none) does not open the app."""
    aioclient_mock.get(
        "http://192.168.1.50:7999/",
        status=303,
        headers={"location": "/login?next=%2F"},
    )

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.1.50", "port": 7999}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
