"""
Tests simplificados para DownloadService.

Este módulo contiene tests unitarios para el servicio de downloads SFTP→S3
sin validaciones SFTP (delegadas a AWS Transfer Family).
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.services.download_service import DownloadService
from src.orchestration.batch_orchestrator import BatchOrchestrator, BatchResult
from src.models.transfer_models import (
    TransferRequest,
    TransferResult,
    TransferType,
    TransferStatus,
    FileTransferRequest,
    FileTransferResult,
    FileStatus
)
from src.exceptions.transfer_exceptions import ValidationError


class TestDownloadServiceInitialization:
    """Tests para la inicialización de DownloadService."""

    def test_initialization_valid_parameters(self):
        """Test inicialización con parámetros válidos."""
        batch_orchestrator = Mock(spec=BatchOrchestrator)

        service = DownloadService(batch_orchestrator=batch_orchestrator)

        assert service.batch_orchestrator == batch_orchestrator

    def test_initialization_missing_batch_orchestrator(self):
        """Test inicialización sin batch_orchestrator."""
        with pytest.raises(ValidationError) as exc_info:
            DownloadService(batch_orchestrator=None)

        assert exc_info.value.error_code == "MISSING_BATCH_ORCHESTRATOR"









class TestExecuteBatchDownload:
    """Tests para el método execute_batch_download."""

    def setup_method(self):
        """Setup para cada test."""
        self.batch_orchestrator = Mock(spec=BatchOrchestrator)
        self.service = DownloadService(self.batch_orchestrator)

    def test_execute_batch_download_successful(self):
        """Test ejecución exitosa de batch download."""
        # Configurar mocks de tiempo
        mock_now = datetime(2023, 1, 1, 12, 0, 0)
        # mock_datetime no longer needed

        # Configurar mock del método execute_transfer
        mock_result = TransferResult(
            transfer_id="exec-123",
            status=TransferStatus.COMPLETED,
            file_results=[
                FileTransferResult("/sftp/file1.txt", FileStatus.COMPLETED),
                FileTransferResult("/sftp/file2.txt", FileStatus.COMPLETED)
            ]
        )

        # Mock batch orchestrator methods
        mock_batch = Mock()
        mock_batch.transfer_id = "exec-123"
        mock_batch.status = TransferStatus.COMPLETED
        mock_batch.file_results = [
            FileTransferResult("/sftp/file1.txt", FileStatus.COMPLETED),
            FileTransferResult("/sftp/file2.txt", FileStatus.COMPLETED)
        ]

        with patch.object(self.service.batch_orchestrator, 'create_batches', return_value=[mock_batch]) as mock_create, \
             patch.object(self.service.batch_orchestrator, 'execute_batches', return_value=[mock_batch]) as mock_execute:

            # Ejecutar batch download
            result = self.service.execute_batch_download(
                sftp_files=["/sftp/file1.txt", "/sftp/file2.txt"],
                connector_id="connector-123",
                s3_destination_path="/bucket/downloads"
            )

            # Verificar resultado
            assert result.transfer_id == "exec-123"
            assert result.status == TransferStatus.COMPLETED
            assert hasattr(result, 'batch_results')
            assert len(result.batch_results) == 1

            # Verificar que se llamaron los métodos del batch orchestrator
            mock_create.assert_called_once()
            mock_execute.assert_called_once()

    def test_execute_batch_download_invalid_sftp_files(self):
        """Test batch download con lista de archivos SFTP inválida."""
        # Lista vacía
        with pytest.raises(ValidationError) as exc_info:
            self.service.execute_batch_download(
                sftp_files=[],
                connector_id="connector-123",
                s3_destination_path="/bucket/downloads"
            )

        assert exc_info.value.error_code == "INVALID_SFTP_FILES_LIST"

        # No es lista
        with pytest.raises(ValidationError) as exc_info:
            self.service.execute_batch_download(
                sftp_files="not-a-list",
                connector_id="connector-123",
                s3_destination_path="/bucket/downloads"
            )

        assert exc_info.value.error_code == "INVALID_SFTP_FILES_LIST"

    def test_execute_batch_download_missing_connector_id(self):
        """Test batch download sin connector_id."""
        with pytest.raises(ValidationError) as exc_info:
            self.service.execute_batch_download(
                sftp_files=["/sftp/file.txt"],
                connector_id="",
                s3_destination_path="/bucket/downloads"
            )

        assert exc_info.value.error_code == "MISSING_CONNECTOR_ID"

    def test_execute_batch_download_missing_s3_destination(self):
        """Test batch download sin s3_destination_path."""
        with pytest.raises(ValidationError) as exc_info:
            self.service.execute_batch_download(
                sftp_files=["/sftp/file.txt"],
                connector_id="connector-123",
                s3_destination_path=""
            )

        assert exc_info.value.error_code == "MISSING_S3_DESTINATION_PATH"

    def test_execute_batch_download_path_generation(self):
        """Test generación correcta de rutas de destino S3."""
        mock_batch = Mock()
        mock_batch.transfer_id = "exec-123"
        mock_batch.status = TransferStatus.COMPLETED
        mock_batch.file_results = []

        with patch.object(self.service.batch_orchestrator, 'create_batches', return_value=[mock_batch]) as mock_create, \
             patch.object(self.service.batch_orchestrator, 'execute_batches', return_value=[mock_batch]):

            # Test con diferentes tipos de rutas SFTP
            self.service.execute_batch_download(
                sftp_files=[
                    "/remote/path/file1.txt",
                    "relative/file2.txt",
                    "simple_file.txt"
                ],
                connector_id="connector-123",
                s3_destination_path="/bucket/downloads"
            )

            # Verificar que create_batches fue llamado
            mock_create.assert_called_once()
            call_args = mock_create.call_args[0][0]  # files argument
            files = call_args

            # Verificar generación de nombres de archivo
            assert files[0].destination_path == "/bucket/downloads/file1.txt"
            assert files[1].destination_path == "/bucket/downloads/file2.txt"
            assert files[2].destination_path == "/bucket/downloads/simple_file.txt"

    def test_execute_batch_download_s3_path_normalization(self):
        """Test normalización de rutas S3 de destino."""
        mock_batch = Mock()
        mock_batch.transfer_id = "exec-123"
        mock_batch.status = TransferStatus.COMPLETED
        mock_batch.file_results = []

        with patch.object(self.service.batch_orchestrator, 'create_batches', return_value=[mock_batch]) as mock_create, \
             patch.object(self.service.batch_orchestrator, 'execute_batches', return_value=[mock_batch]):

            # Test con ruta S3 que termina en slash
            self.service.execute_batch_download(
                sftp_files=["/sftp/file.txt"],
                connector_id="connector-123",
                s3_destination_path="/bucket/downloads/"  # Con slash final
            )

            # Verificar que create_batches fue llamado
            mock_create.assert_called_once()
            call_args = mock_create.call_args[0][0]  # files argument

            # Verificar que se removió el slash duplicado
            assert call_args[0].destination_path == "/bucket/downloads/file.txt"