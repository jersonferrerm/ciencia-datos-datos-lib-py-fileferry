"""
BatchOrchestrator para procesamiento de lotes.

Este módulo implementa la orquestación de transferencias en lotes,
coordinando ThrottleController, SessionManager y AWSTransferClient.
"""

import uuid
import time
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
# datetime removed as it's no longer needed

from src.orchestration.throttle_controller import ThrottleController
from src.orchestration.session_manager import SessionManager
from src.services.interfaces import IAWSClient
from src.models.transfer_models import (
    FileTransferRequest,
    TransferType,
    TransferStatus,
    FileStatus,
    FileTransferResult
)
from src.exceptions.transfer_exceptions import (
    TransferError,
    ValidationError
)


logger = logging.getLogger(__name__)


@dataclass
class Batch:
    """
    Representa un lote de archivos para transferencia.

    Attributes:
        batch_id: Identificador único del lote
        files: Lista de archivos en el lote
        transfer_type: Tipo de transferencia (upload/download)
        connector_id: ID del conector AWS Transfer Family
        created_at: Timestamp de creación del lote
    """
    batch_id: str
    files: List[FileTransferRequest]
    transfer_type: TransferType
    connector_id: str
    created_at: float

    def __post_init__(self):
        """Inicializa campos calculados."""
        if not self.batch_id:
            self.batch_id = str(uuid.uuid4())


@dataclass
class BatchResult:
    """
    Resultado del procesamiento de un lote.

    Attributes:
        batch_id: ID del lote procesado
        transfer_id: ID de ejecución de AWS Transfer Family
        status: Estado del lote
        file_results: Resultados individuales por archivo

        error_message: Mensaje de error si falló
        session_id: ID de la sesión utilizada
    """
    batch_id: str
    transfer_id: Optional[str]
    status: TransferStatus
    file_results: List[FileTransferResult]
    error_message: Optional[str] = None
    session_id: Optional[str] = None


class BatchOrchestrator:
    """
    Orquestador de lotes para transferencias de archivos.

    Coordina la división de archivos en lotes, el control de throughput,
    la gestión de sesiones y las llamadas a la API de AWS Transfer Family.
    """

    def __init__(
        self,
        aws_client: IAWSClient,
        throttle_controller: ThrottleController,
        session_manager: SessionManager,
        max_concurrent_batches: int = 3
    ):
        """
        Inicializa el BatchOrchestrator.

        Args:
            aws_client: Cliente para AWS Transfer Family
            throttle_controller: Controlador de throttling
            session_manager: Gestor de sesiones
            max_concurrent_batches: Máximo número de lotes concurrentes

        Raises:
            ValidationError: Si los parámetros son inválidos
        """
        if not aws_client:
            raise ValidationError(
                "aws_client es requerido",
                error_code="MISSING_AWS_CLIENT"
            )

        if not throttle_controller:
            raise ValidationError(
                "throttle_controller es requerido",
                error_code="MISSING_THROTTLE_CONTROLLER"
            )

        if not session_manager:
            raise ValidationError(
                "session_manager es requerido",
                error_code="MISSING_SESSION_MANAGER"
            )

        if max_concurrent_batches <= 0:
            raise ValidationError(
                "max_concurrent_batches debe ser mayor que 0",
                error_code="INVALID_MAX_CONCURRENT_BATCHES"
            )

        self.aws_client = aws_client
        self.throttle_controller = throttle_controller
        self.session_manager = session_manager
        self.max_concurrent_batches = max_concurrent_batches

    def create_batches(
        self,
        files: List[FileTransferRequest],
        transfer_type: TransferType,
        connector_id: str,
        batch_size: int = 10
    ) -> List[Batch]:
        """
        Divide una lista de archivos en lotes de tamaño máximo especificado.

        Args:
            files: Lista de archivos a dividir en lotes
            transfer_type: Tipo de transferencia (upload/download)
            connector_id: ID del conector AWS Transfer Family
            batch_size: Tamaño máximo del lote (default: 10)

        Returns:
            Lista de lotes creados

        Raises:
            ValidationError: Si los parámetros son inválidos
        """
        if not files:
            raise ValidationError(
                "La lista de archivos no puede estar vacía",
                error_code="EMPTY_FILES_LIST"
            )

        if batch_size <= 0 or batch_size > 10:
            raise ValidationError(
                "batch_size debe estar entre 1 y 10",
                error_code="INVALID_BATCH_SIZE"
            )

        if not connector_id:
            raise ValidationError(
                "connector_id es requerido",
                error_code="MISSING_CONNECTOR_ID"
            )

        batches = []
        current_time = time.time()

        # Dividir archivos en lotes
        for i in range(0, len(files), batch_size):
            batch_files = files[i:i + batch_size]

            batch = Batch(
                batch_id=str(uuid.uuid4()),
                files=batch_files,
                transfer_type=transfer_type,
                connector_id=connector_id,
                created_at=current_time
            )

            batches.append(batch)

        logger.info(
            "Created %d batches from %d files",
            len(batches), len(files),
            extra={
                "total_files": len(files),
                "total_batches": len(batches),
                "batch_size": batch_size,
                "transfer_type": transfer_type.value
            }
        )

        return batches

    def execute_batches(self, batches: List[Batch]) -> List[BatchResult]:
        """
        Ejecuta una lista de lotes coordinando throttling y sesiones.

        Args:
            batches: Lista de lotes a ejecutar

        Returns:
            Lista de resultados de lotes

        Raises:
            TransferError: Si hay errores durante la ejecución
        """
        if not batches:
            return []

        logger.info(
            "Starting execution of %d batches",
            len(batches),
            extra={"batch_count": len(batches)}
        )

        results = []

        # Determinar el número de workers basado en sesiones disponibles
        max_workers = min(
            self.max_concurrent_batches,
            self.session_manager.max_sessions,
            len(batches)
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Enviar todos los lotes para ejecución
            future_to_batch = {
                executor.submit(self._execute_single_batch, batch): batch
                for batch in batches
            }

            # Recopilar resultados conforme se completan
            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]

                try:
                    result = future.result()
                    results.append(result)

                    logger.info(
                        "Batch %s completed with status %s",
                        batch.batch_id, result.status.value,
                        extra={
                            "batch_id": batch.batch_id,
                            "status": result.status.value,
                            "transfer_id": result.transfer_id
                        }
                    )

                except (TransferError, ValidationError) as e:
                    logger.error(
                        "Batch %s failed with transfer/validation error: %s",
                        batch.batch_id, e,
                        extra={"batch_id": batch.batch_id, "error": str(e)}
                    )

                    # Crear resultado de error
                    error_result = BatchResult(
                        batch_id=batch.batch_id,
                        transfer_id=None,
                        status=TransferStatus.FAILED,
                        file_results=[
                            FileTransferResult(
                                file_path=f.source_path,
                                status=FileStatus.FAILED,
                                error_message=str(e)
                            )
                            for f in batch.files
                        ],
                        # datetime fields removed
                        error_message=str(e)
                    )
                    results.append(error_result)
                except Exception as e:
                    logger.error(
                        "Batch %s failed with unexpected error: %s",
                        batch.batch_id, e,
                        extra={"batch_id": batch.batch_id, "error": str(e), "error_type": type(e).__name__}
                    )

                    # Crear resultado de error para errores inesperados
                    error_result = BatchResult(
                        batch_id=batch.batch_id,
                        transfer_id=None,
                        status=TransferStatus.FAILED,
                        file_results=[
                            FileTransferResult(
                                file_path=f.source_path,
                                status=FileStatus.FAILED,
                                error_message=f"Unexpected error: {str(e)}"
                            )
                            for f in batch.files
                        ],
                        error_message=f"Unexpected error: {str(e)}"
                    )
                    results.append(error_result)

        logger.info(
            "Completed execution of %d batches",
            len(batches),
            extra={
                "total_batches": len(batches),
                "successful_batches": len([r for r in results if r.status == TransferStatus.COMPLETED]),
                "failed_batches": len([r for r in results if r.status == TransferStatus.FAILED])
            }
        )

        return results

    def _execute_single_batch(self, batch: Batch) -> BatchResult:
        """
        Ejecuta un lote individual coordinando todos los componentes.

        Args:
            batch: Lote a ejecutar

        Returns:
            Resultado del lote

        Raises:
            TransferError: Si hay errores durante la ejecución
        """
        # started_at removed
        session = None

        try:
            logger.debug(
                "Starting execution of batch %s",
                batch.batch_id,
                extra={
                    "batch_id": batch.batch_id,
                    "file_count": len(batch.files),
                    "transfer_type": batch.transfer_type.value
                }
            )

            # 1. Aplicar throttling
            self.throttle_controller.wait_if_needed(len(batch.files))

            # 2. Adquirir sesión
            session = self.session_manager.acquire_session(timeout=30.0)

            # 3. Preparar solicitud para AWS Transfer Family
            aws_request = self._prepare_aws_request(batch)



            # 4. Ejecutar transferencia
            response = self.aws_client.start_file_transfer(aws_request)
            transfer_id = response.get("TransferId")  # Este es el TransferId único del lote

            if not transfer_id:
                logger.error(
                    "AWS Transfer Family did not return TransferId for batch %s",
                    batch.batch_id,
                    extra={
                        "batch_id": batch.batch_id,
                        "aws_response": response,
                        "aws_request": aws_request
                    }
                )
                raise TransferError(
                    "AWS Transfer Family did not return a TransferId",
                    error_code="MISSING_TRANSFER_ID",
                    context={"aws_response": response}
                )



            # 5. Crear resultados iniciales
            # Todos los archivos del lote comparten el mismo TransferId
            file_results = [
                FileTransferResult(
                    file_path=f.source_path,
                    status=FileStatus.TRANSFERRING,
                    transfer_id=None  # Los archivos individuales no tienen transfer_id propio
                )
                for f in batch.files
            ]

            result = BatchResult(
                batch_id=batch.batch_id,
                transfer_id=transfer_id,
                status=TransferStatus.COMPLETED,  # Marcamos como completado ya que AWS Transfer Family se encarga del resto
                file_results=file_results,
                session_id=session.session_id if session else None
            )

            logger.debug(
                "Batch %s started successfully",
                batch.batch_id,
                extra={
                    "batch_id": batch.batch_id,
                    "transfer_id": transfer_id,
                    "session_id": session.session_id if session else None
                }
            )

            return result

        except (TransferError, ValidationError) as e:
            logger.error(
                "Error executing batch %s: %s",
                batch.batch_id, e,
                extra={"batch_id": batch.batch_id, "error": str(e), "error_code": getattr(e, 'error_code', None)}
            )

            # Crear resultado de error
            file_results = [
                FileTransferResult(
                    file_path=f.source_path,
                    status=FileStatus.FAILED,
                    error_message=str(e)
                )
                for f in batch.files
            ]

            return BatchResult(
                batch_id=batch.batch_id,
                transfer_id=None,
                status=TransferStatus.FAILED,
                file_results=file_results,
                error_message=str(e),
                session_id=session.session_id if session else None
            )

        except Exception as e:
            logger.error(
                "Unexpected error executing batch %s: %s",
                batch.batch_id, e,
                extra={"batch_id": batch.batch_id, "error": str(e), "error_type": type(e).__name__}
            )

            # Crear resultado de error para errores inesperados
            file_results = [
                FileTransferResult(
                    file_path=f.source_path,
                    status=FileStatus.FAILED,
                    error_message=f"Unexpected error: {str(e)}"
                )
                for f in batch.files
            ]

            return BatchResult(
                batch_id=batch.batch_id,
                transfer_id=None,
                status=TransferStatus.FAILED,
                file_results=file_results,
                error_message=f"Unexpected error: {str(e)}",
                session_id=session.session_id if session else None
            )

        finally:
            # Liberar sesión
            if session:
                try:
                    self.session_manager.release_session(session)
                except (TransferError, ValidationError, RuntimeError) as e:
                    logger.warning(
                        "Error releasing session %s: %s",
                        session.session_id, e,
                        extra={"session_id": session.session_id, "error": str(e)}
                    )
                except Exception as e:
                    logger.warning(
                        "Unexpected error releasing session %s: %s",
                        session.session_id, e,
                        extra={"session_id": session.session_id, "error": str(e), "error_type": type(e).__name__}
                    )

    def _prepare_aws_request(self, batch: Batch) -> Dict[str, Any]:
        """
        Prepara la solicitud para AWS Transfer Family API.

        Según la documentación de boto3, los parámetros correctos son:
        - SendFilePaths: Lista de strings (rutas S3 para upload)
        - RetrieveFilePaths: Lista de strings (rutas SFTP para download)
        - LocalDirectoryPath: Directorio local para inbound transfers
        - RemoteDirectoryPath: Directorio remoto para outbound transfers

        Ejemplo de request generado para upload:
        {
            "ConnectorId": "c-1234567890abcdef0",
            "SendFilePaths": [
                "/co-delfos-sandbox-input-634614730521-dev/file_ferry/to_transfer/file1.txt",
                "/co-delfos-sandbox-input-634614730521-dev/file_ferry/to_transfer/file2.txt"
            ],
            "RemoteDirectoryPath": "/file_ferry_test"
        }

        Ejemplo de request generado para download:
        {
            "ConnectorId": "c-1234567890abcdef0",
            "RetrieveFilePaths": [
                "/remote/source/file1.txt",
                "/remote/source/file2.txt"
            ],
            "LocalDirectoryPath": "/co-delfos-sandbox-input-634614730521-dev/downloads"
        }

        Args:
            batch: Lote a procesar

        Returns:
            Diccionario con parámetros para la API

        Raises:
            ValidationError: Si el lote es inválido
        """
        if not batch.files:
            raise ValidationError(
                "El lote no puede estar vacío",
                error_code="EMPTY_BATCH"
            )

        request = {
            "ConnectorId": batch.connector_id
        }

        if batch.transfer_type == TransferType.UPLOAD:
            # Para uploads: S3 -> SFTP
            # SendFilePaths: Lista de strings con rutas S3
            request["SendFilePaths"] = [f.source_path for f in batch.files]

            # RemoteDirectoryPath: Extraer directorio común de destino
            remote_dir = self._extract_common_directory([f.destination_path for f in batch.files])
            if remote_dir:
                request["RemoteDirectoryPath"] = remote_dir

        elif batch.transfer_type == TransferType.DOWNLOAD:
            # Para downloads: SFTP -> S3
            # RetrieveFilePaths: Lista de strings con rutas SFTP
            request["RetrieveFilePaths"] = [f.source_path for f in batch.files]

            # LocalDirectoryPath: Extraer directorio común de destino S3
            local_dir = self._extract_common_directory([f.destination_path for f in batch.files])
            if local_dir:
                request["LocalDirectoryPath"] = local_dir

        else:
            raise ValidationError(
                f"Tipo de transferencia no soportado: {batch.transfer_type}",
                error_code="UNSUPPORTED_TRANSFER_TYPE"
            )

        return request

    def _extract_common_directory(self, file_paths: List[str]) -> Optional[str]:
        """
        Extrae el directorio común de una lista de rutas de archivos.

        Args:
            file_paths: Lista de rutas de archivos

        Returns:
            Directorio común o None si no hay uno claro
        """
        if not file_paths:
            return None

        # Para un solo archivo, extraer su directorio
        if len(file_paths) == 1:
            path = file_paths[0]
            # Remover el nombre del archivo para obtener el directorio
            if '/' in path:
                directory = '/'.join(path.split('/')[:-1])
                # Asegurar que el directorio no esté vacío
                return directory if directory else None
            return None

        # Para múltiples archivos, encontrar el prefijo común
        common_parts = []
        first_path_parts = file_paths[0].split('/')[:-1]  # Excluir nombre de archivo

        for i, part in enumerate(first_path_parts):
            # Verificar si esta parte es común en todas las rutas
            if all(
                len(path.split('/')) > i and path.split('/')[i] == part
                for path in file_paths
            ):
                common_parts.append(part)
            else:
                break

        if common_parts:
            result = '/'.join(common_parts)
            # Asegurar que no devolvamos una cadena vacía
            return result if result else None
        return None

    def execute_remote_delete(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ejecuta una operación de eliminación remota usando AWS Transfer Family.

        Args:
            request: Diccionario con parámetros de eliminación incluyendo:
                - ConnectorId: ID del conector AWS Transfer Family
                - DeletePath: Ruta del archivo o directorio a eliminar

        Returns:
            Dict[str, Any]: Respuesta de la API con DeleteId y otros metadatos

        Raises:
            ValidationError: Si los parámetros son inválidos
            TransferError: Si hay errores durante la eliminación
        """
        logger.info(
            "Starting remote delete operation for path: %s",
            request.get('DeletePath'),
            extra={
                "connector_id": request.get("ConnectorId"),
                "delete_path": request.get("DeletePath")
            }
        )

        session = None

        try:
            # 1. Validar solicitud
            self._validate_delete_request(request)

            # 2. Aplicar throttling para una operación (siempre 1)
            self.throttle_controller.wait_if_needed(1)

            # 3. Adquirir sesión
            session = self.session_manager.acquire_session(timeout=30.0)

            # 4. Ejecutar eliminación usando AWS Transfer Family
            response = self.aws_client.start_remote_delete(request)

            logger.info(
                "Remote delete operation started successfully",
                extra={
                    "delete_id": response.get("DeleteId"),
                    "connector_id": request.get("ConnectorId"),
                    "delete_path": request.get("DeletePath"),
                    "session_id": session.session_id if session else None
                }
            )

            return response

        except (TransferError, ValidationError) as e:
            logger.error("Remote delete operation failed: %s", e)
            raise
        except Exception as e:
            logger.error("Unexpected error in remote delete operation: %s", e, extra={"error_type": type(e).__name__})
            raise TransferError(
                f"Unexpected error during remote delete: {str(e)}",
                error_code="UNEXPECTED_DELETE_ERROR"
            ) from e

        finally:
            # Liberar sesión
            if session:
                try:
                    self.session_manager.release_session(session)
                except (TransferError, ValidationError, RuntimeError) as e:
                    logger.warning(
                        "Error releasing session %s in delete operation: %s",
                        session.session_id, e,
                        extra={"session_id": session.session_id, "error": str(e)}
                    )
                except Exception as e:
                    logger.warning(
                        "Unexpected error releasing session %s in delete operation: %s",
                        session.session_id, e,
                        extra={"session_id": session.session_id, "error": str(e), "error_type": type(e).__name__}
                    )

    def execute_directory_listing(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ejecuta una operación de listado de directorio usando AWS Transfer Family.

        Args:
            request: Diccionario con parámetros de listado incluyendo:
                - ConnectorId: ID del conector AWS Transfer Family
                - RemoteDirectoryPath: Ruta del directorio a listar
                - MaxItems: (Opcional) Número máximo de elementos a listar
                - OutputDirectoryPath: (Opcional) Ruta donde guardar el resultado

        Returns:
            Dict[str, Any]: Respuesta de la API con ListingId y OutputFileName

        Raises:
            ValidationError: Si los parámetros son inválidos
            TransferError: Si hay errores durante el listado
        """
        logger.info(
            "Starting directory listing operation for path: %s",
            request.get('RemoteDirectoryPath'),
            extra={
                "connector_id": request.get("ConnectorId"),
                "remote_directory_path": request.get("RemoteDirectoryPath"),
                "max_items": request.get("MaxItems"),
                "output_directory_path": request.get("OutputDirectoryPath")
            }
        )

        session = None

        try:
            # 1. Validar solicitud
            self._validate_listing_request(request)

            # 2. Aplicar throttling para una operación (siempre 1)
            self.throttle_controller.wait_if_needed(1)

            # 3. Adquirir sesión
            session = self.session_manager.acquire_session(timeout=30.0)

            # 4. Ejecutar listado usando AWS Transfer Family
            response = self.aws_client.start_directory_listing(request)

            logger.info(
                "Directory listing operation started successfully",
                extra={
                    "listing_id": response.get("ListingId"),
                    "output_file_name": response.get("OutputFileName"),
                    "connector_id": request.get("ConnectorId"),
                    "remote_directory_path": request.get("RemoteDirectoryPath"),
                    "session_id": session.session_id if session else None
                }
            )

            return response

        except (TransferError, ValidationError) as e:
            logger.error("Directory listing operation failed: %s", e)
            raise
        except Exception as e:
            logger.error("Unexpected error in directory listing operation: %s", e, extra={"error_type": type(e).__name__})
            raise TransferError(
                f"Unexpected error during directory listing: {str(e)}",
                error_code="UNEXPECTED_LISTING_ERROR"
            ) from e

        finally:
            # Liberar sesión
            if session:
                try:
                    self.session_manager.release_session(session)
                except (TransferError, ValidationError, RuntimeError) as e:
                    logger.warning(
                        "Error releasing session %s in listing operation: %s",
                        session.session_id, e,
                        extra={"session_id": session.session_id, "error": str(e)}
                    )
                except Exception as e:
                    logger.warning(
                        "Unexpected error releasing session %s in listing operation: %s",
                        session.session_id, e,
                        extra={"session_id": session.session_id, "error": str(e), "error_type": type(e).__name__}
                    )

    def _validate_delete_request(self, request: Dict[str, Any]) -> None:
        """
        Valida una solicitud de eliminación remota.

        Args:
            request: Diccionario con parámetros de eliminación

        Raises:
            ValidationError: Si la solicitud es inválida
        """
        if not isinstance(request, dict):
            raise ValidationError(
                "Delete request must be a dictionary",
                error_code="INVALID_REQUEST_TYPE"
            )

        if not request.get("ConnectorId"):
            raise ValidationError(
                "ConnectorId is required",
                error_code="MISSING_CONNECTOR_ID"
            )

        delete_path = request.get("DeletePath")

        if not delete_path:
            raise ValidationError(
                "DeletePath must be provided and cannot be empty",
                error_code="NO_DELETE_PATH_SPECIFIED"
            )

        if not isinstance(delete_path, str):
            raise ValidationError(
                "DeletePath must be a string",
                error_code="INVALID_DELETE_PATH_TYPE"
            )

        if not delete_path.strip():
            raise ValidationError(
                "DeletePath must be a non-empty string",
                error_code="EMPTY_DELETE_PATH"
            )

    def _validate_listing_request(self, request: Dict[str, Any]) -> None:
        """
        Valida una solicitud de listado de directorio.

        Args:
            request: Diccionario con parámetros de listado

        Raises:
            ValidationError: Si la solicitud es inválida
        """
        if not isinstance(request, dict):
            raise ValidationError(
                "Listing request must be a dictionary",
                error_code="INVALID_REQUEST_TYPE"
            )

        if not request.get("ConnectorId"):
            raise ValidationError(
                "ConnectorId is required",
                error_code="MISSING_CONNECTOR_ID"
            )

        remote_directory_path = request.get("RemoteDirectoryPath")

        if not remote_directory_path:
            raise ValidationError(
                "RemoteDirectoryPath must be provided and cannot be empty",
                error_code="NO_REMOTE_DIRECTORY_PATH_SPECIFIED"
            )

        if not isinstance(remote_directory_path, str):
            raise ValidationError(
                "RemoteDirectoryPath must be a string",
                error_code="INVALID_REMOTE_DIRECTORY_PATH_TYPE"
            )

        if not remote_directory_path.strip():
            raise ValidationError(
                "RemoteDirectoryPath must be a non-empty string",
                error_code="EMPTY_REMOTE_DIRECTORY_PATH"
            )

        # Validar MaxItems si está presente
        max_items = request.get("MaxItems")
        if max_items is not None:
            if not isinstance(max_items, int):
                raise ValidationError(
                    "MaxItems must be an integer",
                    error_code="INVALID_MAX_ITEMS_TYPE"
                )

            if max_items < 0:
                raise ValidationError(
                    "MaxItems must be non-negative",
                    error_code="INVALID_MAX_ITEMS_VALUE"
                )

        # Validar OutputDirectoryPath si está presente
        output_directory_path = request.get("OutputDirectoryPath")
        if output_directory_path is not None:
            if not isinstance(output_directory_path, str):
                raise ValidationError(
                    "OutputDirectoryPath must be a string",
                    error_code="INVALID_OUTPUT_DIRECTORY_PATH_TYPE"
                )

            if not output_directory_path.strip():
                raise ValidationError(
                    "OutputDirectoryPath must be a non-empty string if provided",
                    error_code="EMPTY_OUTPUT_DIRECTORY_PATH"
                )

    def get_orchestrator_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas del orquestador.

        Returns:
            Diccionario con estadísticas actuales
        """
        return {
            "throttle_controller": {
                "current_rate": self.throttle_controller.get_current_rate(),
                "remaining_capacity": self.throttle_controller.get_remaining_capacity()
            },
            "session_manager": {
                "active_sessions": self.session_manager.get_active_sessions(),
                "available_sessions": self.session_manager.get_available_sessions(),
                "total_sessions": self.session_manager.get_total_sessions(),
                "max_sessions": self.session_manager.max_sessions
            },
            "orchestrator": {
                "max_concurrent_batches": self.max_concurrent_batches
            }
        }
