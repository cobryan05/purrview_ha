"""async_setup_entry / async_unload_entry: the wiring, not any one piece's own logic
(proxy.py, api.py, services.py, media_source.py each have their own test files)."""

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.purrview import _CARD_URL, async_setup_entry, async_unload_entry
from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import CONF_TOKEN, DOMAIN
from custom_components.purrview.services import SERVICE_FLAG_EVENT

DATA = {"host": "192.168.1.50", "port": 7999, CONF_TOKEN: "s3cr3t"}


@pytest.fixture(autouse=True)
async def _http(hass):
    # async_setup_entry registers the proxy views, which need hass.http to exist -
    # not something a real HA install has to arrange (it's always up), but the test
    # harness starts with none of core's components loaded.
    await async_setup_component(hass, "http", {})
    # add_extra_js_url only needs this one hass.data key to exist, normally seeded by
    # frontend's own async_setup - setting up the real "frontend" component instead
    # pulls in the hass_frontend asset package (the compiled web UI), which is not a
    # dependency this repo otherwise has any reason to carry just for a unit test.
    hass.data.setdefault(DATA_EXTRA_MODULE_URL, set())


def _entry(hass, entry_id="entry-1", data=DATA):
    entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id, data=data)
    entry.add_to_hass(hass)
    return entry


class TestSetup:
    async def test_stores_a_client_built_from_entry_data(self, hass):
        entry = _entry(hass)

        await async_setup_entry(hass, entry)

        client = hass.data[DOMAIN][entry.entry_id]
        assert isinstance(client, PurrViewClient)
        assert client.host == "192.168.1.50"
        assert client.token == "s3cr3t"

    async def test_registers_the_flag_event_service(self, hass):
        entry = _entry(hass)

        await async_setup_entry(hass, entry)

        assert hass.services.has_service(DOMAIN, SERVICE_FLAG_EVENT)

    async def test_a_second_entry_does_not_double_register_the_proxy_view(self, hass):
        """The route-duplication hazard async_setup_entry's own comment warns about -
        two entries must share one registration, not register the view twice."""
        await async_setup_entry(hass, _entry(hass, "entry-1"))
        route_count_after_first = len(hass.http.app.router.routes())

        await async_setup_entry(hass, _entry(hass, "entry-2", {**DATA, "host": "192.168.1.60"}))
        route_count_after_second = len(hass.http.app.router.routes())

        assert route_count_after_second == route_count_after_first

    async def test_registers_the_card_as_a_frontend_module_exactly_once(self, hass):
        from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL

        await async_setup_entry(hass, _entry(hass, "entry-1"))
        await async_setup_entry(hass, _entry(hass, "entry-2", {**DATA, "host": "192.168.1.60"}))

        urls = hass.data[DATA_EXTRA_MODULE_URL]
        assert list(urls).count(_CARD_URL) == 1

    async def test_serves_the_card_file_through_the_static_path(self, hass, hass_client):
        await async_setup_entry(hass, _entry(hass))
        client = await hass_client()

        resp = await client.get(_CARD_URL)

        assert resp.status == 200
        assert b"customElements.define" in await resp.read()

    async def test_registers_the_watch_profiles_view(self, hass):
        await async_setup_entry(hass, _entry(hass))

        canonicals = {resource.canonical for resource in hass.http.app.router.resources()}
        assert "/api/purrview/{entry_id}/watch-profiles" in canonicals


class TestUnload:
    async def test_removes_only_that_entrys_client(self, hass):
        entry1 = _entry(hass, "entry-1")
        entry2 = _entry(hass, "entry-2", {**DATA, "host": "192.168.1.60"})
        await async_setup_entry(hass, entry1)
        await async_setup_entry(hass, entry2)

        await async_unload_entry(hass, entry1)

        assert "entry-1" not in hass.data[DOMAIN]
        assert "entry-2" in hass.data[DOMAIN]

    async def test_service_survives_while_another_entry_remains(self, hass):
        entry1 = _entry(hass, "entry-1")
        entry2 = _entry(hass, "entry-2", {**DATA, "host": "192.168.1.60"})
        await async_setup_entry(hass, entry1)
        await async_setup_entry(hass, entry2)

        await async_unload_entry(hass, entry1)

        assert hass.services.has_service(DOMAIN, SERVICE_FLAG_EVENT)

    async def test_service_is_removed_once_the_last_entry_unloads(self, hass):
        entry = _entry(hass)
        await async_setup_entry(hass, entry)

        await async_unload_entry(hass, entry)

        assert not hass.services.has_service(DOMAIN, SERVICE_FLAG_EVENT)
