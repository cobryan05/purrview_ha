"""purrview.start_recording / stop_recording — recording a camera with no rule behind it.

The service resolves a watch profile to its running watcher and sends that task a
command, so the cases worth pinning are the ones where the resolution or the payload
could be wrong in a way nothing downstream would report: a profile nothing is watching,
and an omitted duration that must stay omitted rather than becoming a second default.
"""

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
from custom_components.purrview.services import (
    SERVICE_START_RECORDING,
    SERVICE_STOP_RECORDING,
    async_register_services,
)

HOST = "192.168.1.50"
PORT = 7999
BASE = f"http://{HOST}:{PORT}"


def _one_entry(hass, entry_id="entry-1"):
    hass.data[DOMAIN] = {entry_id: PurrViewClient(hass, host=HOST, port=PORT)}
    async_register_services(hass)


def _running(hass, aioclient_mock, profile_uuid="p1"):
    aioclient_mock.post(
        f"{BASE}/api/tasks/instances/get",
        json={
            "status": "success",
            "tasks": {
                "task-1": {
                    "config": {"typename": "StreamWatcherTask", "params": {"watch_profile_uuid": profile_uuid}},
                    "instance": {"status": "running"},
                }
            },
        },
    )
    aioclient_mock.post(f"{BASE}/api/tasks/instances/command", json={"status": "success"})


class TestStartRecording:
    async def test_sends_start_to_the_watcher_holding_that_profile(self, hass, aioclient_mock):
        _one_entry(hass)
        _running(hass, aioclient_mock)

        await hass.services.async_call(
            DOMAIN, SERVICE_START_RECORDING, {"profile_uuid": "p1", "source_uuid": "s1"}, blocking=True
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["taskUuid"] == "task-1"
        assert data["command"] == "start_recording"
        assert data["params"]["sourceUuid"] == "s1"

    async def test_an_omitted_duration_is_not_sent_at_all(self, hass, aioclient_mock):
        # The cap belongs to the watch profile. Sending a default from here would pin a
        # second number that silently disagreed the moment the profile's own changed.
        _one_entry(hass)
        _running(hass, aioclient_mock)

        await hass.services.async_call(
            DOMAIN, SERVICE_START_RECORDING, {"profile_uuid": "p1", "source_uuid": "s1"}, blocking=True
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert "maxDurationS" not in data["params"]

    async def test_a_given_duration_is_passed_through(self, hass, aioclient_mock):
        _one_entry(hass)
        _running(hass, aioclient_mock)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_START_RECORDING,
            {"profile_uuid": "p1", "source_uuid": "s1", "max_duration_s": 45},
            blocking=True,
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["params"]["maxDurationS"] == 45.0

    async def test_a_profile_nobody_is_watching_raises(self, hass, aioclient_mock):
        # Not swallowed: the automation believes it is recording, and nothing else would
        # ever tell it otherwise.
        _one_entry(hass)
        aioclient_mock.post(f"{BASE}/api/tasks/instances/get", json={"status": "success", "tasks": {}})

        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, SERVICE_START_RECORDING, {"profile_uuid": "p1", "source_uuid": "s1"}, blocking=True
            )


class TestStopRecording:
    async def test_sends_stop_to_the_watcher(self, hass, aioclient_mock):
        _one_entry(hass)
        _running(hass, aioclient_mock)

        await hass.services.async_call(
            DOMAIN, SERVICE_STOP_RECORDING, {"profile_uuid": "p1", "source_uuid": "s1"}, blocking=True
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["command"] == "stop_recording"

    async def test_stop_never_carries_a_duration(self, hass, aioclient_mock):
        # The schema has no field for it, and the client only attaches one when starting.
        _one_entry(hass)
        _running(hass, aioclient_mock)

        await hass.services.async_call(
            DOMAIN, SERVICE_STOP_RECORDING, {"profile_uuid": "p1", "source_uuid": "s1"}, blocking=True
        )

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["params"] == {"sourceUuid": "s1"}
