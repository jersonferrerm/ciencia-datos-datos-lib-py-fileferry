"""
Delete service implementation.

Este módulo implementa el servicio de eliminación de archivos SFTP,
proporcionando funcionalidades para eliminar archivos remotos usando AWS Transfer Family.
"""

import logging
from typing import List

from src.services.interfaces import ITransferService
from src.orchestration.batch_orchestrator import BatchOrchestrator
from src.models.transfer_models import (
    TransferRequest,
    TransferResult,
    FileTransferResult,
    FileDeleteRequest,
    DeleteResult,
    TransferStatus,
    FileStatus,
    TransferType
)
from src.exceptions.transfer_exceptions import (
    TransferLibraryError,
    ValidationError
)


logger = logging.getLogger(__name__)


class DeleteService(ITransferService): # pragma: no cover
    """
    Servicio para eliminación de archivos SFTP.

    Implementa la lógica de eliminación de archivos remotos usando AWS Transfer Family,
    con manejo de lotes y coordinación de sesiones.
    """

    def __init__(self, batch_orchestrator: BatchOrchestrator):
        """
        Inicializa el servicio de eliminación.

        Args:
            batch_orchestrator: Orquestador de lotes para manejo de sesiones y throttling
        """
        self.batch_orchestrator = batch_orchestrator
        logger.debug("DeleteService initialized")

    def execute_transfer(self, request: TransferRequest) -> TransferResult:
        """
        Ejecuta una operación de eliminación de archivos.

        Args:
            request: Solicitud de transferencia (debe ser tipo DELETE)

        Returns:
            TransferResult: Resultado de la operación de eliminación

        Raises:
            ValidationError: Si la solicitud no es válida para eliminación
            TransferLibraryError: Si ocurre un error durante la eliminación
        """
        # Validar que sea una operación de eliminación
        if request.transfer_type != TransferType.DELETE:
            raise ValidationError(
                f"DeleteService only handles DELETE operations, got {request.transfer_type.value}",
                error_code="INVALID_TRANSFER_TYPE"
            )

        logger.info(
            "Starting delete operation for %d files",
            len(request.files),
            extra={
                "file_count": len(request.files),
                "connector_id": request.connector_id
            }
        )

        try:
            # Procesar cada archivo individualmente ya que la API solo maneja uno a la vez
            file_results = []

            for file_req in request.files:
                try:
                    # Crear solicitud para AWS Transfer Family (un archivo a la vez)
                    aws_request = {
                        "ConnectorId": request.connector_id,
                        "DeletePath": file_req.source_path
                    }

                    # Ejecutar eliminación usando el orquestador
                    execution_result = self.batch_orchestrator.execute_remote_delete(aws_request)

                    # Crear resultado exitoso para este archivo
                    file_result = FileTransferResult(
                        file_path=file_req.source_path,
                        status=FileStatus.QUEUED,
                        transfer_id=execution_result.get("DeleteId")
                    )
                    file_results.append(file_result)

                    logger.debug(
                        "File deletion started: %s",
                        file_req.source_path,
                        extra={
                            "file_path": file_req.source_path,
                            "delete_id": execution_result.get("DeleteId")
                        }
                    )

                except (TransferLibraryError, ValidationError, ValueError, TypeError, KeyError) as e:
                    logger.error(
                        "Failed to delete file %s: %s",
                        file_req.source_path, e,
                        extra={"file_path": file_req.source_path, "error": str(e)}
                    )

                    # Crear resultado de error para este archivo
                    file_result = FileTransferResult(
                        file_path=file_req.source_path,
                        status=FileStatus.FAILED,
                        error_message=str(e)
                    )
                    file_results.append(file_result)

            # Determinar el estado general basado en los resultados individuales
            failed_files = [r for r in file_results if r.status == FileStatus.FAILED]
            if failed_files:
                if len(failed_files) == len(file_results):
                    overall_status = TransferStatus.FAILED
                else:
                    # Hay algunos exitosos y algunos fallidos - usar COMPLETED con información de errores
                    overall_status = TransferStatus.COMPLETED
            else:
                overall_status = TransferStatus.PENDING

            # Usar el primer DeleteId exitoso como transfer_id general
            successful_results = [r for r in file_results if r.transfer_id]
            transfer_id = successful_results[0].transfer_id if successful_results else None

            transfer_result = TransferResult(
                transfer_id=transfer_id,
                status=overall_status,
                file_results=file_results
            )

            logger.info(
                "Delete operation completed: %d files processed",
                len(file_results),
                extra={
                    "total_files": len(file_results),
                    "successful_files": len([r for r in file_results if r.status != FileStatus.FAILED]),
                    "failed_files": len(failed_files),
                    "status": overall_status.value
                }
            )

            return transfer_result

        except Exception as e:
            logger.error("Delete operation failed: %s", e)
            raise TransferLibraryError(
                f"Delete operation failed: {str(e)}",
                error_code="DELETE_OPERATION_FAILED",
                context={"file_count": len(request.files), "original_error": str(e)}
            ) from e

    def delete_files_batch(
        self,
        delete_paths: List[str],
        connector_id: str
    ) -> DeleteResult:
        """
        Elimina múltiples archivos del servidor SFTP usando el formato del API boto3.

        Implementa el requerimiento de delete basado en AWS Transfer Family start_remote_delete
        con múltiples rutas para el mismo conector.

        Args:
            delete_paths: Lista de rutas SFTP de archivos a eliminar (DeletePath)
            connector_id: ID del conector (ConnectorId)

        Returns:
            DeleteResult: Resultado de la operación con lista de delete_id y delete_path

        Raises:
            ValidationError: Si los parámetros son inválidos
            TransferLibraryError: Si ocurre un error durante la eliminación

        Example:
            ```python
            delete_paths = [
                "/remote/path/file1.txt",
                "/remote/path/file2.txt"
            ]

            result = delete_service.delete_files_batch(
                delete_paths=delete_paths,
                connector_id="c-6e6cb1ca1e174d669"
            )
            print(f"Delete operation: {result.status}")
            ```
        """
        logger.info(
            "Starting batch deletion of %d files",
            len(delete_paths),
            extra={
                "file_count": len(delete_paths),
                "connector_id": connector_id
            }
        )

        try:
            # Validar parámetros
            if not delete_paths or not isinstance(delete_paths, list):
                raise ValidationError(
                    "delete_paths must be a non-empty list of SFTP paths",
                    error_code="INVALID_DELETE_PATHS_LIST"
                )

            if not connector_id:
                raise ValidationError(
                    "connector_id is required",
                    error_code="MISSING_CONNECTOR_ID"
                )

            # Procesar cada archivo individualmente ya que la API solo maneja uno a la vez
            file_results = []

            for delete_path in delete_paths:
                try:
                    # Validar que la ruta no esté vacía
                    if not delete_path or not isinstance(delete_path, str):
                        raise ValidationError(
                            f"Delete path must be a non-empty string: {delete_path}",
                            error_code="INVALID_DELETE_PATH"
                        )

                    # Crear solicitud para AWS Transfer Family (un archivo a la vez)
                    aws_request = {
                        "ConnectorId": connector_id,
                        "DeletePath": delete_path
                    }

                    # Ejecutar eliminación
                    execution_result = self.batch_orchestrator.execute_remote_delete(aws_request)

                    # Crear resultado exitoso para este archivo
                    file_result = FileTransferResult(
                        file_path=delete_path,
                        status=FileStatus.QUEUED,
                        transfer_id=execution_result.get("DeleteId")
                    )
                    file_results.append(file_result)

                    logger.debug(
                        "File deletion started: %s",
                        delete_path,
                        extra={
                            "file_path": delete_path,
                            "delete_id": execution_result.get("DeleteId")
                        }
                    )

                except (TransferLibraryError, ValidationError, ValueError, TypeError, KeyError) as e:
                    logger.error(
                        "Failed to delete file %s: %s",
                        delete_path, e,
                        extra={"file_path": delete_path, "error": str(e)}
                    )

                    # Crear resultado de error para este archivo
                    file_result = FileTransferResult(
                        file_path=delete_path,
                        status=FileStatus.FAILED,
                        error_message=str(e)
                    )
                    file_results.append(file_result)

            # Determinar el estado general basado en los resultados individuales
            failed_files = [r for r in file_results if r.status == FileStatus.FAILED]
            if failed_files:
                if len(failed_files) == len(file_results):
                    overall_status = TransferStatus.FAILED
                else:
                    # Hay algunos exitosos y algunos fallidos - usar COMPLETED con información de errores
                    overall_status = TransferStatus.COMPLETED
            else:
                overall_status = TransferStatus.PENDING

            # Usar el primer DeleteId exitoso como execution_id general
            successful_results = [r for r in file_results if r.transfer_id]
            execution_id = successful_results[0].transfer_id if successful_results else None

            delete_result = DeleteResult(
                execution_id=execution_id,
                status=overall_status,
                file_results=file_results
            )

            logger.info(
                "Batch deletion completed: %d files processed",
                len(file_results),
                extra={
                    "total_files": len(file_results),
                    "successful_files": len([r for r in file_results if r.status != FileStatus.FAILED]),
                    "failed_files": len(failed_files),
                    "status": overall_status.value
                }
            )

            return delete_result

        except Exception as e:
            logger.error("Batch deletion failed: %s", e)
            raise TransferLibraryError(
                f"Batch deletion failed: {str(e)}",
                error_code="BATCH_DELETE_FAILED",
                context={"file_count": len(delete_paths), "original_error": str(e)}
            ) from e

    def delete_files(
        self,
        files: List[FileDeleteRequest],
        connector_id: str
    ) -> DeleteResult:
        """
        Elimina múltiples archivos del servidor SFTP.

        Args:
            files: Lista de archivos a eliminar
            connector_id: ID del conector AWS Transfer Family

        Returns:
            DeleteResult: Resultado de la operación de eliminación

        Raises:
            ValidationError: Si los parámetros son inválidos
            TransferLibraryError: Si ocurre un error durante la eliminación
        """
        logger.info(
            "Starting deletion of %d files",
            len(files),
            extra={
                "file_count": len(files),
                "connector_id": connector_id
            }
        )

        try:
            # Validar parámetros
            self._validate_delete_request(files, connector_id)

            # Procesar cada archivo individualmente ya que la API solo maneja uno a la vez
            file_results = []

            for file_req in files:
                try:
                    # Crear solicitud para AWS Transfer Family (un archivo a la vez)
                    aws_request = {
                        "ConnectorId": connector_id,
                        "DeletePath": file_req.file_path
                    }

                    # Ejecutar eliminación
                    execution_result = self.batch_orchestrator.execute_remote_delete(aws_request)

                    # Crear resultado exitoso para este archivo
                    file_result = FileTransferResult(
                        file_path=file_req.file_path,
                        status=FileStatus.QUEUED,
                        transfer_id=execution_result.get("DeleteId")
                    )
                    file_results.append(file_result)

                    logger.debug(
                        "File deletion started: %s",
                        file_req.file_path,
                        extra={
                            "file_path": file_req.file_path,
                            "delete_id": execution_result.get("DeleteId")
                        }
                    )

                except (TransferLibraryError, ValidationError, ValueError, TypeError, KeyError) as e:
                    logger.error(
                        "Failed to delete file %s: %s",
                        file_req.file_path, e,
                        extra={"file_path": file_req.file_path, "error": str(e)}
                    )

                    # Crear resultado de error para este archivo
                    file_result = FileTransferResult(
                        file_path=file_req.file_path,
                        status=FileStatus.FAILED,
                        error_message=str(e)
                    )
                    file_results.append(file_result)

            # Determinar el estado general basado en los resultados individuales
            failed_files = [r for r in file_results if r.status == FileStatus.FAILED]
            if failed_files:
                if len(failed_files) == len(file_results):
                    overall_status = TransferStatus.FAILED
                else:
                    # Hay algunos exitosos y algunos fallidos - usar COMPLETED con información de errores
                    overall_status = TransferStatus.COMPLETED
            else:
                overall_status = TransferStatus.PENDING

            # Usar el primer DeleteId exitoso como execution_id general
            successful_results = [r for r in file_results if r.transfer_id]
            execution_id = successful_results[0].transfer_id if successful_results else None

            delete_result = DeleteResult(
                execution_id=execution_id,
                status=overall_status,
                file_results=file_results
            )

            logger.info(
                "File deletion completed: %d files processed",
                len(file_results),
                extra={
                    "total_files": len(file_results),
                    "successful_files": len([r for r in file_results if r.status != FileStatus.FAILED]),
                    "failed_files": len(failed_files),
                    "status": overall_status.value
                }
            )

            return delete_result

        except Exception as e:
            logger.error("File deletion failed: %s", e)
            raise TransferLibraryError(
                f"File deletion failed: {str(e)}",
                error_code="FILE_DELETION_FAILED",
                context={"file_count": len(files), "original_error": str(e)}
            ) from e

    def _validate_delete_request(
        self,
        files: List[FileDeleteRequest],
        connector_id: str
    ) -> None:
        """
        Valida una solicitud de eliminación de archivos.

        Args:
            files: Lista de archivos a eliminar
            connector_id: ID del conector

        Raises:
            ValidationError: Si la solicitud es inválida
        """
        if not files:
            raise ValidationError(
                "File list cannot be empty for delete operation",
                error_code="EMPTY_FILE_LIST"
            )

        if not isinstance(files, list):
            raise ValidationError(
                "Files must be a list of FileDeleteRequest objects",
                error_code="INVALID_FILE_LIST_TYPE"
            )

        if not connector_id or not isinstance(connector_id, str):
            raise ValidationError(
                "connector_id must be a non-empty string",
                error_code="INVALID_CONNECTOR_ID"
            )

        # Validar cada archivo
        for i, file_req in enumerate(files):
            if not isinstance(file_req, FileDeleteRequest):
                raise ValidationError(
                    f"File {i} must be a FileDeleteRequest object",
                    error_code="INVALID_FILE_REQUEST_TYPE",
                    context={"file_index": i, "type": type(file_req).__name__}
                )

            if not file_req.file_path or not isinstance(file_req.file_path, str):
                raise ValidationError(
                    f"File path is required for file {i}",
                    error_code="MISSING_FILE_PATH",
                    context={"file_index": i}
                )
