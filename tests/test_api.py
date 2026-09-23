"""PurrViewClient: the thin JSON wrapper WP-4's media_source and services build on.

aioclient_mock intercepts calls the same way test_config_flow.py's reachability check
does - no real PurrView instance, matching this integration's existing test style.
"""

from custom_components.purrview.api import PurrViewApiError, PurrViewClient

HOST = "192.168.1.50"
PORT = 7999
BASE = f"http://{HOST}:{PORT}"


def _client(hass, token=None):
    return PurrViewClient(hass, host=HOST, port=PORT, token=token)


class TestAuthHeaders:
    async def test_no_token_sends_no_authorization_header(self, hass, aioclient_mock):
        aioclient_mock.get(f"{BASE}/api/watch-events/facets", json={"status": "success"})

        await _client(hass).get_facets()

        _, _, _, headers = aioclient_mock.mock_calls[-1]
        assert "Authorization" not in headers

    async def test_token_is_sent_as_a_bearer_header(self, hass, aioclient_mock):
        aioclient_mock.get(f"{BASE}/api/watch-events/facets", json={"status": "success"})

        await _client(hass, token="s3cr3t").get_facets()

        _, _, _, headers = aioclient_mock.mock_calls[-1]
        assert headers["Authorization"] == "Bearer s3cr3t"


class TestFacets:
    async def test_missing_facet_groups_default_to_empty_lists(self, hass, aioclient_mock):
        """PurrView's WatchEventFacetsResponse always includes all four - this is about
        not crashing media_source's tree-building against a response some future
        PurrView version trims, not a case that happens today."""
        aioclient_mock.get(
            f"{BASE}/api/watch-events/facets",
            json={"status": "success", "rules": [{"ref": "r1", "name": "Front door"}]},
        )

        facets = await _client(hass).get_facets()

        assert facets["rules"] == [{"ref": "r1", "name": "Front door"}]
        assert facets["subjects"] == []
        assert facets["targets"] == []
        assert facets["sources"] == []


class TestListWatchProfiles:
    async def test_returns_uuid_name_and_enabled(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-profiles",
            json={
                "status": "success",
                "profiles": [
                    {"uuid": "p1", "name": "Cat Watcher", "enabled": True, "trackerTypename": "ignored"},
                    {"uuid": "p2", "name": "Disabled Cam", "enabled": False},
                ],
            },
        )

        profiles = await _client(hass).list_watch_profiles()

        assert profiles == [
            {"uuid": "p1", "name": "Cat Watcher", "enabled": True},
            {"uuid": "p2", "name": "Disabled Cam", "enabled": False},
        ]

    async def test_missing_enabled_defaults_to_true(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-profiles",
            json={"status": "success", "profiles": [{"uuid": "p1", "name": "Cat Watcher"}]},
        )

        profiles = await _client(hass).list_watch_profiles()

        assert profiles == [{"uuid": "p1", "name": "Cat Watcher", "enabled": True}]

    async def test_no_profiles_is_an_empty_list_not_a_crash(self, hass, aioclient_mock):
        aioclient_mock.get(f"{BASE}/api/watch-profiles", json={"status": "success"})

        assert await _client(hass).list_watch_profiles() == []


class TestGetWatchProfileSources:
    async def test_joins_profile_links_with_source_names_in_configured_order(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-profiles/p1",
            json={
                "status": "success",
                "profile": {
                    "sources": [
                        {"sourceUuid": "s2", "order": 1, "enabled": True},
                        {"sourceUuid": "s1", "order": 0, "enabled": True},
                    ]
                },
            },
        )
        aioclient_mock.get(
            f"{BASE}/api/sources/get",
            json={"status": "success", "sources": {"s1": {"name": "Laundry"}, "s2": {"name": "Garage"}}},
        )

        sources = await _client(hass).get_watch_profile_sources("p1")

        assert sources == [{"uuid": "s1", "name": "Laundry"}, {"uuid": "s2", "name": "Garage"}]

    async def test_disabled_links_are_excluded(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-profiles/p1",
            json={
                "status": "success",
                "profile": {
                    "sources": [
                        {"sourceUuid": "s1", "order": 0, "enabled": True},
                        {"sourceUuid": "s2", "order": 1, "enabled": False},
                    ]
                },
            },
        )
        aioclient_mock.get(
            f"{BASE}/api/sources/get",
            json={"status": "success", "sources": {"s1": {"name": "Laundry"}, "s2": {"name": "Garage"}}},
        )

        sources = await _client(hass).get_watch_profile_sources("p1")

        assert sources == [{"uuid": "s1", "name": "Laundry"}]

    async def test_a_source_missing_from_sources_get_falls_back_to_its_uuid(self, hass, aioclient_mock):
        """A source deleted after being linked to a profile shouldn't crash the
        editor's camera picker - it should just show something, its own uuid."""
        aioclient_mock.get(
            f"{BASE}/api/watch-profiles/p1",
            json={"status": "success", "profile": {"sources": [{"sourceUuid": "s1", "order": 0, "enabled": True}]}},
        )
        aioclient_mock.get(f"{BASE}/api/sources/get", json={"status": "success", "sources": {}})

        sources = await _client(hass).get_watch_profile_sources("p1")

        assert sources == [{"uuid": "s1", "name": "s1"}]


class TestListEvents:
    async def test_limit_and_offset_are_passed_through_as_query_params(self, hass, aioclient_mock):
        aioclient_mock.get(f"{BASE}/api/watch-events", json={"status": "success", "events": [], "total": 0})

        await _client(hass).list_events(limit=50, offset=100, source_uuid="src-1")

        _, url, _, _ = aioclient_mock.mock_calls[-1]
        assert url.query["limit"] == "50"
        assert url.query["offset"] == "100"
        assert url.query["source_uuid"] == "src-1"

    async def test_a_list_filter_is_sent_as_repeated_query_keys(self, hass, aioclient_mock):
        """A multi-select filter (source_uuids=[...]) must hit the wire as one repeated
        key per item (?source_uuids=a&source_uuids=b), not a comma-joined string -
        that's the shape WatchEventQuery's own Query(None) list params parse."""
        aioclient_mock.get(f"{BASE}/api/watch-events", json={"status": "success", "events": [], "total": 0})

        await _client(hass).list_events(source_uuids=["s1", "s2"])

        _, url, _, _ = aioclient_mock.mock_calls[-1]
        assert url.query.getall("source_uuids") == ["s1", "s2"]

    async def test_none_filters_are_dropped_not_sent_as_the_string_none(self, hass, aioclient_mock):
        """A caller building filters from optional UI state (e.g. no camera selected)
        passes None for the ones that are not set - those must not become a literal
        `?rule_uuid=None` PurrView would try to match against."""
        aioclient_mock.get(f"{BASE}/api/watch-events", json={"status": "success", "events": [], "total": 0})

        await _client(hass).list_events(rule_uuid=None, source_uuid="src-1")

        _, url, _, _ = aioclient_mock.mock_calls[-1]
        assert "rule_uuid" not in url.query
        assert url.query["source_uuid"] == "src-1"

    async def test_returns_events_and_total(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-events",
            json={"status": "success", "events": [{"uuid": "e1"}], "total": 42},
        )

        events, total = await _client(hass).list_events()

        assert events == [{"uuid": "e1"}]
        assert total == 42


class TestFailureEnvelope:
    async def test_a_status_failure_body_raises_even_with_http_200(self, hass, aioclient_mock):
        """PurrView reports a rejected request in the JSON body, not the status code -
        the conditional that matters is that a 200 does not silently read as success."""
        aioclient_mock.get(
            f"{BASE}/api/watch-events/facets",
            json={"status": "failure", "message": "db unavailable"},
        )

        try:
            await _client(hass).get_facets()
        except PurrViewApiError as err:
            assert "db unavailable" in str(err)
        else:
            raise AssertionError("expected PurrViewApiError")


class TestFlagEvent:
    async def test_reason_and_note_land_under_metadata_flag(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/watch-events/e1",
            json={"status": "success", "event": {"uuid": "e1", "metadataJson": {}}},
        )
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await _client(hass).flag_event("e1", reason="wrong_labels", note="not a cat")

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["reviewState"] == "flagged"
        assert data["metadataJson"]["flag"] == {
            "reason": "wrong_labels",
            "note": "not a cat",
            "source": "home_assistant",
        }

    async def test_existing_metadata_is_preserved_not_overwritten(self, hass, aioclient_mock):
        """The regression this test exists for: a bare PATCH carrying only metadataJson
        replaces the whole column server-side. Flagging an event that already has other
        metadata (e.g. a prior blip note) must not erase it."""
        aioclient_mock.get(
            f"{BASE}/api/watch-events/e1",
            json={
                "status": "success",
                "event": {"uuid": "e1", "metadataJson": {"other_field": "keep me"}},
            },
        )
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await _client(hass).flag_event("e1", reason="wrong_labels")

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["metadataJson"]["other_field"] == "keep me"
        assert data["metadataJson"]["flag"]["reason"] == "wrong_labels"

    async def test_missing_event_still_flags_with_empty_prior_metadata(self, hass, aioclient_mock):
        """get_event returns None on a 404 (or any failure envelope) - flagging must not
        crash on a race where the event was deleted between listing and flagging it."""
        aioclient_mock.get(f"{BASE}/api/watch-events/e1", json={"status": "failure", "message": "not found"})
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await _client(hass).flag_event("e1", reason="wrong_labels")

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["metadataJson"] == {"flag": {"reason": "wrong_labels", "note": "", "source": "home_assistant"}}

    async def test_unflagging_reverts_review_state_and_drops_flag_metadata(self, hass, aioclient_mock):
        """flagged=False is the undo for an accidental flag click - review_state must
        go back to "unreviewed", and the stale reason/note must not survive to be
        inherited by a future re-flag."""
        aioclient_mock.get(
            f"{BASE}/api/watch-events/e1",
            json={
                "status": "success",
                "event": {
                    "uuid": "e1",
                    "metadataJson": {"flag": {"reason": "wrong_labels", "note": "", "source": "home_assistant"}},
                },
            },
        )
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await _client(hass).flag_event("e1", reason="wrong_labels", flagged=False)

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data["reviewState"] == "unreviewed"
        assert "flag" not in data["metadataJson"]


class TestSetEventPinned:
    async def test_pinning_sends_a_bare_patch(self, hass, aioclient_mock):
        """No read-modify-write like flag_event - pinned is its own column, not
        something folded into metadata_json this call could clobber."""
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await _client(hass).set_event_pinned("e1", True)

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data == {"pinned": True}

    async def test_unpinning_sends_pinned_false(self, hass, aioclient_mock):
        aioclient_mock.patch(f"{BASE}/api/watch-events/e1", json={"status": "success"})

        await _client(hass).set_event_pinned("e1", False)

        _, _, data, _ = aioclient_mock.mock_calls[-1]
        assert data == {"pinned": False}
