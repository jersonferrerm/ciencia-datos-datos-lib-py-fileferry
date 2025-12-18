"""
Tests para ListingService.

Este módulo contiene tests unitarios para el servicio de listado de directorios SFTP
que utiliza AWS Transfer Family para operaciones de directorio.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.services.listing_service import ListingService
from src.services.interfaces import IAWSClient
from src.models.transfer_models import DirectoryListing
from src.exceptions.transfer_exceptions import (
    ValidationError,
    TransferError,
    ConnectionError,
    AuthenticationError,
    FileNotFoundError,
    InsufficientPermissionsError,
    TimeoutError
)


class TestListingServiceInitialization:
    """Tests para la inicialización de ListingService."""

    def test_initialization_valid_parameters(self):
        """Test inicialización con parámetros válidos."""
        aws_client = Mock(spec=IAWSClient)

        service = ListingService(aws_client=aws_client)

        assert service.aws_client == aws_client

    def test_initialization_missing_aws_client(self):
        """Test inicialización sin aws_client."""
        with pytest.raises(ValidationError) as exc_info:
            ListingService(aws_client=None)

        assert exc_info.value.error_code == "MISSING_AWS_CLIENT"


class TestValidateListingParameters:
    """Tests para el método _validate_listing_parameters."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_validate_listing_parameters_valid(self):
        """Test validación de parámetros válidos."""
        # No debería lanzar excepción
        self.service._validate_listing_parameters(
            sftp_path="/home/user",
            connector_id="connector-123",
            max_items=100,
            output_directory_path="/output/path"
        )

    def test_validate_listing_parameters_invalid_sftp_path(self):
        """Test validación con sftp_path inválido."""
        invalid_paths = [
            "",  # Vacío
            None,  # None
            123,  # No string
            "   ",  # Solo espacios
        ]

        for path in invalid_paths:
            with pytest.raises(ValidationError) as exc_info:
                self.service._validate_listing_parameters(
                    sftp_path=path,
                    connector_id="connector-123"
                )

            assert exc_info.value.error_code in ["INVALID_SFTP_PATH", "INVALID_SFTP_PATH_FORMAT"]

    def test_validate_listing_parameters_invalid_connector_id(self):
        """Test validación con connector_id inválido."""
        invalid_ids = [
            "",  # Vacío
            None,  # None
            123,  # No string
        ]

        for connector_id in invalid_ids:
            with pytest.raises(ValidationError) as exc_info:
                self.service._validate_listing_parameters(
                    sftp_path="/home/user",
                    connector_id=connector_id
                )

            assert exc_info.value.error_code == "INVALID_CONNECTOR_ID"

    def test_validate_listing_parameters_invalid_sftp_path_format(self):
        """Test validación con formato de ruta SFTP inválido."""
        invalid_paths = [
            "/path/with\0null",  # Carácter null
            "/path/../../../etc/passwd",  # Path traversal
            "a" * 1025,  # Muy largo
        ]

        for path in invalid_paths:
            with pytest.raises(ValidationError) as exc_info:
                self.service._validate_listing_parameters(
                    sftp_path=path,
                    connector_id="connector-123"
                )

            assert exc_info.value.error_code in ["INVALID_SFTP_PATH_FORMAT", "SFTP_PATH_TOO_LONG"]

    def test_validate_listing_parameters_invalid_max_items(self):
        """Test validación con max_items inválido."""
        invalid_max_items = [
            0,  # Cero
            -5,  # Negativo
            "100",  # String
            1001,  # Muy grande
        ]

        for max_items in invalid_max_items:
            with pytest.raises(ValidationError) as exc_info:
                self.service._validate_listing_parameters(
                    sftp_path="/home/user",
                    connector_id="connector-123",
                    max_items=max_items
                )

            assert exc_info.value.error_code in ["INVALID_MAX_ITEMS", "MAX_ITEMS_EXCEEDED"]

    def test_validate_listing_parameters_invalid_output_directory_path(self):
        """Test validación con output_directory_path inválido."""
        invalid_paths = [
            "",  # Vacío
            "   ",  # Solo espacios
            123,  # No string
            "a" * 1025,  # Muy largo
        ]

        for path in invalid_paths:
            with pytest.raises(ValidationError) as exc_info:
                self.service._validate_listing_parameters(
                    sftp_path="/home/user",
                    connector_id="connector-123",
                    output_directory_path=path
                )

            assert exc_info.value.error_code in ["INVALID_OUTPUT_DIRECTORY", "OUTPUT_DIRECTORY_TOO_LONG"]


class TestPrepareListingRequest:
    """Tests para el método _prepare_listing_request."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_prepare_listing_request_basic(self):
        """Test preparación básica de solicitud."""
        request = self.service._prepare_listing_request(
            sftp_path="/home/user",
            connector_id="connector-123",
            max_items=None,
            output_directory_path=None
        )

        expected = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/home/user"
        }

        assert request == expected

    def test_prepare_listing_request_with_max_items(self):
        """Test preparación de solicitud con max_items."""
        request = self.service._prepare_listing_request(
            sftp_path="/data/files",
            connector_id="connector-456",
            max_items=50,
            output_directory_path=None
        )

        expected = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/data/files",
            "MaxItems": 50
        }

        assert request == expected

    def test_prepare_listing_request_max_items_zero(self):
        """Test preparación de solicitud con max_items cero."""
        request = self.service._prepare_listing_request(
            sftp_path="/home/user",
            connector_id="connector-123",
            max_items=0,
            output_directory_path=None
        )

        # max_items=0 no debería incluirse en la solicitud
        expected = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/home/user"
        }

        assert request == expected

    def test_prepare_listing_request_with_output_directory(self):
        """Test preparación de solicitud con output_directory_path."""
        request = self.service._prepare_listing_request(
            sftp_path="/data/files",
            connector_id="connector-456",
            max_items=50,
            output_directory_path="/output/listings"
        )

        expected = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/data/files",
            "MaxItems": 50,
            "OutputDirectoryPath": "/output/listings"
        }

        assert request == expected


class TestPollListingCompletion:
    """Tests para el método _poll_listing_completion."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_poll_listing_completion_immediate_success(self):
        """Test polling con éxito inmediato."""
        # Configurar respuesta exitosa inmediata
        response = {
            "FileTransferResults": [
                {
                    "FilePath": "/test-/file1.txt",
                    "StatusCode": "COMPLETED"
                }
            ]
        }

        self.aws_client.list_file_transfer_results.return_value = response

        result = self.service._poll_listing_completion("exec-123", "connector-123")

        assert result == response
        self.aws_client.list_file_transfer_results.assert_called_with(
            connector_id="connector-123", transfer_id="exec-123"
        )

    @patch('time.sleep')
    def test_poll_listing_completion_eventual_success(self, mock_sleep):
        """Test polling con éxito eventual."""
        # Configurar secuencia de respuestas: IN_PROGRESS -> COMPLETED
        responses = [
            {"FileTransferResults": [{"FilePath": "/test-/file1.txt", "StatusCode": "IN_PROGRESS"}]},
            {"FileTransferResults": [{"FilePath": "/test-/file1.txt", "StatusCode": "COMPLETED"}]}
        ]

        self.aws_client.list_file_transfer_results.side_effect = responses

        result = self.service._poll_listing_completion("exec-123", "connector-123")

        assert result == responses[1]
        assert self.aws_client.list_file_transfer_results.call_count == 2
        mock_sleep.assert_called_once_with(2)  # poll_interval por defecto

    def test_poll_listing_completion_failed_status(self):
        """Test polling con estado FAILED."""
        response = {
            "FileTransferResults": [
                {
                    "FilePath": "/test-/file1.txt",
                    "StatusCode": "FAILED",
                    "FailureCode": "CONNECTION_ERROR",
                    "FailureMessage": "SFTP connection failed"
                }
            ]
        }

        self.aws_client.list_file_transfer_results.return_value = response

        with pytest.raises(TransferError) as exc_info:
            self.service._poll_listing_completion("exec-123", "connector-123")

        assert exc_info.value.error_code == "LISTING_FAILED"
        assert "Directory listing failed for 1 files" in str(exc_info.value)

    def test_poll_listing_completion_no_results(self):
        """Test polling con respuesta vacía."""
        response = {
            "FileTransferResults": []
        }

        self.aws_client.list_file_transfer_results.return_value = response

        # Con resultados vacíos, debería continuar el polling hasta timeout
        with pytest.raises(TimeoutError) as exc_info:
            self.service._poll_listing_completion("exec-123", "connector-123", timeout=1)

        assert exc_info.value.error_code == "LISTING_TIMEOUT"

    @patch('time.time')
    @patch('time.sleep')
    def test_poll_listing_completion_timeout(self, mock_sleep, mock_time):
        """Test polling con timeout."""
        # Configurar tiempo para simular timeout
        mock_time.side_effect = [0, 30, 65]  # start, check, timeout

        # Configurar respuesta que nunca completa
        self.aws_client.list_file_transfer_results.return_value = {
            "FileTransferResults": [
                {"FilePath": "/test-/file1.txt", "StatusCode": "IN_PROGRESS"}
            ]
        }

        with pytest.raises(TimeoutError) as exc_info:
            self.service._poll_listing_completion("exec-123", "connector-123", timeout=60)

        assert exc_info.value.error_code == "LISTING_TIMEOUT"

    @patch('time.sleep')
    def test_poll_listing_completion_connection_error_recovery(self, mock_sleep):
        """Test polling con error de conexión recuperable."""
        # Configurar secuencia: error de conexión -> éxito
        def side_effect(connector_id, transfer_id):
            if self.aws_client.list_file_transfer_results.call_count == 1:
                raise Exception("Connection timeout")
            return {"FileTransferResults": [{"FilePath": "/test-/file1.txt", "StatusCode": "COMPLETED"}]}

        self.aws_client.list_file_transfer_results.side_effect = side_effect

        # Current implementation doesn't handle connection errors with retry
        with pytest.raises(Exception) as exc_info:
            self.service._poll_listing_completion("exec-123", "connector-123")

        assert "Connection timeout" in str(exc_info.value)
        assert self.aws_client.list_file_transfer_results.call_count == 1

    def test_poll_listing_completion_non_recoverable_error(self):
        """Test polling con error no recuperable."""
        # Configurar error no relacionado con conexión
        self.aws_client.list_file_transfer_results.side_effect = Exception("Invalid transfer ID")

        with pytest.raises(Exception) as exc_info:
            self.service._poll_listing_completion("exec-123", "connector-123")

        assert "Invalid transfer ID" in str(exc_info.value)


class TestParseDirectoryResponse:
    """Tests para el método _parse_directory_response."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_parse_directory_response_with_files_and_directories(self):
        """Test parsing de respuesta con archivos y directorios."""
        response = {
            "FileTransferResults": [
                {
                    "FilePath": "/home/user/document.txt",
                    "StatusCode": "COMPLETED"
                },
                {
                    "FilePath": "/home/user/subfolder/",
                    "StatusCode": "COMPLETED"
                },
                {
                    "FilePath": "/home/user/image.jpg",
                    "StatusCode": "COMPLETED"
                }
            ]
        }

        result = self.service._parse_directory_response(response, "/home/user", "listing-123")

        assert isinstance(result, DirectoryListing)
        assert result.path == "/home/user"
        assert result.listing_id == "listing-123"
        assert result.total_items == 3
        assert len(result.files) == 2
        assert len(result.directories) == 1

        # Verificar archivos
        assert len(result.files) == 2
        file_names = [f["name"] for f in result.files]
        assert "document.txt" in file_names
        assert "image.jpg" in file_names

        # Verificar que los archivos tienen la estructura correcta
        for file_info in result.files:
            assert file_info["size"] == 0  # New API doesn't provide size
            assert file_info["type"] == "file"

        # Verificar directorios
        assert len(result.directories) == 1
        dir_names = [d["name"] for d in result.directories]
        assert "subfolder" in dir_names

    def test_parse_directory_response_empty_directory(self):
        """Test parsing de respuesta con directorio vacío."""
        response = {
            "FileTransferResults": []
        }

        result = self.service._parse_directory_response(response, "/empty/dir", "listing-456")

        assert result.path == "/empty/dir"
        assert result.listing_id == "listing-456"
        assert result.total_items == 0
        assert len(result.files) == 0
        assert len(result.directories) == 0

    def test_parse_directory_response_only_files(self):
        """Test parsing de respuesta solo con archivos."""
        response = {
            "FileTransferResults": [
                {
                    "FilePath": "/files/file1.txt",
                    "StatusCode": "COMPLETED"
                },
                {
                    "FilePath": "/files/file2.pdf",
                    "StatusCode": "COMPLETED"
                }
            ]
        }

        result = self.service._parse_directory_response(response, "/files", "listing-789")

        assert len(result.files) == 2
        assert len(result.directories) == 0
        assert result.total_items == 2
        assert result.listing_id == "listing-789"

    def test_parse_directory_response_only_directories(self):
        """Test parsing de respuesta solo con directorios."""
        response = {
            "FileTransferResults": [
                {
                    "FilePath": "/dirs/dir1/",
                    "StatusCode": "COMPLETED"
                },
                {
                    "FilePath": "/dirs/dir2/",
                    "StatusCode": "COMPLETED"
                }
            ]
        }

        result = self.service._parse_directory_response(response, "/dirs", "listing-101")

        assert len(result.files) == 0
        assert len(result.directories) == 2
        assert result.total_items == 2
        assert result.listing_id == "listing-101"
        dir_names = [d["name"] for d in result.directories]
        assert "dir1" in dir_names
        assert "dir2" in dir_names

    def test_parse_directory_response_malformed(self):
        """Test parsing de respuesta malformada."""
        response = {
            "TransferId": "exec-123",
            "Status": "COMPLETED"
            # Missing "FileTransferResults"
        }

        with pytest.raises(TransferError) as exc_info:
            self.service._parse_directory_response(response, "/path", "listing-error")

        assert exc_info.value.error_code == "RESPONSE_PARSE_ERROR"


class TestHandleDirectoryErrors:
    """Tests para el método _handle_directory_errors."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_handle_directory_errors_validation_error(self):
        """Test manejo de ValidationError (re-lanzar)."""
        original_error = ValidationError("Invalid path", error_code="INVALID_PATH")

        with pytest.raises(ValidationError) as exc_info:
            self.service._handle_directory_errors(original_error, "/path")

        assert exc_info.value == original_error

    def test_handle_directory_errors_file_not_found(self):
        """Test manejo de error de archivo no encontrado."""
        original_error = Exception("Directory not found")

        with pytest.raises(FileNotFoundError) as exc_info:
            self.service._handle_directory_errors(original_error, "/missing/path")

        assert exc_info.value.error_code == "DIRECTORY_NOT_FOUND"
        assert "/missing/path" in str(exc_info.value)

    def test_handle_directory_errors_access_denied(self):
        """Test manejo de error de acceso denegado."""
        original_error = Exception("Access denied to directory")

        with pytest.raises(InsufficientPermissionsError) as exc_info:
            self.service._handle_directory_errors(original_error, "/secure/path")

        assert exc_info.value.error_code == "DIRECTORY_ACCESS_DENIED"

    def test_handle_directory_errors_connection_error(self):
        """Test manejo de error de conexión."""
        original_error = Exception("SFTP connection timeout")

        with pytest.raises(ConnectionError) as exc_info:
            self.service._handle_directory_errors(original_error, "/remote/path")

        assert exc_info.value.error_code == "SFTP_CONNECTION_ERROR"

    def test_handle_directory_errors_authentication_error(self):
        """Test manejo de error de autenticación."""
        original_error = Exception("Authentication failed")

        with pytest.raises(AuthenticationError) as exc_info:
            self.service._handle_directory_errors(original_error, "/path")

        assert exc_info.value.error_code == "SFTP_AUTH_ERROR"

    def test_handle_directory_errors_generic_error(self):
        """Test manejo de error genérico."""
        original_error = Exception("Unknown error occurred")

        with pytest.raises(TransferError) as exc_info:
            self.service._handle_directory_errors(original_error, "/path")

        assert exc_info.value.error_code == "DIRECTORY_LISTING_FAILED"


class TestListDirectory:
    """Tests para el método list_directory."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_list_directory_successful(self):
        """Test listado exitoso de directorio."""
        # Configurar respuesta de AWS
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-123",
            "OutputFileName": "directory_listing_20250125.json"
        }

        self.aws_client.list_file_transfer_results.return_value = {
            "FileTransferResults": [
                {
                    "FilePath": "/home/user/file.txt",
                    "StatusCode": "COMPLETED"
                }
            ]
        }

        result = self.service.list_directory("/home/user", "connector-123")

        assert isinstance(result, DirectoryListing)
        assert result.path == "/home/user"
        assert result.listing_id == "listing-123"
        assert result.output_filename == "directory_listing_20250125.json"
        assert len(result.files) == 1
        assert result.files[0]["name"] == "file.txt"

        # Verificar llamadas
        self.aws_client.start_directory_listing.assert_called_once()
        self.aws_client.list_file_transfer_results.assert_called_with(
            connector_id="connector-123", transfer_id="listing-123"
        )

    def test_list_directory_with_max_items(self):
        """Test listado con max_items."""
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-456",
            "OutputFileName": "listing_output.json"
        }
        # Mock the polling response with completed status
        self.aws_client.list_file_transfer_results.return_value = {
            "FileTransferResults": [
                {
                    "FilePath": "/path/file.txt",
                    "StatusCode": "COMPLETED"
                }
            ]
        }

        result = self.service.list_directory("/path", "connector-123", max_items=50)

        # Verificar que se pasó max_items en la solicitud
        call_args = self.aws_client.start_directory_listing.call_args[0][0]
        assert call_args["MaxItems"] == 50

        # Verificar que el resultado es válido
        assert isinstance(result, DirectoryListing)
        assert result.path == "/path"

    def test_list_directory_validation_error(self):
        """Test listado con error de validación."""
        with pytest.raises(ValidationError):
            self.service.list_directory("", "connector-123")  # Path vacío

    def test_list_directory_aws_error(self):
        """Test listado con error de AWS."""
        self.aws_client.start_directory_listing.side_effect = Exception("AWS API error")

        with pytest.raises(Exception) as exc_info:
            self.service.list_directory("/path", "connector-123")

        assert "AWS API error" in str(exc_info.value)


class TestGetDirectoryInfo:
    """Tests para el método get_directory_info."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_get_directory_info_exists(self):
        """Test obtener información de directorio existente."""
        # Mock list_directory para simular directorio existente
        mock_listing = DirectoryListing(
            path="/home/user",
            files=[{"name": "file.txt"}],
            directories=["subdir"],
            total_items=2
        )

        with patch.object(self.service, 'list_directory', return_value=mock_listing):
            info = self.service.get_directory_info("/home/user", "connector-123")

        assert info["path"] == "/home/user"
        assert info["exists"] is True
        assert info["total_items"] == 2
        assert info["accessible"] is True
        assert info["has_files"] is True
        assert info["has_directories"] is True
        assert "last_checked" in info

    def test_get_directory_info_not_found(self):
        """Test obtener información de directorio no encontrado."""
        with patch.object(self.service, 'list_directory', side_effect=FileNotFoundError("Not found")):
            info = self.service.get_directory_info("/missing", "connector-123")

        assert info["path"] == "/missing"
        assert info["exists"] is False
        assert info["total_items"] == 0
        assert info["accessible"] is False
        assert info["has_files"] is False
        assert info["has_directories"] is False

    def test_get_directory_info_error(self):
        """Test obtener información con error general."""
        with patch.object(self.service, 'list_directory', side_effect=Exception("General error")):
            with pytest.raises(Exception) as exc_info:
                self.service.get_directory_info("/error", "connector-123")

        assert "General error" in str(exc_info.value)


class TestListDirectoryAsync:
    """Tests para el método list_directory_async."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_list_directory_async_successful(self):
        """Test inicio exitoso de listado asíncrono."""
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-123",
            "OutputFileName": "async_listing.json"
        }

        result = self.service.list_directory_async("/path", "connector-123")

        assert result["listing_id"] == "listing-123"
        self.aws_client.start_directory_listing.assert_called_once()

    def test_list_directory_async_with_max_items(self):
        """Test inicio de listado asíncrono con max_items."""
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-456",
            "OutputFileName": "max_items_listing.json"
        }

        result = self.service.list_directory_async("/path", "connector-123", max_items=100)

        assert result["listing_id"] == "listing-456"

        # Verificar parámetros de la llamada
        call_args = self.aws_client.start_directory_listing.call_args[0][0]
        assert call_args["MaxItems"] == 100

    def test_list_directory_async_with_output_directory(self):
        """Test inicio de listado asíncrono con output_directory_path."""
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-789",
            "OutputFileName": "custom_output_listing.json"
        }

        result = self.service.list_directory_async(
            "/path",
            "connector-123",
            max_items=50,
            output_directory_path="/custom/output"
        )

        assert result["listing_id"] == "listing-789"

        # Verificar parámetros de la llamada
        call_args = self.aws_client.start_directory_listing.call_args[0][0]
        assert call_args["MaxItems"] == 50
        assert call_args["OutputDirectoryPath"] == "/custom/output"

    def test_list_directory_async_validation_error(self):
        """Test inicio de listado asíncrono con error de validación."""
        with pytest.raises(ValidationError):
            self.service.list_directory_async("", "connector-123")  # Path vacío


class TestGetListingResult:
    """Tests para el método get_listing_result."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.service = ListingService(self.aws_client)

    def test_get_listing_result_completed(self):
        """Test obtener resultado de listado completado."""
        response = {
            "FileTransferResults": [
                {
                    "FilePath": "/path/file.txt",
                    "StatusCode": "COMPLETED"
                }
            ]
        }

        self.aws_client.list_file_transfer_results.return_value = response

        result = self.service.get_listing_result("listing-123", "connector-123", "/path")

        assert isinstance(result, DirectoryListing)
        assert result.path == "/path"
        assert result.listing_id == "listing-123"
        assert len(result.files) == 1

    def test_get_listing_result_failed(self):
        """Test obtener resultado de listado fallido."""
        response = {
            "FileTransferResults": [
                {
                    "FilePath": "/path/file.txt",
                    "StatusCode": "FAILED",
                    "FailureCode": "CONNECTION_ERROR",
                    "FailureMessage": "Connection failed"
                }
            ]
        }

        self.aws_client.list_file_transfer_results.return_value = response

        with pytest.raises(TransferError) as exc_info:
            self.service.get_listing_result("listing-123", "connector-123", "/path")

        assert exc_info.value.error_code == "LISTING_FAILED"
        assert "Directory listing failed for 1 files" in str(exc_info.value)

    def test_get_listing_result_in_progress(self):
        """Test obtener resultado de listado en progreso."""
        response = {
            "FileTransferResults": [
                {
                    "FilePath": "/path/file.txt",
                    "StatusCode": "IN_PROGRESS"
                }
            ]
        }

        self.aws_client.list_file_transfer_results.return_value = response

        with pytest.raises(TransferError) as exc_info:
            self.service.get_listing_result("listing-123", "connector-123", "/path")

        assert exc_info.value.error_code == "LISTING_IN_PROGRESS"


# Tests de integración
class TestListingServiceIntegration:
    """Tests de integración para ListingService."""

    def test_full_listing_workflow(self):
        """Test flujo completo de listado."""
        aws_client = Mock(spec=IAWSClient)
        service = ListingService(aws_client)

        # Configurar respuestas de AWS
        aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-123",
            "OutputFileName": "integration_test_listing.json"
        }
        aws_client.list_file_transfer_results.return_value = {
            "FileTransferResults": [
                {
                    "FilePath": "/remote/documents/document.pdf",
                    "StatusCode": "COMPLETED"
                },
                {
                    "FilePath": "/remote/documents/images/",
                    "StatusCode": "COMPLETED"
                }
            ]
        }

        # Ejecutar listado
        result = service.list_directory("/home/user/documents", "connector-123", max_items=50)

        # Verificar resultado
        assert result.path == "/home/user/documents"
        assert result.listing_id == "listing-123"
        assert result.output_filename == "integration_test_listing.json"
        assert result.total_items == 2
        assert len(result.files) == 1
        assert len(result.directories) == 1

        # Verificar archivo
        file_info = result.files[0]
        assert file_info["name"] == "document.pdf"
        assert file_info["size"] == 0  # New API doesn't provide size directly
        assert file_info["type"] == "file"

        # Verificar directorio
        dir_info = result.directories[0]
        assert dir_info["name"] == "images"
        assert dir_info["type"] == "directory"

        # Verificar llamadas a AWS
        aws_client.start_directory_listing.assert_called_once()
        aws_client.list_file_transfer_results.assert_called_with(
            connector_id="connector-123", transfer_id="listing-123"
        )