"""
Tests for Lambda handler (index.py).
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from src.index import (
    lambda_handler,
    handle_upload,
    handle_download,
    handle_delete,
    handle_list_directory,
    handle_get_status,
    handle_wait_for_completion,
    create_success_response,
    create_error_response
)
from src.transfer_manager import TransferManager
from src.config.config_manager import ConfigManager
from src.models.transfer_models import (
    FileTransferRequest,
    FileDeleteRequest,
    TransferResult,
    DeleteResult,
    TransferStatus
)
from src.exceptions.transfer_exceptions import (
    ValidationError,
    ConfigurationError,
    TransferLibraryError
)


class TestLambdaHandler:
    """Tests for main lambda_handler function"""

    @pytest.fixture
    def mock_context(self):
        """Mock Lambda context"""
        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis.return_value = 30000
        return context

    @pytest.fixture
    def basic_upload_event(self):
        """Basic upload event"""
        return {
            'operation': 'upload',
            'files': ['/bucket/file1.txt', '/bucket/file2.txt'],
            'connector_id': 'test-connector-123',
            'destination_path': '/remote/path'
        }

    @pytest.fixture
    def basic_download_event(self):
        """Basic download event"""
        return {
            'operation': 'download',
            'files': [
                {'source_path': '/remote/file1.txt', 'destination_path': 's3://bucket/file1.txt'},
                {'source_path': '/remote/file2.txt', 'destination_path': 's3://bucket/file2.txt'}
            ],
            'connector_id': 'test-connector-123'
        }

    @patch('src.index.TransferManager')
    @patch('src.index.ConfigManager')
    def test_lambda_handler_upload_success(self, mock_config_manager, mock_transfer_manager,
                                         mock_context, basic_upload_event):
        """Test successful upload operation"""
        # Setup mocks
        mock_tm_instance = Mock()
        mock_transfer_manager.return_value.__enter__.return_value = mock_tm_instance

        mock_result = Mock()
        mock_result.transfer_id = "transfer-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = []
        mock_result.started_at = datetime.now()
        mock_result.completed_at = datetime.now()
        mock_result.error_message = None

        mock_tm_instance.upload_files_batch.return_value = mock_result

        # Execute
        response = lambda_handler(basic_upload_event, mock_context)

        # Verify
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        # La respuesta actual no incluye transfer_id en el nivel superior para upload_files_batch
        assert body['data']['status'] == "COMPLETED"

        mock_tm_instance.upload_files_batch.assert_called_once_with(
            ['/bucket/file1.txt', '/bucket/file2.txt'],
            'test-connector-123',
            '/remote/path'
        )

    def test_lambda_handler_missing_operation(self, mock_context):
        """Test handler with missing operation"""
        event = {'files': []}

        response = lambda_handler(event, mock_context)

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error']['code'] == "MISSING_OPERATION"

    def test_lambda_handler_missing_connector_id(self, mock_context):
        """Test handler with missing connector_id for operations that require it"""
        event = {
            'operation': 'upload',
            'files': ['/bucket/file1.txt']
        }

        response = lambda_handler(event, mock_context)

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error']['code'] == "MISSING_CONNECTOR_ID"

    def test_lambda_handler_invalid_operation(self, mock_context):
        """Test handler with invalid operation"""
        event = {
            'operation': 'invalid_operation',
            'connector_id': 'test-connector'
        }

        with patch('src.index.TransferManager'):
            response = lambda_handler(event, mock_context)

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error']['code'] == "INVALID_OPERATION"

    @patch('src.index.TransferManager')
    def test_lambda_handler_validation_error(self, mock_transfer_manager, mock_context):
        """Test handler with validation error"""
        mock_transfer_manager.return_value.__enter__.side_effect = ValidationError(
            "Invalid input", error_code="VALIDATION_FAILED"
        )

        event = {
            'operation': 'upload',
            'files': [],
            'connector_id': 'test-connector',
            'destination_path': '/remote'
        }

        response = lambda_handler(event, mock_context)

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error']['code'] == "VALIDATION_FAILED"

    @patch('src.index.TransferManager')
    def test_lambda_handler_configuration_error(self, mock_transfer_manager, mock_context):
        """Test handler with configuration error"""
        mock_transfer_manager.return_value.__enter__.side_effect = ConfigurationError(
            "Config error", error_code="CONFIG_ERROR"
        )

        event = {
            'operation': 'upload',
            'files': ['/bucket/file1.txt'],
            'connector_id': 'test-connector',
            'destination_path': '/remote'
        }

        response = lambda_handler(event, mock_context)

        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error']['code'] == "CONFIG_ERROR"

    @patch('src.index.TransferManager')
    def test_lambda_handler_transfer_library_error(self, mock_transfer_manager, mock_context):
        """Test handler with transfer library error"""
        mock_transfer_manager.return_value.__enter__.side_effect = TransferLibraryError(
            "Transfer error", error_code="TRANSFER_ERROR"
        )

        event = {
            'operation': 'upload',
            'files': ['/bucket/file1.txt'],
            'connector_id': 'test-connector',
            'destination_path': '/remote'
        }

        response = lambda_handler(event, mock_context)

        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error']['code'] == "TRANSFER_ERROR"

    @patch('src.index.TransferManager')
    def test_lambda_handler_json_decode_error(self, mock_transfer_manager, mock_context):
        """Test handler with JSON decode error"""
        # This is tricky to test directly since the event is already parsed
        # We'll test by causing a JSON error in the response creation
        mock_tm_instance = Mock()
        mock_transfer_manager.return_value.__enter__.return_value = mock_tm_instance

        # Create an object that can't be JSON serialized
        class NonSerializable:
            pass

        mock_result = Mock()
        mock_result.transfer_id = NonSerializable()  # This will cause JSON error
        mock_tm_instance.upload_files_batch.return_value = mock_result

        event = {
            'operation': 'upload',
            'files': ['/bucket/file1.txt'],
            'connector_id': 'test-connector',
            'destination_path': '/remote'
        }

        # The JSON error will be caught and handled
        response = lambda_handler(event, mock_context)

        # La implementación actual maneja correctamente los objetos no serializables
        # usando default=str en json.dumps, por lo que no falla
        assert response['statusCode'] == 200

    @patch('src.index.TransferManager')
    def test_lambda_handler_unexpected_error(self, mock_transfer_manager, mock_context):
        """Test handler with unexpected error"""
        mock_transfer_manager.return_value.__enter__.side_effect = RuntimeError("Unexpected error")

        event = {
            'operation': 'upload',
            'files': ['/bucket/file1.txt'],
            'connector_id': 'test-connector',
            'destination_path': '/remote'
        }

        response = lambda_handler(event, mock_context)

        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error']['code'] == "INTERNAL_ERROR"


class TestHandleUpload:
    """Tests for handle_upload function"""

    @pytest.fixture
    def mock_transfer_manager(self):
        """Mock TransferManager for testing"""
        return Mock(spec=TransferManager)

    def test_handle_upload_success(self, mock_transfer_manager):
        """Test successful upload handling"""
        mock_result = Mock()
        mock_result.transfer_id = "transfer-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = []
        mock_result.started_at = datetime.now()
        mock_result.completed_at = datetime.now()
        mock_result.error_message = None
        mock_result.batch_results = []  # Agregar batch_results que es lo que devuelve la implementación actual

        mock_transfer_manager.upload_files_batch.return_value = mock_result

        response = handle_upload(
            mock_transfer_manager,
            ['/bucket/file1.txt'],
            'test-connector',
            '/remote/path'
        )

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        # La respuesta actual no incluye transfer_id en el nivel superior para upload_files_batch
        assert body['data']['status'] == "COMPLETED"

    def test_handle_upload_empty_files(self, mock_transfer_manager):
        """Test upload with empty files list"""
        response = handle_upload(
            mock_transfer_manager,
            [],
            'test-connector',
            '/remote/path'
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "EMPTY_FILE_LIST"

    def test_handle_upload_missing_destination_path(self, mock_transfer_manager):
        """Test upload with missing destination path"""
        response = handle_upload(
            mock_transfer_manager,
            ['/bucket/file1.txt'],
            'test-connector',
            None
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "MISSING_DESTINATION_PATH"

    def test_handle_upload_exception(self, mock_transfer_manager):
        """Test upload with exception"""
        mock_transfer_manager.upload_files_batch.side_effect = RuntimeError("Upload failed")

        with pytest.raises(RuntimeError):
            handle_upload(
                mock_transfer_manager,
                ['/bucket/file1.txt'],
                'test-connector',
                '/remote/path'
            )


class TestHandleDownload:
    """Tests for handle_download function"""

    @pytest.fixture
    def mock_transfer_manager(self):
        """Mock TransferManager for testing"""
        return Mock(spec=TransferManager)

    def test_handle_download_success(self, mock_transfer_manager):
        """Test successful download handling"""
        mock_result = Mock()
        mock_result.transfer_id = "transfer-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = []
        mock_result.started_at = datetime.now()
        mock_result.completed_at = datetime.now()
        mock_result.error_message = None

        mock_transfer_manager.download_files_batch.return_value = mock_result

        files = ['/remote/file1.txt']
        s3_destination_path = 's3://bucket/downloads/'

        response = handle_download(
            mock_transfer_manager,
            files,
            'test-connector',
            s3_destination_path
        )

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['status'] == "COMPLETED"

        # Verify download_files_batch was called with correct parameters
        mock_transfer_manager.download_files_batch.assert_called_once_with(
            sftp_files=files,
            connector_id='test-connector',
            s3_destination_path=s3_destination_path
        )

    def test_handle_download_empty_files(self, mock_transfer_manager):
        """Test download with empty files list"""
        response = handle_download(
            mock_transfer_manager,
            [],
            'test-connector',
            's3://bucket/downloads/'
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "EMPTY_FILE_LIST"

    def test_handle_download_with_metadata(self, mock_transfer_manager):
        """Test download with file metadata - simplified batch format doesn't support metadata"""
        mock_result = Mock()
        mock_result.transfer_id = "transfer-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = []
        mock_result.started_at = None
        mock_result.completed_at = None
        mock_result.error_message = None

        mock_transfer_manager.download_files_batch.return_value = mock_result

        files = ['/remote/file1.txt']
        s3_destination_path = 's3://bucket/downloads/'

        response = handle_download(
            mock_transfer_manager,
            files,
            'test-connector',
            s3_destination_path
        )

        assert response['statusCode'] == 200

        # Verify download_files_batch was called
        mock_transfer_manager.download_files_batch.assert_called_once_with(
            sftp_files=files,
            connector_id='test-connector',
            s3_destination_path=s3_destination_path
        )


class TestHandleDelete:
    """Tests for handle_delete function"""

    @pytest.fixture
    def mock_transfer_manager(self):
        """Mock TransferManager for testing"""
        return Mock(spec=TransferManager)

    def test_handle_delete_success(self, mock_transfer_manager):
        """Test successful delete handling"""
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
        mock_result.execution_id = "delete-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = mock_file_results
        mock_result.error_message = None

        mock_transfer_manager.delete_files_batch.return_value = mock_result

        files = ['/remote/file1.txt', '/remote/file2.txt']

        response = handle_delete(
            mock_transfer_manager,
            files,
            'test-connector'
        )

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['status'] == "COMPLETED"

        # Verify batch_results structure
        batch_results = body['data']['batch_results']
        assert len(batch_results) == 2
        assert batch_results[0]['delete_id'] == 'delete-id-123'
        assert batch_results[0]['delete_path'] == '/remote/file1.txt'
        assert batch_results[0]['status'] == 'QUEUED'
        assert batch_results[1]['delete_id'] == 'delete-id-456'
        assert batch_results[1]['delete_path'] == '/remote/file2.txt'
        assert batch_results[1]['status'] == 'QUEUED'

        # Verify delete_files_batch was called with correct parameters
        mock_transfer_manager.delete_files_batch.assert_called_once_with(
            files, 'test-connector'
        )

    def test_handle_delete_with_errors(self, mock_transfer_manager):
        """Test delete handling with some errors"""
        from src.models.transfer_models import FileTransferResult, FileStatus

        # Mock file results with mixed success/failure
        mock_file_results = [
            FileTransferResult(
                file_path='/remote/file1.txt',
                status=FileStatus.QUEUED,
                transfer_id='delete-id-123'
            ),
            FileTransferResult(
                file_path='/remote/file2.txt',
                status=FileStatus.FAILED,
                error_message='File not found'
            )
        ]

        mock_result = Mock()
        mock_result.execution_id = "delete-123"
        mock_result.status = TransferStatus.COMPLETED
        mock_result.file_results = mock_file_results
        mock_result.error_message = None

        mock_transfer_manager.delete_files_batch.return_value = mock_result

        files = ['/remote/file1.txt', '/remote/file2.txt']

        response = handle_delete(
            mock_transfer_manager,
            files,
            'test-connector'
        )

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True

        # Verify batch_results structure with errors
        batch_results = body['data']['batch_results']
        assert len(batch_results) == 2
        assert batch_results[0]['delete_id'] == 'delete-id-123'
        assert batch_results[0]['status'] == 'QUEUED'
        assert batch_results[0]['error_message'] is None
        assert batch_results[1]['delete_id'] is None
        assert batch_results[1]['status'] == 'FAILED'
        assert batch_results[1]['error_message'] == 'File not found'

    def test_handle_delete_empty_files(self, mock_transfer_manager):
        """Test delete with empty files list"""
        response = handle_delete(
            mock_transfer_manager,
            [],
            'test-connector'
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "EMPTY_FILE_LIST"


class TestHandleListDirectory:
    """Tests for handle_list_directory function"""

    @pytest.fixture
    def mock_transfer_manager(self):
        """Mock TransferManager for testing"""
        return Mock(spec=TransferManager)

    def test_handle_list_directory_success(self, mock_transfer_manager):
        """Test successful directory listing"""
        mock_listing = Mock()
        mock_listing.listing_id = "listing-123"
        mock_listing.output_filename = "s3://bucket/listing.json"
        mock_listing.path = "/remote/directory"

        mock_transfer_manager.list_directory.return_value = mock_listing

        response = handle_list_directory(
            mock_transfer_manager,
            '/remote/directory',
            'test-connector',
            max_items=100,
            output_directory_path='s3://bucket/'
        )

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['listing_id'] == "listing-123"
        assert body['data']['output_filename'] == "s3://bucket/listing.json"
        assert body['data']['path'] == "/remote/directory"

    def test_handle_list_directory_missing_sftp_path(self, mock_transfer_manager):
        """Test directory listing with missing SFTP path"""
        response = handle_list_directory(
            mock_transfer_manager,
            None,
            'test-connector'
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "MISSING_SFTP_PATH"


class TestHandleGetStatus:
    """Tests for handle_get_status function"""

    @pytest.fixture
    def mock_transfer_manager(self):
        """Mock TransferManager for testing"""
        return Mock(spec=TransferManager)

    def test_handle_get_status_success(self, mock_transfer_manager):
        """Test successful status retrieval"""
        mock_status = {
            'status': 'COMPLETED',
            'total_files': 5,
            'completed_files': 5
        }

        mock_transfer_manager.get_transfer_status.return_value = mock_status

        response = handle_get_status(
            mock_transfer_manager,
            'transfer-123'
        )

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['status'] == 'COMPLETED'
        assert body['data']['total_files'] == 5

    def test_handle_get_status_missing_transfer_id(self, mock_transfer_manager):
        """Test status retrieval with missing transfer ID"""
        response = handle_get_status(
            mock_transfer_manager,
            None
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "MISSING_TRANSFER_PARAMS"

    def test_handle_get_status_multiple_transfers_success(self, mock_transfer_manager):
        """Test successful status retrieval for multiple transfers"""
        mock_status = {
            "success": True,
            "data": [
                {
                    "transfer_id": "transfer-1",
                    "connector_id": "c-test123",
                    "overall_status": "COMPLETED",
                    "total_files": 2
                },
                {
                    "transfer_id": "transfer-2",
                    "connector_id": "c-test123",
                    "overall_status": "IN_PROGRESS",
                    "total_files": 1
                }
            ],
            "timestamp": "2025-01-09T12:00:00.000000"
        }
        mock_transfer_manager.get_multiple_transfer_status.return_value = mock_status

        response = handle_get_status(
            mock_transfer_manager,
            None,
            ["transfer-1", "transfer-2"],
            "c-test123"
        )

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert len(body['data']['results']) == 2
        assert body['data']['results'][0]['transfer_id'] == 'transfer-1'
        assert body['data']['results'][1]['transfer_id'] == 'transfer-2'

    def test_handle_get_status_multiple_transfers_missing_connector_id(self, mock_transfer_manager):
        """Test multiple transfers without connector_id"""
        response = handle_get_status(
            mock_transfer_manager,
            None,
            ["transfer-1", "transfer-2"],
            None
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "MISSING_CONNECTOR_ID"

    def test_handle_get_status_multiple_transfers_invalid_list(self, mock_transfer_manager):
        """Test multiple transfers with invalid transfer_ids list"""
        response = handle_get_status(
            mock_transfer_manager,
            None,
            [],
            "c-test123"
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "INVALID_TRANSFER_IDS"


class TestHandleWaitForCompletion:
    """Tests for handle_wait_for_completion function"""

    @pytest.fixture
    def mock_transfer_manager(self):
        """Mock TransferManager for testing"""
        return Mock(spec=TransferManager)

    def test_handle_wait_for_completion_success(self, mock_transfer_manager):
        """Test successful wait for completion"""
        mock_final_status = {
            'status': 'COMPLETED',
            'total_files': 3,
            'completed_files': 3
        }

        mock_transfer_manager.wait_for_completion.return_value = mock_final_status

        response = handle_wait_for_completion(
            mock_transfer_manager,
            'transfer-123',
            timeout=300,
            poll_interval=5
        )

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data']['status'] == 'COMPLETED'

        mock_transfer_manager.wait_for_completion.assert_called_once_with(
            'transfer-123', 300, 5
        )

    def test_handle_wait_for_completion_missing_transfer_id(self, mock_transfer_manager):
        """Test wait for completion with missing transfer ID"""
        response = handle_wait_for_completion(
            mock_transfer_manager,
            None
        )

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['error']['code'] == "MISSING_TRANSFER_ID"


class TestResponseHelpers:
    """Tests for response helper functions"""

    def test_create_success_response(self):
        """Test success response creation"""
        data = {'key': 'value', 'number': 123}

        response = create_success_response(data)

        assert response['statusCode'] == 200
        assert 'Content-Type' in response['headers']
        assert response['headers']['Content-Type'] == 'application/json'
        assert 'Access-Control-Allow-Origin' in response['headers']

        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['data'] == data
        assert 'timestamp' in body

    def test_create_success_response_with_datetime(self):
        """Test success response with datetime objects"""
        data = {'timestamp': datetime.now()}

        response = create_success_response(data)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        # datetime should be serialized as string
        assert isinstance(body['data']['timestamp'], str)

    def test_create_error_response(self):
        """Test error response creation"""
        response = create_error_response(400, "TEST_ERROR", "Test error message")

        assert response['statusCode'] == 400
        assert 'Content-Type' in response['headers']
        assert response['headers']['Content-Type'] == 'application/json'

        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error']['code'] == "TEST_ERROR"
        assert body['error']['message'] == "Test error message"
        assert 'timestamp' in body

    def test_create_error_response_different_status_codes(self):
        """Test error response with different status codes"""
        response_400 = create_error_response(400, "BAD_REQUEST", "Bad request")
        response_500 = create_error_response(500, "INTERNAL_ERROR", "Internal error")

        assert response_400['statusCode'] == 400
        assert response_500['statusCode'] == 500

        body_400 = json.loads(response_400['body'])
        body_500 = json.loads(response_500['body'])

        assert body_400['error']['code'] == "BAD_REQUEST"
        assert body_500['error']['code'] == "INTERNAL_ERROR"