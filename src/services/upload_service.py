"""
UploadService para transferencias S3→SFTP.

Este módulo implementa el servicio especializado en cargas de archivos
desde Amazon S3 hacia servidores SFTP externos utilizando AWS Transfer Family.
"""

import logging
from typing import List

from src.services.interfaces import ITransferService
from src.models.transfer_models import (
    TransferRequest,
    TransferResult,
    TransferType,
    TransferStatus,
    FileTransferRequest,
    FileStatus
)
from src.orchestration.batch_orchestrator import BatchOrchestrator
from src.exceptions.transfer_exceptions import (
    TransferError,
    ValidationError,
    FileNotFoundError as TransferFileNotFoundError,
    InsufficientPermissionsError
)


logger = logging.getLogger(__name__)


class UploadService(ITransferService):
    """
    Servicio especializado en cargas S3 → SFTP.

    Maneja la lógica específica de upload incluyendo validaciones de archivos S3,
    coordinación con BatchOrchestrator y manejo de errores específicos para uploads.
    """

    def __init__(
        self,
        batch_orchestrator: BatchOrchestrator
    ):
        """
        Inicializa el UploadService.

        Args:
            batch_orchestrator: Orquestador de lotes para coordinación

        Raises:
            ValidationError: Si los parámetros son inválidos
        """
        if not batch_orchestrator:
            raise ValidationError(
                "batch_orchestrator es requerido",
                error_code="MISSING_BATCH_ORCHESTRATOR"
            )

        self.batch_orchestrator = batch_orchestrator

    def execute_batch_transfer(
        self,
        files: List[str],
        connector_id: str,
        destination_path: str
    ) -> TransferResult: # pragma: no cover
        """
        Ejecuta una transferencia de lote S3 → SFTP usando formato boto3.

        Implementa el patrón del API start_file_transfer de boto3 donde múltiples
        archivos se transfieren a la misma ruta de destino.

        Args:
            files: Lista de rutas S3 (SendFilePaths en boto3)
            connector_id: ID del conector (ConnectorId en boto3)
            destination_path: Ruta de destino SFTP (RemoteDirectoryPath en boto3)

        Returns:
            TransferResult: Resultado de la operación con TransferId

        Raises:
            ValidationError: Si la solicitud no es válida
            TransferError: Si ocurre un error durante la transferencia
        """

        logger.info(
            "Starting batch upload transfer",
            extra={
                "file_count": len(files),
                "connector_id": connector_id,
                "destination_path": destination_path
            }
        )

        try:
            # 1. Validar la solicitud
            self._validate_batch_request(files, connector_id, destination_path)

            # 2. Convertir a formato interno FileTransferRequest
            file_requests = []
            for file_path in files:
                # Extraer nombre del archivo de la ruta S3
                file_name = file_path.split('/')[-1]
                # Construir ruta de destino completa
                full_destination = f"{destination_path.rstrip('/')}/{file_name}"

                file_requests.append(
                    FileTransferRequest(
                        source_path=file_path,
                        destination_path=full_destination
                    )
                )

            # 3. Crear solicitud de transferencia interna
            transfer_request = TransferRequest(
                files=file_requests,
                connector_id=connector_id,
                transfer_type=TransferType.UPLOAD
            )

            # 4. Ejecutar usando el método existente
            result = self.execute_transfer(transfer_request)

            logger.info(
                "Batch upload transfer completed with status %s",
                result.status.value,
                extra={
                    "transfer_id": result.transfer_id,
                    "status": result.status.value,
                    "successful_files": len([
                        f for f in result.file_results
                        if f.status == FileStatus.COMPLETED
                    ]),
                    "failed_files": len([
                        f for f in result.file_results
                        if f.status == FileStatus.FAILED
                    ])
                }
            )

            return result

        except (ValidationError, TransferError, TransferFileNotFoundError, InsufficientPermissionsError) as e:
            logger.error(
                "Batch upload transfer failed with error: %s",
                e,
                extra={"error": str(e)}
            )

            # Crear resultado de error con estructura batch_results
            file_results_data = [
                {
                    "file_path": file_path,
                    "status": FileStatus.FAILED.value,
                    "error_message": str(e)
                }
                for file_path in files
            ]

            # Crear un batch_result único para errores de batch
            batch_results_data = [{
                "transfer_id": None,  # No hay TransferId para errores de batch
                "file_results": file_results_data
            }]

            # Crear el resultado con la estructura personalizada
            custom_result = TransferResult(
                transfer_id=None,
                status=TransferStatus.FAILED,
                file_results=[],  # Vacío porque usamos batch_results
                error_message=f"Batch upload transfer failed: {str(e)}"
            )

            # Agregar los batch_results como atributo personalizado
            custom_result.batch_results = batch_results_data

            return custom_result

    def _validate_batch_request(
        self,
        files: List[str],
        connector_id: str,
        destination_path: str
    ) -> None:
        """
        Valida una solicitud de transferencia en lote.

        Args:
            files: Lista de rutas S3
            connector_id: ID del conector
            destination_path: Ruta de destino SFTP

        Raises:
            ValidationError: Si la solicitud no es válida
        """
        if not files or not isinstance(files, list):
            raise ValidationError(
                "files must be a non-empty list",
                error_code="INVALID_FILES_LIST"
            )



        if not connector_id or not isinstance(connector_id, str):
            raise ValidationError(
                "connector_id must be a non-empty string",
                error_code="INVALID_CONNECTOR_ID"
            )

        if not destination_path or not isinstance(destination_path, str):
            raise ValidationError(
                "destination_path must be a non-empty string",
                error_code="INVALID_DESTINATION_PATH"
            )

        # Validar cada archivo
        for i, file_path in enumerate(files):
            if not isinstance(file_path, str) or not file_path.strip():
                raise ValidationError(
                    f"File path {i} must be a non-empty string",
                    error_code="INVALID_FILE_PATH",
                    context={"file_index": i, "path": file_path}
                )



    def execute_transfer(self, request: TransferRequest) -> TransferResult:
        """
        Ejecuta una transferencia de carga S3 → SFTP.

        Coordina todo el proceso de transferencia incluyendo validación,
        división en lotes y ejecución coordinada.

        Args:
            request: Solicitud de transferencia con archivos y configuración

        Returns:
            TransferResult: Resultado de la operación con estado y detalles

        Raises:
            ValidationError: Si la solicitud no es válida
            TransferError: Si ocurre un error durante la transferencia
        """

        logger.info(
            "Starting upload transfer",
            extra={
                "file_count": len(request.files),
                "connector_id": request.connector_id
            }
        )

        try:
            # 1. Validar la solicitud
            self._validate_upload_request(request)

            # 2. Crear lotes con todos los archivos (sin validar existencia en S3)
            batches = self.batch_orchestrator.create_batches(
                files=request.files,
                transfer_type=TransferType.UPLOAD,
                connector_id=request.connector_id,
                batch_size=10
            )

            logger.info(
                "Created %d batches for %d files",
                len(batches),
                len(request.files),
                extra={
                    "batch_count": len(batches),
                    "total_files": len(request.files)
                }
            )

            # 3. Ejecutar lotes
            batch_results = self.batch_orchestrator.execute_batches(batches)

            # 4. Consolidar resultados
            result = self._consolidate_batch_results(batch_results)

            # 6. El transfer_id viene directamente de AWS Transfer Family
            # No generar IDs falsos - usar el TransferId real de la respuesta

            logger.info(
                "Upload transfer completed with status %s",
                result.status.value,
                extra={
                    "transfer_id": result.transfer_id,
                    "status": result.status.value,
                    "successful_files": len([f for f in result.file_results if f.status == FileStatus.COMPLETED]),
                    "failed_files": len([f for f in result.file_results if f.status == FileStatus.FAILED])
                }
            )

            return result

        except (ValidationError, TransferError, TransferFileNotFoundError, InsufficientPermissionsError) as e:
            logger.error(
                "Upload transfer failed with error: %s",
                e,
                extra={"error": str(e)}
            )

            # Crear resultado de error con estructura batch_results
            file_results_data = [
                {
                    "file_path": f.source_path,
                    "status": FileStatus.FAILED.value,
                    "error_message": str(e)
                }
                for f in request.files
            ]

            # Crear un batch_result único para errores generales
            batch_results_data = [{
                "transfer_id": None,  # No hay TransferId para errores generales
                "file_results": file_results_data
            }]

            # Crear el resultado con la estructura personalizada
            custom_result = TransferResult(
                transfer_id=None,
                status=TransferStatus.FAILED,
                file_results=[],  # Vacío porque usamos batch_results
                error_message=f"Upload transfer failed: {str(e)}"
            )

            # Agregar los batch_results como atributo personalizado
            custom_result.batch_results = batch_results_data

            return custom_result

    def _validate_upload_request(self, request: TransferRequest) -> None:
        """
        Valida una solicitud de upload.

        Args:
            request: Solicitud de transferencia a validar

        Raises:
            ValidationError: Si la solicitud no es válida
        """
        if not request:
            raise ValidationError(
                "Transfer request cannot be None",
                error_code="NULL_REQUEST"
            )

        if request.transfer_type != TransferType.UPLOAD:
            raise ValidationError(
                f"Invalid transfer type for UploadService: {request.transfer_type}",
                error_code="INVALID_TRANSFER_TYPE"
            )

        if not request.files:
            raise ValidationError(
                "File list cannot be empty",
                error_code="EMPTY_FILE_LIST"
            )

        if not request.connector_id:
            raise ValidationError(
                "Connector ID is required",
                error_code="MISSING_CONNECTOR_ID"
            )

        # Validar cada archivo
        for i, file_req in enumerate(request.files):
            if not file_req.source_path:
                raise ValidationError(
                    f"Source path is required for file {i}",
                    error_code="MISSING_SOURCE_PATH",
                    context={"file_index": i}
                )

            if not file_req.destination_path:
                raise ValidationError(
                    f"Destination path is required for file {i}",
                    error_code="MISSING_DESTINATION_PATH",
                    context={"file_index": i}
                )


    def _consolidate_batch_results(
        self,
        batch_results: List['BatchResult']
    ) -> TransferResult:
        """
        Consolida los resultados de múltiples lotes en un resultado único.

        Args:
            batch_results: Lista de resultados de lotes

        Returns:
            TransferResult: Resultado consolidado con estructura de batch_results
        """
        has_failures = False
        has_successes = False

        # Crear batch_results con la estructura solicitada
        batch_results_data = []

        for batch_result in batch_results:
            if batch_result.status == TransferStatus.FAILED:
                has_failures = True
            elif batch_result.status == TransferStatus.COMPLETED:
                has_successes = True

            # Crear file_results para este batch
            file_results_data = []
            for file_result in batch_result.file_results:
                file_results_data.append({
                    "file_path": file_result.file_path,
                    "status": file_result.status.value,
                    "error_message": file_result.error_message
                })

            # Agregar este batch a los resultados
            batch_results_data.append({
                "transfer_id": batch_result.transfer_id,
                "file_results": file_results_data
            })

        # Determinar estado general
        if not batch_results:
            overall_status = TransferStatus.FAILED
        elif has_failures and not has_successes:
            overall_status = TransferStatus.FAILED
        elif has_failures and has_successes:
            overall_status = TransferStatus.FAILED  # Si hay fallas, consideramos como fallido
        else:
            overall_status = TransferStatus.COMPLETED

        # Crear mensaje de error si hay fallas
        error_message = None
        if has_failures:
            failed_batches = len([b for b in batch_results if b.status == TransferStatus.FAILED])
            total_batches = len(batch_results)
            error_message = f"{failed_batches} of {total_batches} batches failed to transfer"

        # Usar el primer transfer_id como identificador principal (para compatibilidad)
        main_transfer_id = None
        for batch_result in batch_results:
            if batch_result.transfer_id:
                main_transfer_id = batch_result.transfer_id
                break

        # Crear el resultado con la estructura personalizada
        custom_result = TransferResult(
            transfer_id=main_transfer_id,
            status=overall_status,
            file_results=[],  # Vacío porque usamos batch_results
            error_message=error_message
        )

        # Agregar los batch_results como atributo personalizado
        custom_result.batch_results = batch_results_data

        return custom_result
