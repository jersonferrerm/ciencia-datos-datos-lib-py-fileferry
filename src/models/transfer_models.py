"""
Transfer data models.

Este módulo define todos los modelos de datos relacionados con transferencias
de archivos, incluyendo solicitudes, resultados y estados.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum


class TransferType(Enum):
    """Tipos de operación de transferencia."""
    UPLOAD = "upload"
    DOWNLOAD = "download"
    DELETE = "delete"


class TransferStatus(Enum):
    """Estados posibles de una transferencia."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FileStatus(Enum):
    """Estados posibles de un archivo individual."""
    QUEUED = "QUEUED"
    TRANSFERRING = "TRANSFERRING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class FileTransferRequest:
    """
    Representa una solicitud de transferencia de archivo individual.

    Attributes:
        source_path: Ruta del archivo origen
        destination_path: Ruta del archivo destino
        metadata: Metadatos opcionales del archivo
    """
    source_path: str
    destination_path: str
    metadata: Optional[Dict[str, str]] = None


@dataclass
class TransferRequest:
    """
    Solicitud de transferencia que puede contener múltiples archivos.

    Attributes:
        files: Lista de archivos a transferir
        connector_id: ID del conector AWS Transfer Family
        transfer_type: Tipo de transferencia (upload/download)
        options: Opciones adicionales de transferencia
    """
    files: List[FileTransferRequest]
    connector_id: str
    transfer_type: TransferType
    options: Optional['TransferOptions'] = None


@dataclass
class FileTransferResult:
    """
    Resultado de transferencia para un archivo individual.

    Attributes:
        file_path: Ruta del archivo
        status: Estado de la transferencia del archivo
        transfer_id: ID de transferencia (si aplica)
        error_message: Mensaje de error (si falló)
    """
    file_path: str
    status: FileStatus
    transfer_id: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class TransferResult:
    """
    Resultado de una operación de transferencia.

    Attributes:
        transfer_id: ID único de la transferencia
        status: Estado general de la transferencia
        file_results: Resultados individuales por archivo
        error_message: Mensaje de error general
    """
    transfer_id: str
    status: TransferStatus
    file_results: List[FileTransferResult]
    error_message: Optional[str] = None


@dataclass
class DirectoryListing:
    """
    Resultado de listado de directorio SFTP.

    Attributes:
        path: Ruta del directorio listado
        files: Lista de archivos en el directorio
        directories: Lista de subdirectorios
        total_items: Total de elementos encontrados
        listing_id: ID de la operación de listado (ListingId de start_directory_listing)
        output_filename: Nombre del archivo de salida generado (OutputFileName de start_directory_listing)
        connector_id: ID del conector AWS Transfer Family
    """
    path: str
    files: List[Dict[str, Any]]
    directories: List[Dict[str, Any]]
    total_items: int
    listing_id: Optional[str] = None
    output_filename: Optional[str] = None
    connector_id: Optional[str] = None


@dataclass
class FileDeleteRequest:
    """
    Representa una solicitud de eliminación de archivo SFTP.

    Attributes:
        file_path: Ruta del archivo a eliminar en el servidor SFTP
        metadata: Metadatos opcionales
    """
    file_path: str
    metadata: Optional[Dict[str, str]] = None


@dataclass
class DeleteResult:
    """
    Resultado de una operación de eliminación de archivos.

    Attributes:
        execution_id: ID único de la operación de eliminación
        status: Estado general de la eliminación
        file_results: Resultados individuales por archivo
        error_message: Mensaje de error general
    """
    execution_id: str
    status: TransferStatus
    file_results: List[FileTransferResult]
    error_message: Optional[str] = None
