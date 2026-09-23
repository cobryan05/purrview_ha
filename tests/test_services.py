"""purrview.flag_event: the service WP-1's endpoint exists for HA to call (WP-4 step 4)."""

from homeassistant.exceptions import ServiceValidationError

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
from custom_components.purrview.services import SERVICE_FLAG_EVENT, SERVICE_PIN_EVENT, async_register_services

HOST = "192.168.1.50"
PORT = 7999
BASE = f"http://{HOST}:{PORT}"


def _one_entry(hass, entry_id="entry-1"):
    hass.data[DOMAIN] = {entry_id: PurrViewClient(hass, host=HOST, port=PORT)}
    async_register_services(hass)


class TestSingleInstance:
    async def test_reaches_the_flag_endpoint_with_no_config_entry_id_needed(self, hass, aioclient_mock):
        """The common case: one PurrView configured, so config_entry_id is optional."""
        _one_entry(hass)
        aioclient_mock.get(f"{BASE}/api/watch-events/e1", json={"status": "success", "event": {"uuid": "e1"}})
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await hass.services.async_call(
            DOMAIN, SERVICE_FLAG_EVENT, {"event_uuid": "e1", "reason": "wrong_labels"}, blocking=True
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["reviewState"] == "flagged"
        assert data["metadataJson"]["flag"]["reason"] == "wrong_labels"

    async def test_note_is_optional(self, hass, aioclient_mock):
        _one_entry(hass)
        aioclient_mock.get(f"{BASE}/api/watch-events/e1", json={"status": "success", "event": {"uuid": "e1"}})
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await hass.services.async_call(
            DOMAIN, SERVICE_FLAG_EVENT, {"event_uuid": "e1", "reason": "wrong_labels"}, blocking=True
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["metadataJson"]["flag"]["note"] == ""

    async def test_flagged_false_unflags_instead_of_flagging(self, hass, aioclient_mock):
        """The toggle path the Lovelace card's unflag click drives - flagged defaults to
        True, so this only exercises correctly if the schema/handler actually thread
        flagged=False through to the client rather than silently dropping it."""
        _one_entry(hass)
        aioclient_mock.get(
            f"{BASE}/api/watch-events/e1",
            json={
                "status": "success",
                "event": {"uuid": "e1", "metadataJson": {"flag": {"reason": "wrong_labels"}}},
            },
        )
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await hass.services.async_call(
            DOMAIN,
            SERVICE_FLAG_EVENT,
            {"event_uuid": "e1", "reason": "wrong_labels", "flagged": False},
            blocking=True,
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["reviewState"] == "unreviewed"
        assert "flag" not in data["metadataJson"]


class TestMultipleInstances:
    async def test_ambiguous_without_config_entry_id_is_rejected(self, hass):
        hass.data[DOMAIN] = {
            "entry-1": PurrViewClient(hass, host="192.168.1.50", port=7999),
            "entry-2": PurrViewClient(hass, host="192.168.1.60", port=7999),
        }
        async_register_services(hass)

        try:
            await hass.services.async_call(
                DOMAIN, SERVICE_FLAG_EVENT, {"event_uuid": "e1", "reason": "wrong_labels"}, blocking=True
            )
        except ServiceValidationError:
            pass
        else:
            raise AssertionError("expected ServiceValidationError")

    async def test_config_entry_id_selects_the_right_instance(self, hass, aioclient_mock):
        hass.data[DOMAIN] = {
            "entry-1": PurrViewClient(hass, host="192.168.1.50", port=7999),
            "entry-2": PurrViewClient(hass, host="192.168.1.60", port=7999),
        }
        async_register_services(hass)
        aioclient_mock.get("http://192.168.1.60:7999/api/watch-events/e1", json={"status": "success", "event": {}})
        aioclient_mock.patch("http://192.168.1.60:7999/api/watch-events/e1", json={"status": "success"})

        await hass.services.async_call(
            DOMAIN,
            SERVICE_FLAG_EVENT,
            {"event_uuid": "e1", "reason": "wrong_labels", "config_entry_id": "entry-2"},
            blocking=True,
        )

        # No call reached entry-1's host at all - not just that entry-2's did.
        assert all("192.168.1.50" not in str(call[1]) for call in aioclient_mock.mock_calls)

    async def test_unknown_config_entry_id_is_rejected(self, hass):
        hass.data[DOMAIN] = {
            "entry-1": PurrViewClient(hass, host="192.168.1.50", port=7999),
            "entry-2": PurrViewClient(hass, host="192.168.1.60", port=7999),
        }
        async_register_services(hass)

        try:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_FLAG_EVENT,
                {"event_uuid": "e1", "reason": "wrong_labels", "config_entry_id": "no-such-entry"},
                blocking=True,
            )
        except ServiceValidationError:
            pass
        else:
            raise AssertionError("expected ServiceValidationError")


class TestNoInstanceConfigured:
    async def test_is_rejected_rather_than_crashing(self, hass):
        hass.data[DOMAIN] = {}
        async_register_services(hass)

        try:
            await hass.services.async_call(
                DOMAIN, SERVICE_FLAG_EVENT, {"event_uuid": "e1", "reason": "wrong_labels"}, blocking=True
            )
        except ServiceValidationError:
            pass
        else:
            raise AssertionError("expected ServiceValidationError")


class TestSchemaValidation:
    async def test_reason_is_required(self, hass):
        _one_entry(hass)

        try:
            await hass.services.async_call(DOMAIN, SERVICE_FLAG_EVENT, {"event_uuid": "e1"}, blocking=True)
        except Exception:  # voluptuous raises vol.Invalid, wrapped by the service call machinery
            pass
        else:
            raise AssertionError("expected a schema validation error")


class TestPinEventService:
    """purrview.pin_event. Instance resolution (single/multiple/none/config_entry_id)
    is the same `_resolve_client` flag_event already exercises above - not repeated
    here, since it does not vary by which service calls it."""

    async def test_pinned_defaults_to_true_when_omitted(self, hass, aioclient_mock):
        _one_entry(hass)
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await hass.services.async_call(DOMAIN, SERVICE_PIN_EVENT, {"event_uuid": "e1"}, blocking=True)

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data == {"pinned": True}

    async def test_pinned_false_unpins(self, hass, aioclient_mock):
        _one_entry(hass)
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await hass.services.async_call(
            DOMAIN, SERVICE_PIN_EVENT, {"event_uuid": "e1", "pinned": False}, blocking=True
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data == {"pinned": False}
