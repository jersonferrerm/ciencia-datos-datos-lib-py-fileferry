"""
DownloadService para transferencias SFTP→S3.

Este módulo implementa el servicio especializado en descargas de archivos
desde servidores SFTP externos hacia Amazon S3 utilizando AWS Transfer Family.
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
    ValidationError
)


logger = logging.getLogger(__name__)


class DownloadService(ITransferService):
    """
    Servicio especializado en descargas SFTP → S3.

    Maneja la lógica específica de download incluyendo validaciones de rutas SFTP,
    coordinación con BatchOrchestrator y manejo de errores específicos para downloads.
    """

    def __init__(self, batch_orchestrator: BatchOrchestrator):
        """
        Inicializa el DownloadService.

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

    def execute_batch_download(
        self,
        sftp_files: List[str],
        connector_id: str,
        s3_destination_path: str
    ) -> TransferResult:
        """
        Descarga múltiples archivos de SFTP a S3 usando el formato del API boto3.

        Implementa el requerimiento de download usando AWS Transfer Family start_file_transfer
        con RetrieveFilePaths y LocalDirectoryPath según la documentación oficial.

        Args:
            sftp_files: Lista de rutas SFTP de archivos a descargar (RetrieveFilePaths)
            connector_id: ID del conector (ConnectorId)
            s3_destination_path: Ruta de destino en S3 (LocalDirectoryPath)

        Returns:
            TransferResult: Resultado de la operación con estado y detalles

        Raises:
            ValidationError: Si los parámetros son inválidos
            TransferError: Si ocurre un error durante la transferencia

        Example:
            ```python
            sftp_files = [
                "/remote/path/file1.txt",
                "/remote/path/file2.txt"
            ]

            result = download_service.execute_batch_download(
                sftp_files=sftp_files,
                connector_id="c-6e6cb1ca1e174d669",
                s3_destination_path="/co-delfos-sandbox-input-634614730521-dev/downloads"
            )
            print(f"Transfer {result.transfer_id}: {result.status}")
            ```
        """

        logger.info(
            "Starting batch download of %d files from SFTP to S3",
            len(sftp_files),
            extra={
                "file_count": len(sftp_files),
                "connector_id": connector_id,
                "s3_destination_path": s3_destination_path
            }
        )

        try:
            # Validar parámetros
            if not sftp_files or not isinstance(sftp_files, list):
                raise ValidationError(
                    "sftp_files must be a non-empty list of SFTP paths",
                    error_code="INVALID_SFTP_FILES_LIST"
                )

            if not connector_id:
                raise ValidationError(
                    "connector_id is required",
                    error_code="MISSING_CONNECTOR_ID"
                )

            if not s3_destination_path:
                raise ValidationError(
                    "s3_destination_path is required",
                    error_code="MISSING_S3_DESTINATION_PATH"
                )

            # Convertir a FileTransferRequest objects para compatibilidad
            file_requests = []
            for sftp_path in sftp_files:
                # Para downloads, source_path es SFTP y destination_path es S3
                # Generar nombre de archivo de destino basado en el nombre del archivo SFTP
                filename = sftp_path.split('/')[-1] if '/' in sftp_path else sftp_path
                s3_full_path = f"{s3_destination_path.rstrip('/')}/{filename}"

                file_requests.append(
                    FileTransferRequest(
                        source_path=sftp_path,
                        destination_path=s3_full_path
                    )
                )

            # Crear solicitud de transferencia
            transfer_request = TransferRequest(
                files=file_requests,
                connector_id=connector_id,
                transfer_type=TransferType.DOWNLOAD
            )

            # Ejecutar usando el método existente pero con consolidación batch
            # Crear lotes
            batches = self.batch_orchestrator.create_batches(
                transfer_request.files,
                transfer_request.transfer_type,
                transfer_request.connector_id
            )

            # Ejecutar lotes
            batch_results = self.batch_orchestrator.execute_batches(batches)

            # Consolidar con formato batch_results
            result = self._consolidate_batch_results(batch_results)

            logger.info(
                "Batch download completed: %s",
                result.transfer_id,
                extra={
                    "transfer_id": result.transfer_id,
                    "status": result.status.value,
                    "file_count": len(result.file_results)
                }
            )

            return result

        except Exception as e:
            logger.error("Batch download failed: %s", e)
            if isinstance(e, ValidationError):
                raise
            else:
                # Crear file_results para el error
                file_results_data = []
                for sftp_path in sftp_files:
                    file_results_data.append({
                        "file_path": sftp_path,
                        "status": FileStatus.FAILED.value,
                        "error_message": str(e)
                    })

                # Crear un batch_result único para errores de batch
                batch_results_data = [{
                    "transfer_id": None,  # No hay TransferId para errores de batch
                    "file_results": file_results_data
                }]

                # Crear resultado de error con batch_results
                custom_result = TransferResult(
                    transfer_id=None,
                    status=TransferStatus.FAILED,
                    file_results=[],  # Vacío porque usamos batch_results
                    error_message="Batch download failed: " + str(e)
                )

                # Agregar los batch_results como atributo personalizado
                custom_result.batch_results = batch_results_data

                return custom_result




    def _consolidate_batch_results(
        self,
        batch_results: List['BatchResult']
    ) -> TransferResult:
        """
        Consolida los resultados de múltiples lotes en un resultado único.

        Args:
            batch_results: Lista de resultados de lotes

        Returns:
            TransferResult: Resultado consolidado con batch_results
        """
        all_file_results = []
        has_failures = False
        has_successes = False

        # Obtener transfer_id del primer lote exitoso
        transfer_id = None
        for batch_result in batch_results:
            if batch_result.transfer_id:
                transfer_id = batch_result.transfer_id
                break

        for batch_result in batch_results:
            all_file_results.extend(batch_result.file_results)

            if batch_result.status == TransferStatus.FAILED:
                has_failures = True
            elif batch_result.status == TransferStatus.COMPLETED:
                has_successes = True

        # Determinar estado general
        if not batch_results:
            overall_status = TransferStatus.FAILED
        elif has_failures and not has_successes:
            overall_status = TransferStatus.FAILED
        elif has_failures and has_successes:
            overall_status = TransferStatus.COMPLETED  # Parcialmente exitoso
        else:
            overall_status = TransferStatus.COMPLETED

        # Crear mensaje de error si hay fallas
        error_message = None
        if has_failures:
            failed_count = len([f for f in all_file_results if f.status == FileStatus.FAILED])
            total_count = len(all_file_results)
            error_message = "%d of %d files failed to transfer" % (failed_count, total_count)



        # Crear batch_results con la estructura solicitada
        batch_results_data = []

        for batch_result in batch_results:
            # Convertir file_results a formato serializable
            file_results_data = []
            for file_result in batch_result.file_results:
                file_results_data.append({
                    "file_path": file_result.file_path,
                    "status": file_result.status.value if hasattr(file_result.status, 'value') else str(file_result.status),
                    "error_message": file_result.error_message
                })

            batch_results_data.append({
                "transfer_id": batch_result.transfer_id,
                "file_results": file_results_data
            })

        # Crear el resultado con la estructura personalizada
        custom_result = TransferResult(
            transfer_id=transfer_id,
            status=overall_status,
            file_results=[],  # Vacío porque usamos batch_results
            error_message=error_message
        )

        # Agregar los batch_results como atributo personalizado
        custom_result.batch_results = batch_results_data

        return custom_result
