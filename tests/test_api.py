"""PurrViewClient: the thin JSON wrapper WP-4's media_source and services build on.

aioclient_mock intercepts calls the same way test_config_flow.py's reachability check
does - no real PurrView instance, matching this integration's existing test style.
"""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.purrview.api import (
    PurrViewApiError,
    PurrViewAuthError,
    PurrViewClient,
)
from custom_components.purrview.const import DOMAIN

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


class TestListLabels:
    async def test_a_response_without_labels_is_an_empty_tree(self, hass, aioclient_mock):
        """Same defensiveness as get_facets above: the card's Subject dropdown falls
        back to a flat list of refs when the tree is empty, rather than raising."""
        aioclient_mock.get(f"{BASE}/api/labels", json={"status": "success"})

        assert await _client(hass).list_labels() == []

    async def test_returns_the_label_rows(self, hass, aioclient_mock):
        aioclient_mock.get(
            f"{BASE}/api/labels",
            json={"status": "success", "labels": [{"uuid": "l1", "name": "Bowl", "parentUuid": None}]},
        )

        labels = await _client(hass).list_labels()

        assert [l["uuid"] for l in labels] == ["l1"]


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


class TestRejectedCredential:
    async def test_a_401_raises_an_auth_error_not_a_bare_transport_error(self, hass, aioclient_mock):
        """Every caller already handles PurrViewApiError, so the auth case subclasses
        it — but it has to be distinguishable, and its message has to name the token
        rather than surfacing an opaque 401."""
        aioclient_mock.get(f"{BASE}/api/labels", status=401)
        client = _client(hass, token="stale")

        with pytest.raises(PurrViewAuthError) as caught:
            await client.list_labels()

        assert isinstance(caught.value, PurrViewApiError)
        assert "token" in str(caught.value).lower()

    async def test_a_login_redirect_is_an_auth_error_not_a_json_decode_failure(self, hass, aioclient_mock):
        """With a password set and no token configured, PurrView bounces us to its
        login form. Following it would hand json() a page of HTML."""
        aioclient_mock.get(
            f"{BASE}/api/labels",
            status=303,
            headers={"location": "/login?next=%2F"},
            text="<html>login form</html>",
        )
        client = _client(hass)

        with pytest.raises(PurrViewAuthError):
            await client.list_labels()


class TestScheme:
    async def test_https_is_used_when_the_entry_asks_for_it(self, hass, aioclient_mock):
        """A PurrView behind a TLS reverse proxy was unreachable while the scheme was
        hardcoded: every call went to http:// regardless of how the entry was set up."""
        aioclient_mock.get(f"https://{HOST}:{PORT}/api/labels", json={"status": "success", "labels": []})

        client = PurrViewClient(hass, host=HOST, port=PORT, use_ssl=True)

        assert client.base_url == f"https://{HOST}:{PORT}"
        await client.list_labels()
        assert aioclient_mock.call_count == 1

    async def test_plain_http_remains_the_default(self, hass):
        """Entries created before the scheme was configurable carry no ssl key."""
        assert PurrViewClient(hass, host=HOST, port=PORT).base_url == f"http://{HOST}:{PORT}"


class TestReauthTrigger:
    async def test_a_refused_call_starts_a_reauth_flow(self, hass, aioclient_mock):
        """Nothing here polls PurrView, so a refused call is the only moment a rotated
        token is noticed. Without this the cards just fail until someone reads a log."""
        aioclient_mock.get(f"{BASE}/api/labels", status=401)
        entry = MockConfigEntry(domain=DOMAIN, data={"host": HOST, "port": PORT, "token": "stale"})
        entry.add_to_hass(hass)
        client = PurrViewClient(hass, host=HOST, port=PORT, token="stale", entry=entry)

        with pytest.raises(PurrViewAuthError):
            await client.list_labels()
        await hass.async_block_till_done()

        assert [f["context"]["source"] for f in hass.config_entries.flow.async_progress()] == ["reauth"]

    async def test_a_successful_call_starts_no_flow(self, hass, aioclient_mock):
        aioclient_mock.get(f"{BASE}/api/labels", json={"status": "success", "labels": []})
        entry = MockConfigEntry(domain=DOMAIN, data={"host": HOST, "port": PORT, "token": "good"})
        entry.add_to_hass(hass)

        await PurrViewClient(hass, host=HOST, port=PORT, token="good", entry=entry).list_labels()
        await hass.async_block_till_done()

        assert hass.config_entries.flow.async_progress() == []


class TestTrailingSlashRedirect:
    async def test_a_collection_redirect_is_followed(self, hass, aioclient_mock):
        """PurrView's collection routes answer the bare path with FastAPI's 307 to the
        trailing-slash form. Not following it left the events card with an empty body
        to decode, while the live card - which calls no such route - kept working."""
        aioclient_mock.get(
            f"{BASE}/api/watch-events",
            status=307,
            headers={"location": f"{BASE}/api/watch-events/?limit=5&offset=0"},
        )
        aioclient_mock.get(
            f"{BASE}/api/watch-events/",
            json={"status": "success", "events": [{"uuid": "e1"}], "total": 1},
        )

        events, total = await _client(hass).list_events(limit=5)

        assert [e["uuid"] for e in events] == ["e1"]
        assert total == 1

    async def test_the_query_is_not_sent_twice(self, hass, aioclient_mock):
        """The Location carries the query already; re-sending params as well would
        repeat every filter, and a repeated key is how this API spells a multi-select."""
        aioclient_mock.get(
            f"{BASE}/api/watch-events",
            status=307,
            headers={"location": f"{BASE}/api/watch-events/?limit=5&offset=0"},
        )
        aioclient_mock.get(f"{BASE}/api/watch-events/", json={"status": "success", "events": [], "total": 0})

        await _client(hass).list_events(limit=5)

        url = aioclient_mock.mock_calls[-1][1]
        assert sorted(url.query.getall("limit")) == ["5"]

    async def test_a_redirect_cannot_move_the_token_to_another_host(self, hass, aioclient_mock):
        """A Location is a value from the network. Only its path is used, so a hostile
        or misconfigured one cannot replay the Authorization header elsewhere."""
        aioclient_mock.get(
            f"{BASE}/api/labels",
            status=307,
            headers={"location": "http://evil.example/api/labels/"},
        )
        aioclient_mock.get(f"{BASE}/api/labels/", json={"status": "success", "labels": []})

        await _client(hass, token="s3cr3t").list_labels()

        assert aioclient_mock.mock_calls[-1][1].host == "192.168.1.50"

    async def test_a_login_bounce_is_still_not_followed(self, hass, aioclient_mock):
        """The reason allow_redirects was off in the first place."""
        aioclient_mock.get(
            f"{BASE}/api/labels",
            status=303,
            headers={"location": "/login?next=%2F"},
            text="<html>login</html>",
        )

        with pytest.raises(PurrViewAuthError):
            await _client(hass).list_labels()
