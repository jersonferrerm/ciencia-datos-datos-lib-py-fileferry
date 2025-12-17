"""
Tests for MonitoringService.

Este módulo contiene las pruebas unitarias para el servicio de monitoreo
de transferencias.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.services.monitoring_service import MonitoringService
from src.exceptions.transfer_exceptions import ValidationError, TransferError


class TestMonitoringService:
    """Tests for MonitoringService class"""

    @pytest.fixture
    def mock_aws_client(self):
        """Mock AWS client"""
        return Mock()

    @pytest.fixture
    def monitoring_service(self, mock_aws_client):
        """MonitoringService instance with mocked dependencies"""
        return MonitoringService(aws_client=mock_aws_client)

    def test_determine_overall_status_partially_completed(self, monitoring_service):
        """Test that overall status is PARTIALLY_COMPLETED when there are both completed and failed files"""
        file_results = [
            {"StatusCode": "COMPLETED", "FilePath": "/path/file1.txt"},
            {"StatusCode": "FAILED", "FilePath": "/path/file2.txt", "FailureCode": "FILE_NOT_FOUND"},
            {"StatusCode": "COMPLETED", "FilePath": "/path/file3.txt"}
        ]

        status = monitoring_service._determine_overall_status(file_results, None)

        assert status == "PARTIALLY_COMPLETED"

    def test_determine_overall_status_completed(self, monitoring_service):
        """Test that overall status is COMPLETED when all files are completed"""
        file_results = [
            {"StatusCode": "COMPLETED", "FilePath": "/path/file1.txt"},
            {"StatusCode": "COMPLETED", "FilePath": "/path/file2.txt"},
            {"StatusCode": "COMPLETED", "FilePath": "/path/file3.txt"}
        ]

        status = monitoring_service._determine_overall_status(file_results, None)

        assert status == "COMPLETED"

    def test_determine_overall_status_failed(self, monitoring_service):
        """Test that overall status is FAILED when all files are failed"""
        file_results = [
            {"StatusCode": "FAILED", "FilePath": "/path/file1.txt", "FailureCode": "FILE_NOT_FOUND"},
            {"StatusCode": "FAILED", "FilePath": "/path/file2.txt", "FailureCode": "PERMISSION_DENIED"}
        ]

        status = monitoring_service._determine_overall_status(file_results, None)

        assert status == "FAILED"

    def test_determine_overall_status_in_progress(self, monitoring_service):
        """Test that overall status is IN_PROGRESS when there are files in progress"""
        file_results = [
            {"StatusCode": "COMPLETED", "FilePath": "/path/file1.txt"},
            {"StatusCode": "IN_PROGRESS", "FilePath": "/path/file2.txt"},
            {"StatusCode": "QUEUED", "FilePath": "/path/file3.txt"}
        ]

        status = monitoring_service._determine_overall_status(file_results, None)

        assert status == "IN_PROGRESS"

    def test_calculate_transfer_stats(self, monitoring_service):
        """Test transfer statistics calculation"""
        file_results = [
            {"StatusCode": "COMPLETED", "FilePath": "/path/file1.txt"},
            {"StatusCode": "FAILED", "FilePath": "/path/file2.txt"},
            {"StatusCode": "IN_PROGRESS", "FilePath": "/path/file3.txt"},
            {"StatusCode": "QUEUED", "FilePath": "/path/file4.txt"},
            {"StatusCode": "COMPLETED", "FilePath": "/path/file5.txt"}
        ]

        stats = monitoring_service._calculate_transfer_stats(file_results)

        assert stats["completed"] == 2
        assert stats["failed"] == 1
        assert stats["in_progress"] == 1
        assert stats["queued"] == 1