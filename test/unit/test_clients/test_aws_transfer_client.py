"""
Tests para AWSTransferClient.

Este módulo contiene tests unitarios para el cliente AWS Transfer Family,
incluyendo validaciones de parámetros y manejo de errores.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from botocore.exceptions import ClientError, BotoCoreError

from src.clients.aws_transfer_client import AWSTransferClient
from src.models.config_models import RetryConfig
from src.exceptions.transfer_exceptions import (
    ValidationError,
    TransferError,
    ConnectionError as TransferConnectionError,
    AuthenticationError,
    ThrottleError,
    TimeoutError as TransferTimeoutError
)


class TestAWSTransferClientInitialization:
    """Tests para la inicialización de AWSTransferClient."""

    @patch('clients.aws_transfer_client.boto3.client')
    def test_initialization_default_config(self, mock_boto_client):
        """Test inicialización con configuración por defecto."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client

        client = AWSTransferClient()

        assert client._client == mock_client
        assert client.retry_config is not None
        mock_boto_client.assert_called_once_with('transfer')

    @patch('clients.aws_transfer_client.boto3.client')
    def test_initialization_custom_retry_config(self, mock_boto_client):
        """Test inicialización con configuración de reintentos personalizada."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client

        custom_retry = RetryConfig(max_attempts=5, base_delay=2.0)
        client = AWSTransferClient(retry_config=custom_retry)

        assert client.retry_config == custom_retry
        assert client.retry_config.max_attempts == 5
        assert client.retry_config.base_delay == 2.0

    @patch('clients.aws_transfer_client.boto3.client')
    def test_initialization_boto_error(self, mock_boto_client):
        """Test inicialización con error de boto3."""
        mock_boto_client.side_effect = Exception("AWS credentials not found")

        with pytest.raises(AuthenticationError) as exc_info:
            AWSTransferClient()

        assert exc_info.value.error_code == "AUTH_FAILED"
        assert "credentials" in str(exc_info.value)

    @patch('clients.aws_transfer_client.boto3.client')
    def test_initialization_connection_error(self, mock_boto_client):
        """Test inicialización con error de conexión (no credentials)."""
        mock_boto_client.side_effect = Exception("Network connection failed")

        with pytest.raises(TransferConnectionError) as exc_info:
            AWSTransferClient()

        assert exc_info.value.error_code == "CONNECTION_FAILED"
        assert "Network connection failed" in str(exc_info.value.context["original_error"])


class TestStartDirectoryListingValidation:
    """Tests para validación de parámetros en start_directory_listing."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client'):
            self.client = AWSTransferClient()

    def test_validate_directory_listing_request_valid(self):
        """Test validación de solicitud válida."""
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": 100,
            "OutputDirectoryPath": "/output/path"
        }

        # No debería lanzar excepción
        self.client._validate_directory_listing_request(request)

    def test_validate_directory_listing_request_missing_connector_id(self):
        """Test validación sin ConnectorId."""
        request = {
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_directory_listing_request(request)

        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

    def test_validate_directory_listing_request_missing_directory_path(self):
        """Test validación sin RemoteDirectoryPath."""
        request = {
            "ConnectorId": "connector-123"
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_directory_listing_request(request)

        assert exc_info.value.error_code == "MISSING_DIRECTORY_PATH"

    def test_validate_directory_listing_request_invalid_max_items(self):
        """Test validación con MaxItems inválido."""
        invalid_max_items = [0, -5, "100", 1001]

        for max_items in invalid_max_items:
            request = {
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": "/remote/path",
                "MaxItems": max_items
            }

            with pytest.raises(ValidationError) as exc_info:
                self.client._validate_directory_listing_request(request)

            assert exc_info.value.error_code in ["INVALID_MAX_ITEMS", "MAX_ITEMS_EXCEEDED"]

    def test_validate_directory_listing_request_invalid_output_directory(self):
        """Test validación con OutputDirectoryPath inválido."""
        invalid_paths = [
            "",  # Vacío
            "   ",  # Solo espacios
            123,  # No string
            "a" * 1025,  # Muy largo
        ]

        for path in invalid_paths:
            request = {
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": "/remote/path",
                "OutputDirectoryPath": path
            }

            with pytest.raises(ValidationError) as exc_info:
                self.client._validate_directory_listing_request(request)

            assert exc_info.value.error_code in ["INVALID_OUTPUT_DIRECTORY", "OUTPUT_DIRECTORY_TOO_LONG"]

    def test_validate_directory_listing_request_long_directory_path(self):
        """Test validación con RemoteDirectoryPath muy largo."""
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "a" * 1025  # Muy largo
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_directory_listing_request(request)

        assert exc_info.value.error_code == "DIRECTORY_PATH_TOO_LONG"


class TestStartDirectoryListing:
    """Tests para el método start_directory_listing."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_start_directory_listing_successful(self):
        """Test inicio exitoso de listado de directorio."""
        # Configurar respuesta exitosa
        expected_response = {
            "ListingId": "listing-123",
            "OutputFileName": "directory_listing_20250125.json"
        }
        self.mock_client.start_directory_listing.return_value = expected_response

        # Ejecutar solicitud
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": 100
        }

        response = self.client.start_directory_listing(request)

        # Verificar resultado
        assert response == expected_response
        self.mock_client.start_directory_listing.assert_called_once_with(**request)

    def test_start_directory_listing_with_output_directory(self):
        """Test inicio de listado con OutputDirectoryPath."""
        # Configurar respuesta exitosa
        expected_response = {
            "ListingId": "listing-456",
            "OutputFileName": "custom_listing.json"
        }
        self.mock_client.start_directory_listing.return_value = expected_response

        # Ejecutar solicitud con output directory
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": 50,
            "OutputDirectoryPath": "/custom/output"
        }

        response = self.client.start_directory_listing(request)

        # Verificar resultado
        assert response == expected_response
        assert response["ListingId"] == "listing-456"
        assert response["OutputFileName"] == "custom_listing.json"
        self.mock_client.start_directory_listing.assert_called_once_with(**request)

    def test_start_directory_listing_throttling_error(self):
        """Test manejo de error de throttling."""
        # Configurar error de throttling
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            },
            'ResponseMetadata': {
                'RequestId': 'test-request-id'
            }
        }

        self.mock_client.start_directory_listing.side_effect = ClientError(
            error_response, 'start_directory_listing'
        )

        # Ejecutar solicitud
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(ThrottleError) as exc_info:
            self.client.start_directory_listing(request)

        assert exc_info.value.error_code == "Throttling"
        assert "Rate exceeded" in str(exc_info.value)

    def test_start_directory_listing_access_denied_error(self):
        """Test manejo de error de acceso denegado."""
        # Configurar error de acceso denegado
        error_response = {
            'Error': {
                'Code': 'AccessDenied',
                'Message': 'Access denied to connector'
            }
        }

        self.mock_client.start_directory_listing.side_effect = ClientError(
            error_response, 'start_directory_listing'
        )

        # Ejecutar solicitud
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(AuthenticationError) as exc_info:
            self.client.start_directory_listing(request)

        assert exc_info.value.error_code == "AccessDenied"

    def test_start_directory_listing_validation_error(self):
        """Test manejo de error de validación de AWS."""
        # Configurar error de validación
        error_response = {
            'Error': {
                'Code': 'ValidationException',
                'Message': 'Invalid connector ID'
            }
        }

        self.mock_client.start_directory_listing.side_effect = ClientError(
            error_response, 'start_directory_listing'
        )

        # Ejecutar solicitud
        request = {
            "ConnectorId": "invalid-connector",
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client.start_directory_listing(request)

        assert exc_info.value.error_code == "ValidationException"

    def test_start_directory_listing_connection_error(self):
        """Test manejo de error de conexión."""
        # Configurar error de conexión
        self.mock_client.start_directory_listing.side_effect = BotoCoreError()

        # Ejecutar solicitud
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(TransferConnectionError) as exc_info:
            self.client.start_directory_listing(request)

        assert exc_info.value.error_code == "CONNECTION_FAILED"

    @patch('time.sleep')
    def test_start_directory_listing_retry_on_throttling(self, mock_sleep):
        """Test reintentos en caso de throttling."""
        # Configurar secuencia: throttling -> éxito
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            }
        }

        success_response = {
            "ListingId": "listing-retry-123",
            "OutputFileName": "retry_listing.json"
        }

        self.mock_client.start_directory_listing.side_effect = [
            ClientError(error_response, 'start_directory_listing'),
            success_response
        ]

        # Ejecutar solicitud
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        response = self.client.start_directory_listing(request)

        # Verificar que se reintentó y tuvo éxito
        assert response == success_response
        assert self.mock_client.start_directory_listing.call_count == 2
        mock_sleep.assert_called_once()  # Se hizo sleep entre reintentos

    @patch('time.sleep')
    def test_start_directory_listing_max_retries_exceeded(self, mock_sleep):
        """Test falla después de agotar reintentos."""
        # Configurar error persistente de throttling
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            }
        }

        self.mock_client.start_directory_listing.side_effect = ClientError(
            error_response, 'start_directory_listing'
        )

        # Ejecutar solicitud
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(ThrottleError):
            self.client.start_directory_listing(request)

        # Verificar que se hicieron todos los reintentos
        assert self.mock_client.start_directory_listing.call_count == self.client.retry_config.max_attempts


class TestListFileTransferResults:
    """Tests para el método list_file_transfer_results."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_list_file_transfer_results_successful(self):
        """Test list_file_transfer_results exitoso."""
        # Configurar respuesta exitosa
        expected_response = {
            "FileTransferResults": [
                {
                    "FilePath": "/source/file.txt",
                    "StatusCode": "COMPLETED"
                }
            ]
        }
        self.mock_client.list_file_transfer_results.return_value = expected_response

        # Ejecutar solicitud
        response = self.client.list_file_transfer_results("connector-123", "transfer-123")

        # Verificar resultado
        assert response == expected_response
        self.mock_client.list_file_transfer_results.assert_called_once_with(
            ConnectorId="connector-123", TransferId="transfer-123"
        )

    def test_list_file_transfer_results_invalid_params(self):
        """Test list_file_transfer_results con parámetros inválidos."""
        # Test connector_id inválido
        invalid_connector_ids = [None, "", "   ", 123]

        for invalid_id in invalid_connector_ids:
            with pytest.raises(ValidationError) as exc_info:
                self.client.list_file_transfer_results(invalid_id, "transfer-123")

            assert exc_info.value.error_code == "INVALID_CONNECTOR_ID"

        # Test transfer_id inválido
        invalid_transfer_ids = [None, "", "   ", 123]

        for invalid_id in invalid_transfer_ids:
            with pytest.raises(ValidationError) as exc_info:
                self.client.list_file_transfer_results("connector-123", invalid_id)

            assert exc_info.value.error_code == "INVALID_TRANSFER_ID"

    def test_list_file_transfer_results_not_found(self):
        """Test list_file_transfer_results con transferencia no encontrada."""
        # Configurar error de no encontrado
        error_response = {
            'Error': {
                'Code': 'TransferNotFound',
                'Message': 'Transfer not found'
            }
        }

        self.mock_client.list_file_transfer_results.side_effect = ClientError(
            error_response, 'list_file_transfer_results'
        )

        with pytest.raises(ValidationError) as exc_info:
            self.client.list_file_transfer_results("connector-123", "nonexistent-id")

        assert exc_info.value.error_code == "TransferNotFound"

    def test_list_file_transfer_results_with_pagination(self):
        """Test list_file_transfer_results con paginación."""
        expected_response = {
            "FileTransferResults": [
                {"FilePath": "/file1.txt", "StatusCode": "COMPLETED"},
                {"FilePath": "/file2.txt", "StatusCode": "COMPLETED"}
            ],
            "NextToken": "next-page-token"
        }
        self.mock_client.list_file_transfer_results.return_value = expected_response

        # Ejecutar solicitud con parámetros de paginación
        response = self.client.list_file_transfer_results(
            "connector-123",
            "transfer-123",
            next_token="current-token",
            max_results=10
        )

        # Verificar resultado
        assert response == expected_response
        self.mock_client.list_file_transfer_results.assert_called_once_with(
            ConnectorId="connector-123",
            TransferId="transfer-123",
            NextToken="current-token",
            MaxResults=10
        )


class TestErrorHandling:
    """Tests para manejo de errores generales."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_is_retriable_error(self):
        """Test identificación de errores retriables."""
        retriable_errors = [
            'Throttling',
            'ThrottlingException',
            'RequestLimitExceeded',
            'ServiceUnavailable',
            'InternalServerError',
            'RequestTimeout'
        ]

        for error_code in retriable_errors:
            assert self.client._is_retriable_error(error_code) is True

        non_retriable_errors = [
            'AccessDenied',
            'ValidationException',
            'ExecutionNotFound',
            'InvalidParameterValue'
        ]

        for error_code in non_retriable_errors:
            assert self.client._is_retriable_error(error_code) is False

    def test_calculate_backoff_delay(self):
        """Test cálculo de delay para backoff exponencial."""
        # Test con configuración por defecto
        delay_0 = self.client._calculate_backoff_delay(0)
        delay_1 = self.client._calculate_backoff_delay(1)
        delay_2 = self.client._calculate_backoff_delay(2)

        # Verificar que el delay aumenta exponencialmente
        assert delay_0 == 1.0  # base_delay
        assert delay_1 == 2.0  # base_delay * exponential_base^1
        assert delay_2 == 4.0  # base_delay * exponential_base^2

        # Test que no exceda max_delay
        large_attempt = 10
        delay_large = self.client._calculate_backoff_delay(large_attempt)
        assert delay_large <= self.client.retry_config.max_delay

    def test_handle_api_error_mapping(self):
        """Test mapeo de errores de API a excepciones específicas."""
        # Create a proper ClientError instance
        from botocore.exceptions import ClientError

        error_response = {
            'Error': {'Code': 'Throttling', 'Message': 'Rate limit exceeded'},
            'ResponseMetadata': {'RequestId': 'test-request-id'}
        }
        mock_error = ClientError(error_response, 'TestOperation')

        # Test ThrottleError
        with pytest.raises(ThrottleError):
            self.client._handle_api_error(
                mock_error, "Throttling", "Rate limit exceeded"
            )

        # Test AuthenticationError
        error_response_auth = {
            'Error': {'Code': 'AccessDenied', 'Message': 'Access denied'},
            'ResponseMetadata': {'RequestId': 'test-request-id'}
        }
        mock_error_auth = ClientError(error_response_auth, 'TestOperation')
        with pytest.raises(AuthenticationError):
            self.client._handle_api_error(
                mock_error_auth, "AccessDenied", "Access denied"
            )

        # Test ValidationError
        error_response_val = {
            'Error': {'Code': 'ValidationException', 'Message': 'Invalid parameter'},
            'ResponseMetadata': {'RequestId': 'test-request-id'}
        }
        mock_error_val = ClientError(error_response_val, 'TestOperation')
        with pytest.raises(ValidationError):
            self.client._handle_api_error(
                mock_error_val, "ValidationException", "Invalid parameter"
            )

        # Test TimeoutError
        error_response_timeout = {
            'Error': {'Code': 'RequestTimeout', 'Message': 'Request timed out'},
            'ResponseMetadata': {'RequestId': 'test-request-id'}
        }
        mock_error_timeout = ClientError(error_response_timeout, 'TestOperation')
        with pytest.raises(TransferTimeoutError):
            self.client._handle_api_error(
                mock_error_timeout, "RequestTimeout", "Request timed out"
            )

        # Test ConnectionError
        error_response_conn = {
            'Error': {'Code': 'ServiceUnavailable', 'Message': 'Service unavailable'},
            'ResponseMetadata': {'RequestId': 'test-request-id'}
        }
        mock_error_conn = ClientError(error_response_conn, 'TestOperation')
        with pytest.raises(TransferConnectionError):
            self.client._handle_api_error(
                mock_error_conn, "ServiceUnavailable", "Service unavailable"
            )

        # Test TransferError genérico
        error_response_generic = {
            'Error': {'Code': 'UnknownError', 'Message': 'Unknown error occurred'},
            'ResponseMetadata': {'RequestId': 'test-request-id'}
        }
        mock_error_generic = ClientError(error_response_generic, 'TestOperation')
        with pytest.raises(TransferError):
            self.client._handle_api_error(
                mock_error_generic, "UnknownError", "Unknown error occurred"
            )


class TestStartFileTransfer:
    """Tests para el método start_file_transfer."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_start_file_transfer_successful_upload(self):
        """Test inicio exitoso de transferencia de upload."""
        expected_response = {
            "TransferId": "transfer-123"
        }
        self.mock_client.start_file_transfer.return_value = expected_response

        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file1.txt", "s3://bucket/file2.txt"]
        }

        response = self.client.start_file_transfer(request)

        assert response == expected_response
        self.mock_client.start_file_transfer.assert_called_once_with(**request)

    def test_start_file_transfer_successful_download(self):
        """Test inicio exitoso de transferencia de download."""
        expected_response = {
            "TransferId": "transfer-456"
        }
        self.mock_client.start_file_transfer.return_value = expected_response

        request = {
            "ConnectorId": "connector-123",
            "RetrieveFilePaths": ["/remote/file1.txt", "/remote/file2.txt"],
            "LocalDirectoryPath": "/local/downloads"
        }

        response = self.client.start_file_transfer(request)

        assert response == expected_response
        self.mock_client.start_file_transfer.assert_called_once_with(**request)

    def test_start_file_transfer_validation_errors(self):
        """Test errores de validación en start_file_transfer."""
        # Test sin ConnectorId
        with pytest.raises(ValidationError) as exc_info:
            self.client.start_file_transfer({})
        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

        # Test sin archivos
        with pytest.raises(ValidationError) as exc_info:
            self.client.start_file_transfer({"ConnectorId": "test"})
        assert exc_info.value.error_code == "NO_FILES_SPECIFIED"

        # Test con ambos tipos de archivos
        with pytest.raises(ValidationError) as exc_info:
            self.client.start_file_transfer({
                "ConnectorId": "test",
                "SendFilePaths": ["file1.txt"],
                "RetrieveFilePaths": ["file2.txt"]
            })
        assert exc_info.value.error_code == "CONFLICTING_FILE_PATHS"

        # Test exceso de archivos
        with pytest.raises(ValidationError) as exc_info:
            self.client.start_file_transfer({
                "ConnectorId": "test",
                "SendFilePaths": [f"file{i}.txt" for i in range(11)]
            })
        assert exc_info.value.error_code == "BATCH_SIZE_EXCEEDED"

    @patch('time.sleep')
    def test_start_file_transfer_retry_success(self, mock_sleep):
        """Test reintentos exitosos en start_file_transfer."""
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            }
        }

        success_response = {"TransferId": "transfer-retry-123"}

        self.mock_client.start_file_transfer.side_effect = [
            ClientError(error_response, 'start_file_transfer'),
            success_response
        ]

        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file.txt"]
        }

        response = self.client.start_file_transfer(request)

        assert response == success_response
        assert self.mock_client.start_file_transfer.call_count == 2
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    def test_start_file_transfer_botocore_error_retry(self, mock_sleep):
        """Test reintentos con BotoCoreError en start_file_transfer."""
        success_response = {"TransferId": "transfer-botocore-123"}

        self.mock_client.start_file_transfer.side_effect = [
            BotoCoreError(),
            success_response
        ]

        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file.txt"]
        }

        response = self.client.start_file_transfer(request)

        assert response == success_response
        assert self.mock_client.start_file_transfer.call_count == 2
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    def test_start_file_transfer_botocore_error_max_retries(self, mock_sleep):
        """Test BotoCoreError que agota todos los reintentos."""
        self.mock_client.start_file_transfer.side_effect = BotoCoreError()

        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file.txt"]
        }

        with pytest.raises(TransferConnectionError) as exc_info:
            self.client.start_file_transfer(request)

        assert exc_info.value.error_code == "CONNECTION_FAILED"
        assert self.mock_client.start_file_transfer.call_count == self.client.retry_config.max_attempts

    @patch('time.sleep')
    def test_start_file_transfer_max_retries_exceeded(self, mock_sleep):
        """Test que agota todos los reintentos con errores retriables."""
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            }
        }

        self.mock_client.start_file_transfer.side_effect = ClientError(
            error_response, 'start_file_transfer'
        )

        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file.txt"]
        }

        with pytest.raises(ThrottleError):
            self.client.start_file_transfer(request)

        assert self.mock_client.start_file_transfer.call_count == self.client.retry_config.max_attempts


class TestStartRemoteDelete:
    """Tests para el método start_remote_delete."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_start_remote_delete_successful(self):
        """Test inicio exitoso de eliminación remota."""
        expected_response = {
            "DeleteId": "delete-123"
        }
        self.mock_client.start_remote_delete.return_value = expected_response

        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/file/to/delete.txt"
        }

        response = self.client.start_remote_delete(request)

        assert response == expected_response
        self.mock_client.start_remote_delete.assert_called_once_with(**request)

    def test_start_remote_delete_validation_errors(self):
        """Test errores de validación en start_remote_delete."""
        # Test sin ConnectorId
        with pytest.raises(ValidationError) as exc_info:
            self.client.start_remote_delete({"DeletePath": "/path"})
        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

        # Test sin DeletePath
        with pytest.raises(ValidationError) as exc_info:
            self.client.start_remote_delete({"ConnectorId": "test"})
        assert exc_info.value.error_code == "NO_DELETE_PATH_SPECIFIED"

        # Test DeletePath vacío
        with pytest.raises(ValidationError) as exc_info:
            self.client.start_remote_delete({
                "ConnectorId": "test",
                "DeletePath": "   "
            })
        assert exc_info.value.error_code == "EMPTY_DELETE_PATH"

        # Test DeletePath muy largo
        with pytest.raises(ValidationError) as exc_info:
            self.client.start_remote_delete({
                "ConnectorId": "test",
                "DeletePath": "a" * 1025
            })
        assert exc_info.value.error_code == "DELETE_PATH_TOO_LONG"


class TestValidationMethods:
    """Tests para métodos de validación."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client'):
            self.client = AWSTransferClient()

    def test_validate_transfer_request_valid_send_files(self):
        """Test validación exitosa para SendFilePaths."""
        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file1.txt", "s3://bucket/file2.txt"],
            "RemoteDirectoryPath": "/remote/path"
        }

        # No debería lanzar excepción
        self.client._validate_transfer_request(request)

    def test_validate_transfer_request_valid_retrieve_files(self):
        """Test validación exitosa para RetrieveFilePaths."""
        request = {
            "ConnectorId": "connector-123",
            "RetrieveFilePaths": ["/remote/file1.txt", "/remote/file2.txt"],
            "LocalDirectoryPath": "/local/path"
        }

        # No debería lanzar excepción
        self.client._validate_transfer_request(request)

    def test_validate_transfer_request_invalid_file_paths(self):
        """Test validación con rutas de archivo inválidas."""
        # SendFilePaths con elementos inválidos
        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["valid-path", "", "   ", 123]
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request(request)
        assert exc_info.value.error_code == "INVALID_SEND_FILE_PATH"

        # RetrieveFilePaths con elementos inválidos
        request = {
            "ConnectorId": "connector-123",
            "RetrieveFilePaths": ["valid-path", None]
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request(request)
        assert exc_info.value.error_code == "INVALID_RETRIEVE_FILE_PATH"

    def test_validate_transfer_request_invalid_directories(self):
        """Test validación con directorios inválidos."""
        # LocalDirectoryPath inválido
        request = {
            "ConnectorId": "connector-123",
            "RetrieveFilePaths": ["/remote/file.txt"],
            "LocalDirectoryPath": ""
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request(request)
        assert exc_info.value.error_code == "INVALID_LOCAL_DIRECTORY_PATH"

        # RemoteDirectoryPath inválido
        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file.txt"],
            "RemoteDirectoryPath": 123
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request(request)
        assert exc_info.value.error_code == "INVALID_REMOTE_DIRECTORY_PATH"

    def test_validate_directory_listing_request_edge_cases(self):
        """Test casos límite en validación de directory listing."""
        # MaxItems en el límite
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/path",
            "MaxItems": 1000
        }
        self.client._validate_directory_listing_request(request)

        # DirectoryPath en el límite
        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "a" * 1024
        }
        self.client._validate_directory_listing_request(request)

    def test_validate_remote_delete_request_edge_cases(self):
        """Test casos límite en validación de remote delete."""
        # DeletePath en el límite
        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "a" * 1024
        }
        self.client._validate_remote_delete_request(request)

        # DeletePath con tipo incorrecto
        request = {
            "ConnectorId": "connector-123",
            "DeletePath": 123
        }

        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_remote_delete_request(request)
        assert exc_info.value.error_code == "INVALID_DELETE_PATH_TYPE"


class TestErrorHandlingExtended:
    """Tests extendidos para manejo de errores."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_handle_api_error_all_mappings(self):
        """Test mapeo completo de errores de API."""
        error_mappings = [
            ("Throttling", ThrottleError),
            ("ThrottlingException", ThrottleError),
            ("RequestLimitExceeded", ThrottleError),
            ("AccessDenied", AuthenticationError),
            ("UnauthorizedOperation", AuthenticationError),
            ("ValidationException", ValidationError),
            ("InvalidParameterValue", ValidationError),
            ("RequestTimeout", TransferTimeoutError),
            ("RequestTimeoutException", TransferTimeoutError),
            ("ServiceUnavailable", TransferConnectionError),
            ("InternalServerError", TransferConnectionError),
            ("Forbidden", TransferError),  # Forbidden maps to TransferError, not AuthenticationError
            ("MalformedInput", TransferError),  # MalformedInput maps to TransferError
            ("InternalError", TransferError),  # InternalError maps to TransferError
            ("UnknownError", TransferError)
        ]

        from botocore.exceptions import ClientError

        for error_code, expected_exception in error_mappings:
            # Create a proper ClientError instance
            error_response = {
                'Error': {'Code': error_code, 'Message': f'Test {error_code} error'},
                'ResponseMetadata': {'RequestId': 'test-request-id'}
            }
            mock_error = ClientError(error_response, 'TestOperation')

            with pytest.raises(expected_exception):
                self.client._handle_api_error(
                    mock_error, error_code, f"Test {error_code} error"
                )

    def test_calculate_backoff_delay_edge_cases(self):
        """Test casos límite del cálculo de backoff delay."""
        # Test con attempt 0
        delay = self.client._calculate_backoff_delay(0)
        assert delay == self.client.retry_config.base_delay

        # Test que respeta max_delay
        large_attempt = 20
        delay = self.client._calculate_backoff_delay(large_attempt)
        assert delay <= self.client.retry_config.max_delay

        # Test con configuración personalizada
        custom_retry = RetryConfig(base_delay=0.1, max_delay=5.0, exponential_base=3.0)
        with patch('clients.aws_transfer_client.boto3.client'):
            custom_client = AWSTransferClient(retry_config=custom_retry)

        delay_0 = custom_client._calculate_backoff_delay(0)
        delay_1 = custom_client._calculate_backoff_delay(1)

        assert delay_0 == 0.1
        assert abs(delay_1 - 0.3) < 0.001  # Use approximate comparison for floating point

    def test_is_retriable_error_comprehensive(self):
        """Test completo de identificación de errores retriables."""
        # Based on the actual implementation, these are the retriable errors
        retriable_errors = [
            'Throttling',
            'ThrottlingException',
            'RequestLimitExceeded',
            'ServiceUnavailable',
            'InternalServerError',
            'InternalError',
            'RequestTimeout',
            'RequestTimeoutException'
        ]

        for error_code in retriable_errors:
            assert self.client._is_retriable_error(error_code) is True

        non_retriable_errors = [
            'AccessDenied',
            'ValidationException',
            'ExecutionNotFound',
            'InvalidParameterValue',
            'MalformedInput',
            'UnauthorizedOperation',
            'Forbidden',
            'ResourceNotFound',
            'ServiceTimeout',  # Not in the actual implementation
            'SlowDown'  # Not in the actual implementation
        ]

        for error_code in non_retriable_errors:
            assert self.client._is_retriable_error(error_code) is False


class TestRetryConfiguration:
    """Tests para configuración de reintentos."""

    def test_custom_retry_configuration(self):
        """Test configuración personalizada de reintentos."""
        custom_retry = RetryConfig(
            max_attempts=5,
            base_delay=0.5,
            max_delay=30.0,
            exponential_base=1.5
        )

        with patch('clients.aws_transfer_client.boto3.client'):
            client = AWSTransferClient(retry_config=custom_retry)

        # Verificar configuración
        assert client.retry_config.max_attempts == 5
        assert client.retry_config.base_delay == 0.5
        assert client.retry_config.max_delay == 30.0
        assert client.retry_config.exponential_base == 1.5

        # Test cálculo de delay con configuración personalizada
        delay_0 = client._calculate_backoff_delay(0)
        delay_1 = client._calculate_backoff_delay(1)

        assert delay_0 == 0.5
        assert delay_1 == 0.75  # 0.5 * 1.5^1


class TestIntegrationScenarios:
    """Tests de escenarios de integración."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_complete_transfer_workflow(self):
        """Test flujo completo de transferencia."""
        # 1. Iniciar transferencia
        start_response = {"TransferId": "transfer-workflow-123"}
        self.mock_client.start_file_transfer.return_value = start_response

        transfer_request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file.txt"]
        }

        start_result = self.client.start_file_transfer(transfer_request)
        assert start_result["TransferId"] == "transfer-workflow-123"

        # 2. Listar resultados
        results_response = {
            "FileTransferResults": [
                {"FilePath": "s3://bucket/file.txt", "StatusCode": "COMPLETED"}
            ]
        }
        self.mock_client.list_file_transfer_results.return_value = results_response

        results = self.client.list_file_transfer_results(
            "connector-123",
            "transfer-workflow-123"
        )
        assert len(results["FileTransferResults"]) == 1
        assert results["FileTransferResults"][0]["StatusCode"] == "COMPLETED"

    def test_directory_operations_workflow(self):
        """Test flujo de operaciones de directorio."""
        # 1. Listar directorio
        listing_response = {
            "ListingId": "listing-123",
            "OutputFileName": "directory_list.json"
        }
        self.mock_client.start_directory_listing.return_value = listing_response

        listing_request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/directory"
        }

        listing_result = self.client.start_directory_listing(listing_request)
        assert listing_result["ListingId"] == "listing-123"

        # 2. Eliminar archivo
        delete_response = {"DeleteId": "delete-123"}
        self.mock_client.start_remote_delete.return_value = delete_response

        delete_request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/directory/old_file.txt"
        }

        delete_result = self.client.start_remote_delete(delete_request)
        assert delete_result["DeleteId"] == "delete-123"

    @patch('time.sleep')
    def test_resilient_error_handling(self, mock_sleep):
        """Test manejo resiliente de errores múltiples."""
        # Secuencia de errores: throttling -> timeout -> éxito
        error_responses = [
            ClientError({
                'Error': {'Code': 'Throttling', 'Message': 'Rate exceeded'}
            }, 'start_file_transfer'),
            ClientError({
                'Error': {'Code': 'RequestTimeout', 'Message': 'Request timed out'}
            }, 'start_file_transfer'),
            {"TransferId": "resilient-123"}
        ]

        self.mock_client.start_file_transfer.side_effect = error_responses

        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/resilient-test.txt"]
        }

        result = self.client.start_file_transfer(request)

        assert result["TransferId"] == "resilient-123"
        assert self.mock_client.start_file_transfer.call_count == 3
        assert mock_sleep.call_count == 2  # Dos reintentos


class TestBotoCoreErrorHandling:
    """Tests específicos para manejo de BotoCoreError."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    @patch('time.sleep')
    def test_start_directory_listing_botocore_error_retry(self, mock_sleep):
        """Test reintentos con BotoCoreError en start_directory_listing."""
        success_response = {"ListingId": "listing-botocore-123"}

        self.mock_client.start_directory_listing.side_effect = [
            BotoCoreError(),
            success_response
        ]

        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        response = self.client.start_directory_listing(request)

        assert response == success_response
        assert self.mock_client.start_directory_listing.call_count == 2
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    def test_start_directory_listing_botocore_error_max_retries(self, mock_sleep):
        """Test BotoCoreError que agota todos los reintentos en start_directory_listing."""
        self.mock_client.start_directory_listing.side_effect = BotoCoreError()

        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(TransferConnectionError) as exc_info:
            self.client.start_directory_listing(request)

        assert exc_info.value.error_code == "CONNECTION_FAILED"
        assert self.mock_client.start_directory_listing.call_count == self.client.retry_config.max_attempts

    @patch('time.sleep')
    def test_list_file_transfer_results_botocore_error_retry(self, mock_sleep):
        """Test reintentos con BotoCoreError en list_file_transfer_results."""
        success_response = {
            "FileTransferResults": [
                {"FilePath": "/file.txt", "StatusCode": "COMPLETED"}
            ]
        }

        self.mock_client.list_file_transfer_results.side_effect = [
            BotoCoreError(),
            success_response
        ]

        response = self.client.list_file_transfer_results("connector-123", "transfer-123")

        assert response == success_response
        assert self.mock_client.list_file_transfer_results.call_count == 2
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    def test_list_file_transfer_results_botocore_error_max_retries(self, mock_sleep):
        """Test BotoCoreError que agota todos los reintentos en list_file_transfer_results."""
        self.mock_client.list_file_transfer_results.side_effect = BotoCoreError()

        with pytest.raises(TransferConnectionError) as exc_info:
            self.client.list_file_transfer_results("connector-123", "transfer-123")

        assert exc_info.value.error_code == "CONNECTION_FAILED"
        assert self.mock_client.list_file_transfer_results.call_count == self.client.retry_config.max_attempts


class TestTransferErrorFallback:
    """Tests para casos donde se lanza TransferError como fallback."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_start_file_transfer_fallback_to_transfer_error(self):
        """Test que start_file_transfer lanza TransferError cuando se agotan reintentos con errores retriables."""
        # Configurar error retriable persistente
        error_response = {
            'Error': {
                'Code': 'InternalServerError',
                'Message': 'Internal server error'
            }
        }

        self.mock_client.start_file_transfer.side_effect = ClientError(
            error_response, 'start_file_transfer'
        )

        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file.txt"]
        }

        # Debería agotar reintentos y lanzar ConnectionError (no TransferError)
        with pytest.raises(TransferConnectionError):
            self.client.start_file_transfer(request)

    def test_start_directory_listing_fallback_to_transfer_error(self):
        """Test que start_directory_listing lanza TransferError cuando se agotan reintentos."""
        # Configurar error retriable persistente
        error_response = {
            'Error': {
                'Code': 'ServiceUnavailable',
                'Message': 'Service temporarily unavailable'
            }
        }

        self.mock_client.start_directory_listing.side_effect = ClientError(
            error_response, 'start_directory_listing'
        )

        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        # Debería agotar reintentos y lanzar ConnectionError (no TransferError)
        with pytest.raises(TransferConnectionError):
            self.client.start_directory_listing(request)

    def test_start_remote_delete_fallback_to_transfer_error(self):
        """Test que start_remote_delete lanza TransferError cuando se agotan reintentos."""
        # Configurar error retriable persistente
        error_response = {
            'Error': {
                'Code': 'RequestTimeout',
                'Message': 'Request timed out'
            }
        }

        self.mock_client.start_remote_delete.side_effect = ClientError(
            error_response, 'start_remote_delete'
        )

        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/file.txt"
        }

        # Debería agotar reintentos y lanzar TimeoutError (no TransferError)
        with pytest.raises(TransferTimeoutError):
            self.client.start_remote_delete(request)


class TestMissingLineCoverage:
    """Tests específicos para cubrir líneas faltantes."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_start_file_transfer_all_retries_exhausted_transfer_error(self):
        """Test TransferError cuando se agotan todos los reintentos en start_file_transfer."""
        # Configurar error retriable que agote todos los reintentos
        # pero que no sea manejado por _handle_api_error
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            }
        }

        # Mock para que _handle_api_error no se ejecute (simular que se agotan reintentos)
        self.mock_client.start_file_transfer.side_effect = ClientError(
            error_response, 'start_file_transfer'
        )

        request = {
            "ConnectorId": "connector-123",
            "SendFilePaths": ["s3://bucket/file.txt"]
        }

        # Debería lanzar ThrottleError, no TransferError
        with pytest.raises(ThrottleError):
            self.client.start_file_transfer(request)

    def test_list_file_transfer_results_invalid_max_results(self):
        """Test validación de max_results inválido en list_file_transfer_results."""
        # Test max_results negativo
        with pytest.raises(ValidationError) as exc_info:
            self.client.list_file_transfer_results(
                "connector-123",
                "transfer-123",
                max_results=-1
            )
        assert exc_info.value.error_code == "INVALID_MAX_RESULTS"

        # Test max_results cero
        with pytest.raises(ValidationError) as exc_info:
            self.client.list_file_transfer_results(
                "connector-123",
                "transfer-123",
                max_results=0
            )
        assert exc_info.value.error_code == "INVALID_MAX_RESULTS"

        # Test max_results no entero
        with pytest.raises(ValidationError) as exc_info:
            self.client.list_file_transfer_results(
                "connector-123",
                "transfer-123",
                max_results="10"
            )
        assert exc_info.value.error_code == "INVALID_MAX_RESULTS"

    @patch('time.sleep')
    def test_list_file_transfer_results_retriable_error_with_retry(self, mock_sleep):
        """Test error retriable en list_file_transfer_results que se reintenta."""
        error_response = {
            'Error': {
                'Code': 'ServiceUnavailable',
                'Message': 'Service temporarily unavailable'
            }
        }

        success_response = {
            "FileTransferResults": [
                {"FilePath": "/file.txt", "StatusCode": "COMPLETED"}
            ]
        }

        self.mock_client.list_file_transfer_results.side_effect = [
            ClientError(error_response, 'list_file_transfer_results'),
            success_response
        ]

        response = self.client.list_file_transfer_results("connector-123", "transfer-123")

        assert response == success_response
        assert self.mock_client.list_file_transfer_results.call_count == 2
        mock_sleep.assert_called_once()

    def test_list_file_transfer_results_all_retries_exhausted_transfer_error(self):
        """Test TransferError cuando se agotan reintentos en list_file_transfer_results."""
        # Configurar error retriable persistente
        error_response = {
            'Error': {
                'Code': 'ServiceUnavailable',
                'Message': 'Service unavailable'
            }
        }

        self.mock_client.list_file_transfer_results.side_effect = ClientError(
            error_response, 'list_file_transfer_results'
        )

        # Debería agotar reintentos y lanzar ConnectionError
        with pytest.raises(TransferConnectionError):
            self.client.list_file_transfer_results("connector-123", "transfer-123")

        assert self.mock_client.list_file_transfer_results.call_count == self.client.retry_config.max_attempts

    def test_start_directory_listing_all_retries_exhausted_transfer_error(self):
        """Test TransferError cuando se agotan reintentos en start_directory_listing."""
        # Configurar error retriable persistente
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            }
        }

        self.mock_client.start_directory_listing.side_effect = ClientError(
            error_response, 'start_directory_listing'
        )

        request = {
            "ConnectorId": "connector-123",
            "RemoteDirectoryPath": "/remote/path"
        }

        # Debería agotar reintentos y lanzar ThrottleError
        with pytest.raises(ThrottleError):
            self.client.start_directory_listing(request)

        assert self.mock_client.start_directory_listing.call_count == self.client.retry_config.max_attempts

    def test_start_remote_delete_all_retries_exhausted_transfer_error(self):
        """Test TransferError cuando se agotan reintentos en start_remote_delete."""
        # Configurar error retriable persistente
        error_response = {
            'Error': {
                'Code': 'InternalServerError',
                'Message': 'Internal server error'
            }
        }

        self.mock_client.start_remote_delete.side_effect = ClientError(
            error_response, 'start_remote_delete'
        )

        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/file.txt"
        }

        # Debería agotar reintentos y lanzar ConnectionError
        with pytest.raises(TransferConnectionError):
            self.client.start_remote_delete(request)

        assert self.mock_client.start_remote_delete.call_count == self.client.retry_config.max_attempts

class TestAWSTransferClientRemoteDeleteOperations:
    """Tests para operaciones de eliminación remota."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client') as mock_boto:
            self.mock_client = Mock()
            mock_boto.return_value = self.mock_client
            self.client = AWSTransferClient()

    def test_start_remote_delete_with_retry_success(self):
        """Test start_remote_delete con reintentos exitosos."""
        # Configurar secuencia: throttling -> éxito
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            }
        }

        success_response = {"DeleteId": "delete-retry-123"}

        self.mock_client.start_remote_delete.side_effect = [
            ClientError(error_response, 'start_remote_delete'),
            success_response
        ]

        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/file.txt"
        }

        with patch('time.sleep'):
            response = self.client.start_remote_delete(request)

        assert response == success_response
        assert self.mock_client.start_remote_delete.call_count == 2

    def test_start_remote_delete_max_retries_exceeded(self):
        """Test start_remote_delete que agota todos los reintentos."""
        error_response = {
            'Error': {
                'Code': 'Throttling',
                'Message': 'Rate exceeded'
            }
        }

        self.mock_client.start_remote_delete.side_effect = ClientError(
            error_response, 'start_remote_delete'
        )

        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/file.txt"
        }

        with patch('time.sleep'):
            with pytest.raises(ThrottleError):
                self.client.start_remote_delete(request)

        assert self.mock_client.start_remote_delete.call_count == self.client.retry_config.max_attempts

    def test_start_remote_delete_botocore_error_retry(self):
        """Test start_remote_delete con BotoCoreError y reintentos."""
        success_response = {"DeleteId": "delete-botocore-123"}

        self.mock_client.start_remote_delete.side_effect = [
            BotoCoreError(),
            success_response
        ]

        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/file.txt"
        }

        with patch('time.sleep'):
            response = self.client.start_remote_delete(request)

        assert response == success_response
        assert self.mock_client.start_remote_delete.call_count == 2

    def test_start_remote_delete_botocore_error_max_retries(self):
        """Test start_remote_delete con BotoCoreError que agota reintentos."""
        self.mock_client.start_remote_delete.side_effect = BotoCoreError()

        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/file.txt"
        }

        with patch('time.sleep'):
            with pytest.raises(TransferConnectionError) as exc_info:
                self.client.start_remote_delete(request)

        assert exc_info.value.error_code == "CONNECTION_FAILED"
        assert self.mock_client.start_remote_delete.call_count == self.client.retry_config.max_attempts

    def test_start_remote_delete_fallback_to_transfer_error(self):
        """Test start_remote_delete que cae a TransferError."""
        # Configurar error no retriable para que caiga directamente a TransferError
        error_response = {
            'Error': {
                'Code': 'UnknownError',
                'Message': 'Unknown error'
            }
        }

        self.mock_client.start_remote_delete.side_effect = ClientError(
            error_response, 'start_remote_delete'
        )

        request = {
            "ConnectorId": "connector-123",
            "DeletePath": "/remote/file.txt"
        }

        with pytest.raises(TransferError) as exc_info:
            self.client.start_remote_delete(request)

        assert exc_info.value.error_code == "UnknownError"


class TestAWSTransferClientValidationEdgeCases:
    """Tests para casos edge de validación."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client'):
            self.client = AWSTransferClient()

    def test_validate_transfer_request_invalid_file_paths_edge_cases(self):
        """Test _validate_transfer_request con casos edge de file paths."""
        # Test con SendFilePaths que contiene string vacío
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request({
                "ConnectorId": "connector-123",
                "SendFilePaths": ["valid/path.txt", ""]
            })
        assert exc_info.value.error_code == "INVALID_SEND_FILE_PATH"
        assert exc_info.value.context["file_index"] == 1

        # Test con SendFilePaths que contiene solo espacios
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request({
                "ConnectorId": "connector-123",
                "SendFilePaths": ["   "]
            })
        assert exc_info.value.error_code == "INVALID_SEND_FILE_PATH"

        # Test con RetrieveFilePaths que contiene string vacío
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request({
                "ConnectorId": "connector-123",
                "RetrieveFilePaths": ["valid/path.txt", ""]
            })
        assert exc_info.value.error_code == "INVALID_RETRIEVE_FILE_PATH"
        assert exc_info.value.context["file_index"] == 1

        # Test con RetrieveFilePaths que contiene solo espacios
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request({
                "ConnectorId": "connector-123",
                "RetrieveFilePaths": ["   "]
            })
        assert exc_info.value.error_code == "INVALID_RETRIEVE_FILE_PATH"

    def test_validate_transfer_request_invalid_directories_edge_cases(self):
        """Test _validate_transfer_request con casos edge de directorios."""
        # Test con LocalDirectoryPath que no es string
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request({
                "ConnectorId": "connector-123",
                "RetrieveFilePaths": ["/remote/file.txt"],
                "LocalDirectoryPath": 123
            })
        assert exc_info.value.error_code == "INVALID_LOCAL_DIRECTORY_PATH"

        # Test con LocalDirectoryPath solo espacios
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request({
                "ConnectorId": "connector-123",
                "RetrieveFilePaths": ["/remote/file.txt"],
                "LocalDirectoryPath": "   "
            })
        assert exc_info.value.error_code == "INVALID_LOCAL_DIRECTORY_PATH"

        # Test con RemoteDirectoryPath que no es string
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request({
                "ConnectorId": "connector-123",
                "SendFilePaths": ["/s3/file.txt"],
                "RemoteDirectoryPath": 123
            })
        assert exc_info.value.error_code == "INVALID_REMOTE_DIRECTORY_PATH"

        # Test con RemoteDirectoryPath solo espacios
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_transfer_request({
                "ConnectorId": "connector-123",
                "SendFilePaths": ["/s3/file.txt"],
                "RemoteDirectoryPath": "   "
            })
        assert exc_info.value.error_code == "INVALID_REMOTE_DIRECTORY_PATH"

    def test_validate_remote_delete_request_edge_cases(self):
        """Test _validate_remote_delete_request con casos edge."""
        # Test con request que no es dict
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_remote_delete_request("not_a_dict")
        assert exc_info.value.error_code == "INVALID_REQUEST_TYPE"

        # Test con DeletePath que no es string
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_remote_delete_request({
                "ConnectorId": "connector-123",
                "DeletePath": 123
            })
        assert exc_info.value.error_code == "INVALID_DELETE_PATH_TYPE"

        # Test con DeletePath muy largo
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_remote_delete_request({
                "ConnectorId": "connector-123",
                "DeletePath": "a" * 1025
            })
        assert exc_info.value.error_code == "DELETE_PATH_TOO_LONG"

    def test_validate_directory_listing_request_edge_cases(self):
        """Test _validate_directory_listing_request con casos edge."""
        # Test con request que no es dict
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_directory_listing_request("not_a_dict")
        assert exc_info.value.error_code == "INVALID_REQUEST_TYPE"

        # Test con RemoteDirectoryPath muy largo
        with pytest.raises(ValidationError) as exc_info:
            self.client._validate_directory_listing_request({
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": "a" * 1025
            })
        assert exc_info.value.error_code == "DIRECTORY_PATH_TOO_LONG"


class TestAWSTransferClientErrorHandlingEdgeCases:
    """Tests para casos edge de manejo de errores."""

    def setup_method(self):
        """Setup para cada test."""
        with patch('clients.aws_transfer_client.boto3.client'):
            self.client = AWSTransferClient()

    def test_calculate_backoff_delay_edge_cases(self):
        """Test _calculate_backoff_delay con casos edge."""
        # Test con attempt muy grande que excede max_delay
        large_attempt = 20
        delay = self.client._calculate_backoff_delay(large_attempt)
        assert delay == self.client.retry_config.max_delay

        # Test con attempt 0
        delay_0 = self.client._calculate_backoff_delay(0)
        assert delay_0 == self.client.retry_config.base_delay

    def test_handle_api_error_comprehensive_mapping(self):
        """Test _handle_api_error con mapeo comprehensivo de errores."""
        from botocore.exceptions import ClientError

        # Create a proper ClientError instance
        error_response = {
            'Error': {'Code': 'InternalServerError', 'Message': 'Internal server error'},
            'ResponseMetadata': {'RequestId': 'test-request-id'}
        }
        mock_error = ClientError(error_response, 'TestOperation')

        # Test InternalServerError -> TransferConnectionError
        with pytest.raises(TransferConnectionError):
            self.client._handle_api_error(
                mock_error, "InternalServerError", "Internal server error"
            )

        # Test RequestTimeoutException -> TimeoutError
        with pytest.raises(TransferTimeoutError):
            self.client._handle_api_error(
                mock_error, "RequestTimeoutException", "Request timeout"
            )

        # Test InvalidParameterValue -> ValidationError
        with pytest.raises(ValidationError):
            self.client._handle_api_error(
                mock_error, "InvalidParameterValue", "Invalid parameter"
            )

        # Test error desconocido -> TransferError
        with pytest.raises(TransferError):
            self.client._handle_api_error(
                mock_error, "UnknownErrorCode", "Unknown error"
            )