"""
Unit tests for DeleteService.

Este módulo contiene las pruebas unitarias para el servicio de eliminación
de archivos SFTP.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.services.delete_service import DeleteService
from src.models.transfer_models import (
    FileDeleteRequest,
    TransferRequest,
    TransferType,
    DeleteResult,
    TransferStatus,
    FileStatus
)
from src.exceptions.transfer_exceptions import (
    ValidationError,
    TransferLibraryError
)


class TestDeleteService:
    """Test cases for DeleteService."""

    def setup_method(self):
        """Setup test fixtures."""
        self.mock_batch_orchestrator = Mock()
        self.delete_service = DeleteService(self.mock_batch_orchestrator)

    def test_delete_files_success(self):
        """Test successful file deletion."""
        # Arrange
        files = [
            FileDeleteRequest(file_path="/remote/path/file1.txt"),
            FileDeleteRequest(file_path="/remote/path/file2.txt")
        ]
        connector_id = "test-connector-123"

        # Mock response from batch orchestrator (called once per file)
        mock_response = {
            "DeleteId": "exec-123"
        }
        self.mock_batch_orchestrator.execute_remote_delete.return_value = mock_response

        # Act
        result = self.delete_service.delete_files(files, connector_id)

        # Assert
        assert isinstance(result, DeleteResult)
        assert result.execution_id == "exec-123"  # First successful DeleteId
        assert result.status == TransferStatus.PENDING
        assert len(result.file_results) == 2
        assert result.file_results[0].file_path == "/remote/path/file1.txt"
        assert result.file_results[1].file_path == "/remote/path/file2.txt"

        # Verify batch orchestrator was called twice (once per file)
        assert self.mock_batch_orchestrator.execute_remote_delete.call_count == 2

        # Check first call
        first_call_args = self.mock_batch_orchestrator.execute_remote_delete.call_args_list[0][0][0]
        assert first_call_args["ConnectorId"] == connector_id
        assert first_call_args["DeletePath"] == "/remote/path/file1.txt"

        # Check second call
        second_call_args = self.mock_batch_orchestrator.execute_remote_delete.call_args_list[1][0][0]
        assert second_call_args["ConnectorId"] == connector_id
        assert second_call_args["DeletePath"] == "/remote/path/file2.txt"

    def test_delete_files_empty_list(self):
        """Test deletion with empty file list."""
        # Arrange
        files = []
        connector_id = "test-connector-123"

        # Act & Assert
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files(files, connector_id)

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"

    def test_delete_files_invalid_connector_id(self):
        """Test deletion with invalid connector ID."""
        # Arrange
        files = [FileDeleteRequest(file_path="/remote/path/file1.txt")]
        connector_id = ""

        # Act & Assert
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files(files, connector_id)

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"

    def test_delete_files_invalid_file_type(self):
        """Test deletion with invalid file type."""
        # Arrange
        files = ["not_a_file_delete_request"]
        connector_id = "test-connector-123"

        # Act & Assert
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files(files, connector_id)

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"

    def test_delete_files_directory_path(self):
        """Test deletion with directory path (should succeed now)."""
        # Arrange
        files = [FileDeleteRequest(file_path="/remote/path/directory/")]
        connector_id = "test-connector-123"

        # Mock response from batch orchestrator
        mock_response = {"DeleteId": "exec-456"}
        self.mock_batch_orchestrator.execute_remote_delete.return_value = mock_response

        # Act
        result = self.delete_service.delete_files(files, connector_id)

        # Assert - directories can now be deleted
        assert isinstance(result, DeleteResult)
        assert result.execution_id == "exec-456"
        assert len(result.file_results) == 1
        assert result.file_results[0].file_path == "/remote/path/directory/"

    def test_delete_files_missing_file_path(self):
        """Test deletion with missing file path."""
        # Arrange
        files = [FileDeleteRequest(file_path="")]
        connector_id = "test-connector-123"

        # Act & Assert
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files(files, connector_id)

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"

    def test_execute_transfer_wrong_type(self):
        """Test execute_transfer with wrong transfer type."""
        # Arrange
        files = [FileDeleteRequest(file_path="/remote/path/file1.txt")]
        request = TransferRequest(
            files=[],  # Not used for this test
            connector_id="test-connector-123",
            transfer_type=TransferType.UPLOAD  # Wrong type
        )

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            self.delete_service.execute_transfer(request)

        assert exc_info.value.error_code == "INVALID_TRANSFER_TYPE"

    def test_delete_files_orchestrator_error(self):
        """Test deletion when batch orchestrator raises error."""
        # Arrange
        files = [FileDeleteRequest(file_path="/remote/path/file1.txt")]
        connector_id = "test-connector-123"

        # Mock orchestrator to raise error
        self.mock_batch_orchestrator.execute_remote_delete.side_effect = Exception("AWS Error")

        # Act & Assert - current implementation raises exception instead of returning failed result
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files(files, connector_id)

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "AWS Error" in str(exc_info.value)

    def test_delete_files_with_metadata(self):
        """Test deletion with file metadata."""
        # Arrange
        files = [
            FileDeleteRequest(
                file_path="/remote/path/file1.txt",
                metadata={"reason": "cleanup", "user": "admin"}
            )
        ]
        connector_id = "test-connector-123"

        # Mock response
        mock_response = {"DeleteId": "exec-456"}
        self.mock_batch_orchestrator.execute_remote_delete.return_value = mock_response

        # Act
        result = self.delete_service.delete_files(files, connector_id)

        # Assert
        assert result.execution_id == "exec-456"
        assert len(result.file_results) == 1

        # Verify the file path was passed correctly (metadata is not passed to AWS)
        call_args = self.mock_batch_orchestrator.execute_remote_delete.call_args[0][0]
        assert call_args["DeletePath"] == "/remote/path/file1.txt"

    def test_delete_files_missing_delete_id(self):
        """Test deletion when AWS doesn't return DeleteId."""
        # Arrange
        files = [FileDeleteRequest(file_path="/remote/path/file1.txt")]
        connector_id = "test-connector-123"

        # Mock response without DeleteId
        mock_response = {"Status": "STARTED"}  # Missing DeleteId
        self.mock_batch_orchestrator.execute_remote_delete.return_value = mock_response

        # Act
        result = self.delete_service.delete_files(files, connector_id)

        # Assert - should return result with no execution_id
        assert isinstance(result, DeleteResult)
        assert result.execution_id is None  # No successful DeleteId
        assert len(result.file_results) == 1
        assert result.file_results[0].transfer_id is None

    def test_delete_files_partial_success(self):
        """Test deletion with partial success (some files fail)."""
        # Arrange
        files = [
            FileDeleteRequest(file_path="/remote/path/file1.txt"),
            FileDeleteRequest(file_path="/remote/path/file2.txt")
        ]
        connector_id = "test-connector-123"

        # Mock orchestrator to succeed for first file, fail for second
        def side_effect(request):
            if request["DeletePath"] == "/remote/path/file1.txt":
                return {"DeleteId": "exec-123"}
            else:
                raise Exception("File not found")

        self.mock_batch_orchestrator.execute_remote_delete.side_effect = side_effect

        # Act & Assert - current implementation raises exception on first failure
        with pytest.raises(TransferLibraryError) as exc_info:
            self.delete_service.delete_files(files, connector_id)

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "File not found" in str(exc_info.value)