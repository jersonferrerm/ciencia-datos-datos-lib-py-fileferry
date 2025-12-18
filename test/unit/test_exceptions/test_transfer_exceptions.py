"""
Tests para excepciones de transferencia.

Este módulo contiene tests unitarios para toda la jerarquía de excepciones
personalizadas de la librería S3-SFTP Transfer.
"""

import pytest

from src.exceptions.transfer_exceptions import (
    TransferLibraryError,
    ConfigurationError,
    TransferError,
    ValidationError,
    ThrottleError,
    ConnectionError,
    AuthenticationError,
    TimeoutError,
    FileNotFoundError,
    InsufficientPermissionsError
)


class TestTransferLibraryError:
    """Tests para la excepción base TransferLibraryError."""

    def test_basic_creation(self):
        """Test creación básica de TransferLibraryError."""
        error = TransferLibraryError("Test error message")

        assert str(error) == "Test error message"
        assert error.message == "Test error message"
        assert error.error_code is None
        assert error.context == {}

    def test_creation_with_error_code(self):
        """Test creación con código de error."""
        error = TransferLibraryError("Test error", error_code="E001")

        assert str(error) == "[E001] Test error"
        assert error.message == "Test error"
        assert error.error_code == "E001"
        assert error.context == {}

    def test_creation_with_context(self):
        """Test creación con contexto."""
        context = {"file": "test.txt", "operation": "upload"}
        error = TransferLibraryError("Test error", context=context)

        assert error.message == "Test error"
        assert error.error_code is None
        assert error.context == context

    def test_creation_with_all_parameters(self):
        """Test creación con todos los parámetros."""
        context = {"file": "test.txt", "size": 1024}
        error = TransferLibraryError(
            "Complete error",
            error_code="E002",
            context=context
        )

        assert str(error) == "[E002] Complete error"
        assert error.message == "Complete error"
        assert error.error_code == "E002"
        assert error.context == context

    def test_inheritance_from_exception(self):
        """Test que TransferLibraryError hereda de Exception."""
        error = TransferLibraryError("Test")
        assert isinstance(error, Exception)

    def test_context_default_empty_dict(self):
        """Test que context por defecto es un diccionario vacío."""
        error = TransferLibraryError("Test", context=None)
        assert error.context == {}


class TestConfigurationError:
    """Tests para ConfigurationError."""

    def test_configuration_error_creation(self):
        """Test creación de ConfigurationError."""
        error = ConfigurationError("Missing environment variable")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "Missing environment variable"
        assert error.message == "Missing environment variable"

    def test_configuration_error_with_code(self):
        """Test ConfigurationError con código."""
        error = ConfigurationError(
            "Invalid connector_id",
            error_code="CONFIG_001"
        )

        assert str(error) == "[CONFIG_001] Invalid connector_id"
        assert error.error_code == "CONFIG_001"

    def test_configuration_error_with_context(self):
        """Test ConfigurationError con contexto."""
        context = {"variable": "CONNECTOR_ID", "value": None}
        error = ConfigurationError(
            "Environment variable not set",
            context=context
        )

        assert error.context == context


class TestTransferError:
    """Tests para TransferError."""

    def test_transfer_error_creation(self):
        """Test creación de TransferError."""
        error = TransferError("Transfer failed")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "Transfer failed"

    def test_transfer_error_with_details(self):
        """Test TransferError con detalles."""
        context = {"file": "large_file.zip", "operation": "upload"}
        error = TransferError(
            "Network timeout during transfer",
            error_code="TRANSFER_001",
            context=context
        )

        assert error.message == "Network timeout during transfer"
        assert error.error_code == "TRANSFER_001"
        assert error.context["file"] == "large_file.zip"
        assert error.context["operation"] == "upload"


class TestValidationError:
    """Tests para ValidationError."""

    def test_validation_error_creation(self):
        """Test creación de ValidationError."""
        error = ValidationError("Invalid file path")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "Invalid file path"

    def test_validation_error_with_field_info(self):
        """Test ValidationError con información de campo."""
        context = {"field": "source_path", "value": "", "constraint": "non-empty"}
        error = ValidationError(
            "Field validation failed",
            error_code="VALIDATION_001",
            context=context
        )

        assert error.context["field"] == "source_path"
        assert error.context["constraint"] == "non-empty"


class TestThrottleError:
    """Tests para ThrottleError."""

    def test_throttle_error_creation(self):
        """Test creación de ThrottleError."""
        error = ThrottleError("Rate limit exceeded")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "Rate limit exceeded"

    def test_throttle_error_with_rate_info(self):
        """Test ThrottleError con información de rate."""
        context = {
            "current_rate": 150,
            "max_rate": 100,
            "retry_after": 30
        }
        error = ThrottleError(
            "Throughput limit exceeded",
            error_code="THROTTLE_001",
            context=context
        )

        assert error.context["current_rate"] == 150
        assert error.context["max_rate"] == 100
        assert error.context["retry_after"] == 30


class TestConnectionError:
    """Tests para ConnectionError."""

    def test_connection_error_creation(self):
        """Test creación de ConnectionError."""
        error = ConnectionError("Unable to connect to SFTP server")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "Unable to connect to SFTP server"

    def test_connection_error_with_server_info(self):
        """Test ConnectionError con información del servidor."""
        context = {
            "host": "sftp.example.com",
            "port": 22,
            "timeout": 30
        }
        error = ConnectionError(
            "Connection timeout",
            error_code="CONN_001",
            context=context
        )

        assert error.context["host"] == "sftp.example.com"
        assert error.context["port"] == 22


class TestAuthenticationError:
    """Tests para AuthenticationError."""

    def test_authentication_error_creation(self):
        """Test creación de AuthenticationError."""
        error = AuthenticationError("Invalid AWS credentials")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "Invalid AWS credentials"

    def test_authentication_error_with_service_info(self):
        """Test AuthenticationError con información del servicio."""
        context = {
            "service": "transfer",
            "region": "us-east-1",
            "action": "StartFileTransfer"
        }
        error = AuthenticationError(
            "Access denied",
            error_code="AUTH_001",
            context=context
        )

        assert error.context["service"] == "transfer"
        assert error.context["action"] == "StartFileTransfer"


class TestTimeoutError:
    """Tests para TimeoutError."""

    def test_timeout_error_creation(self):
        """Test creación de TimeoutError."""
        error = TimeoutError("Operation timed out")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "Operation timed out"

    def test_timeout_error_with_timing_info(self):
        """Test TimeoutError con información de timing."""
        context = {
            "operation": "file_transfer",
            "timeout_seconds": 300,
            "elapsed_seconds": 350
        }
        error = TimeoutError(
            "Transfer timeout exceeded",
            error_code="TIMEOUT_001",
            context=context
        )

        assert error.context["timeout_seconds"] == 300
        assert error.context["elapsed_seconds"] == 350


class TestFileNotFoundError:
    """Tests para FileNotFoundError."""

    def test_file_not_found_error_creation(self):
        """Test creación de FileNotFoundError."""
        error = FileNotFoundError("File does not exist")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "File does not exist"

    def test_file_not_found_error_with_path_info(self):
        """Test FileNotFoundError con información de ruta."""
        context = {
            "file_path": "/remote/path/missing_file.txt",
            "operation": "download",
            "checked_at": "2023-01-01T12:00:00Z"
        }
        error = FileNotFoundError(
            "Source file not found",
            error_code="FILE_001",
            context=context
        )

        assert error.context["file_path"] == "/remote/path/missing_file.txt"
        assert error.context["operation"] == "download"


class TestInsufficientPermissionsError:
    """Tests para InsufficientPermissionsError."""

    def test_insufficient_permissions_error_creation(self):
        """Test creación de InsufficientPermissionsError."""
        error = InsufficientPermissionsError("Permission denied")

        assert isinstance(error, TransferLibraryError)
        assert str(error) == "Permission denied"

    def test_insufficient_permissions_error_with_permission_info(self):
        """Test InsufficientPermissionsError con información de permisos."""
        context = {
            "resource": "/secure/directory/",
            "required_permission": "write",
            "current_user": "transfer_user"
        }
        error = InsufficientPermissionsError(
            "Write permission required",
            error_code="PERM_001",
            context=context
        )

        assert error.context["resource"] == "/secure/directory/"
        assert error.context["required_permission"] == "write"


# Tests de jerarquía de excepciones
class TestExceptionHierarchy:
    """Tests para verificar la jerarquía de excepciones."""

    def test_all_exceptions_inherit_from_base(self):
        """Test que todas las excepciones heredan de TransferLibraryError."""
        exception_classes = [
            ConfigurationError,
            TransferError,
            ValidationError,
            ThrottleError,
            ConnectionError,
            AuthenticationError,
            TimeoutError,
            FileNotFoundError,
            InsufficientPermissionsError
        ]

        for exc_class in exception_classes:
            error = exc_class("Test message")
            assert isinstance(error, TransferLibraryError)
            assert isinstance(error, Exception)

    def test_exception_catching_by_base_class(self):
        """Test que se pueden capturar todas las excepciones por la clase base."""
        exceptions_to_test = [
            ConfigurationError("Config error"),
            TransferError("Transfer error"),
            ValidationError("Validation error"),
            ThrottleError("Throttle error"),
            ConnectionError("Connection error"),
            AuthenticationError("Auth error"),
            TimeoutError("Timeout error"),
            FileNotFoundError("File error"),
            InsufficientPermissionsError("Permission error")
        ]

        for error in exceptions_to_test:
            try:
                raise error
            except TransferLibraryError as e:
                assert isinstance(e, TransferLibraryError)
                assert str(e) == error.message
            except Exception:
                pytest.fail(f"Exception {type(error)} should be caught by TransferLibraryError")

    def test_exception_specific_catching(self):
        """Test captura específica de cada tipo de excepción."""
        # Test ConfigurationError específico
        try:
            raise ConfigurationError("Config issue")
        except ConfigurationError as e:
            assert e.message == "Config issue"

        # Test TransferError específico
        try:
            raise TransferError("Transfer issue")
        except TransferError as e:
            assert e.message == "Transfer issue"

        # Test ValidationError específico
        try:
            raise ValidationError("Validation issue")
        except ValidationError as e:
            assert e.message == "Validation issue"


# Tests de casos de uso comunes
class TestCommonUseCases:
    """Tests para casos de uso comunes de excepciones."""

    def test_chained_exception_context(self):
        """Test contexto enriquecido en excepciones encadenadas."""
        # Simular una excepción de bajo nivel
        original_context = {"file": "test.txt", "size": 1024}
        low_level_error = ConnectionError(
            "Network unreachable",
            error_code="CONN_001",
            context=original_context
        )

        # Crear excepción de alto nivel con contexto adicional
        high_level_context = {
            "operation": "batch_upload",
            "batch_id": "batch-123",
            "retry_attempt": 2
        }
        high_level_error = TransferError(
            "Batch upload failed",
            error_code="TRANSFER_002",
            context=high_level_context
        )

        # Verificar que ambos contextos están disponibles
        assert low_level_error.context["file"] == "test.txt"
        assert high_level_error.context["operation"] == "batch_upload"

    def test_error_code_patterns(self):
        """Test patrones comunes de códigos de error."""
        errors_with_codes = [
            ConfigurationError("Test", error_code="CONFIG_001"),
            TransferError("Test", error_code="TRANSFER_001"),
            ValidationError("Test", error_code="VALIDATION_001"),
            ThrottleError("Test", error_code="THROTTLE_001"),
            ConnectionError("Test", error_code="CONN_001"),
            AuthenticationError("Test", error_code="AUTH_001"),
            TimeoutError("Test", error_code="TIMEOUT_001"),
            FileNotFoundError("Test", error_code="FILE_001"),
            InsufficientPermissionsError("Test", error_code="PERM_001")
        ]

        for error in errors_with_codes:
            # Verificar formato del string con código
            assert str(error).startswith("[")
            assert "] Test" in str(error)
            assert error.error_code is not None
            assert "_" in error.error_code  # Patrón CATEGORY_NUMBER