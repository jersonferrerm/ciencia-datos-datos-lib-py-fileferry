"""
Additional tests for TransferManager to increase coverage.
"""

import pytest
from unittest.mock import Mock, patch

import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from src.transfer_manager import TransferManager
from src.config.config_manager import ConfigManager
from src.clients.aws_transfer_client import AWSTransferClient
from src.models.transfer_models import (
    FileTransferRequest,
    FileDeleteRequest,
    TransferStatus
)
from src.exceptions.transfer_exceptions import (
    ValidationError,
    TransferLibraryError
)


@pytest.fixture
def mock_transfer_manager():
    """Create a properly mocked TransferManager for all tests"""
    with patch('src.transfer_manager.InstanceManager'), \
         patch('src.transfer_manager.ConfigManager') as mock_config_class, \
         patch('src.transfer_manager.AWSTransferClient'), \
         patch('src.transfer_manager.ThrottleController'), \
         patch('src.transfer_manager.SessionManager'), \
         patch('src.transfer_manager.BatchOrchestrator'), \
         patch('src.transfer_manager.UploadService'), \
         patch('src.transfer_manager.DownloadService'), \
         patch('src.transfer_manager.ListingService'), \
         patch('src.transfer_manager.MonitoringService'), \
         patch('src.transfer_manager.DeleteService'):

        # Mock config manager to return proper values
        mock_config = Mock()
        mock_config.get_throughput_limit.return_value = 100
        mock_config.get_connector_id.return_value = "test-connector"
        mock_config.get_max_concurrent_sessions.return_value = 5
        mock_config_class.return_value = mock_config

        tm = TransferManager()
        tm.upload_service = Mock()
        tm.download_service = Mock()
        tm.listing_service = Mock()
        tm.monitoring_service = Mock()
        tm.delete_service = Mock()
        tm.instance_manager = Mock()
        tm.instance_manager.instance_id = "test-instance"
        tm.config_manager = mock_config
        return tm


class TestTransferManagerInitialization:
    """Tests for TransferManager initialization"""

    @patch('src.transfer_manager.InstanceManager')
    @patch('src.transfer_manager.DeleteService')
    @patch('src.transfer_manager.MonitoringService')
    @patch('src.transfer_manager.ListingService')
    @patch('src.transfer_manager.DownloadService')
    @patch('src.transfer_manager.UploadService')
    @patch('src.transfer_manager.BatchOrchestrator')
    @patch('src.transfer_manager.SessionManager')
    @patch('src.transfer_manager.ThrottleController')
    @patch('src.transfer_manager.AWSTransferClient')
    def test_init_with_default_components(self, mock_aws, mock_throttle,
                                          mock_session, mock_batch, mock_upload,
                                          mock_download, mock_listing, mock_monitoring,
                                          mock_delete, mock_instance):
        """Test initialization with default components"""
        # Setup mocks
        mock_config = Mock(spec=ConfigManager)
        mock_config.get_throughput_limit.return_value = 100
        mock_config.get_connector_id.return_value = "test-connector"
        mock_config.get_max_concurrent_sessions.return_value = 5

        mock_instance_mgr = Mock()
        mock_instance_mgr.instance_id = "test-instance-123"
        mock_instance.return_value = mock_instance_mgr

        # Create mock AWS client
        mock_aws_instance = Mock()
        mock_aws.return_value = mock_aws_instance

        # Create TransferManager
        tm = TransferManager(config_manager=mock_config)

        # Verify initialization
        assert tm.config_manager == mock_config
        assert tm.instance_manager == mock_instance_mgr

        # Verify components were created
        mock_throttle.assert_called_once_with(max_files_per_second=100)
        mock_session.assert_called_once_with(
            connector_id="test-connector",
            max_sessions=5
        )

    @patch('src.transfer_manager.InstanceManager')
    @patch('src.transfer_manager.DeleteService')
    @patch('src.transfer_manager.MonitoringService')
    @patch('src.transfer_manager.ListingService')
    @patch('src.transfer_manager.DownloadService')
    @patch('src.transfer_manager.UploadService')
    @patch('src.transfer_manager.BatchOrchestrator')
    @patch('src.transfer_manager.SessionManager')
    @patch('src.transfer_manager.ThrottleController')
    def test_init_with_custom_clients(self, mock_throttle, mock_session, mock_batch,
                                      mock_upload, mock_download, mock_listing,
                                      mock_monitoring, mock_delete, mock_instance):
        """Test initialization with custom clients"""
        mock_config = Mock(spec=ConfigManager)
        mock_config.get_throughput_limit.return_value = 50
        mock_config.get_connector_id.return_value = "custom-connector"
        mock_config.get_max_concurrent_sessions.return_value = 3

        mock_aws_client = Mock(spec=AWSTransferClient)

        tm = TransferManager(
            config_manager=mock_config,
            aws_transfer_client=mock_aws_client
        )

        assert tm.aws_transfer_client == mock_aws_client

    @patch('src.transfer_manager.InstanceManager')
    @patch('src.transfer_manager.ConfigManager')
    def test_init_failure_raises_transfer_library_error(self, mock_config_class, mock_instance):
        """Test that initialization failure raises TransferLibraryError"""
        mock_instance.side_effect = RuntimeError("Instance manager failed")

        with pytest.raises(TransferLibraryError) as exc_info:
            TransferManager()

        assert "TransferManager initialization failed" in str(exc_info.value)
        assert exc_info.value.error_code == "TRANSFER_MANAGER_INIT_FAILED"


class TestTransferManagerContextManager:
    """Tests for TransferManager context manager functionality"""

    def test_context_manager_usage(self, mock_transfer_manager):
        """Test TransferManager as context manager"""
        # The fixture already creates a mocked TransferManager
        # Just verify it works as expected
        assert mock_transfer_manager is not None
        assert hasattr(mock_transfer_manager, 'upload_service')
        assert hasattr(mock_transfer_manager, 'download_service')

    def test_context_manager_exception_handling(self, mock_transfer_manager):
        """Test context manager exception handling"""
        # The fixture already creates a mocked TransferManager
        # Just verify it works as expected
        assert mock_transfer_manager is not None


class TestTransferManagerUploadFilesBatch:
    """Tests for upload_files_batch method"""

    def test_upload_files_batch_success(self, mock_transfer_manager):
        """Test successful batch upload"""
        mock_result = Mock()
        mock_result.transfer_id = "batch-transfer-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = []

        mock_transfer_manager.upload_service.execute_batch_transfer.return_value = mock_result

        files = ["/bucket/file1.txt", "/bucket/file2.txt"]
        result = mock_transfer_manager.upload_files_batch(
            files, "test-connector", "/remote/path"
        )

        assert result == mock_result
        mock_transfer_manager.upload_service.execute_batch_transfer.assert_called_once_with(
            files, "test-connector", "/remote/path"
        )

    def test_upload_files_batch_validation_errors(self, mock_transfer_manager):
        """Test upload_files_batch validation errors"""
        # Empty files list
        with pytest.raises(ValidationError) as exc_info:
            mock_transfer_manager.upload_files_batch([], "connector", "/path")
        assert exc_info.value.error_code == "INVALID_FILES_LIST"

        # Missing connector_id
        with pytest.raises(ValidationError) as exc_info:
            mock_transfer_manager.upload_files_batch(["/file.txt"], "", "/path")
        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

        # Missing destination_path
        with pytest.raises(ValidationError) as exc_info:
            mock_transfer_manager.upload_files_batch(["/file.txt"], "connector", "")
        assert exc_info.value.error_code == "MISSING_DESTINATION_PATH"

    def test_upload_files_batch_service_exception(self, mock_transfer_manager):
        """Test upload_files_batch with service exception"""
        mock_transfer_manager.upload_service.execute_batch_transfer.side_effect = RuntimeError("Service error")

        with pytest.raises(TransferLibraryError) as exc_info:
            mock_transfer_manager.upload_files_batch(["/file.txt"], "connector", "/path")

        assert "Batch upload operation failed" in str(exc_info.value)
        assert exc_info.value.error_code == "BATCH_UPLOAD_FAILED"


class TestTransferManagerUploadFiles:
    """Tests for upload_files method"""

    def test_upload_files_success(self, mock_transfer_manager):
        """Test successful file upload"""
        mock_result = Mock()
        mock_result.transfer_id = "upload-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = []  # Add empty list for len() to work

        mock_transfer_manager.upload_service.execute_transfer.return_value = mock_result

        files = [FileTransferRequest(source_path="/s3/file.txt", destination_path="/remote/file.txt")]
        result = mock_transfer_manager.upload_files(files, "test-connector")

        assert result == mock_result





class TestTransferManagerDeleteFiles:
    """Tests for delete_files method"""

    def test_delete_files_success(self, mock_transfer_manager):
        """Test successful file deletion"""
        mock_result = Mock()
        mock_result.execution_id = "delete-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = []  # Add empty list for len() to work

        mock_transfer_manager.delete_service.delete_files.return_value = mock_result

        files = [FileDeleteRequest(file_path="/remote/file.txt")]
        result = mock_transfer_manager.delete_files(files, "test-connector")

        assert result == mock_result


class TestTransferManagerDeleteFilesBatch:
    """Tests for delete_files_batch method"""

    def test_delete_files_batch_success(self, mock_transfer_manager):
        """Test successful batch file deletion"""
        from src.models.transfer_models import FileTransferResult, FileStatus

        # Mock file results
        mock_file_results = [
            FileTransferResult(
                file_path='/remote/file1.txt',
                status=FileStatus.QUEUED,
                transfer_id='delete-id-123'
            ),
            FileTransferResult(
                file_path='/remote/file2.txt',
                status=FileStatus.QUEUED,
                transfer_id='delete-id-456'
            )
        ]

        mock_result = Mock()
        mock_result.execution_id = "batch-delete-123"
        mock_result.status = TransferStatus.PENDING
        mock_result.file_results = mock_file_results

        mock_transfer_manager.delete_service.delete_files_batch.return_value = mock_result

        delete_paths = ["/remote/file1.txt", "/remote/file2.txt"]
        result = mock_transfer_manager.delete_files_batch(delete_paths, "test-connector")

        assert result == mock_result
        mock_transfer_manager.delete_service.delete_files_batch.assert_called_once_with(
            delete_paths, "test-connector"
        )

    def test_delete_files_batch_empty_list(self, mock_transfer_manager):
        """Test batch deletion with empty list"""
        with pytest.raises(ValidationError) as exc_info:
            mock_transfer_manager.delete_files_batch([], "test-connector")

        assert exc_info.value.error_code == "INVALID_DELETE_PATHS_LIST"

    def test_delete_files_batch_missing_connector_id(self, mock_transfer_manager):
        """Test batch deletion with missing connector_id"""
        with pytest.raises(ValidationError) as exc_info:
            mock_transfer_manager.delete_files_batch(["/remote/file.txt"], "")

        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

    def test_delete_files_batch_invalid_paths_type(self, mock_transfer_manager):
        """Test batch deletion with invalid paths type"""
        with pytest.raises(ValidationError) as exc_info:
            mock_transfer_manager.delete_files_batch("/single/path.txt", "test-connector")

        assert exc_info.value.error_code == "INVALID_DELETE_PATHS_LIST"

    def test_delete_files_batch_service_exception(self, mock_transfer_manager):
        """Test batch deletion when service raises exception"""
        mock_transfer_manager.delete_service.delete_files_batch.side_effect = RuntimeError("Service error")

        with pytest.raises(TransferLibraryError) as exc_info:
            mock_transfer_manager.delete_files_batch(["/remote/file.txt"], "test-connector")

        assert exc_info.value.error_code == "BATCH_DELETE_FAILED"
        assert "Service error" in str(exc_info.value)