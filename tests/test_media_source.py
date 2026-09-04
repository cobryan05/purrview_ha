"""PurrViewMediaSource: the browse tree and playback resolution (WP-4 step 3).

The test hass fixture defaults to US/Pacific, not UTC - bucket_start values below
are chosen mid-day in Pacific time (not near a day boundary) so the local-day
rollup in _browse_days is exercised for real, not accidentally passing because the
offset happened to be zero.
"""

from homeassistant.components.media_source.error import Unresolvable

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
from custom_components.purrview.media_source import PurrViewMediaSource

HOST = "192.168.1.50"
PORT = 7999
BASE = f"http://{HOST}:{PORT}"
ENTRY_ID = "entry-1"


def _source(hass) -> PurrViewMediaSource:
    hass.data[DOMAIN] = {ENTRY_ID: PurrViewClient(hass, host=HOST, port=PORT)}
    return PurrViewMediaSource(hass)


def _browse(hass, identifier: str):
    source = _source(hass)

    class _Item:
        pass

    item = _Item()
    item.identifier = identifier
    return source, item


class TestRootAndGroupings:
    async def test_single_entry_skips_straight_to_groupings(self, hass):
        source, item = _browse(hass, "")

        result = await source.async_browse_media(item)

        titles = [c.title for c in result.children]
        assert titles == ["By camera", "By subject", "By type", "Recent"]

    async def test_multiple_entries_are_listed_first(self, hass):
        hass.data[DOMAIN] = {
            "entry-1": PurrViewClient(hass, host="192.168.1.50", port=7999),
            "entry-2": PurrViewClient(hass, host="192.168.1.60", port=7999),
        }
        source = PurrViewMediaSource(hass)

        class _Item:
            identifier = ""

        result = await source.async_browse_media(_Item())

        assert {c.identifier for c in result.children} == {"entry-1", "entry-2"}

    async def test_no_configured_entries_is_unresolvable(self, hass):
        hass.data[DOMAIN] = {}
        source = PurrViewMediaSource(hass)

        class _Item:
            identifier = ""

        try:
            await source.async_browse_media(_Item())
        except Unresolvable:
            pass
        else:
            raise AssertionError("expected Unresolvable")

    async def test_unknown_entry_id_is_unresolvable(self, hass):
        source, item = _browse(hass, "no-such-entry")

        try:
            await source.async_browse_media(item)
        except Unresolvable:
            pass
        else:
            raise AssertionError("expected Unresolvable")

    async def test_unknown_grouping_is_unresolvable(self, hass):
        source, item = _browse(hass, f"{ENTRY_ID}/nonsense")

        try:
            await source.async_browse_media(item)
        except Unresolvable:
            pass
        else:
            raise AssertionError("expected Unresolvable")


class TestDimensionLevels:
    async def test_cameras_are_named_from_facets_and_counted_from_groups(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-events/groups",
            json={
                "status": "success",
                "groups": [
                    {"sourceUuid": "src-1", "ruleUuid": "r1", "count": 3},
                    {"sourceUuid": "src-1", "ruleUuid": "r2", "count": 2},
                    {"sourceUuid": "src-2", "ruleUuid": "r1", "count": 1},
                ],
            },
        )
        aioclient_mock.get(
            f"{BASE}/api/watch-events/facets",
            json={
                "status": "success",
                "sources": [{"ref": "src-1", "name": "Front door"}, {"ref": "src-2", "name": "Garage"}],
            },
        )
        source, item = _browse(hass, f"{ENTRY_ID}/by_camera")

        result = await source.async_browse_media(item)

        titles = {c.title for c in result.children}
        # src-1's two group rows (rules r1+r2) collapse into one folder, counts summed.
        assert titles == {"Front door (5)", "Garage (1)"}

    async def test_a_camera_with_no_facet_name_falls_back_to_its_ref(self, hass, aioclient_mock):
        """A camera that fired events but was since deleted from config still has to be
        browsable - facets is derived from history same as list_groups, but nothing
        guarantees the two calls race the same way, so a name lookup miss must degrade,
        not crash."""
        aioclient_mock.get(
            f"{BASE}/api/watch-events/groups",
            json={"status": "success", "groups": [{"sourceUuid": "src-9", "ruleUuid": "r1", "count": 1}]},
        )
        aioclient_mock.get(f"{BASE}/api/watch-events/facets", json={"status": "success", "sources": []})
        source, item = _browse(hass, f"{ENTRY_ID}/by_camera")

        result = await source.async_browse_media(item)

        assert result.children[0].title == "src-9 (1)"

    async def test_level_3_filters_by_the_level_2_selection(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-events/groups",
            json={"status": "success", "groups": [{"sourceUuid": "src-1", "ruleUuid": "r1", "count": 4}]},
        )
        aioclient_mock.get(
            f"{BASE}/api/watch-events/facets",
            json={
                "status": "success",
                "rules": [{"ref": "r1", "name": "Motion"}],
                "sources": [{"ref": "src-1", "name": "Front door"}],
            },
        )
        source, item = _browse(hass, f"{ENTRY_ID}/by_camera/src-1")

        result = await source.async_browse_media(item)

        assert result.title == "Front door"
        assert result.children[0].title == "Motion (4)"
        _, url, _, _ = aioclient_mock.mock_calls[-2]  # the /groups call, not /facets
        assert url.query["source_uuid"] == "src-1"


class TestDayLevel:
    async def test_local_days_are_composed_from_utc_hour_buckets(self, hass, aioclient_mock):
        # 18:00 UTC in June is 11:00 Pacific (PDT, UTC-7) - safely inside June 15th
        # local no matter which side of a naive day-boundary check you'd get wrong.
        aioclient_mock.get(
            f"{BASE}/api/watch-events/histogram",
            json={
                "status": "success",
                "bucket": "hour",
                "buckets": [
                    {"bucketStart": "2026-06-15T18:00:00", "count": 3},
                    {"bucketStart": "2026-06-15T19:00:00", "count": 2},
                    {"bucketStart": "2026-06-14T18:00:00", "count": 1},
                ],
            },
        )
        aioclient_mock.get(
            f"{BASE}/api/watch-events/facets",
            json={"status": "success", "rules": [{"ref": "r1", "name": "Motion"}]},
        )
        source, item = _browse(hass, f"{ENTRY_ID}/by_camera/src-1/r1")

        result = await source.async_browse_media(item)

        titles = {c.title for c in result.children}
        assert titles == {"2026-06-15 (5)", "2026-06-14 (1)"}


class TestEventLevel:
    async def test_only_events_with_a_complete_clip_are_listed(self, hass, aioclient_mock):
        """The conditional that matters: an event mid-extraction, or one whose clip
        expired out of the ring buffer, has nothing to play - listing it as a leaf
        would be a dead link in the media browser."""
        aioclient_mock.get(
            f"{BASE}/api/watch-events",
            json={
                "status": "success",
                "events": [
                    {
                        "uuid": "e1",
                        "startedAt": "2026-06-15T18:30:00",
                        "subjectName": "Tabby",
                        "hasSnapshot": True,
                        "recordings": [{"uuid": "rec-1", "kind": "clip", "status": "complete"}],
                    },
                    {
                        "uuid": "e2",
                        "startedAt": "2026-06-15T19:00:00",
                        "recordings": [{"uuid": "rec-2", "kind": "clip", "status": "pending"}],
                    },
                    {"uuid": "e3", "startedAt": "2026-06-15T19:30:00", "recordings": []},
                ],
                "total": 3,
            },
        )
        source, item = _browse(hass, f"{ENTRY_ID}/by_camera/src-1/r1/2026-06-15")

        result = await source.async_browse_media(item)

        assert [c.identifier for c in result.children] == [f"{ENTRY_ID}/event/e1"]
        assert result.children[0].can_play is True
        assert result.children[0].thumbnail == f"/api/purrview/{ENTRY_ID}/snapshot/e1"

    async def test_too_deep_identifier_is_unresolvable(self, hass):
        source, item = _browse(hass, f"{ENTRY_ID}/by_camera/src-1/r1/2026-06-15/extra")

        try:
            await source.async_browse_media(item)
        except Unresolvable:
            pass
        else:
            raise AssertionError("expected Unresolvable")


class TestRecent:
    async def test_recent_lists_playable_events_with_no_intermediate_levels(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-events",
            json={
                "status": "success",
                "events": [
                    {
                        "uuid": "e1",
                        "startedAt": "2026-06-15T18:30:00",
                        "ruleName": "Motion",
                        "hasSnapshot": False,
                        "recordings": [{"uuid": "rec-1", "kind": "clip", "status": "complete"}],
                    }
                ],
                "total": 1,
            },
        )
        source, item = _browse(hass, f"{ENTRY_ID}/recent")

        result = await source.async_browse_media(item)

        assert len(result.children) == 1
        assert result.children[0].thumbnail is None


class TestResolveMedia:
    async def test_resolves_to_the_clip_recording_through_the_proxy(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-events/e1",
            json={
                "status": "success",
                "event": {"uuid": "e1", "recordings": [{"uuid": "rec-1", "kind": "clip", "status": "complete"}]},
            },
        )
        source, item = _browse(hass, f"{ENTRY_ID}/event/e1")

        result = await source.async_resolve_media(item)

        assert result.url == f"/api/purrview/{ENTRY_ID}/recording/rec-1"
        assert result.mime_type == "video/mp4"

    async def test_an_event_with_no_complete_clip_is_unresolvable(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-events/e1",
            json={
                "status": "success",
                "event": {"uuid": "e1", "recordings": [{"uuid": "rec-1", "kind": "timelapse", "status": "complete"}]},
            },
        )
        source, item = _browse(hass, f"{ENTRY_ID}/event/e1")

        try:
            await source.async_resolve_media(item)
        except Unresolvable:
            pass
        else:
            raise AssertionError("expected Unresolvable")

    async def test_a_deleted_event_is_unresolvable_not_a_crash(self, hass, aioclient_mock):
        aioclient_mock.get(f"{BASE}/api/watch-events/e1", json={"status": "failure", "message": "not found"})
        source, item = _browse(hass, f"{ENTRY_ID}/event/e1")

        try:
            await source.async_resolve_media(item)
        except Unresolvable:
            pass
        else:
            raise AssertionError("expected Unresolvable")

    async def test_a_malformed_identifier_is_unresolvable(self, hass):
        source, item = _browse(hass, f"{ENTRY_ID}/by_camera")  # a folder, not a leaf

        try:
            await source.async_resolve_media(item)
        except Unresolvable:
            pass
        else:
            raise AssertionError("expected Unresolvable")
