"""Config flow tests.

Covers the two outcomes that matter: a reachable host produces a saved entry,
an unreachable one re-shows the form with an error instead of blowing up.
"""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    assert result["data"] == {
        "host": "192.168.1.50",
        "port": 7999,
        "ssl": False,
        "verify_ssl": True,
    }


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


class TestDuplicateInstances:
    async def test_the_same_host_and_port_cannot_be_added_twice(self, hass, aioclient_mock):
        """Two entries for one instance each register their own client under their own
        entry_id, so both halves of the UI keep working while the cards, the media
        browser and the services all silently pick whichever one the user configured
        them against."""
        aioclient_mock.get("http://192.168.1.50:7999/", status=200)
        MockConfigEntry(
            domain=DOMAIN, unique_id="192.168.1.50:7999", data={"host": "192.168.1.50", "port": 7999}
        ).add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.50", "port": 7999}
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    async def test_a_second_instance_on_another_port_is_allowed(self, hass, aioclient_mock):
        aioclient_mock.get("http://192.168.1.50:8999/", status=200)
        MockConfigEntry(
            domain=DOMAIN, unique_id="192.168.1.50:7999", data={"host": "192.168.1.50", "port": 7999}
        ).add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.50", "port": 8999}
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY


class TestReauth:
    def _entry(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="192.168.1.50:7999",
            data={"host": "192.168.1.50", "port": 7999, "token": "stale"},
        )
        entry.add_to_hass(hass)
        return entry

    async def test_a_new_token_replaces_the_stale_one(self, hass, aioclient_mock):
        """Rotating the PurrView token used to mean deleting the entry and rebuilding
        it, losing the card configuration pointed at its entry_id."""
        aioclient_mock.get("http://192.168.1.50:7999/", status=200)
        entry = self._entry(hass)

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"token": "fresh"})

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data["token"] == "fresh"
        assert entry.data["host"] == "192.168.1.50"

    async def test_a_still_bad_token_re_shows_the_form(self, hass, aioclient_mock):
        aioclient_mock.get("http://192.168.1.50:7999/", status=401)
        entry = self._entry(hass)

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"token": "also-wrong"})

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}
        assert entry.data["token"] == "stale"
