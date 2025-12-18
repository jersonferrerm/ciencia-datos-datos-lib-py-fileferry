"""
Integration tests for delete functionality.

Este módulo contiene las pruebas de integración para la funcionalidad
de eliminación de archivos SFTP.
"""

import json
from unittest.mock import Mock, patch

from src.index import lambda_handler


class TestDeleteIntegration:
    """Integration tests for delete operations."""

    def test_delete_operation_success(self):
        """Test successful delete operation through Lambda handler."""
        # Arrange
        event = {
            "operation": "delete",
            "files": ["/remote/path/file1.txt", "/remote/path/file2.txt"],
            "connector_id": "test-connector-123"
        }

        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis.return_value = 30000

        # Mock the TransferManager and its delete_files_batch method
        with patch('src.index.TransferManager') as mock_transfer_manager_class:
            mock_transfer_manager = Mock()
            mock_transfer_manager_class.return_value.__enter__.return_value = mock_transfer_manager

            # Mock delete result
            mock_result = Mock()
            mock_result.execution_id = "exec-123"
            mock_result.status.value = "PENDING"
            mock_result.file_results = [
                Mock(
                    file_path="/remote/path/file1.txt",
                    status=Mock(value="QUEUED"),
                    transfer_id="delete-123-1",
                    error_message=None
                ),
                Mock(
                    file_path="/remote/path/file2.txt",
                    status=Mock(value="QUEUED"),
                    transfer_id="delete-123-2",
                    error_message=None
                )
            ]
            mock_result.error_message = None

            mock_transfer_manager.delete_files_batch.return_value = mock_result

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 200

            body = json.loads(response["body"])
            assert body["success"] is True
            assert body["data"]["status"] == "PENDING"
            assert body["data"]["error_message"] is None
            assert len(body["data"]["batch_results"]) == 2
            assert body["data"]["batch_results"][0]["delete_path"] == "/remote/path/file1.txt"
            assert body["data"]["batch_results"][1]["delete_path"] == "/remote/path/file2.txt"

            # Verify delete_files_batch was called with correct parameters
            mock_transfer_manager.delete_files_batch.assert_called_once()
            call_args = mock_transfer_manager.delete_files_batch.call_args
            files_arg = call_args[0][0]
            connector_id_arg = call_args[0][1]

            assert len(files_arg) == 2
            assert files_arg[0] == "/remote/path/file1.txt"
            assert files_arg[1] == "/remote/path/file2.txt"
            assert connector_id_arg == "test-connector-123"

    def test_delete_operation_empty_files(self):
        """Test delete operation with empty files list."""
        # Arrange
        event = {
            "operation": "delete",
            "files": [],
            "connector_id": "test-connector-123"
        }

        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis.return_value = 30000

        # Mock the TransferManager to avoid initialization issues
        with patch('src.index.TransferManager') as mock_transfer_manager_class:
            mock_transfer_manager = Mock()
            mock_transfer_manager_class.return_value.__enter__.return_value = mock_transfer_manager

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 400

            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "EMPTY_FILE_LIST"

    def test_delete_operation_invalid_files_format(self):
        """Test delete operation with invalid files format."""
        # Arrange
        event = {
            "operation": "delete",
            "files": [
                {"metadata": {"key": "value"}}  # Invalid format - should be string paths
            ],
            "connector_id": "test-connector-123"
        }

        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis.return_value = 30000

        # Mock the TransferManager to simulate validation error
        with patch('src.index.TransferManager') as mock_transfer_manager_class:
            mock_transfer_manager = Mock()
            mock_transfer_manager_class.return_value.__enter__.return_value = mock_transfer_manager

            from src.exceptions.transfer_exceptions import ValidationError
            mock_transfer_manager.delete_files_batch.side_effect = ValidationError(
                "delete_paths must be a non-empty list of SFTP paths",
                error_code="INVALID_DELETE_PATHS_LIST"
            )

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 400

            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "INVALID_DELETE_PATHS_LIST"

    def test_delete_operation_single_file(self):
        """Test delete operation with single file."""
        # Arrange
        event = {
            "operation": "delete",
            "files": ["/remote/path/file1.txt"],
            "connector_id": "test-connector-123"
        }

        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis.return_value = 30000

        # Mock the TransferManager
        with patch('src.index.TransferManager') as mock_transfer_manager_class:
            mock_transfer_manager = Mock()
            mock_transfer_manager_class.return_value.__enter__.return_value = mock_transfer_manager

            # Mock delete result
            mock_result = Mock()
            mock_result.execution_id = "exec-456"
            mock_result.status.value = "PENDING"
            mock_result.file_results = [
                Mock(
                    file_path="/remote/path/file1.txt",
                    status=Mock(value="QUEUED"),
                    transfer_id="delete-456-1",
                    error_message=None
                )
            ]
            mock_result.error_message = None

            mock_transfer_manager.delete_files_batch.return_value = mock_result

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 200

            body = json.loads(response["body"])
            assert body["success"] is True
            assert body["data"]["status"] == "PENDING"
            assert len(body["data"]["batch_results"]) == 1
            assert body["data"]["batch_results"][0]["delete_path"] == "/remote/path/file1.txt"

            # Verify the correct method was called
            mock_transfer_manager.delete_files_batch.assert_called_once()
            call_args = mock_transfer_manager.delete_files_batch.call_args
            files_arg = call_args[0][0]

            assert len(files_arg) == 1
            assert files_arg[0] == "/remote/path/file1.txt"

    def test_delete_operation_no_connector_id(self):
        """Test delete operation without connector_id (should fail)."""
        # Arrange
        event = {
            "operation": "delete",
            "files": ["/remote/path/file1.txt"]
            # No connector_id provided
        }

        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis.return_value = 30000

        # Act
        response = lambda_handler(event, context)

        # Assert
        assert response["statusCode"] == 400

        body = json.loads(response["body"])
        assert body["success"] is False
        assert body["error"]["code"] == "MISSING_CONNECTOR_ID"
        assert "connector_id is required" in body["error"]["message"]

    def test_delete_operation_transfer_error(self):
        """Test delete operation with transfer service error."""
        # Arrange
        event = {
            "operation": "delete",
            "files": ["/remote/path/file1.txt"],
            "connector_id": "test-connector-123"
        }

        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis.return_value = 30000

        # Mock the TransferManager to simulate transfer error
        with patch('src.index.TransferManager') as mock_transfer_manager_class:
            mock_transfer_manager = Mock()
            mock_transfer_manager_class.return_value.__enter__.return_value = mock_transfer_manager

            from src.exceptions.transfer_exceptions import TransferLibraryError
            mock_transfer_manager.delete_files_batch.side_effect = TransferLibraryError(
                "Failed to connect to SFTP server",
                error_code="SFTP_CONNECTION_FAILED"
            )

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 500

            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "SFTP_CONNECTION_FAILED"
            assert "Failed to connect to SFTP server" in body["error"]["message"]

    def test_delete_operation_partial_failure(self):
        """Test delete operation with partial failure."""
        # Arrange
        event = {
            "operation": "delete",
            "files": ["/remote/path/file1.txt", "/remote/path/nonexistent.txt"],
            "connector_id": "test-connector-123"
        }

        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis.return_value = 30000

        # Mock the TransferManager
        with patch('src.index.TransferManager') as mock_transfer_manager_class:
            mock_transfer_manager = Mock()
            mock_transfer_manager_class.return_value.__enter__.return_value = mock_transfer_manager

            # Mock delete result with partial failure
            mock_result = Mock()
            mock_result.execution_id = "exec-789"
            mock_result.status.value = "COMPLETED"
            mock_result.file_results = [
                Mock(
                    file_path="/remote/path/file1.txt",
                    status=Mock(value="COMPLETED"),
                    transfer_id="delete-789-1",
                    error_message=None
                ),
                Mock(
                    file_path="/remote/path/nonexistent.txt",
                    status=Mock(value="FAILED"),
                    transfer_id="delete-789-2",
                    error_message="File not found"
                )
            ]
            mock_result.error_message = None

            mock_transfer_manager.delete_files_batch.return_value = mock_result

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 200

            body = json.loads(response["body"])
            assert body["success"] is True
            assert body["data"]["status"] == "COMPLETED"
            assert len(body["data"]["batch_results"]) == 2

            # Check first file succeeded
            assert body["data"]["batch_results"][0]["delete_path"] == "/remote/path/file1.txt"
            assert body["data"]["batch_results"][0]["status"] == "COMPLETED"
            assert body["data"]["batch_results"][0]["error_message"] is None

            # Check second file failed
            assert body["data"]["batch_results"][1]["delete_path"] == "/remote/path/nonexistent.txt"
            assert body["data"]["batch_results"][1]["status"] == "FAILED"
            assert body["data"]["batch_results"][1]["error_message"] == "File not found"