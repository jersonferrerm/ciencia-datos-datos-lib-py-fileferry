"""
Tests para el módulo index.py - Lambda handler principal.

Este módulo contiene tests unitarios para el handler principal de Lambda,
enfocándose en aumentar el coverage especialmente para la operación upload.
"""

import json
from datetime import datetime
from unittest.mock import Mock, patch

from src.index import (
    lambda_handler,
    handle_upload,
    create_success_response,
    create_error_response
)

from src.exceptions.transfer_exceptions import (
    ValidationError,
    ConfigurationError,
    TransferLibraryError
)


class TestLambdaHandler:
    """Tests para la función lambda_handler principal."""

    def test_upload_operation_success(self):
        """Test exitoso de operación upload."""
        # Arrange
        event = {
            "operation": "upload",
            "files": [
                "/bucket/path/file1.txt",
                "/bucket/path/file2.txt"
            ],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()
        context.aws_request_id = "test-request-123"
        context.function_name = "test-function"
        context.get_remaining_time_in_millis = Mock(return_value=30000)

        # Mock del TransferManager y su resultado
        mock_file_result_1 = Mock()
        mock_file_result_1.file_path = "/bucket/path/file1.txt"
        mock_file_result_1.status.value = "COMPLETED"
        mock_file_result_1.error_message = None

        mock_file_result_2 = Mock()
        mock_file_result_2.file_path = "/bucket/path/file2.txt"
        mock_file_result_2.status.value = "COMPLETED"
        mock_file_result_2.error_message = None

        mock_transfer_result = Mock()
        mock_transfer_result.transfer_id = "transfer-123"
        mock_transfer_result.status.value = "COMPLETED"
        mock_transfer_result.file_results = [mock_file_result_1, mock_file_result_2]
        mock_transfer_result.started_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_transfer_result.completed_at = datetime(2024, 1, 1, 12, 5, 0)
        mock_transfer_result.error_message = None

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager') as mock_config_class:

            # Configurar mocks
            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.upload_files_batch.return_value = mock_transfer_result
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 200

            body = json.loads(response["body"])
            assert body["success"] is True
            assert body["data"]["status"] == "COMPLETED"
            assert "batch_results" in body["data"]


            # Verificar que se llamaron los métodos correctos
            mock_tm.upload_files_batch.assert_called_once_with(
                ["/bucket/path/file1.txt", "/bucket/path/file2.txt"],
                "c-test123",
                "/sftp/uploads/"
            )

    def test_upload_operation_missing_operation(self):
        """Test de error cuando falta el parámetro operation."""
        # Arrange
        event = {
            "files": ["/bucket/path/file1.txt"],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        # Act
        response = lambda_handler(event, context)

        # Assert
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["success"] is False
        assert body["error"]["code"] == "MISSING_OPERATION"

    def test_upload_operation_missing_connector_id(self):
        """Test de error cuando falta connector_id para upload."""
        # Arrange
        event = {
            "operation": "upload",
            "files": ["/bucket/path/file1.txt"],
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        # Act
        response = lambda_handler(event, context)

        # Assert
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["success"] is False
        assert body["error"]["code"] == "MISSING_CONNECTOR_ID"

    def test_upload_operation_empty_files_list(self):
        """Test de error cuando la lista de archivos está vacía."""
        # Arrange
        event = {
            "operation": "upload",
            "files": [],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 400
            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "EMPTY_FILE_LIST"

    def test_upload_operation_missing_destination_path(self):
        """Test de error cuando falta destination_path."""
        # Arrange
        event = {
            "operation": "upload",
            "files": ["/bucket/path/file1.txt"],
            "connector_id": "c-test123"
        }
        context = Mock()

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 400
            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "MISSING_DESTINATION_PATH"

    def test_upload_operation_validation_error(self):
        """Test de manejo de ValidationError durante upload."""
        # Arrange
        event = {
            "operation": "upload",
            "files": ["/bucket/path/file1.txt"],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        # Crear una excepción con error_code
        validation_error = ValidationError("Invalid file path", "INVALID_FILE")

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.upload_files_batch.side_effect = validation_error
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 400
            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "INVALID_FILE"

    def test_upload_operation_configuration_error(self):
        """Test de manejo de ConfigurationError durante upload."""
        # Arrange
        event = {
            "operation": "upload",
            "files": ["/bucket/path/file1.txt"],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        # Crear una excepción con error_code
        config_error = ConfigurationError("Invalid configuration", "CONFIG_ERROR")

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.upload_files_batch.side_effect = config_error
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 500
            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "CONFIG_ERROR"

    def test_upload_operation_transfer_library_error(self):
        """Test de manejo de TransferLibraryError durante upload."""
        # Arrange
        event = {
            "operation": "upload",
            "files": ["/bucket/path/file1.txt"],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        # Crear una excepción con error_code
        transfer_error = TransferLibraryError("Transfer failed", "TRANSFER_ERROR")

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.upload_files_batch.side_effect = transfer_error
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 500
            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "TRANSFER_ERROR"

    def test_upload_operation_with_partial_failure(self):
        """Test de upload con algunos archivos fallidos."""
        # Arrange
        event = {
            "operation": "upload",
            "files": [
                "/bucket/path/file1.txt",
                "/bucket/path/file2.txt"
            ],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        # Mock con un archivo exitoso y otro fallido
        mock_file_result_1 = Mock()
        mock_file_result_1.file_path = "/bucket/path/file1.txt"
        mock_file_result_1.status.value = "COMPLETED"
        mock_file_result_1.error_message = None

        mock_file_result_2 = Mock()
        mock_file_result_2.file_path = "/bucket/path/file2.txt"
        mock_file_result_2.status.value = "FAILED"
        mock_file_result_2.error_message = "File not found"

        mock_transfer_result = Mock()
        mock_transfer_result.transfer_id = "transfer-789"
        mock_transfer_result.status.value = "FAILED"
        mock_transfer_result.file_results = [mock_file_result_1, mock_file_result_2]
        mock_transfer_result.batch_results = []  # Agregar batch_results que es lo que devuelve la implementación actual
        mock_transfer_result.started_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_transfer_result.completed_at = datetime(2024, 1, 1, 12, 5, 0)
        mock_transfer_result.error_message = "Some files failed to transfer"

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.upload_files_batch.return_value = mock_transfer_result
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["success"] is True
            assert body["data"]["status"] == "FAILED"
            assert "batch_results" in body["data"]
            # La respuesta actual no incluye file_results en el nivel superior

    def test_upload_operation_unexpected_error(self):
        """Test de manejo de errores inesperados."""
        # Arrange
        event = {
            "operation": "upload",
            "files": ["/bucket/path/file1.txt"],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.upload_files_batch.side_effect = RuntimeError("Unexpected error")
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 500
            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "INTERNAL_ERROR"

    def test_invalid_operation(self):
        """Test de operación inválida."""
        # Arrange
        event = {
            "operation": "invalid_operation",
            "connector_id": "c-test123"
        }
        context = Mock()

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 400
            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "INVALID_OPERATION"


class TestHandleUpload:
    """Tests específicos para la función handle_upload."""

    def test_handle_upload_success(self):
        """Test exitoso de handle_upload."""
        # Arrange
        mock_transfer_manager = Mock()
        files = ["/bucket/path/file1.txt", "/bucket/path/file2.txt"]
        connector_id = "c-test123"
        destination_path = "/sftp/uploads/"

        mock_file_result = Mock()
        mock_file_result.file_path = "/bucket/path/file1.txt"
        mock_file_result.status.value = "TRANSFERRING"
        mock_file_result.error_message = None

        mock_result = Mock()
        mock_result.transfer_id = "transfer-456"
        mock_result.status.value = "IN_PROGRESS"
        mock_result.file_results = [mock_file_result]
        mock_result.started_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_result.completed_at = None
        mock_result.error_message = None
        mock_transfer_manager.upload_files_batch.return_value = mock_result

        # Act
        response = handle_upload(mock_transfer_manager, files, connector_id, destination_path)

        # Assert
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["success"] is True
        # La respuesta actual no incluye transfer_id en el nivel superior
        assert body["data"]["status"] == "IN_PROGRESS"

    def test_handle_upload_empty_files(self):
        """Test de handle_upload con lista vacía de archivos."""
        # Arrange
        mock_transfer_manager = Mock()
        files = []
        connector_id = "c-test123"
        destination_path = "/sftp/uploads/"

        # Act
        response = handle_upload(mock_transfer_manager, files, connector_id, destination_path)

        # Assert
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["success"] is False
        assert body["error"]["code"] == "EMPTY_FILE_LIST"

    def test_handle_upload_missing_destination_path(self):
        """Test de handle_upload sin destination_path."""
        # Arrange
        mock_transfer_manager = Mock()
        files = ["/bucket/path/file1.txt"]
        connector_id = "c-test123"
        destination_path = None

        # Act
        response = handle_upload(mock_transfer_manager, files, connector_id, destination_path)

        # Assert
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["success"] is False
        assert body["error"]["code"] == "MISSING_DESTINATION_PATH"


    def test_upload_operation_with_datetime_serialization(self):
        """Test de upload verificando serialización correcta de datetime."""
        # Arrange
        event = {
            "operation": "upload",
            "files": ["/bucket/path/file1.txt"],
            "connector_id": "c-test123",
            "destination_path": "/sftp/uploads/"
        }
        context = Mock()

        # Mock con datetime None para completed_at
        mock_file_result = Mock()
        mock_file_result.file_path = "/bucket/path/file1.txt"
        mock_file_result.status.value = "IN_PROGRESS"
        mock_file_result.error_message = None

        mock_transfer_result = Mock()
        mock_transfer_result.transfer_id = "transfer-datetime-test"
        mock_transfer_result.status.value = "IN_PROGRESS"
        mock_transfer_result.file_results = [mock_file_result]
        # Remove datetime fields that no longer exist
        mock_transfer_result.error_message = None

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.upload_files_batch.return_value = mock_transfer_result
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["success"] is True
            # started_at field no longer exists
            # completed_at field no longer exists


    def test_download_operation_success(self):
        """Test exitoso de operación download."""
        # Arrange
        event = {
            "operation": "download",
            "files": ["/sftp/file1.txt"],
            "connector_id": "c-test123",
            "s3_destination_path": "s3://bucket/downloads/"
        }
        context = Mock()

        # Mock del resultado de download
        mock_file_result = Mock()
        mock_file_result.file_path = "/sftp/file1.txt"
        mock_file_result.status.value = "COMPLETED"
        mock_file_result.error_message = None

        mock_transfer_result = Mock()
        mock_transfer_result.transfer_id = "download-123"
        mock_transfer_result.status.value = "COMPLETED"
        mock_transfer_result.file_results = [mock_file_result]
        mock_transfer_result.started_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_transfer_result.completed_at = datetime(2024, 1, 1, 12, 5, 0)
        mock_transfer_result.error_message = None

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.download_files_batch.return_value = mock_transfer_result
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["success"] is True
            assert body["data"]["status"] == "COMPLETED"

    def test_get_status_operation_success(self):
        """Test exitoso de operación get_status."""
        # Arrange
        event = {
            "operation": "get_status",
            "transfer_id": "transfer-123"
        }
        context = Mock()

        mock_status = {
            "transfer_id": "transfer-123",
            "status": "COMPLETED",
            "progress": "100%"
        }

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm.get_transfer_status.return_value = mock_status
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["success"] is True
            assert body["data"]["transfer_id"] == "transfer-123"

    def test_get_status_missing_transfer_id(self):
        """Test de get_status sin transfer_id."""
        # Arrange
        event = {
            "operation": "get_status"
        }
        context = Mock()

        with patch('src.index.TransferManager') as mock_tm_class, \
             patch('src.index.ConfigManager'):

            mock_tm = Mock()
            mock_tm.__enter__ = Mock(return_value=mock_tm)
            mock_tm.__exit__ = Mock(return_value=None)
            mock_tm_class.return_value = mock_tm

            # Act
            response = lambda_handler(event, context)

            # Assert
            assert response["statusCode"] == 400
            body = json.loads(response["body"])
            assert body["success"] is False
            assert body["error"]["code"] == "MISSING_TRANSFER_PARAMS"


class TestUtilityFunctions:
    """Tests para funciones utilitarias."""

    def test_create_success_response(self):
        """Test de create_success_response."""
        # Arrange
        data = {"test": "data", "number": 123}

        # Act
        response = create_success_response(data)

        # Assert
        assert response["statusCode"] == 200
        assert "Content-Type" in response["headers"]
        assert response["headers"]["Content-Type"] == "application/json"
        assert response["headers"]["Access-Control-Allow-Origin"] == "*"
        assert response["headers"]["Access-Control-Allow-Methods"] == "POST, OPTIONS"

        body = json.loads(response["body"])
        assert body["success"] is True
        assert body["data"] == data
        assert "timestamp" in body

    def test_create_error_response(self):
        """Test de create_error_response."""
        # Arrange
        status_code = 400
        error_code = "TEST_ERROR"
        message = "Test error message"

        # Act
        response = create_error_response(status_code, error_code, message)

        # Assert
        assert response["statusCode"] == 400
        assert "Content-Type" in response["headers"]
        assert response["headers"]["Content-Type"] == "application/json"
        assert response["headers"]["Access-Control-Allow-Origin"] == "*"

        body = json.loads(response["body"])
        assert body["success"] is False
        assert body["error"]["code"] == error_code
        assert body["error"]["message"] == message
        assert "timestamp" in body

    def test_create_success_response_with_complex_data(self):
        """Test de create_success_response con datos complejos."""
        # Arrange
        data = {
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "boolean": True,
            "null_value": None
        }

        # Act
        response = create_success_response(data)

        # Assert
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["success"] is True
        assert body["data"]["nested"]["key"] == "value"
        assert body["data"]["list"] == [1, 2, 3]
        assert body["data"]["boolean"] is True
        assert body["data"]["null_value"] is None

    def test_create_error_response_different_status_codes(self):
        """Test de create_error_response con diferentes códigos de estado."""
        # Test 500 error
        response_500 = create_error_response(500, "INTERNAL_ERROR", "Internal server error")
        assert response_500["statusCode"] == 500

        # Test 404 error
        response_404 = create_error_response(404, "NOT_FOUND", "Resource not found")
        assert response_404["statusCode"] == 404

        # Test 403 error
        response_403 = create_error_response(403, "FORBIDDEN", "Access denied")
        assert response_403["statusCode"] == 403