"""
Tests para BatchOrchestrator.

Este módulo contiene tests unitarios para el orquestador de lotes
que coordina throttling, sesiones y llamadas a AWS Transfer Family.
"""

from unittest.mock import Mock, MagicMock, patch
import pytest

from src.orchestration.batch_orchestrator import BatchOrchestrator, Batch, BatchResult
from src.orchestration.throttle_controller import ThrottleController
from src.orchestration.session_manager import SessionManager, Session
from src.services.interfaces import IAWSClient
from src.models.transfer_models import (
    FileTransferRequest,
    TransferType,
    TransferStatus,
    FileStatus,
    FileTransferResult
)
from src.exceptions.transfer_exceptions import ValidationError


class TestBatch:
    """Tests para la clase Batch."""

    def test_batch_creation_basic(self):
        """Test creación básica de Batch."""
        files = [
            FileTransferRequest("/source/file1.txt", "/dest/file1.txt"),
            FileTransferRequest("/source/file2.txt", "/dest/file2.txt")
        ]

        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        assert batch.batch_id == "batch-123"
        assert batch.files == files
        assert batch.transfer_type == TransferType.UPLOAD
        assert batch.connector_id == "connector-456"
        assert batch.created_at == 1000.0

    def test_batch_post_init_generates_id(self):
        """Test que __post_init__ genera ID si está vacío."""
        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]

        batch = Batch(
            batch_id="",
            files=files,
            transfer_type=TransferType.DOWNLOAD,
            connector_id="connector-123",
            created_at=1000.0
        )

        # Debería haber generado un UUID
        assert batch.batch_id != ""
        assert len(batch.batch_id) > 10


class TestBatchResult:
    """Tests para la clase BatchResult."""

    def test_batch_result_creation_success(self):
        """Test creación de BatchResult exitoso."""
        file_results = [
            FileTransferResult("/file1.txt", FileStatus.COMPLETED, "exec-123"),
            FileTransferResult("/file2.txt", FileStatus.COMPLETED, "exec-123")
        ]

        result = BatchResult(
            batch_id="batch-123",
            transfer_id="exec-123",
            status=TransferStatus.COMPLETED,
            file_results=file_results,
            session_id="session-456"
        )

        assert result.batch_id == "batch-123"
        assert result.transfer_id == "exec-123"
        assert result.status == TransferStatus.COMPLETED
        assert result.file_results == file_results
        assert result.session_id == "session-456"
        # completed_at field no longer exists
        assert result.error_message is None

    def test_batch_result_creation_failure(self):
        """Test creación de BatchResult fallido."""
        result = BatchResult(
            batch_id="batch-123",
            transfer_id=None,
            status=TransferStatus.FAILED,
            file_results=[],
            error_message="Connection failed"
        )

        assert result.status == TransferStatus.FAILED
        assert result.transfer_id is None
        assert result.error_message == "Connection failed"


class TestBatchOrchestratorInitialization:
    """Tests para la inicialización de BatchOrchestrator."""

    def test_initialization_valid_parameters(self):
        """Test inicialización con parámetros válidos."""
        aws_client = Mock(spec=IAWSClient)
        throttle_controller = Mock(spec=ThrottleController)
        session_manager = Mock(spec=SessionManager)

        orchestrator = BatchOrchestrator(
            aws_client=aws_client,
            throttle_controller=throttle_controller,
            session_manager=session_manager,
            max_concurrent_batches=5
        )

        assert orchestrator.aws_client == aws_client
        assert orchestrator.throttle_controller == throttle_controller
        assert orchestrator.session_manager == session_manager
        assert orchestrator.max_concurrent_batches == 5

    def test_initialization_default_max_concurrent(self):
        """Test inicialización con max_concurrent_batches por defecto."""
        aws_client = Mock(spec=IAWSClient)
        throttle_controller = Mock(spec=ThrottleController)
        session_manager = Mock(spec=SessionManager)

        orchestrator = BatchOrchestrator(
            aws_client=aws_client,
            throttle_controller=throttle_controller,
            session_manager=session_manager
        )

        assert orchestrator.max_concurrent_batches == 3

    def test_initialization_missing_aws_client(self):
        """Test inicialización sin aws_client."""
        throttle_controller = Mock(spec=ThrottleController)
        session_manager = Mock(spec=SessionManager)

        with pytest.raises(ValidationError) as exc_info:
            BatchOrchestrator(
                aws_client=None,
                throttle_controller=throttle_controller,
                session_manager=session_manager
            )

        assert exc_info.value.error_code == "MISSING_AWS_CLIENT"

    def test_initialization_missing_throttle_controller(self):
        """Test inicialización sin throttle_controller."""
        aws_client = Mock(spec=IAWSClient)
        session_manager = Mock(spec=SessionManager)

        with pytest.raises(ValidationError) as exc_info:
            BatchOrchestrator(
                aws_client=aws_client,
                throttle_controller=None,
                session_manager=session_manager
            )

        assert exc_info.value.error_code == "MISSING_THROTTLE_CONTROLLER"

    def test_initialization_missing_session_manager(self):
        """Test inicialización sin session_manager."""
        aws_client = Mock(spec=IAWSClient)
        throttle_controller = Mock(spec=ThrottleController)

        with pytest.raises(ValidationError) as exc_info:
            BatchOrchestrator(
                aws_client=aws_client,
                throttle_controller=throttle_controller,
                session_manager=None
            )

        assert exc_info.value.error_code == "MISSING_SESSION_MANAGER"

    def test_initialization_invalid_max_concurrent_batches(self):
        """Test inicialización con max_concurrent_batches inválido."""
        aws_client = Mock(spec=IAWSClient)
        throttle_controller = Mock(spec=ThrottleController)
        session_manager = Mock(spec=SessionManager)

        with pytest.raises(ValidationError) as exc_info:
            BatchOrchestrator(
                aws_client=aws_client,
                throttle_controller=throttle_controller,
                session_manager=session_manager,
                max_concurrent_batches=0
            )

        assert exc_info.value.error_code == "INVALID_MAX_CONCURRENT_BATCHES"


class TestCreateBatches:
    """Tests para el método create_batches."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_create_batches_basic(self):
        """Test creación básica de lotes."""
        files = [
            FileTransferRequest(f"/source/file{i}.txt", f"/dest/file{i}.txt")
            for i in range(5)
        ]

        batches = self.orchestrator.create_batches(
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-123",
            batch_size=3
        )

        assert len(batches) == 2  # 5 archivos / 3 por lote = 2 lotes
        assert len(batches[0].files) == 3
        assert len(batches[1].files) == 2

        for batch in batches:
            assert batch.transfer_type == TransferType.UPLOAD
            assert batch.connector_id == "connector-123"
            assert batch.batch_id != ""
            assert batch.created_at > 0

    def test_create_batches_exact_division(self):
        """Test creación de lotes con división exacta."""
        files = [
            FileTransferRequest(f"/source/file{i}.txt", f"/dest/file{i}.txt")
            for i in range(10)
        ]

        batches = self.orchestrator.create_batches(
            files=files,
            transfer_type=TransferType.DOWNLOAD,
            connector_id="connector-456",
            batch_size=5
        )

        assert len(batches) == 2
        assert len(batches[0].files) == 5
        assert len(batches[1].files) == 5

    def test_create_batches_single_file(self):
        """Test creación de lotes con un solo archivo."""
        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]

        batches = self.orchestrator.create_batches(
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-123"
        )

        assert len(batches) == 1
        assert len(batches[0].files) == 1
        assert batches[0].files[0] == files[0]

    def test_create_batches_empty_files_list(self):
        """Test creación de lotes con lista vacía."""
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator.create_batches(
                files=[],
                transfer_type=TransferType.UPLOAD,
                connector_id="connector-123"
            )

        assert exc_info.value.error_code == "EMPTY_FILES_LIST"

    def test_create_batches_invalid_batch_size(self):
        """Test creación de lotes con batch_size inválido."""
        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator.create_batches(
                files=files,
                transfer_type=TransferType.UPLOAD,
                connector_id="connector-123",
                batch_size=0
            )

        assert exc_info.value.error_code == "INVALID_BATCH_SIZE"

        with pytest.raises(ValidationError):
            self.orchestrator.create_batches(
                files=files,
                transfer_type=TransferType.UPLOAD,
                connector_id="connector-123",
                batch_size=15
            )

    def test_create_batches_missing_connector_id(self):
        """Test creación de lotes sin connector_id."""
        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator.create_batches(
                files=files,
                transfer_type=TransferType.UPLOAD,
                connector_id=""
            )

        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"


class TestExecuteBatches:
    """Tests para el método execute_batches."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager,
            max_concurrent_batches=2
        )

        # Configurar mocks por defecto
        self.session_manager.max_sessions = 5

    def test_execute_batches_empty_list(self):
        """Test ejecución de lista vacía de lotes."""
        results = self.orchestrator.execute_batches([])

        assert results == []

    @patch('src.orchestration.batch_orchestrator.ThreadPoolExecutor')
    def test_execute_batches_successful(self, mock_executor_class):
        """Test ejecución exitosa de lotes."""
        # Configurar mocks
        mock_executor = MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor

        # Crear lotes de prueba
        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]
        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        # Configurar resultado exitoso
        successful_result = BatchResult(
            batch_id="batch-123",
            transfer_id="exec-123",
            status=TransferStatus.COMPLETED,
            file_results=[],
            session_id=None
        )

        # Mock future
        mock_future = MagicMock()
        mock_future.result.return_value = successful_result

        mock_executor.submit.return_value = mock_future
        mock_executor_class.return_value.__enter__.return_value.submit = mock_executor.submit

        # Mock as_completed
        with patch('src.orchestration.batch_orchestrator.as_completed', return_value=[mock_future]):
            results = self.orchestrator.execute_batches([batch])

        assert len(results) == 1
        assert results[0] == successful_result

    def test_execute_batches_determines_max_workers(self):
        """Test que execute_batches determina correctamente max_workers."""
        # Configurar diferentes escenarios
        self.orchestrator.max_concurrent_batches = 10
        self.session_manager.max_sessions = 3

        # Crear mocks más realistas con batch_id y files
        batches = []
        for i in range(5):
            batch = Mock()
            batch.batch_id = f"batch-{i}"
            batch.files = []  # Lista vacía para evitar errores de iteración
            batches.append(batch)

        with patch('src.orchestration.batch_orchestrator.ThreadPoolExecutor') as mock_executor_class:
            with patch('src.orchestration.batch_orchestrator.as_completed', return_value=[]):
                self.orchestrator.execute_batches(batches)

        # Debería usar min(10, 3, 5) = 3 workers
        mock_executor_class.assert_called_once_with(max_workers=3)


class TestExecuteSingleBatch:
    """Tests para el método _execute_single_batch."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_execute_single_batch_successful(self):
        """Test ejecución exitosa de un lote individual."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_file_transfer.return_value = {"TransferId": "exec-123"}

        # Crear lote de prueba
        files = [
            FileTransferRequest("/source/file1.txt", "/dest/file1.txt"),
            FileTransferRequest("/source/file2.txt", "/dest/file2.txt")
        ]
        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        # Ejecutar
        result = self.orchestrator._execute_single_batch(batch)

        # Verificar resultado
        assert result.batch_id == "batch-123"
        assert result.transfer_id == "exec-123"
        assert result.status == TransferStatus.COMPLETED  # La implementación actual marca como COMPLETED inmediatamente
        assert len(result.file_results) == 2
        assert result.session_id == "session-123"
        assert result.error_message is None

        # Verificar llamadas a mocks
        self.throttle_controller.wait_if_needed.assert_called_once_with(2)
        self.session_manager.acquire_session.assert_called_once_with(timeout=30.0)
        self.aws_client.start_file_transfer.assert_called_once()
        self.session_manager.release_session.assert_called_once_with(mock_session)

    def test_execute_single_batch_throttle_error(self):
        """Test ejecución de lote con error de throttling."""
        # Configurar throttle_controller para lanzar error
        self.throttle_controller.wait_if_needed.side_effect = Exception("Throttle error")

        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]
        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        # Ejecutar
        result = self.orchestrator._execute_single_batch(batch)

        # Verificar resultado de error
        assert result.batch_id == "batch-123"
        assert result.transfer_id is None
        assert result.status == TransferStatus.FAILED
        assert "Throttle error" in result.error_message
        assert len(result.file_results) == 1
        assert result.file_results[0].status == FileStatus.FAILED

    def test_execute_single_batch_session_acquisition_error(self):
        """Test ejecución de lote con error al adquirir sesión."""
        # Configurar session_manager para lanzar error
        self.session_manager.acquire_session.side_effect = Exception("No sessions available")

        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]
        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        # Ejecutar
        result = self.orchestrator._execute_single_batch(batch)

        # Verificar resultado de error
        assert result.status == TransferStatus.FAILED
        assert "No sessions available" in result.error_message

    def test_execute_single_batch_aws_client_error(self):
        """Test ejecución de lote con error del cliente AWS."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_file_transfer.side_effect = Exception("AWS API error")

        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]
        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        # Ejecutar
        result = self.orchestrator._execute_single_batch(batch)

        # Verificar resultado de error
        assert result.status == TransferStatus.FAILED
        assert "AWS API error" in result.error_message

        # Verificar que se liberó la sesión
        self.session_manager.release_session.assert_called_once_with(mock_session)

    def test_execute_single_batch_session_release_error(self):
        """Test ejecución de lote con error al liberar sesión."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_file_transfer.return_value = {"TransferId": "exec-123"}
        self.session_manager.release_session.side_effect = Exception("Release error")

        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]
        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        # Ejecutar (no debería lanzar excepción)
        result = self.orchestrator._execute_single_batch(batch)

        # Debería completarse exitosamente a pesar del error de release
        assert result.status == TransferStatus.COMPLETED  # La implementación actual marca como COMPLETED inmediatamente
        assert result.transfer_id == "exec-123"


class TestPrepareAwsRequest:
    """Tests para el método _prepare_aws_request."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_prepare_aws_request_upload(self):
        """Test preparación de solicitud AWS para upload."""
        files = [
            FileTransferRequest("/s3/bucket/file1.txt", "/sftp/remote/file1.txt"),
            FileTransferRequest("/s3/bucket/file2.txt", "/sftp/remote/file2.txt")
        ]

        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        request = self.orchestrator._prepare_aws_request(batch)

        assert request["ConnectorId"] == "connector-456"
        assert "SendFilePaths" in request
        assert len(request["SendFilePaths"]) == 2

        assert request["SendFilePaths"][0] == "/s3/bucket/file1.txt"
        assert request["SendFilePaths"][1] == "/s3/bucket/file2.txt"

    def test_prepare_aws_request_download(self):
        """Test preparación de solicitud AWS para download."""
        files = [
            FileTransferRequest("/sftp/remote/file1.txt", "/s3/bucket/file1.txt"),
            FileTransferRequest("/sftp/remote/file2.txt", "/s3/bucket/file2.txt")
        ]

        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.DOWNLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        request = self.orchestrator._prepare_aws_request(batch)

        assert request["ConnectorId"] == "connector-456"
        assert "RetrieveFilePaths" in request
        assert len(request["RetrieveFilePaths"]) == 2

        assert request["RetrieveFilePaths"][0] == "/sftp/remote/file1.txt"
        assert request["RetrieveFilePaths"][1] == "/sftp/remote/file2.txt"

    def test_prepare_aws_request_empty_batch(self):
        """Test preparación de solicitud AWS con lote vacío."""
        batch = Batch(
            batch_id="batch-123",
            files=[],
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._prepare_aws_request(batch)

        assert exc_info.value.error_code == "EMPTY_BATCH"

    def test_prepare_aws_request_unsupported_transfer_type(self):
        """Test preparación de solicitud AWS con tipo de transferencia no soportado."""
        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]

        # Crear batch con tipo inválido (simulando un enum corrupto)
        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type="INVALID_TYPE",  # Tipo inválido
            connector_id="connector-456",
            created_at=1000.0
        )

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._prepare_aws_request(batch)

        assert exc_info.value.error_code == "UNSUPPORTED_TRANSFER_TYPE"


class TestGetOrchestratorStats:
    """Tests para el método get_orchestrator_stats."""

    def test_get_orchestrator_stats(self):
        """Test obtención de estadísticas del orquestador."""
        # Configurar mocks
        aws_client = Mock(spec=IAWSClient)
        throttle_controller = Mock(spec=ThrottleController)
        session_manager = Mock(spec=SessionManager)

        throttle_controller.get_current_rate.return_value = 75.5
        throttle_controller.get_remaining_capacity.return_value = 25

        session_manager.get_active_sessions.return_value = 3
        session_manager.get_available_sessions.return_value = 2
        session_manager.get_total_sessions.return_value = 5
        session_manager.max_sessions = 5

        orchestrator = BatchOrchestrator(
            aws_client=aws_client,
            throttle_controller=throttle_controller,
            session_manager=session_manager,
            max_concurrent_batches=4
        )

        stats = orchestrator.get_orchestrator_stats()

        # Verificar estructura de estadísticas
        assert "throttle_controller" in stats
        assert "session_manager" in stats
        assert "orchestrator" in stats

        # Verificar datos de throttle_controller
        assert stats["throttle_controller"]["current_rate"] == 75.5
        assert stats["throttle_controller"]["remaining_capacity"] == 25

        # Verificar datos de session_manager
        assert stats["session_manager"]["active_sessions"] == 3
        assert stats["session_manager"]["available_sessions"] == 2
        assert stats["session_manager"]["total_sessions"] == 5
        assert stats["session_manager"]["max_sessions"] == 5

        # Verificar datos del orchestrator
        assert stats["orchestrator"]["max_concurrent_batches"] == 4


# Tests de integración
class TestBatchOrchestratorIntegration:
    """Tests de integración para BatchOrchestrator."""

    def test_full_workflow_integration(self):
        """Test flujo completo de trabajo."""
        # Crear mocks realistas
        aws_client = Mock(spec=IAWSClient)
        throttle_controller = Mock(spec=ThrottleController)
        session_manager = Mock(spec=SessionManager)

        # Configurar comportamiento de mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        session_manager.acquire_session.return_value = mock_session
        session_manager.max_sessions = 5
        aws_client.start_file_transfer.return_value = {"TransferId": "exec-123"}

        orchestrator = BatchOrchestrator(
            aws_client=aws_client,
            throttle_controller=throttle_controller,
            session_manager=session_manager
        )

        # Crear archivos de prueba
        files = [
            FileTransferRequest(f"/source/file{i}.txt", f"/dest/file{i}.txt")
            for i in range(15)
        ]

        # 1. Crear lotes
        batches = orchestrator.create_batches(
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            batch_size=5
        )

        assert len(batches) == 3  # 15 archivos / 5 por lote

        # 2. Ejecutar un lote individual
        result = orchestrator._execute_single_batch(batches[0])

        assert result.status == TransferStatus.COMPLETED  # La implementación actual marca como COMPLETED inmediatamente
        assert result.transfer_id == "exec-123"
        assert len(result.file_results) == 5

        # Verificar que se llamaron los métodos correctos
        throttle_controller.wait_if_needed.assert_called_with(5)
        session_manager.acquire_session.assert_called_with(timeout=30.0)
        aws_client.start_file_transfer.assert_called_once()
        session_manager.release_session.assert_called_with(mock_session)


class TestExecuteDirectoryListing:
    """Tests para el método execute_directory_listing."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_execute_directory_listing_successful(self):
        """Test ejecución exitosa de listado de directorio."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-123",
            "OutputFileName": "directory_listing_20241225_120000.json"
        }

        # Preparar solicitud
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": 100,
            "OutputDirectoryPath": "/output/path"
        }

        # Ejecutar
        response = self.orchestrator.execute_directory_listing(request)

        # Verificar respuesta
        assert response["ListingId"] == "listing-123"
        assert response["OutputFileName"] == "directory_listing_20241225_120000.json"

        # Verificar llamadas a mocks
        self.throttle_controller.wait_if_needed.assert_called_once_with(1)
        self.session_manager.acquire_session.assert_called_once_with(timeout=30.0)
        self.aws_client.start_directory_listing.assert_called_once_with(request)
        self.session_manager.release_session.assert_called_once_with(mock_session)

    def test_execute_directory_listing_minimal_request(self):
        """Test ejecución de listado con parámetros mínimos."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-456",
            "OutputFileName": "directory_listing_20241225_120001.json"
        }

        # Preparar solicitud mínima
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path"
        }

        # Ejecutar
        response = self.orchestrator.execute_directory_listing(request)

        # Verificar respuesta
        assert response["ListingId"] == "listing-456"
        assert "OutputFileName" in response

        # Verificar que se llamó con la solicitud correcta
        self.aws_client.start_directory_listing.assert_called_once_with(request)

    def test_execute_directory_listing_validation_error(self):
        """Test ejecución de listado con error de validación."""
        # Preparar solicitud inválida (sin ConnectorId)
        request = {
            "RemoteDirectoryPath": "/remote/path"
        }

        # Ejecutar y verificar error
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator.execute_directory_listing(request)

        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

        # Verificar que no se llamaron otros métodos
        self.throttle_controller.wait_if_needed.assert_not_called()
        self.session_manager.acquire_session.assert_not_called()
        self.aws_client.start_directory_listing.assert_not_called()

    def test_execute_directory_listing_session_acquisition_error(self):
        """Test ejecución de listado con error al adquirir sesión."""
        # Configurar session_manager para lanzar error
        self.session_manager.acquire_session.side_effect = Exception("No sessions available")

        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path"
        }

        # Ejecutar y verificar que se propaga el error
        with pytest.raises(Exception) as exc_info:
            self.orchestrator.execute_directory_listing(request)

        assert "No sessions available" in str(exc_info.value)

    def test_execute_directory_listing_aws_client_error(self):
        """Test ejecución de listado con error del cliente AWS."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_directory_listing.side_effect = Exception("AWS API error")

        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path"
        }

        # Ejecutar y verificar que se propaga el error
        with pytest.raises(Exception) as exc_info:
            self.orchestrator.execute_directory_listing(request)

        assert "AWS API error" in str(exc_info.value)

        # Verificar que se liberó la sesión
        self.session_manager.release_session.assert_called_once_with(mock_session)

    def test_execute_directory_listing_session_release_error(self):
        """Test ejecución de listado con error al liberar sesión."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-123",
            "OutputFileName": "directory_listing_20241225_120000.json"
        }
        self.session_manager.release_session.side_effect = Exception("Release error")

        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path"
        }

        # Ejecutar (no debería lanzar excepción)
        response = self.orchestrator.execute_directory_listing(request)

        # Debería completarse exitosamente a pesar del error de release
        assert response["ListingId"] == "listing-123"


class TestValidateListingRequest:
    """Tests para el método _validate_listing_request."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_validate_listing_request_valid_minimal(self):
        """Test validación de solicitud mínima válida."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path"
        }

        # No debería lanzar excepción
        self.orchestrator._validate_listing_request(request)

    def test_validate_listing_request_valid_complete(self):
        """Test validación de solicitud completa válida."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": 100,
            "OutputDirectoryPath": "/output/path"
        }

        # No debería lanzar excepción
        self.orchestrator._validate_listing_request(request)

    def test_validate_listing_request_invalid_type(self):
        """Test validación con tipo de solicitud inválido."""
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request("not a dict")

        assert exc_info.value.error_code == "INVALID_REQUEST_TYPE"

    def test_validate_listing_request_missing_connector_id(self):
        """Test validación sin ConnectorId."""
        request = {
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

    def test_validate_listing_request_empty_connector_id(self):
        """Test validación con ConnectorId vacío."""
        request = {
            "ConnectorId": "",
            "RemoteDirectoryPath": "/remote/path"
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

    def test_validate_listing_request_missing_remote_directory_path(self):
        """Test validación sin RemoteDirectoryPath."""
        request = {
            "ConnectorId": "connector-456"
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "NO_REMOTE_DIRECTORY_PATH_SPECIFIED"

    def test_validate_listing_request_empty_remote_directory_path(self):
        """Test validación con RemoteDirectoryPath vacío."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": ""
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "NO_REMOTE_DIRECTORY_PATH_SPECIFIED"

    def test_validate_listing_request_whitespace_remote_directory_path(self):
        """Test validación con RemoteDirectoryPath solo espacios."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "   "
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "EMPTY_REMOTE_DIRECTORY_PATH"

    def test_validate_listing_request_invalid_remote_directory_path_type(self):
        """Test validación con RemoteDirectoryPath de tipo inválido."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": 123
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "INVALID_REMOTE_DIRECTORY_PATH_TYPE"

    def test_validate_listing_request_invalid_max_items_type(self):
        """Test validación con MaxItems de tipo inválido."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": "not an integer"
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "INVALID_MAX_ITEMS_TYPE"

    def test_validate_listing_request_negative_max_items(self):
        """Test validación con MaxItems negativo."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": -1
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "INVALID_MAX_ITEMS_VALUE"

    def test_validate_listing_request_zero_max_items(self):
        """Test validación con MaxItems cero (válido)."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": 0
        }

        # No debería lanzar excepción
        self.orchestrator._validate_listing_request(request)

    def test_validate_listing_request_invalid_output_directory_path_type(self):
        """Test validación con OutputDirectoryPath de tipo inválido."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "OutputDirectoryPath": 123
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "INVALID_OUTPUT_DIRECTORY_PATH_TYPE"

    def test_validate_listing_request_empty_output_directory_path(self):
        """Test validación con OutputDirectoryPath vacío."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "OutputDirectoryPath": ""
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "EMPTY_OUTPUT_DIRECTORY_PATH"

    def test_validate_listing_request_whitespace_output_directory_path(self):
        """Test validación con OutputDirectoryPath solo espacios."""
        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "OutputDirectoryPath": "   "
        }

        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request(request)

        assert exc_info.value.error_code == "EMPTY_OUTPUT_DIRECTORY_PATH"


class TestExecuteRemoteDelete:
    """Tests para el método execute_remote_delete."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_execute_remote_delete_successful(self):
        """Test ejecución exitosa de eliminación remota."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_remote_delete.return_value = {
            "DeleteId": "delete-123"
        }

        # Preparar solicitud
        request = {
            "ConnectorId": "connector-456",
            "DeletePath": "/remote/file.txt"
        }

        # Ejecutar
        response = self.orchestrator.execute_remote_delete(request)

        # Verificar respuesta
        assert response["DeleteId"] == "delete-123"

        # Verificar llamadas a mocks
        self.throttle_controller.wait_if_needed.assert_called_once_with(1)
        self.session_manager.acquire_session.assert_called_once_with(timeout=30.0)
        self.aws_client.start_remote_delete.assert_called_once_with(request)
        self.session_manager.release_session.assert_called_once_with(mock_session)


class TestBatchOrchestratorExecutionEdgeCases:
    """Tests para casos edge de ejecución de lotes."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_execute_single_batch_missing_transfer_id(self):
        """Test _execute_single_batch cuando AWS no retorna TransferId."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        # AWS retorna respuesta sin TransferId
        self.aws_client.start_file_transfer.return_value = {}

        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]
        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        # Ejecutar
        result = self.orchestrator._execute_single_batch(batch)

        # Verificar resultado de error
        assert result.status == TransferStatus.FAILED
        assert result.transfer_id is None
        assert "AWS Transfer Family did not return a TransferId" in result.error_message


class TestBatchOrchestratorAwsRequestPreparation:
    """Tests para preparación de requests AWS."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_prepare_aws_request_upload_with_remote_directory(self):
        """Test _prepare_aws_request para upload con RemoteDirectoryPath."""
        files = [
            FileTransferRequest("/s3/bucket/file1.txt", "/sftp/remote/dir/file1.txt"),
            FileTransferRequest("/s3/bucket/file2.txt", "/sftp/remote/dir/file2.txt")
        ]

        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.UPLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        request = self.orchestrator._prepare_aws_request(batch)

        assert request["ConnectorId"] == "connector-456"
        assert "SendFilePaths" in request
        assert len(request["SendFilePaths"]) == 2
        assert "RemoteDirectoryPath" in request
        assert request["RemoteDirectoryPath"] == "/sftp/remote/dir"

    def test_prepare_aws_request_download_with_local_directory(self):
        """Test _prepare_aws_request para download con LocalDirectoryPath."""
        files = [
            FileTransferRequest("/sftp/remote/file1.txt", "/s3/bucket/downloads/file1.txt"),
            FileTransferRequest("/sftp/remote/file2.txt", "/s3/bucket/downloads/file2.txt")
        ]

        batch = Batch(
            batch_id="batch-123",
            files=files,
            transfer_type=TransferType.DOWNLOAD,
            connector_id="connector-456",
            created_at=1000.0
        )

        request = self.orchestrator._prepare_aws_request(batch)

        assert request["ConnectorId"] == "connector-456"
        assert "RetrieveFilePaths" in request
        assert len(request["RetrieveFilePaths"]) == 2
        assert "LocalDirectoryPath" in request
        assert request["LocalDirectoryPath"] == "/s3/bucket/downloads"


class TestBatchOrchestratorDirectoryExtraction:
    """Tests para extracción de directorios comunes."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_extract_common_directory_single_file(self):
        """Test _extract_common_directory con un solo archivo."""
        file_paths = ["/remote/path/to/file.txt"]

        result = self.orchestrator._extract_common_directory(file_paths)

        assert result == "/remote/path/to"

    def test_extract_common_directory_no_common_path(self):
        """Test _extract_common_directory sin ruta común."""
        file_paths = [
            "/remote/path1/file1.txt",
            "/different/path2/file2.txt"
        ]

        result = self.orchestrator._extract_common_directory(file_paths)

        assert result is None

    def test_extract_common_directory_empty_result(self):
        """Test _extract_common_directory que resulta en string vacío."""
        file_paths = [
            "file1.txt",  # Sin directorio
            "file2.txt"
        ]

        result = self.orchestrator._extract_common_directory(file_paths)

        assert result is None

    def test_extract_common_directory_empty_list(self):
        """Test _extract_common_directory con lista vacía."""
        result = self.orchestrator._extract_common_directory([])

        assert result is None


class TestBatchOrchestratorRemoteOperations:
    """Tests para operaciones remotas."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_execute_remote_delete_successful(self):
        """Test execute_remote_delete exitoso."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_remote_delete.return_value = {"DeleteId": "delete-123"}

        request = {
            "ConnectorId": "connector-456",
            "DeletePath": "/remote/file/to/delete.txt"
        }

        # Ejecutar
        response = self.orchestrator.execute_remote_delete(request)

        # Verificar
        assert response["DeleteId"] == "delete-123"
        self.throttle_controller.wait_if_needed.assert_called_once_with(1)
        self.session_manager.acquire_session.assert_called_once_with(timeout=30.0)
        self.aws_client.start_remote_delete.assert_called_once_with(request)
        self.session_manager.release_session.assert_called_once_with(mock_session)

    def test_execute_remote_delete_with_exception(self):
        """Test execute_remote_delete con excepción."""
        # Configurar mock para lanzar excepción
        self.throttle_controller.wait_if_needed.side_effect = Exception("Throttle error")

        request = {
            "ConnectorId": "connector-456",
            "DeletePath": "/remote/file.txt"
        }

        # Ejecutar y verificar que se propaga la excepción
        with pytest.raises(Exception) as exc_info:
            self.orchestrator.execute_remote_delete(request)

        assert "Throttle error" in str(exc_info.value)

    def test_execute_remote_delete_session_release_error(self):
        """Test execute_remote_delete con error al liberar sesión."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_remote_delete.return_value = {"DeleteId": "delete-123"}
        self.session_manager.release_session.side_effect = Exception("Release error")

        request = {
            "ConnectorId": "connector-456",
            "DeletePath": "/remote/file.txt"
        }

        # Ejecutar (no debería lanzar excepción)
        response = self.orchestrator.execute_remote_delete(request)

        # Debería completarse exitosamente a pesar del error de release
        assert response["DeleteId"] == "delete-123"

    def test_execute_directory_listing_successful(self):
        """Test execute_directory_listing exitoso."""
        # Configurar mocks
        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session
        self.aws_client.start_directory_listing.return_value = {
            "ListingId": "listing-123",
            "OutputFileName": "listing.json"
        }

        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path",
            "MaxItems": 100
        }

        # Ejecutar
        response = self.orchestrator.execute_directory_listing(request)

        # Verificar
        assert response["ListingId"] == "listing-123"
        self.throttle_controller.wait_if_needed.assert_called_once_with(1)
        self.session_manager.acquire_session.assert_called_once_with(timeout=30.0)
        self.aws_client.start_directory_listing.assert_called_once_with(request)
        self.session_manager.release_session.assert_called_once_with(mock_session)

    def test_execute_directory_listing_with_exception(self):
        """Test execute_directory_listing con excepción."""
        # Configurar mock para lanzar excepción
        self.aws_client.start_directory_listing.side_effect = Exception("Listing error")

        mock_session = Session("session-123", "connector-456", 1000.0, 1000.0)
        self.session_manager.acquire_session.return_value = mock_session

        request = {
            "ConnectorId": "connector-456",
            "RemoteDirectoryPath": "/remote/path"
        }

        # Ejecutar y verificar que se propaga la excepción
        with pytest.raises(Exception) as exc_info:
            self.orchestrator.execute_directory_listing(request)

        assert "Listing error" in str(exc_info.value)
        # Verificar que se liberó la sesión
        self.session_manager.release_session.assert_called_once_with(mock_session)


class TestBatchOrchestratorValidationEdgeCases:
    """Tests para casos edge de validación."""

    def setup_method(self):
        """Setup para cada test."""
        self.aws_client = Mock(spec=IAWSClient)
        self.throttle_controller = Mock(spec=ThrottleController)
        self.session_manager = Mock(spec=SessionManager)

        self.orchestrator = BatchOrchestrator(
            aws_client=self.aws_client,
            throttle_controller=self.throttle_controller,
            session_manager=self.session_manager
        )

    def test_validate_delete_request_edge_cases(self):
        """Test _validate_delete_request con casos edge."""
        # Test con request no dict
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_delete_request("not_a_dict")
        assert exc_info.value.error_code == "INVALID_REQUEST_TYPE"

        # Test con DeletePath que no es string
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_delete_request({
                "ConnectorId": "connector-123",
                "DeletePath": 123
            })
        assert exc_info.value.error_code == "INVALID_DELETE_PATH_TYPE"

        # Test con DeletePath solo espacios
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_delete_request({
                "ConnectorId": "connector-123",
                "DeletePath": "   "
            })
        assert exc_info.value.error_code == "EMPTY_DELETE_PATH"

    def test_validate_listing_request_edge_cases(self):
        """Test _validate_listing_request con casos edge."""
        # Test con request no dict
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request("not_a_dict")
        assert exc_info.value.error_code == "INVALID_REQUEST_TYPE"

        # Test con RemoteDirectoryPath que no es string
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request({
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": 123
            })
        assert exc_info.value.error_code == "INVALID_REMOTE_DIRECTORY_PATH_TYPE"

        # Test con RemoteDirectoryPath solo espacios
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request({
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": "   "
            })
        assert exc_info.value.error_code == "EMPTY_REMOTE_DIRECTORY_PATH"

        # Test con MaxItems que no es int
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request({
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": "/path",
                "MaxItems": "not_an_int"
            })
        assert exc_info.value.error_code == "INVALID_MAX_ITEMS_TYPE"

        # Test con MaxItems negativo
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request({
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": "/path",
                "MaxItems": -1
            })
        assert exc_info.value.error_code == "INVALID_MAX_ITEMS_VALUE"

        # Test con OutputDirectoryPath que no es string
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request({
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": "/path",
                "OutputDirectoryPath": 123
            })
        assert exc_info.value.error_code == "INVALID_OUTPUT_DIRECTORY_PATH_TYPE"

        # Test con OutputDirectoryPath solo espacios
        with pytest.raises(ValidationError) as exc_info:
            self.orchestrator._validate_listing_request({
                "ConnectorId": "connector-123",
                "RemoteDirectoryPath": "/path",
                "OutputDirectoryPath": "   "
            })
        assert exc_info.value.error_code == "EMPTY_OUTPUT_DIRECTORY_PATH"