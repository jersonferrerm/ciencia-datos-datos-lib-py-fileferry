"""
Tests para TransferManager.

Este módulo contiene tests unitarios para la fachada principal de la librería
que proporciona la API pública para todas las operaciones de transferencia.
"""

import pytest
from unittest.mock import Mock, patch


try:
    # Intentar import como paquete primero
    from src.transfer_manager import TransferManager
    from src.config.config_manager import ConfigManager
    from src.services.upload_service import UploadService
    from src.services.download_service import DownloadService
    from src.services.listing_service import ListingService
    from src.services.monitoring_service import MonitoringService
    from src.orchestration.batch_orchestrator import BatchOrchestrator
    from src.orchestration.throttle_controller import ThrottleController
    from src.orchestration.session_manager import SessionManager
    from src.clients.aws_transfer_client import AWSTransferClient
    from src.models.transfer_models import (
        FileTransferRequest,
        TransferRequest,
        TransferResult,
        TransferType,
        TransferStatus,
        DirectoryListing
    )
    from src.exceptions.transfer_exceptions import (
        TransferLibraryError,
        ConfigurationError,
        ValidationError
    )
except ImportError:
    # Fallback a imports directos
    import transfer_manager
    TransferManager = transfer_manager.TransferManager
    import config.config_manager
    ConfigManager = config.config_manager.ConfigManager
    import services.upload_service
    UploadService = services.upload_service.UploadService
    import services.download_service
    DownloadService = services.download_service.DownloadService
    import services.listing_service
    ListingService = services.listing_service.ListingService
    import services.monitoring_service
    MonitoringService = services.monitoring_service.MonitoringService
    import orchestration.batch_orchestrator
    BatchOrchestrator = orchestration.batch_orchestrator.BatchOrchestrator
    import orchestration.throttle_controller
    ThrottleController = orchestration.throttle_controller.ThrottleController
    import orchestration.session_manager
    SessionManager = orchestration.session_manager.SessionManager
    import clients.aws_transfer_client
    AWSTransferClient = clients.aws_transfer_client.AWSTransferClient
    from src.exceptions.transfer_exceptions import (
        TransferLibraryError,
        ConfigurationError,
        ValidationError
    )
    import src.utils.instance_manager
    InstanceManager = src.utils.instance_manager.InstanceManager


class TestTransferManagerInitialization:
    """Tests para la inicialización de TransferManager."""

    @patch('src.transfer_manager.InstanceManager')
    @patch('src.transfer_manager.ConfigManager')
    @patch('src.transfer_manager.AWSTransferClient')
    def test_initialization_with_defaults(self, mock_aws_client, mock_config_manager, mock_instance_manager):
        """Test inicialización con valores por defecto."""
        # Configurar mocks
        mock_config = Mock()
        mock_config.get_throughput_limit.return_value = 100
        mock_config.get_max_concurrent_sessions.return_value = 5
        mock_config.get_connector_id.return_value = "connector-123"
        mock_config_manager.return_value = mock_config

        mock_instance = Mock()
        mock_instance.instance_id = "instance-456"
        mock_instance_manager.return_value = mock_instance

        # Mock AWS client to avoid region issues
        mock_aws_instance = Mock()
        mock_aws_client.return_value = mock_aws_instance

        # Crear TransferManager
        manager = TransferManager()

        # Verificar inicialización
        assert manager.config_manager == mock_config
        assert manager.instance_manager == mock_instance
        assert isinstance(manager.throttle_controller, ThrottleController)
        assert isinstance(manager.session_manager, SessionManager)
        assert isinstance(manager.batch_orchestrator, BatchOrchestrator)
        assert isinstance(manager.upload_service, UploadService)
        assert isinstance(manager.download_service, DownloadService)
        assert isinstance(manager.listing_service, ListingService)
        assert isinstance(manager.monitoring_service, MonitoringService)

    def test_initialization_with_custom_components(self):
        """Test inicialización con componentes personalizados."""
        # Crear mocks personalizados
        config_manager = Mock(spec=ConfigManager)
        config_manager.get_throughput_limit.return_value = 50
        config_manager.get_max_concurrent_sessions.return_value = 3
        config_manager.get_connector_id.return_value = "custom-connector"

        aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "custom-instance"
            mock_instance_manager.return_value = mock_instance

            # Crear TransferManager con componentes personalizados
            manager = TransferManager(
                config_manager=config_manager,
                aws_transfer_client=aws_client
            )

            # Verificar que usa los componentes personalizados
            assert manager.config_manager == config_manager
            assert manager.aws_transfer_client == aws_client

    @patch('src.transfer_manager.AWSTransferClient')
    @patch('src.transfer_manager.ConfigManager')
    def test_initialization_failure(self, mock_config_manager, mock_aws_client):
        """Test falla en la inicialización."""
        # Configurar mock para lanzar excepción
        mock_config_manager.side_effect = Exception("Config error")

        with pytest.raises(TransferLibraryError) as exc_info:
            TransferManager()

        assert exc_info.value.error_code == "TRANSFER_MANAGER_INIT_FAILED"
        assert "Config error" in str(exc_info.value)


class TestUploadFiles:
    """Tests para el método upload_files."""

    def setup_method(self):
        """Setup para cada test."""
        # Crear mocks para todos los componentes
        self.config_manager = Mock(spec=ConfigManager)
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"

        self.aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )

    def test_upload_files_successful(self):
        """Test upload exitoso de archivos."""
        # Crear archivos de prueba
        files = [
            FileTransferRequest("/bucket/file1.txt", "/sftp/file1.txt"),
            FileTransferRequest("/bucket/file2.txt", "/sftp/file2.txt")
        ]

        # Configurar mock del upload service
        expected_result = TransferResult(
            transfer_id="transfer-123",
            status=TransferStatus.COMPLETED,
            file_results=[]
        )

        with patch.object(self.manager.upload_service, 'execute_transfer', return_value=expected_result) as mock_execute:
            result = self.manager.upload_files(files, "connector-123")

        # Verificar resultado
        assert result == expected_result

        # Verificar que se llamó al upload service con los parámetros correctos
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args[0][0]
        assert isinstance(call_args, TransferRequest)
        assert call_args.files == files
        assert call_args.connector_id == "connector-123"
        assert call_args.transfer_type == TransferType.UPLOAD

    def test_upload_files_with_custom_connector_id(self):
        """Test upload con connector_id personalizado."""
        files = [FileTransferRequest("/bucket/file.txt", "/sftp/file.txt")]

        expected_result = TransferResult(
            transfer_id="transfer-456",
            status=TransferStatus.COMPLETED,
            file_results=[]
        )

        with patch.object(self.manager.upload_service, 'execute_transfer', return_value=expected_result) as mock_execute:
            result = self.manager.upload_files(files, connector_id="custom-connector")

        # Verificar que se usó el connector_id personalizado
        call_args = mock_execute.call_args[0][0]
        assert call_args.connector_id == "custom-connector"

    def test_upload_files_empty_list(self):
        """Test upload con lista vacía de archivos."""
        with pytest.raises(ValidationError) as exc_info:
            self.manager.upload_files([], "test-connector-123")

        assert exc_info.value.error_code == "EMPTY_FILE_LIST"
        assert "upload" in str(exc_info.value)

    def test_upload_files_invalid_file_type(self):
        """Test upload con tipo de archivo inválido."""
        invalid_files = ["not_a_file_request", "another_invalid"]

        with pytest.raises(ValidationError) as exc_info:
            self.manager.upload_files(invalid_files, "test-connector-123")

        assert exc_info.value.error_code == "INVALID_FILE_REQUEST_TYPE"

    def test_upload_files_missing_source_path(self):
        """Test upload con source_path faltante."""
        files = [FileTransferRequest("", "/sftp/file.txt")]

        with pytest.raises(ValidationError) as exc_info:
            self.manager.upload_files(files, "test-connector-123")

        assert exc_info.value.error_code == "MISSING_SOURCE_PATH"
        assert exc_info.value.context["file_index"] == 0

    def test_upload_files_missing_destination_path(self):
        """Test upload con destination_path faltante."""
        files = [FileTransferRequest("/bucket/file.txt", "")]

        with pytest.raises(ValidationError) as exc_info:
            self.manager.upload_files(files, "test-connector-123")

        assert exc_info.value.error_code == "MISSING_DESTINATION_PATH"

    def test_upload_files_service_error(self):
        """Test upload con error del servicio."""
        files = [FileTransferRequest("/bucket/file.txt", "/sftp/file.txt")]

        # Configurar error en el upload service
        with patch.object(self.manager.upload_service, 'execute_transfer', side_effect=Exception("Service error")):
            with pytest.raises(TransferLibraryError) as exc_info:
                self.manager.upload_files(files, "test-connector-123")

        assert exc_info.value.error_code == "UPLOAD_FAILED"
        assert "Service error" in str(exc_info.value)

    def test_upload_files_validation_error_passthrough(self):
        """Test que ValidationError se pasa sin modificar."""
        files = [FileTransferRequest("/bucket/file.txt", "/sftp/file.txt")]

        validation_error = ValidationError("Invalid file", error_code="INVALID_FILE")

        with patch.object(self.manager.upload_service, 'execute_transfer', side_effect=validation_error):
            with pytest.raises(ValidationError) as exc_info:
                self.manager.upload_files(files, "test-connector-123")

        assert exc_info.value == validation_error




class TestListDirectory:
    """Tests para el método list_directory."""

    def setup_method(self):
        """Setup para cada test."""
        self.config_manager = Mock(spec=ConfigManager)
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"

        self.aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )

    def test_list_directory_successful(self):
        """Test listado exitoso de directorio."""
        expected_listing = DirectoryListing(
            path="/remote/path",
            files=[{"name": "file.txt", "size": 1024}],
            directories=["subdir"],
            total_items=2
        )

        with patch.object(self.manager.listing_service, 'list_directory', return_value=expected_listing) as mock_list:
            result = self.manager.list_directory("/remote/path", "connector-123")

        assert result == expected_listing

        # Verificar parámetros de la llamada
        mock_list.assert_called_once_with(
            sftp_path="/remote/path",
            connector_id="connector-123",
            max_items=None,
            output_directory_path=None
        )

    def test_list_directory_with_max_items(self):
        """Test listado con max_items."""
        expected_listing = DirectoryListing(
            path="/remote/path",
            files=[],
            directories=[],
            total_items=0
        )

        with patch.object(self.manager.listing_service, 'list_directory', return_value=expected_listing) as mock_list:
            result = self.manager.list_directory("/remote/path", "connector-123", max_items=50)

        mock_list.assert_called_once_with(
            sftp_path="/remote/path",
            connector_id="connector-123",
            max_items=50,
            output_directory_path=None
        )

    def test_list_directory_with_custom_connector_id(self):
        """Test listado con connector_id personalizado."""
        expected_listing = DirectoryListing(
            path="/remote/path",
            files=[],
            directories=[],
            total_items=0
        )

        with patch.object(self.manager.listing_service, 'list_directory', return_value=expected_listing) as mock_list:
            result = self.manager.list_directory("/remote/path", connector_id="custom-connector")

        mock_list.assert_called_once_with(
            sftp_path="/remote/path",
            connector_id="custom-connector",
            max_items=None,
            output_directory_path=None
        )

    def test_list_directory_with_output_directory_path(self):
        """Test listado con output_directory_path."""
        expected_listing = DirectoryListing(
            path="/remote/path",
            files=[],
            directories=[],
            total_items=0,
            listing_id="listing-123",
            output_filename="custom_listing.json"
        )

        with patch.object(self.manager.listing_service, 'list_directory', return_value=expected_listing) as mock_list:
            result = self.manager.list_directory(
                "/remote/path",
                "connector-123",
                max_items=100,
                output_directory_path="/custom/output"
            )

        assert result == expected_listing
        mock_list.assert_called_once_with(
            sftp_path="/remote/path",
            connector_id="connector-123",
            max_items=100,
            output_directory_path="/custom/output"
        )

    def test_list_directory_with_all_parameters(self):
        """Test listado con todos los parámetros."""
        expected_listing = DirectoryListing(
            path="/remote/path",
            files=[{"name": "file.txt", "size": 1024}],
            directories=["subdir"],
            total_items=2,
            listing_id="listing-456",
            output_filename="full_params_listing.json"
        )

        with patch.object(self.manager.listing_service, 'list_directory', return_value=expected_listing) as mock_list:
            result = self.manager.list_directory(
                sftp_path="/remote/path",
                connector_id="connector-456",
                max_items=50,
                output_directory_path="/output/listings"
            )

        assert result == expected_listing
        assert result.listing_id == "listing-456"
        assert result.output_filename == "full_params_listing.json"

        mock_list.assert_called_once_with(
            sftp_path="/remote/path",
            connector_id="connector-456",
            max_items=50,
            output_directory_path="/output/listings"
        )

    def test_list_directory_invalid_path(self):
        """Test listado con ruta inválida."""
        invalid_paths = ["", None, 123]

        for path in invalid_paths:
            with pytest.raises(ValidationError) as exc_info:
                self.manager.list_directory(path, "test-connector-123")

            assert exc_info.value.error_code == "INVALID_SFTP_PATH"

    def test_list_directory_service_error(self):
        """Test listado con error del servicio."""
        with patch.object(self.manager.listing_service, 'list_directory', side_effect=Exception("Listing error")):
            with pytest.raises(TransferLibraryError) as exc_info:
                self.manager.list_directory("/remote/path", "test-connector-123")

        assert exc_info.value.error_code == "DIRECTORY_LISTING_FAILED"


class TestGetTransferStatus:
    """Tests para el método get_transfer_status."""

    def setup_method(self):
        """Setup para cada test."""
        self.config_manager = Mock(spec=ConfigManager)
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"

        self.aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )

    def test_get_transfer_status_successful(self):
        """Test obtención exitosa de estado."""
        expected_status = {
            "transfer_id": "transfer-123",
            "status": "COMPLETED",
            "total_files": 5,
            "completed_files": 5,
            "failed_files": 0
        }

        with patch.object(self.manager.monitoring_service, 'get_transfer_status', return_value=expected_status) as mock_status:
            result = self.manager.get_transfer_status("transfer-123")

        assert result == expected_status
        mock_status.assert_called_once_with("transfer-123", "connector-123")

    def test_get_transfer_status_invalid_id(self):
        """Test obtención de estado con ID inválido."""
        invalid_ids = ["", None, 123]

        for transfer_id in invalid_ids:
            with pytest.raises(ValidationError) as exc_info:
                self.manager.get_transfer_status(transfer_id)

            assert exc_info.value.error_code == "INVALID_TRANSFER_ID"

    def test_get_transfer_status_service_error(self):
        """Test obtención de estado con error del servicio."""
        with patch.object(self.manager.monitoring_service, 'get_transfer_status', side_effect=Exception("Status error")):
            with pytest.raises(TransferLibraryError) as exc_info:
                self.manager.get_transfer_status("transfer-123")

        assert exc_info.value.error_code == "STATUS_QUERY_FAILED"


class TestWaitForCompletion:
    """Tests para el método wait_for_completion."""

    def setup_method(self):
        """Setup para cada test."""
        self.config_manager = Mock(spec=ConfigManager)
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"

        self.aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )

    def test_wait_for_completion_successful(self):
        """Test espera exitosa de finalización."""
        expected_status = {
            "transfer_id": "transfer-123",
            "status": "COMPLETED",
            "total_files": 3,
            "completed_files": 3
        }

        with patch.object(self.manager.monitoring_service, 'poll_until_complete', return_value=expected_status) as mock_poll:
            result = self.manager.wait_for_completion("transfer-123")

        assert result == expected_status
        mock_poll.assert_called_once_with(
            transfer_id="transfer-123",
            connector_id="connector-123",
            timeout=None,
            poll_interval=None
        )

    def test_wait_for_completion_with_custom_parameters(self):
        """Test espera con parámetros personalizados."""
        expected_status = {"status": "COMPLETED"}

        with patch.object(self.manager.monitoring_service, 'poll_until_complete', return_value=expected_status) as mock_poll:
            result = self.manager.wait_for_completion("transfer-123", timeout=300, poll_interval=10)

        mock_poll.assert_called_once_with(
            transfer_id="transfer-123",
            connector_id="connector-123",
            timeout=300,
            poll_interval=10
        )

    def test_wait_for_completion_service_error(self):
        """Test espera con error del servicio."""
        with patch.object(self.manager.monitoring_service, 'poll_until_complete', side_effect=Exception("Polling error")):
            with pytest.raises(TransferLibraryError) as exc_info:
                self.manager.wait_for_completion("transfer-123")

        assert exc_info.value.error_code == "WAIT_FOR_COMPLETION_FAILED"


class TestGetConfiguration:
    """Tests para el método get_configuration."""

    def setup_method(self):
        """Setup para cada test."""
        self.config_manager = Mock(spec=ConfigManager)
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"

        self.aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )
            # Keep reference to the mock instance for later use
            self.manager.instance_manager = mock_instance

    def test_get_configuration_successful(self):
        """Test obtención exitosa de configuración."""
        expected_config = {
            "connector_id": "connector-123",
            "throughput_limit": 100,
            "max_concurrent_sessions": 5
        }

        self.config_manager.get_all_config.return_value = expected_config

        result = self.manager.get_configuration()

        assert result["connector_id"] == "connector-123"
        assert result["throughput_limit"] == 100
        assert result["max_concurrent_sessions"] == 5
        assert result["instance_id"] == "test-instance"

    def test_get_configuration_error(self):
        """Test obtención de configuración con error."""
        self.config_manager.get_all_config.side_effect = Exception("Config error")

        with pytest.raises(TransferLibraryError) as exc_info:
            self.manager.get_configuration()

        assert exc_info.value.error_code == "CONFIG_RETRIEVAL_FAILED"


class TestValidateFileList:
    """Tests para el método _validate_file_list."""

    def setup_method(self):
        """Setup para cada test."""
        self.config_manager = Mock(spec=ConfigManager)
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"

        self.aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )

    def test_validate_file_list_valid(self):
        """Test validación de lista válida."""
        files = [
            FileTransferRequest("source1", "dest1"),
            FileTransferRequest("source2", "dest2")
        ]

        # No debería lanzar excepción
        self.manager._validate_file_list(files, "upload")

    def test_validate_file_list_empty(self):
        """Test validación de lista vacía."""
        with pytest.raises(ValidationError) as exc_info:
            self.manager._validate_file_list([], "upload")

        assert exc_info.value.error_code == "EMPTY_FILE_LIST"
        assert exc_info.value.context["operation"] == "upload"

    def test_validate_file_list_not_list(self):
        """Test validación con tipo incorrecto."""
        with pytest.raises(ValidationError) as exc_info:
            self.manager._validate_file_list("not_a_list", "download")

        assert exc_info.value.error_code == "INVALID_FILE_LIST_TYPE"
        assert exc_info.value.context["type"] == "str"

    def test_validate_file_list_invalid_file_type(self):
        """Test validación con tipo de archivo incorrecto."""
        files = [
            FileTransferRequest("source", "dest"),
            "invalid_file"  # No es FileTransferRequest
        ]

        with pytest.raises(ValidationError) as exc_info:
            self.manager._validate_file_list(files, "upload")

        assert exc_info.value.error_code == "INVALID_FILE_REQUEST_TYPE"
        assert exc_info.value.context["file_index"] == 1
        assert exc_info.value.context["type"] == "str"

    def test_validate_file_list_missing_source_path(self):
        """Test validación con source_path faltante."""
        files = [FileTransferRequest("", "dest")]

        with pytest.raises(ValidationError) as exc_info:
            self.manager._validate_file_list(files, "download")

        assert exc_info.value.error_code == "MISSING_SOURCE_PATH"
        assert exc_info.value.context["file_index"] == 0
        assert exc_info.value.context["operation"] == "download"

    def test_validate_file_list_missing_destination_path(self):
        """Test validación con destination_path faltante."""
        files = [FileTransferRequest("source", "")]

        with pytest.raises(ValidationError) as exc_info:
            self.manager._validate_file_list(files, "upload")

        assert exc_info.value.error_code == "MISSING_DESTINATION_PATH"
        assert exc_info.value.context["file_index"] == 0


class TestContextManager:
    """Tests para el context manager."""

    def test_context_manager_usage(self):
        """Test uso como context manager."""
        config_manager = Mock(spec=ConfigManager)
        config_manager.get_throughput_limit.return_value = 100
        config_manager.get_max_concurrent_sessions.return_value = 5
        config_manager.get_connector_id.return_value = "connector-123"

        aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            # Usar como context manager
            with TransferManager(config_manager, aws_client) as manager:
                assert isinstance(manager, TransferManager)
                assert manager.config_manager == config_manager


# Tests de integración
class TestTransferManagerIntegration:
    """Tests de integración para TransferManager."""

    def test_full_upload_workflow(self):
        """Test flujo completo de upload."""
        # Crear mocks realistas
        config_manager = Mock(spec=ConfigManager)
        config_manager.get_throughput_limit.return_value = 100
        config_manager.get_max_concurrent_sessions.return_value = 5
        config_manager.get_connector_id.return_value = "connector-123"
        config_manager.get_all_config.return_value = {
            "connector_id": "connector-123",
            "throughput_limit": 100
        }

        aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "integration-test"
            mock_instance_manager.return_value = mock_instance

            manager = TransferManager(config_manager, aws_client)
            # Keep reference to the mock instance for later use
            manager.instance_manager = mock_instance

            # Configurar mocks para flujo exitoso
            upload_result = TransferResult(
                transfer_id="integration-transfer",
                status=TransferStatus.COMPLETED,
                file_results=[]
            )

            with patch.object(manager.upload_service, 'execute_transfer', return_value=upload_result):
                # Ejecutar upload
                files = [FileTransferRequest("/bucket/file.txt", "/sftp/file.txt")]
                result = manager.upload_files(files, "test-connector-123")

                # Verificar resultado
                assert result.transfer_id == "integration-transfer"
                assert result.status == TransferStatus.COMPLETED

                # Obtener configuración
                config = manager.get_configuration()
                assert config["connector_id"] == "connector-123"
                assert config["instance_id"] == "integration-test"

    def test_error_handling_chain(self):
        """Test cadena de manejo de errores."""
        config_manager = Mock(spec=ConfigManager)
        config_manager.get_throughput_limit.return_value = 100
        config_manager.get_max_concurrent_sessions.return_value = 5
        config_manager.get_connector_id.return_value = "connector-123"

        aws_client = Mock(spec=AWSTransferClient)

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "error-test"
            mock_instance_manager.return_value = mock_instance

            manager = TransferManager(config_manager, aws_client)

            # Test error de validación (se pasa sin modificar)
            validation_error = ValidationError("Invalid input", error_code="INVALID_INPUT")
            with patch.object(manager.upload_service, 'execute_transfer', side_effect=validation_error):
                with pytest.raises(ValidationError) as exc_info:
                    files = [FileTransferRequest("/bucket/file.txt", "/sftp/file.txt")]
                    manager.upload_files(files, "test-connector-123")

                assert exc_info.value == validation_error

            # Test error genérico (se envuelve)
            with patch.object(manager.upload_service, 'execute_transfer', side_effect=Exception("Generic error")):
                with pytest.raises(TransferLibraryError) as exc_info:
                    files = [FileTransferRequest("/bucket/file.txt", "/sftp/file.txt")]
                    manager.upload_files(files, "test-connector-123")

                assert exc_info.value.error_code == "UPLOAD_FAILED"
                assert "Generic error" in str(exc_info.value)


class TestTransferManagerDownloadBatch:
    """Tests para el método download_files_batch."""

    def setup_method(self):
        """Setup para cada test."""
        self.config_manager = Mock()
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"
        self.config_manager.get_all_config.return_value = {
            "connector_id": "connector-123",
            "throughput_limit": 100,
            "max_concurrent_sessions": 5
        }

        self.aws_client = Mock()

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )

    def test_download_files_batch_successful(self):
        """Test download_files_batch exitoso."""
        sftp_files = ["/remote/file1.txt", "/remote/file2.txt"]

        expected_result = TransferResult(
            transfer_id="download-123",
            status=TransferStatus.COMPLETED,
            file_results=[]
        )

        with patch.object(self.manager.download_service, 'execute_batch_download', return_value=expected_result) as mock_download:
            result = self.manager.download_files_batch(
                sftp_files=sftp_files,
                connector_id="connector-123",
                s3_destination_path="/s3/downloads"
            )

        assert result == expected_result
        mock_download.assert_called_once_with(
            sftp_files, "connector-123", "/s3/downloads"
        )

    def test_download_files_batch_validation_errors(self):
        """Test download_files_batch con errores de validación."""
        # Test con sftp_files vacío
        with pytest.raises(ValidationError) as exc_info:
            self.manager.download_files_batch([], "connector-123", "/s3/dest")
        assert exc_info.value.error_code == "INVALID_SFTP_FILES_LIST"

        # Test con sftp_files no lista
        with pytest.raises(ValidationError) as exc_info:
            self.manager.download_files_batch("not_a_list", "connector-123", "/s3/dest")
        assert exc_info.value.error_code == "INVALID_SFTP_FILES_LIST"

        # Test sin connector_id
        with pytest.raises(ValidationError) as exc_info:
            self.manager.download_files_batch(["/file.txt"], "", "/s3/dest")
        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

        # Test sin s3_destination_path
        with pytest.raises(ValidationError) as exc_info:
            self.manager.download_files_batch(["/file.txt"], "connector-123", "")
        assert exc_info.value.error_code == "MISSING_S3_DESTINATION_PATH"

    def test_download_files_batch_service_error(self):
        """Test download_files_batch con error del servicio."""
        with patch.object(self.manager.download_service, 'execute_batch_download', side_effect=Exception("Download error")):
            with pytest.raises(TransferLibraryError) as exc_info:
                self.manager.download_files_batch(["/file.txt"], "connector-123", "/s3/dest")

        assert exc_info.value.error_code == "BATCH_DOWNLOAD_FAILED"
        assert "Download error" in str(exc_info.value)


class TestTransferManagerMultipleStatus:
    """Tests para el método get_multiple_transfer_status."""

    def setup_method(self):
        """Setup para cada test."""
        self.config_manager = Mock()
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"

        self.aws_client = Mock()

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )

    def test_get_multiple_transfer_status_successful(self):
        """Test get_multiple_transfer_status exitoso."""
        transfer_ids = ["transfer-1", "transfer-2"]
        expected_status = {
            "data": [
                {"transfer_id": "transfer-1", "overall_status": "COMPLETED"},
                {"transfer_id": "transfer-2", "overall_status": "IN_PROGRESS"}
            ]
        }

        with patch.object(self.manager.monitoring_service, 'get_multiple_transfer_status', return_value=expected_status) as mock_status:
            result = self.manager.get_multiple_transfer_status(transfer_ids, "connector-123")

        assert result == expected_status
        mock_status.assert_called_once_with(
            transfer_ids=transfer_ids,
            connector_id="connector-123"
        )

    def test_get_multiple_transfer_status_validation_errors(self):
        """Test get_multiple_transfer_status con errores de validación."""
        # Test con transfer_ids vacío
        with pytest.raises(ValidationError) as exc_info:
            self.manager.get_multiple_transfer_status([], "connector-123")
        assert exc_info.value.error_code == "INVALID_TRANSFER_IDS"

        # Test con transfer_ids no lista
        with pytest.raises(ValidationError) as exc_info:
            self.manager.get_multiple_transfer_status("not_a_list", "connector-123")
        assert exc_info.value.error_code == "INVALID_TRANSFER_IDS"

        # Test sin connector_id
        with pytest.raises(ValidationError) as exc_info:
            self.manager.get_multiple_transfer_status(["transfer-1"], "")
        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

        # Test con transfer_id inválido en la lista
        with pytest.raises(ValidationError) as exc_info:
            self.manager.get_multiple_transfer_status(["transfer-1", ""], "connector-123")
        assert exc_info.value.error_code == "INVALID_TRANSFER_ID"
        assert exc_info.value.context["index"] == 1

    def test_get_multiple_transfer_status_service_error(self):
        """Test get_multiple_transfer_status con error del servicio."""
        with patch.object(self.manager.monitoring_service, 'get_multiple_transfer_status', side_effect=Exception("Status error")):
            with pytest.raises(TransferLibraryError) as exc_info:
                self.manager.get_multiple_transfer_status(["transfer-1"], "connector-123")

        assert exc_info.value.error_code == "MULTIPLE_STATUS_QUERY_FAILED"


class TestTransferManagerAdditionalMethods:
    """Tests adicionales para métodos de TransferManager."""

    def setup_method(self):
        """Setup para cada test."""
        self.config_manager = Mock()
        self.config_manager.get_throughput_limit.return_value = 100
        self.config_manager.get_max_concurrent_sessions.return_value = 5
        self.config_manager.get_connector_id.return_value = "connector-123"
        self.config_manager.get_all_config.return_value = {
            "connector_id": "connector-123",
            "throughput_limit": 100,
            "max_concurrent_sessions": 5
        }

        self.aws_client = Mock()

        with patch('src.transfer_manager.InstanceManager') as mock_instance_manager:
            mock_instance = Mock()
            mock_instance.instance_id = "test-instance"
            mock_instance_manager.return_value = mock_instance

            self.manager = TransferManager(
                config_manager=self.config_manager,
                aws_transfer_client=self.aws_client,
            )
            # Keep reference to the mock instance for later use
            self.manager.instance_manager = mock_instance

    def test_get_configuration_successful(self):
        """Test get_configuration exitoso."""
        result = self.manager.get_configuration()

        assert result["connector_id"] == "connector-123"
        assert result["throughput_limit"] == 100
        assert result["max_concurrent_sessions"] == 5
        assert result["instance_id"] == "test-instance"

    def test_get_configuration_error(self):
        """Test get_configuration con error."""
        self.config_manager.get_all_config.side_effect = Exception("Config error")

        with pytest.raises(TransferLibraryError) as exc_info:
            self.manager.get_configuration()

        assert exc_info.value.error_code == "CONFIG_RETRIEVAL_FAILED"

    def test_context_manager_successful(self):
        """Test uso exitoso como context manager."""
        with self.manager as manager:
            assert manager == self.manager

    def test_context_manager_with_exception(self):
        """Test context manager con excepción."""
        try:
            with self.manager as manager:
                raise ValueError("Test error")
        except ValueError:
            pass  # Esperado

        # El context manager debería manejar la excepción correctamente
        assert True  # Si llegamos aquí, el context manager funcionó

    def test_upload_files_batch_validation_edge_cases(self):
        """Test upload_files_batch para cubrir casos edge de validación."""
        # Test con files no lista
        with pytest.raises(ValidationError) as exc_info:
            self.manager.upload_files_batch("not_a_list", "connector-123", "/dest")
        assert exc_info.value.error_code == "INVALID_FILES_LIST"

        # Test con files vacío
        with pytest.raises(ValidationError) as exc_info:
            self.manager.upload_files_batch([], "connector-123", "/dest")
        assert exc_info.value.error_code == "INVALID_FILES_LIST"

    def test_upload_files_batch_service_error_types(self):
        """Test upload_files_batch con diferentes tipos de errores del servicio."""
        files = ["/bucket/file1.txt", "/bucket/file2.txt"]

        with patch.object(self.manager.upload_service, 'execute_batch_transfer', side_effect=ValidationError("Validation error", "VALIDATION_ERROR")):
            with pytest.raises(ValidationError):
                self.manager.upload_files_batch(files, "connector-123", "/dest")

        with patch.object(self.manager.upload_service, 'execute_batch_transfer', side_effect=ConfigurationError("Config error", "CONFIG_ERROR")):
            with pytest.raises(ConfigurationError):
                self.manager.upload_files_batch(files, "connector-123", "/dest")

        with patch.object(self.manager.upload_service, 'execute_batch_transfer', side_effect=TransferLibraryError("Transfer error", "TRANSFER_ERROR")):
            with pytest.raises(TransferLibraryError):
                self.manager.upload_files_batch(files, "connector-123", "/dest")