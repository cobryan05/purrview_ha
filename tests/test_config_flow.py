"""Config flow tests.

Covers the two outcomes that matter: a reachable host produces a saved entry,
an unreachable one re-shows the form with an error instead of blowing up.
"""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.whiskerwatcher.const import DOMAIN


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
