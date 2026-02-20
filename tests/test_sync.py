"""Tests for sync.py CLI tool."""

from __future__ import annotations

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

import sync


class TestSyncCLI:
    """Test sync.py command-line tool."""

    @patch("sync.init_db")
    @patch("sync.full_sync")
    def test_sync_default_days(self, mock_sync, mock_init_db):
        """Test sync with default 7 days."""
        mock_sync.return_value = {
            "properties_discovered": 2,
            "sites_synced": 2,
            "total_rows": 150,
            "status": "completed",
            "errors": [],
        }

        with patch.object(sys, "argv", ["sync.py"]):
            result = sync.main()

        assert result == 0
        mock_init_db.assert_called_once()
        mock_sync.assert_called_once_with(7)

    @patch("sync.init_db")
    @patch("sync.full_sync")
    def test_sync_custom_days(self, mock_sync, mock_init_db):
        """Test sync with custom days parameter."""
        mock_sync.return_value = {
            "properties_discovered": 3,
            "sites_synced": 3,
            "total_rows": 500,
            "status": "completed",
            "errors": [],
        }

        with patch.object(sys, "argv", ["sync.py", "--days", "14"]):
            result = sync.main()

        assert result == 0
        mock_sync.assert_called_once_with(14)

    @patch("sync.init_db")
    @patch("sync.full_sync")
    def test_sync_initial_flag(self, mock_sync, mock_init_db):
        """Test sync with --initial flag (90 days)."""
        mock_sync.return_value = {
            "properties_discovered": 5,
            "sites_synced": 5,
            "total_rows": 10000,
            "status": "completed",
            "errors": [],
        }

        with patch.object(sys, "argv", ["sync.py", "--initial"]):
            result = sync.main()

        assert result == 0
        mock_sync.assert_called_once_with(90)

    @patch("sync.init_db")
    @patch("sync.full_sync")
    def test_sync_with_errors(self, mock_sync, mock_init_db):
        """Test sync that completes with errors."""
        mock_sync.return_value = {
            "properties_discovered": 3,
            "sites_synced": 2,
            "total_rows": 200,
            "status": "partial",
            "errors": ["Error fetching site1", "403 forbidden on site2"],
        }

        with patch.object(sys, "argv", ["sync.py"]):
            result = sync.main()

        # Should return 1 (error) when status != "completed"
        assert result == 1

    @patch("sync.init_db")
    @patch("sync.full_sync")
    def test_sync_output_formatting(self, mock_sync, mock_init_db, capsys):
        """Test that sync prints formatted output."""
        mock_sync.return_value = {
            "properties_discovered": 2,
            "sites_synced": 2,
            "total_rows": 1234567,
            "status": "completed",
            "errors": [],
        }

        with patch.object(sys, "argv", ["sync.py", "--days", "30"]):
            sync.main()

        captured = capsys.readouterr()
        assert "Starting GSC sync for 30 days" in captured.out
        assert "Properties discovered: 2" in captured.out
        assert "Sites synced: 2" in captured.out
        assert "1,234,567" in captured.out  # Check number formatting
        assert "Status: completed" in captured.out

    @patch("sync.init_db")
    @patch("sync.full_sync")
    def test_sync_prints_errors(self, mock_sync, mock_init_db, capsys):
        """Test that errors are printed to stdout."""
        mock_sync.return_value = {
            "properties_discovered": 2,
            "sites_synced": 1,
            "total_rows": 100,
            "status": "partial",
            "errors": ["Failed to sync example.com", "Timeout on test.com"],
        }

        with patch.object(sys, "argv", ["sync.py"]):
            sync.main()

        captured = capsys.readouterr()
        assert "Errors (2):" in captured.out
        assert "Failed to sync example.com" in captured.out
        assert "Timeout on test.com" in captured.out
