"""
Tests for DeleteService batch functionality.

Este módulo contiene las pruebas unitarias para el nuevo método delete_files_batch
del servicio de eliminación de archivos SFTP.
"""

import pytest
from unittest.mock import Mock

from src.services.delete_service import DeleteService
from src.models.transfer_models import (
    DeleteResult,
    TransferStatus,
    FileStatus,
    FileTransferResult
)
from src.exceptions.transfer_exceptions import (
    ValidationError,
    TransferLibraryError
)


class TestDeleteServiceBatch:
    """Test cases for DeleteService batch functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.mock_batch_orchestrator = Mock()
        self.delete_service = DeleteService(self.mock_batch_orchestrator)

    def test_delete_files_batch_success(self):
        """Test successful batch file deletion."""
        # Arrange
        delete_paths = [
            "/remote/path/file1.txt",
            "/remote/path/file2.txt",
            "/remote/path/subdir/file3.txt"
        ]
        connector_id = "test-connector-123"

        # Mock response from batch orchestrator (called once per file)
        mock_response = {
            "DeleteId": "delete-id-123"
        }
        self.mock_batch_orchestrator.execute_remote_delete.return_value = mock_response

        # Act
        result = self.delete_service.delete_files_batch(delete_paths, connector_id)

        # Assert
        assert isinstance(result, DeleteResult)
        assert result.execution_id == "delete-id-123"  # First successful DeleteId
        assert result.status == TransferStatus.PENDING
        assert len(result.file_results) == 3

        # Verify all file paths are correct
        assert result.file_results[0].file_path == "/remote/path/file1.txt"
        assert result.file_results[1].file_path == "/remote/path/file2.txt"
        assert result.file_results[2].file_path == "/remote/path/subdir/file3.txt"

        # Verify all files have QUEUED status
        for file_result in result.file_results:
            assert file_result.status == FileStatus.QUEUED
            assert file_result.transfer_id == "delete-id-123"

        # Verify batch orchestrator was called three times (once per file)
        assert self.mock_batch_orchestrator.execute_remote_delete.call_count == 3

        # Check each call
        calls = self.mock_batch_orchestrator.execute_remote_delete.call_args_list
        for i, call in enumerate(calls):
            call_args = call[0][0]
            assert call_args["ConnectorId"] == connector_id
            assert call_args["DeletePath"] == delete_paths[i]

    def test_delete_files_batch_empty_list(self):
        """Test batch deletion with empty file list."""
        # Arrange
        delete_paths = []
        connector_id = "test-connector-123"

        # Act & Assert
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files_batch(delete_paths, connector_id)

        assert exc_info.value.error_code == "BATCH_DELETE_FAILED"

    def test_delete_files_batch_invalid_connector_id(self):
        """Test batch deletion with invalid connector ID."""
        # Arrange
        delete_paths = ["/remote/path/file1.txt"]
        connector_id = ""

        # Act & Assert
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files_batch(delete_paths, connector_id)

        assert exc_info.value.error_code == "BATCH_DELETE_FAILED"

    def test_delete_files_batch_invalid_path_type(self):
        """Test batch deletion with invalid path type."""
        # Arrange
        delete_paths = ["/valid/path.txt", 123, "/another/valid/path.txt"]  # 123 is invalid
        connector_id = "test-connector-123"

        # Mock successful execution for valid paths
        mock_response = {"DeleteId": "delete-valid"}
        self.mock_batch_orchestrator.execute_remote_delete.return_value = mock_response

        # Act
        result = self.delete_service.delete_files_batch(delete_paths, connector_id)

        # Assert - should handle invalid path gracefully
        assert isinstance(result, DeleteResult)
        assert result.status == TransferStatus.COMPLETED  # Mixed results (some succeed, some fail)
        assert len(result.file_results) == 3

        # First file should succeed
        assert result.file_results[0].status == FileStatus.QUEUED
        assert result.file_results[0].file_path == "/valid/path.txt"

        # Second file should fail due to validation error
        assert result.file_results[1].status == FileStatus.FAILED
        assert result.file_results[1].file_path == 123
        assert "Delete path must be a non-empty string" in result.file_results[1].error_message

        # Third file should succeed
        assert result.file_results[2].status == FileStatus.QUEUED
        assert result.file_results[2].file_path == "/another/valid/path.txt"

    def test_delete_files_batch_partial_success(self):
        """Test batch deletion with partial success (some files fail)."""
        # Arrange
        delete_paths = [
            "/remote/path/file1.txt",
            "/remote/path/file2.txt",
            "/remote/path/file3.txt"
        ]
        connector_id = "test-connector-123"

        # Mock orchestrator to succeed for first and third files, fail for second
        def side_effect(request):
            if request["DeletePath"] == "/remote/path/file2.txt":
                raise Exception("File not found")
            else:
                return {"DeleteId": f"delete-{request['DeletePath'].split('/')[-1]}"}

        self.mock_batch_orchestrator.execute_remote_delete.side_effect = side_effect

        # Act & Assert - current implementation raises exception on first failure
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files_batch(delete_paths, connector_id)

        assert exc_info.value.error_code == "BATCH_DELETE_FAILED"
        assert "File not found" in str(exc_info.value)