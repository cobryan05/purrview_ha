"""PurrViewClient.get_running_watcher_tasks / get_live_preview (WP-5 backend).

There is no "list running watchers" endpoint on PurrView's side - these resolve a
watch profile to its currently-running task the same way the app's own NVR pane
does client-side (fetchRunningWatchers in main.js): from the full task-instance
listing, filtered by typename and by an in-progress status.
"""

from custom_components.purrview.api import PurrViewClient

HOST = "192.168.1.50"
PORT = 7999
BASE = f"http://{HOST}:{PORT}"


def _client(hass) -> PurrViewClient:
    return PurrViewClient(hass, host=HOST, port=PORT)


def _task(typename="StreamWatcherTask", status="running", profile_uuid="p1"):
    return {
        "config": {"typename": typename, "params": {"watch_profile_uuid": profile_uuid}},
        "instance": {"status": status},
    }


class TestGetRunningWatcherTasks:
    async def test_returns_running_watchers_with_their_profile(self, hass, aioclient_mock):
        aioclient_mock.post(
            f"{BASE}/api/tasks/instances/get",
            json={"status": "success", "tasks": {"task-1": _task(profile_uuid="p1")}},
        )

        result = await _client(hass).get_running_watcher_tasks()

        assert result == [{"taskUuid": "task-1", "profileUuid": "p1"}]

    async def test_a_stopped_watchers_retained_instance_is_excluded(self, hass, aioclient_mock):
        """A watcher's instance row is retained after it stops - listing it as
        running would send the card polling a task with no live view forever."""
        aioclient_mock.post(
            f"{BASE}/api/tasks/instances/get",
            json={"status": "success", "tasks": {"task-1": _task(status="finished")}},
        )

        assert await _client(hass).get_running_watcher_tasks() == []

    async def test_non_watcher_tasks_are_excluded(self, hass, aioclient_mock):
        aioclient_mock.post(
            f"{BASE}/api/tasks/instances/get",
            json={"status": "success", "tasks": {"task-1": _task(typename="TrainModelTask")}},
        )

        assert await _client(hass).get_running_watcher_tasks() == []

    async def test_a_watcher_with_no_profile_uuid_is_excluded_not_crashed_on(self, hass, aioclient_mock):
        task = _task()
        task["config"]["params"] = {}
        aioclient_mock.post(f"{BASE}/api/tasks/instances/get", json={"status": "success", "tasks": {"task-1": task}})

        assert await _client(hass).get_running_watcher_tasks() == []

    async def test_paused_and_pending_count_as_running(self, hass, aioclient_mock):
        aioclient_mock.post(
            f"{BASE}/api/tasks/instances/get",
            json={
                "status": "success",
                "tasks": {
                    "t-paused": _task(status="paused", profile_uuid="p1"),
                    "t-pending": _task(status="pending", profile_uuid="p2"),
                },
            },
        )

        result = await _client(hass).get_running_watcher_tasks()

        assert {r["profileUuid"] for r in result} == {"p1", "p2"}


class TestGetLivePreview:
    async def test_returns_none_when_the_profile_has_no_running_watcher(self, hass, aioclient_mock):
        aioclient_mock.post(f"{BASE}/api/tasks/instances/get", json={"status": "success", "tasks": {}})

        result = await _client(hass).get_live_preview(profile_uuid="p1")

        assert result is None

    async def test_resolves_the_matching_tasks_live_preview(self, hass, aioclient_mock):
        aioclient_mock.post(
            f"{BASE}/api/tasks/instances/get",
            json={"status": "success", "tasks": {"task-1": _task(profile_uuid="p1")}},
        )
        aioclient_mock.get(
            f"{BASE}/api/tasks/instances/task-1/live-preview",
            json={"status": "success", "preview": {"frameSeq": 7}},
        )

        result = await _client(hass).get_live_preview(profile_uuid="p1")

        assert result == {"frameSeq": 7}

    async def test_since_seq_and_source_uuid_are_passed_through(self, hass, aioclient_mock):
        aioclient_mock.post(
            f"{BASE}/api/tasks/instances/get",
            json={"status": "success", "tasks": {"task-1": _task(profile_uuid="p1")}},
        )
        aioclient_mock.get(f"{BASE}/api/tasks/instances/task-1/live-preview", json={"status": "success", "preview": {}})

        await _client(hass).get_live_preview(profile_uuid="p1", source_uuid="src-1", since_seq=42)

        _, url, _, _ = aioclient_mock.mock_calls[-1]
        assert url.query["source_uuid"] == "src-1"
        assert url.query["since_seq"] == "42"

    async def test_since_seq_zero_is_sent_not_dropped(self, hass, aioclient_mock):
        """0 is a legitimate seq (no frame yet) - _query_params must not treat it as
        falsy the way it treats None, or the very first poll after a restart would
        silently ask for every frame again instead of "since the start"."""
        aioclient_mock.post(
            f"{BASE}/api/tasks/instances/get",
            json={"status": "success", "tasks": {"task-1": _task(profile_uuid="p1")}},
        )
        aioclient_mock.get(f"{BASE}/api/tasks/instances/task-1/live-preview", json={"status": "success", "preview": {}})

        await _client(hass).get_live_preview(profile_uuid="p1", since_seq=0)

        _, url, _, _ = aioclient_mock.mock_calls[-1]
        assert url.query["since_seq"] == "0"

    async def test_full_true_is_sent_only_when_requested(self, hass, aioclient_mock):
        aioclient_mock.post(
            f"{BASE}/api/tasks/instances/get",
            json={"status": "success", "tasks": {"task-1": _task(profile_uuid="p1")}},
        )
        aioclient_mock.get(f"{BASE}/api/tasks/instances/task-1/live-preview", json={"status": "success", "preview": {}})

        await _client(hass).get_live_preview(profile_uuid="p1", full=True)

        _, url, _, _ = aioclient_mock.mock_calls[-1]
        assert url.query["full"] == "true"
