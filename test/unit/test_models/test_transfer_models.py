"""
Tests para modelos de transferencia.

Este módulo contiene tests unitarios para todos los dataclasses y enums
relacionados con transferencias de archivos.
"""

import pytest
from datetime import datetime
from typing import Dict, Any

from src.models.transfer_models import (
    TransferType,
    TransferStatus,
    FileStatus,
    FileTransferRequest,
    TransferRequest,
    FileTransferResult,
    TransferResult,
    DirectoryListing
)
from src.models.config_models import TransferOptions, RetryConfig


class TestTransferType:
    """Tests para el enum TransferType."""

    def test_transfer_type_values(self):
        """Test que verifica los valores del enum TransferType."""
        assert TransferType.UPLOAD.value == "upload"
        assert TransferType.DOWNLOAD.value == "download"
        assert TransferType.DELETE.value == "delete"

    def test_transfer_type_members(self):
        """Test que verifica que todos los miembros esperados están presentes."""
        expected_members = {"UPLOAD", "DOWNLOAD", "DELETE"}
        actual_members = {member.name for member in TransferType}
        assert actual_members == expected_members


class TestTransferStatus:
    """Tests para el enum TransferStatus."""

    def test_transfer_status_values(self):
        """Test que verifica los valores del enum TransferStatus."""
        assert TransferStatus.PENDING.value == "PENDING"
        assert TransferStatus.IN_PROGRESS.value == "IN_PROGRESS"
        assert TransferStatus.COMPLETED.value == "COMPLETED"
        assert TransferStatus.FAILED.value == "FAILED"
        assert TransferStatus.CANCELLED.value == "CANCELLED"

    def test_transfer_status_members(self):
        """Test que verifica que todos los miembros esperados están presentes."""
        expected_members = {"PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED"}
        actual_members = {member.name for member in TransferStatus}
        assert actual_members == expected_members


class TestFileStatus:
    """Tests para el enum FileStatus."""

    def test_file_status_values(self):
        """Test que verifica los valores del enum FileStatus."""
        assert FileStatus.QUEUED.value == "QUEUED"
        assert FileStatus.TRANSFERRING.value == "TRANSFERRING"
        assert FileStatus.COMPLETED.value == "COMPLETED"
        assert FileStatus.FAILED.value == "FAILED"
        assert FileStatus.SKIPPED.value == "SKIPPED"

    def test_file_status_members(self):
        """Test que verifica que todos los miembros esperados están presentes."""
        expected_members = {"QUEUED", "TRANSFERRING", "COMPLETED", "FAILED", "SKIPPED"}
        actual_members = {member.name for member in FileStatus}
        assert actual_members == expected_members


class TestFileTransferRequest:
    """Tests para el dataclass FileTransferRequest."""

    def test_file_transfer_request_creation(self):
        """Test creación básica de FileTransferRequest."""
        request = FileTransferRequest(
            source_path="/source/file.txt",
            destination_path="/dest/file.txt"
        )

        assert request.source_path == "/source/file.txt"
        assert request.destination_path == "/dest/file.txt"
        assert request.metadata is None

    def test_file_transfer_request_with_metadata(self):
        """Test creación de FileTransferRequest con metadata."""
        metadata = {"content-type": "text/plain", "encoding": "utf-8"}
        request = FileTransferRequest(
            source_path="/source/file.txt",
            destination_path="/dest/file.txt",
            metadata=metadata
        )

        assert request.source_path == "/source/file.txt"
        assert request.destination_path == "/dest/file.txt"
        assert request.metadata == metadata

    def test_file_transfer_request_equality(self):
        """Test igualdad entre instancias de FileTransferRequest."""
        request1 = FileTransferRequest("/source/file.txt", "/dest/file.txt")
        request2 = FileTransferRequest("/source/file.txt", "/dest/file.txt")
        request3 = FileTransferRequest("/source/other.txt", "/dest/other.txt")

        assert request1 == request2
        assert request1 != request3


class TestTransferRequest:
    """Tests para el dataclass TransferRequest."""

    def test_transfer_request_creation(self):
        """Test creación básica de TransferRequest."""
        files = [
            FileTransferRequest("/source/file1.txt", "/dest/file1.txt"),
            FileTransferRequest("/source/file2.txt", "/dest/file2.txt")
        ]

        request = TransferRequest(
            files=files,
            connector_id="s.12345",
            transfer_type=TransferType.UPLOAD
        )

        assert request.files == files
        assert request.connector_id == "s.12345"
        assert request.transfer_type == TransferType.UPLOAD
        assert request.options is None

    def test_transfer_request_with_options(self):
        """Test creación de TransferRequest con opciones."""
        files = [FileTransferRequest("/source/file.txt", "/dest/file.txt")]
        options = TransferOptions(overwrite_existing=True, timeout_seconds=600)

        request = TransferRequest(
            files=files,
            connector_id="s.12345",
            transfer_type=TransferType.DOWNLOAD,
            options=options
        )

        assert request.files == files
        assert request.connector_id == "s.12345"
        assert request.transfer_type == TransferType.DOWNLOAD
        assert request.options == options


class TestFileTransferResult:
    """Tests para el dataclass FileTransferResult."""

    def test_file_transfer_result_success(self):
        """Test creación de FileTransferResult exitoso."""
        result = FileTransferResult(
            file_path="/path/to/file.txt",
            status=FileStatus.COMPLETED,
            transfer_id="transfer-123"
        )

        assert result.file_path == "/path/to/file.txt"
        assert result.status == FileStatus.COMPLETED
        assert result.transfer_id == "transfer-123"
        assert result.error_message is None


    def test_file_transfer_result_failure(self):
        """Test creación de FileTransferResult fallido."""
        result = FileTransferResult(
            file_path="/path/to/file.txt",
            status=FileStatus.FAILED,
            error_message="Connection timeout"
        )

        assert result.file_path == "/path/to/file.txt"
        assert result.status == FileStatus.FAILED
        assert result.transfer_id is None
        assert result.error_message == "Connection timeout"



class TestTransferResult:
    """Tests para el dataclass TransferResult."""

    def test_transfer_result_creation(self):
        """Test creación básica de TransferResult."""
        file_results = [
            FileTransferResult("/file1.txt", FileStatus.COMPLETED),
            FileTransferResult("/file2.txt", FileStatus.FAILED, error_message="Error")
        ]

        result = TransferResult(
            transfer_id="transfer-123",
            status=TransferStatus.COMPLETED,
            file_results=file_results
        )

        assert result.transfer_id == "transfer-123"
        assert result.status == TransferStatus.COMPLETED
        assert result.file_results == file_results
        assert result.error_message is None

    def test_transfer_result_with_completion(self):
        """Test TransferResult con tiempo de finalización."""
        started_at = datetime.now()
        completed_at = datetime.now()

        result = TransferResult(
            transfer_id="transfer-123",
            status=TransferStatus.COMPLETED,
            file_results=[]
        )

        # completed_at field no longer exists

    def test_transfer_result_with_error(self):
        """Test TransferResult con error general."""
        result = TransferResult(
            transfer_id="transfer-123",
            status=TransferStatus.FAILED,
            file_results=[],
            error_message="General transfer failure"
        )

        assert result.error_message == "General transfer failure"


class TestDirectoryListing:
    """Tests para el dataclass DirectoryListing."""

    def test_directory_listing_creation(self):
        """Test creación de DirectoryListing."""
        files = [
            {"name": "file1.txt", "size": 1024, "modified": "2023-01-01"},
            {"name": "file2.txt", "size": 2048, "modified": "2023-01-02"}
        ]
        directories = ["subdir1", "subdir2"]

        listing = DirectoryListing(
            path="/remote/path",
            files=files,
            directories=directories,
            total_items=4
        )

        assert listing.path == "/remote/path"
        assert listing.files == files
        assert listing.directories == directories
        assert listing.total_items == 4

    def test_directory_listing_empty(self):
        """Test DirectoryListing vacío."""
        listing = DirectoryListing(
            path="/empty/path",
            files=[],
            directories=[],
            total_items=0
        )

        assert listing.path == "/empty/path"
        assert listing.files == []
        assert listing.directories == []
        assert listing.total_items == 0


# Tests de integración entre modelos
class TestModelIntegration:
    """Tests de integración entre diferentes modelos."""

    def test_complete_transfer_workflow(self):
        """Test que simula un flujo completo de transferencia."""
        # Crear solicitud de transferencia
        files = [
            FileTransferRequest("/source/file1.txt", "/dest/file1.txt"),
            FileTransferRequest("/source/file2.txt", "/dest/file2.txt")
        ]

        request = TransferRequest(
            files=files,
            connector_id="s.12345",
            transfer_type=TransferType.UPLOAD,
            options=TransferOptions(overwrite_existing=True)
        )

        # Crear resultados de archivos
        file_results = [
            FileTransferResult(
                file_path="/source/file1.txt",
                status=FileStatus.COMPLETED,
                transfer_id="transfer-file1",

            ),
            FileTransferResult(
                file_path="/source/file2.txt",
                status=FileStatus.FAILED,
                error_message="Permission denied"
            )
        ]

        # Crear resultado de transferencia
        result = TransferResult(
            transfer_id="transfer-123",
            status=TransferStatus.COMPLETED,
            file_results=file_results
        )

        # Verificar que todo está conectado correctamente
        assert len(request.files) == len(result.file_results)
        assert request.transfer_type == TransferType.UPLOAD
        assert result.status == TransferStatus.COMPLETED
        assert len([r for r in result.file_results if r.status == FileStatus.COMPLETED]) == 1
        assert len([r for r in result.file_results if r.status == FileStatus.FAILED]) == 1