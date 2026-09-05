"""PurrViewEventGroupsView/PurrViewEventHistogramView: back the timeline view's lanes
and marks, the same way test_events_view.py covers the grid/filter-bar views.
"""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.setup import async_setup_component

from custom_components.purrview.api import PurrViewClient
from custom_components.purrview.const import DOMAIN
from custom_components.purrview.events import PurrViewEventGroupsView, PurrViewEventHistogramView


async def _register(hass, *, groups=None, groups_side_effect=None, histogram_result=None, histogram_side_effect=None):
    await async_setup_component(hass, "http", {})
    client = MagicMock(spec=PurrViewClient)
    if groups_side_effect is not None:
        client.list_groups = AsyncMock(side_effect=groups_side_effect)
    else:
        client.list_groups = AsyncMock(return_value=groups or [])
    if histogram_side_effect is not None:
        client.histogram = AsyncMock(side_effect=histogram_side_effect)
    else:
        client.histogram = AsyncMock(return_value=histogram_result or ("hour", []))
    hass.data[DOMAIN] = {"entry-1": client}
    hass.http.register_view(PurrViewEventGroupsView(hass))
    hass.http.register_view(PurrViewEventHistogramView(hass))
    return client


class TestGroupsHappyPath:
    async def test_returns_groups(self, hass, hass_client):
        await _register(hass, groups=[{"subjectRef": "s1", "subjectName": "Kitty", "count": 5}])
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-groups")

        assert resp.status == 200
        assert (await resp.json())["groups"] == [{"subjectRef": "s1", "subjectName": "Kitty", "count": 5}]

    async def test_forwards_only_allowlisted_filters(self, hass, hass_client):
        purrview_client = await _register(hass)
        client = await hass_client()

        await client.get("/api/purrview/entry-1/event-groups?source_uuids=s1&not_a_real_filter=x")

        purrview_client.list_groups.assert_awaited_once_with(source_uuids=["s1"])

    async def test_repeated_keys_become_a_multi_select_list(self, hass, hass_client):
        purrview_client = await _register(hass)
        client = await hass_client()

        await client.get("/api/purrview/entry-1/event-groups?subject_refs=a&subject_refs=b")

        purrview_client.list_groups.assert_awaited_once_with(subject_refs=["a", "b"])


class TestGroupsErrors:
    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/event-groups")

        assert resp.status == 404

    async def test_purrview_error_becomes_502(self, hass, hass_client):
        from custom_components.purrview.api import PurrViewApiError

        await _register(hass, groups_side_effect=PurrViewApiError("db unavailable"))
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-groups")

        assert resp.status == 502


class TestHistogramHappyPath:
    async def test_returns_resolved_bucket_and_buckets(self, hass, hass_client):
        await _register(hass, histogram_result=("day", [{"bucketStart": "2026-09-01T00:00:00", "count": 3}]))
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-histogram?bucket=hour")

        assert resp.status == 200
        body = await resp.json()
        # The resolved bucket can legitimately differ from what was requested - a wide
        # range coarsens server-side rather than silently truncating.
        assert body["bucket"] == "day"
        assert body["buckets"] == [{"bucketStart": "2026-09-01T00:00:00", "count": 3}]

    async def test_defaults_to_hour_bucket_when_unspecified(self, hass, hass_client):
        purrview_client = await _register(hass)
        client = await hass_client()

        await client.get("/api/purrview/entry-1/event-histogram")

        purrview_client.histogram.assert_awaited_once_with(bucket="hour")

    async def test_forwards_only_allowlisted_filters(self, hass, hass_client):
        purrview_client = await _register(hass)
        client = await hass_client()

        await client.get("/api/purrview/entry-1/event-histogram?bucket=day&subject_refs=s1&bogus=x")

        purrview_client.histogram.assert_awaited_once_with(bucket="day", subject_refs=["s1"])


class TestHistogramErrors:
    async def test_unknown_entry_id_is_404(self, hass, hass_client):
        await _register(hass)
        client = await hass_client()

        resp = await client.get("/api/purrview/no-such-entry/event-histogram")

        assert resp.status == 404

    async def test_purrview_error_becomes_502(self, hass, hass_client):
        from custom_components.purrview.api import PurrViewApiError

        await _register(hass, histogram_side_effect=PurrViewApiError("db unavailable"))
        client = await hass_client()

        resp = await client.get("/api/purrview/entry-1/event-histogram")

        assert resp.status == 502


class TestRequiresAuth:
    async def test_groups_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        await _register(hass)
        client = await hass_client_no_auth()

        resp = await client.get("/api/purrview/entry-1/event-groups")

        assert resp.status == 401

    async def test_histogram_without_hass_auth_is_rejected(self, hass, hass_client_no_auth):
        await _register(hass)
        client = await hass_client_no_auth()

        resp = await client.get("/api/purrview/entry-1/event-histogram")

        assert resp.status == 401
