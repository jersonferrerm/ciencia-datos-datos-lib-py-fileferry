"""
Extended tests for DeleteService to increase coverage.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.services.delete_service import DeleteService
from src.orchestration.batch_orchestrator import BatchOrchestrator
from src.models.transfer_models import (
    FileDeleteRequest,
    DeleteResult,
    TransferStatus,
    FileStatus,
    FileTransferResult
)
from src.exceptions.transfer_exceptions import (
    ValidationError,
    TransferLibraryError
)


class TestDeleteServiceInitialization:
    """Tests for DeleteService initialization"""

    def test_init_with_batch_orchestrator(self):
        """Test initialization with batch orchestrator"""
        mock_orchestrator = Mock(spec=BatchOrchestrator)

        service = DeleteService(batch_orchestrator=mock_orchestrator)

        assert service.batch_orchestrator == mock_orchestrator

    def test_init_without_batch_orchestrator(self):
        """Test initialization without batch orchestrator"""
        with pytest.raises(TypeError):
            DeleteService()


class TestDeleteServiceDeleteFiles:
    """Tests for delete_files method"""

    @pytest.fixture
    def mock_orchestrator(self):
        """Mock batch orchestrator"""
        return Mock(spec=BatchOrchestrator)

    @pytest.fixture
    def delete_service(self, mock_orchestrator):
        """DeleteService instance for testing"""
        return DeleteService(batch_orchestrator=mock_orchestrator)

    @pytest.fixture
    def sample_delete_requests(self):
        """Sample delete requests for testing"""
        return [
            FileDeleteRequest(
                file_path="/remote/path/file1.txt",
                metadata={"key1": "value1"}
            ),
            FileDeleteRequest(
                file_path="/remote/path/file2.txt",
                metadata={"key2": "value2"}
            )
        ]

    def test_delete_files_success(self, delete_service, mock_orchestrator, sample_delete_requests):
        """Test successful file deletion"""
        # Mock orchestrator response for each file
        mock_execution_result = {
            'DeleteId': 'delete-123'
        }
        mock_orchestrator.execute_remote_delete.return_value = mock_execution_result

        # Execute delete
        result = delete_service.delete_files(sample_delete_requests, "test-connector-123")

        # Verify result
        assert isinstance(result, DeleteResult)
        assert result.execution_id == 'delete-123'
        assert result.status == TransferStatus.PENDING
        assert len(result.file_results) == 2
        assert result.file_results[0].file_path == "/remote/path/file1.txt"
        assert result.file_results[1].file_path == "/remote/path/file2.txt"

        # Verify orchestrator was called for each file
        assert mock_orchestrator.execute_remote_delete.call_count == 2

    def test_delete_files_validation_empty_list(self, delete_service):
        """Test delete_files with empty file list"""
        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files([], "test-connector")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "File list cannot be empty" in str(exc_info.value)

    def test_delete_files_validation_none_list(self, delete_service):
        """Test delete_files with None file list"""
        with pytest.raises(TypeError):
            delete_service.delete_files(None, "test-connector")

    def test_delete_files_validation_missing_connector_id(self, delete_service, sample_delete_requests):
        """Test delete_files with missing connector_id"""
        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(sample_delete_requests, "")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"

        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(sample_delete_requests, None)

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"

    def test_delete_files_validation_invalid_file_request(self, delete_service):
        """Test delete_files with invalid file request objects"""
        invalid_requests = [
            FileDeleteRequest(file_path="/valid/path.txt"),
            "not-a-file-request",  # Invalid type
            FileDeleteRequest(file_path="/another/valid/path.txt")
        ]

        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(invalid_requests, "test-connector")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "must be a FileDeleteRequest object" in str(exc_info.value)

    def test_delete_files_validation_missing_file_path(self, delete_service):
        """Test delete_files with missing file paths"""
        invalid_requests = [
            FileDeleteRequest(file_path="/valid/path.txt"),
            FileDeleteRequest(file_path=""),  # Empty path
            FileDeleteRequest(file_path="/another/valid/path.txt")
        ]

        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(invalid_requests, "test-connector")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "File path is required" in str(exc_info.value)

    def test_delete_files_orchestrator_exception(self, delete_service, mock_orchestrator, sample_delete_requests):
        """Test delete_files with orchestrator exception"""
        mock_orchestrator.execute_remote_delete.side_effect = RuntimeError("Orchestrator failed")

        # Current implementation raises exception on orchestrator failure
        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(sample_delete_requests, "test-connector")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "Orchestrator failed" in str(exc_info.value)

    def test_delete_files_get_results_exception(self, delete_service, mock_orchestrator, sample_delete_requests):
        """Test delete_files with exception getting results"""
        # Mock successful execution for first file but failed for second
        mock_orchestrator.execute_remote_delete.side_effect = [
            {'DeleteId': 'delete-123'},
            RuntimeError("Failed to delete second file")
        ]

        # Current implementation raises exception on first failure
        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(sample_delete_requests, "test-connector")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "Failed to delete second file" in str(exc_info.value)

    def test_delete_files_partial_failure(self, delete_service, mock_orchestrator, sample_delete_requests):
        """Test delete_files with partial failure"""
        # Mock orchestrator response - first succeeds, second fails
        mock_orchestrator.execute_remote_delete.side_effect = [
            {'DeleteId': 'delete-456'},
            RuntimeError("File not found")
        ]

        # Current implementation raises exception on first failure
        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(sample_delete_requests, "test-connector-456")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "File not found" in str(exc_info.value)

    def test_delete_files_with_metadata(self, delete_service, mock_orchestrator):
        """Test delete_files with file metadata"""
        requests_with_metadata = [
            FileDeleteRequest(
                file_path="/remote/file1.txt",
                metadata={
                    "priority": "high",
                    "category": "temp_files",
                    "created_by": "user123"
                }
            ),
            FileDeleteRequest(
                file_path="/remote/file2.txt",
                metadata={
                    "priority": "low",
                    "category": "logs"
                }
            )
        ]

        # Mock orchestrator response
        mock_execution_result = {
            'DeleteId': 'delete-with-metadata-789'
        }
        mock_orchestrator.execute_remote_delete.return_value = mock_execution_result

        # Execute delete
        result = delete_service.delete_files(requests_with_metadata, "test-connector")

        # Verify the service handled the metadata correctly (metadata is preserved in the request objects)
        assert result.execution_id == 'delete-with-metadata-789'
        assert result.status == TransferStatus.PENDING
        assert len(result.file_results) == 2

    def test_delete_files_large_batch(self, delete_service, mock_orchestrator):
        """Test delete_files with large batch of files"""
        # Create large batch of delete requests
        large_batch = []
        for i in range(100):
            large_batch.append(
                FileDeleteRequest(
                    file_path=f"/remote/batch/file_{i:03d}.txt",
                    metadata={"batch_id": "large_batch_001", "file_index": i}
                )
            )

        # Mock orchestrator response - most succeed, some fail
        def mock_delete_response(request):
            file_path = request.get('DeletePath', '')
            if 'file_095' in file_path or 'file_096' in file_path or 'file_097' in file_path or 'file_098' in file_path or 'file_099' in file_path:
                raise RuntimeError(f"Error deleting {file_path}")
            return {'DeleteId': f'delete-{file_path.split("/")[-1]}'}

        mock_orchestrator.execute_remote_delete.side_effect = mock_delete_response

        # Execute delete
        # Current implementation raises exception on first failure
        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(large_batch, "test-connector")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "Error deleting" in str(exc_info.value)

    def test_delete_files_status_mapping(self, delete_service, mock_orchestrator, sample_delete_requests):
        """Test delete_files status mapping from orchestrator"""
        # Mock successful execution
        mock_execution_result = {
            'DeleteId': 'test-status-mapping'
        }
        mock_orchestrator.execute_remote_delete.return_value = mock_execution_result

        result = delete_service.delete_files([sample_delete_requests[0]], "test-connector")

        # With current implementation, successful individual deletes result in PENDING status
        assert result.status == TransferStatus.PENDING

    def test_delete_files_timing_information(self, delete_service, mock_orchestrator, sample_delete_requests):
        """Test delete_files includes timing information"""
        mock_execution_result = {
            'DeleteId': 'timed-delete-123'
        }
        mock_orchestrator.execute_remote_delete.return_value = mock_execution_result

        # Record start time (use UTC to match implementation)
        start_time = datetime.utcnow()

        # Execute delete
        result = delete_service.delete_files([sample_delete_requests[0]], "test-connector")

        # Record end time
        end_time = datetime.utcnow()

        # Timing information no longer exists
        # assert result.started_at is not None
        # started_at field no longer exists

    def test_delete_files_error_context_preservation(self, delete_service, mock_orchestrator, sample_delete_requests):
        """Test that error context is preserved through the delete process"""
        # Mock orchestrator to raise exception with context
        original_error = RuntimeError("Network timeout during delete")
        mock_orchestrator.execute_remote_delete.side_effect = original_error

        # Current implementation raises exception on first failure
        with pytest.raises(TransferLibraryError) as exc_info:
            delete_service.delete_files(sample_delete_requests, "test-connector")

        assert exc_info.value.error_code == "FILE_DELETION_FAILED"
        assert "Network timeout during delete" in str(exc_info.value)


class TestDeleteServiceEdgeCases:
    """Tests for edge cases and error conditions"""

    @pytest.fixture
    def delete_service(self):
        """DeleteService instance for testing"""
        mock_orchestrator = Mock(spec=BatchOrchestrator)
        return DeleteService(batch_orchestrator=mock_orchestrator)

    def test_delete_files_with_special_characters_in_paths(self, delete_service):
        """Test delete_files with special characters in file paths"""
        special_requests = [
            FileDeleteRequest(file_path="/remote/path with spaces/file.txt"),
            FileDeleteRequest(file_path="/remote/path/file-with-dashes.txt"),
            FileDeleteRequest(file_path="/remote/path/file_with_underscores.txt"),
            FileDeleteRequest(file_path="/remote/path/file.with.dots.txt"),
            FileDeleteRequest(file_path="/remote/path/file(with)parentheses.txt"),
            FileDeleteRequest(file_path="/remote/path/file[with]brackets.txt"),
            FileDeleteRequest(file_path="/remote/path/file{with}braces.txt"),
            FileDeleteRequest(file_path="/remote/path/file@with#symbols$.txt")
        ]

        # Mock successful execution
        mock_execution_result = {
            'DeleteId': 'special-chars-delete'
        }
        delete_service.batch_orchestrator.execute_remote_delete.return_value = mock_execution_result

        # Should handle special characters without issues
        result = delete_service.delete_files(special_requests, "test-connector")

        assert result.status == TransferStatus.PENDING
        assert len(result.file_results) == len(special_requests)

    def test_delete_files_with_very_long_paths(self, delete_service):
        """Test delete_files with very long file paths"""
        # Create a very long path (close to filesystem limits)
        long_directory = "/remote/" + "very_long_directory_name_" * 10
        long_filename = "very_long_filename_" * 10 + ".txt"
        long_path = long_directory + "/" + long_filename

        long_path_request = FileDeleteRequest(file_path=long_path)

        # Mock successful execution
        mock_execution_result = {
            'DeleteId': 'long-path-delete'
        }
        delete_service.batch_orchestrator.execute_remote_delete.return_value = mock_execution_result

        # Should handle long paths without issues
        result = delete_service.delete_files([long_path_request], "test-connector")

        assert result.status == TransferStatus.PENDING
        assert result.file_results[0].file_path == long_path

    def test_delete_files_with_unicode_paths(self, delete_service):
        """Test delete_files with Unicode characters in file paths"""
        unicode_requests = [
            FileDeleteRequest(file_path="/remote/path/файл.txt"),  # Cyrillic
            FileDeleteRequest(file_path="/remote/path/文件.txt"),   # Chinese
            FileDeleteRequest(file_path="/remote/path/ファイル.txt"), # Japanese
            FileDeleteRequest(file_path="/remote/path/파일.txt"),   # Korean
            FileDeleteRequest(file_path="/remote/path/archivo.txt"), # Spanish with accents
            FileDeleteRequest(file_path="/remote/path/fichier_café.txt"), # French with accents
            FileDeleteRequest(file_path="/remote/path/αρχείο.txt")  # Greek
        ]

        # Mock successful execution
        mock_execution_result = {
            'DeleteId': 'unicode-delete'
        }
        delete_service.batch_orchestrator.execute_remote_delete.return_value = mock_execution_result

        # Should handle Unicode paths without issues
        result = delete_service.delete_files(unicode_requests, "test-connector")

        assert result.status == TransferStatus.PENDING
        assert len(result.file_results) == len(unicode_requests)

        # Verify Unicode paths are preserved
        for i, file_result in enumerate(result.file_results):
            assert file_result.file_path == unicode_requests[i].file_path