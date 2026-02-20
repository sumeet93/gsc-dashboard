"""Tests for GSC client (mocked API calls)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import date, timedelta

from database import get_all_sites, get_db


class TestDiscoverProperties:
    @patch("gsc_client._build_service")
    def test_discover_properties(self, mock_build):
        from gsc_client import discover_properties

        mock_service = MagicMock()
        mock_service.sites().list().execute.return_value = {
            "siteEntry": [
                {"siteUrl": "https://a.com/", "permissionLevel": "siteOwner"},
                {"siteUrl": "https://b.com/", "permissionLevel": "siteFullUser"},
            ]
        }

        result = discover_properties(mock_service)
        assert len(result) == 2
        assert result[0]["siteUrl"] == "https://a.com/"
        assert result[1]["permissionLevel"] == "siteFullUser"

    @patch("gsc_client._build_service")
    def test_discover_empty_properties(self, mock_build):
        from gsc_client import discover_properties

        mock_service = MagicMock()
        mock_service.sites().list().execute.return_value = {"siteEntry": []}
        result = discover_properties(mock_service)
        assert len(result) == 0


class TestFetchPropertyData:
    @patch("gsc_client._build_service")
    def test_fetch_property_data(self, mock_build):
        from gsc_client import fetch_property_data

        mock_service = MagicMock()
        mock_service.searchanalytics().query().execute.return_value = {
            "rows": [
                {"keys": ["keyword1", "/page1"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 5.0},
                {"keys": ["keyword2", "/page2"], "clicks": 5, "impressions": 50, "ctr": 0.1, "position": 12.0},
            ]
        }

        result = fetch_property_data(
            mock_service, "https://example.com/",
            date.today() - timedelta(days=7), date.today(),
        )
        assert len(result) == 2
        assert result[0]["keyword"] == "keyword1"
        assert result[0]["clicks"] == 10
        assert result[1]["page"] == "/page2"

    @patch("gsc_client._build_service")
    def test_fetch_property_data_empty(self, mock_build):
        from gsc_client import fetch_property_data

        mock_service = MagicMock()
        mock_service.searchanalytics().query().execute.return_value = {"rows": []}

        result = fetch_property_data(
            mock_service, "https://example.com/",
            date.today() - timedelta(days=7), date.today(),
        )
        assert len(result) == 0

    @patch("gsc_client._build_service")
    def test_fetch_handles_403(self, mock_build):
        from gsc_client import fetch_property_data
        from googleapiclient.errors import HttpError
        import httplib2

        mock_service = MagicMock()
        resp = httplib2.Response({"status": 403})
        mock_service.searchanalytics().query().execute.side_effect = HttpError(
            resp, b"Forbidden"
        )

        result = fetch_property_data(
            mock_service, "https://noaccess.com/",
            date.today() - timedelta(days=7), date.today(),
        )
        assert len(result) == 0


class TestSyncProperty:
    @patch("gsc_client.fetch_property_data")
    def test_sync_property(self, mock_fetch):
        from gsc_client import sync_property
        from database import upsert_site

        mock_fetch.return_value = [
            {"keyword": "kw1", "page": "/p1", "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 5.0},
        ]

        site_id = upsert_site("https://example.com/")
        mock_service = MagicMock()

        rows, error = sync_property(mock_service, "https://example.com/", site_id, days=3)
        assert rows > 0
        assert error == ""

    @patch("gsc_client.fetch_property_data")
    def test_sync_property_handles_error(self, mock_fetch):
        from gsc_client import sync_property
        from database import upsert_site

        mock_fetch.side_effect = Exception("API error")

        site_id = upsert_site("https://example.com/")
        mock_service = MagicMock()

        rows, error = sync_property(mock_service, "https://example.com/", site_id, days=1)
        assert rows == 0
        assert "API error" in error


class TestFullSync:
    @patch("gsc_client.sync_property")
    @patch("gsc_client.discover_properties")
    @patch("gsc_client._build_service")
    def test_full_sync(self, mock_build, mock_discover, mock_sync):
        from gsc_client import full_sync

        mock_discover.return_value = [
            {"siteUrl": "https://a.com/", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://b.com/", "permissionLevel": "siteOwner"},
        ]
        mock_sync.return_value = (100, "")

        result = full_sync(days=7)
        assert result["properties_discovered"] == 2
        assert result["sites_synced"] == 2
        assert result["status"] == "completed"

    @patch("gsc_client.sync_property")
    @patch("gsc_client.discover_properties")
    @patch("gsc_client._build_service")
    def test_full_sync_with_errors(self, mock_build, mock_discover, mock_sync):
        from gsc_client import full_sync

        mock_discover.return_value = [
            {"siteUrl": "https://a.com/", "permissionLevel": "siteOwner"},
        ]
        mock_sync.return_value = (0, "https://a.com/: access denied")

        result = full_sync(days=7)
        assert result["status"] == "completed_with_errors"
        assert len(result["errors"]) == 1
