"""
Main TransferManager class - API entry point for the library.

Este módulo implementa la fachada principal de la librería S3-SFTP Transfer,
proporcionando una interfaz simple y unificada para todas las operaciones
de transferencia de archivos.
"""

import logging
from typing import List, Dict, Any, Optional

from src.config.config_manager import ConfigManager

from src.services.upload_service import UploadService
from src.services.download_service import DownloadService
from src.services.listing_service import ListingService
from src.services.monitoring_service import MonitoringService
from src.services.delete_service import DeleteService

from src.orchestration.batch_orchestrator import BatchOrchestrator
from src.orchestration.throttle_controller import ThrottleController
from src.orchestration.session_manager import SessionManager

from src.clients.aws_transfer_client import AWSTransferClient

from src.models.transfer_models import (
    FileTransferRequest,
    TransferRequest,
    TransferResult,
    TransferType,
    FileDeleteRequest,
    DeleteResult
)
from src.exceptions.transfer_exceptions import (
    TransferLibraryError,
    ConfigurationError,
    ValidationError
)
from src.utils.instance_manager import InstanceManager


logger = logging.getLogger(__name__)


class TransferManager:
    """
    Punto de entrada principal para todas las operaciones de transferencia.

    Proporciona una interfaz simple que oculta la complejidad interna del
    manejo de lotes, polling y coordinación de servicios.
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        aws_transfer_client: Optional[AWSTransferClient] = None
    ):
        """
        Inicializa el TransferManager.

        Args:
            config_manager: Gestor de configuración (opcional, se crea uno por defecto)
            aws_transfer_client: Cliente AWS Transfer Family (opcional, se crea uno por defecto)

        Raises:
            ConfigurationError: Si hay problemas de configuración
            TransferLibraryError: Si hay errores de inicialización
        """
        try:
            # Inicializar gestión de instancias Lambda-safe
            self.instance_manager = InstanceManager()

            # Configuración
            self.config_manager = config_manager or ConfigManager()

            # Clientes AWS
            self.aws_transfer_client = aws_transfer_client or AWSTransferClient()

            # Componentes de orquestación
            self.throttle_controller = ThrottleController(
                max_files_per_second=self.config_manager.get_throughput_limit()
            )
            self.session_manager = SessionManager(
                connector_id=self.config_manager.get_connector_id(),
                max_sessions=self.config_manager.get_max_concurrent_sessions()
            )
            self.batch_orchestrator = BatchOrchestrator(
                throttle_controller=self.throttle_controller,
                session_manager=self.session_manager,
                aws_client=self.aws_transfer_client
            )

            # Servicios de transferencia
            self.upload_service = UploadService(
                batch_orchestrator=self.batch_orchestrator
            )
            self.download_service = DownloadService(
                batch_orchestrator=self.batch_orchestrator
            )
            self.listing_service = ListingService(
                aws_client=self.aws_transfer_client
            )
            self.monitoring_service = MonitoringService(
                aws_client=self.aws_transfer_client
            )
            self.delete_service = DeleteService(
                batch_orchestrator=self.batch_orchestrator
            )

            logger.info(
                "TransferManager initialized successfully",
                extra={
                    "instance_id": self.instance_manager.instance_id,
                    "connector_id": self.config_manager.get_connector_id(),
                    "throughput_limit": self.config_manager.get_throughput_limit(),
                    "max_sessions": self.config_manager.get_max_concurrent_sessions()
                }
            )

        except Exception as e:
            logger.error("Failed to initialize TransferManager: %s", e)
            raise TransferLibraryError(
                f"TransferManager initialization failed: {str(e)}",
                error_code="TRANSFER_MANAGER_INIT_FAILED",
                context={"original_error": str(e)}
            ) from e

    def upload_files_batch(
        self,
        files: List[str],
        connector_id: str,
        destination_path: str
    ) -> TransferResult:
        """
        Carga múltiples archivos de S3 a SFTP usando el formato del API boto3.

        Implementa el requerimiento 6.1: API simple que oculta complejidad de lotes.
        Formato similar al API start_file_transfer de boto3.

        Args:
            files: Lista de rutas S3 de archivos a cargar (SendFilePaths)
            connector_id: ID del conector (ConnectorId)
            destination_path: Ruta de destino en el servidor SFTP (RemoteDirectoryPath)

        Returns:
            TransferResult: Resultado de la operación con estado y detalles

        Raises:
            ValidationError: Si los parámetros son inválidos
            ConfigurationError: Si hay problemas de configuración
            TransferLibraryError: Si ocurre un error durante la transferencia

        Example:
            ```python
            files = [
                "/co-delfos-sandbox-input-634614730521-dev/file_ferry/to_transfer/file1.txt",
                "/co-delfos-sandbox-input-634614730521-dev/file_ferry/to_transfer/file2.txt"
            ]

            result = transfer_manager.upload_files_batch(
                files=files,
                connector_id="c-6e6cb1ca1e174d669",
                destination_path="/file_ferry_test"
            )
            print(f"Transfer {result.transfer_id}: {result.status}")
            ```
        """
        logger.info(
            "Starting batch upload of %d files",
            len(files),
            extra={
                "file_count": len(files),
                "destination_path": destination_path,
                "instance_id": self.instance_manager.instance_id
            }
        )

        try:
            # Validar parámetros
            if not files or not isinstance(files, list):
                raise ValidationError(
                    "files must be a non-empty list of S3 paths",
                    error_code="INVALID_FILES_LIST"
                )

            if not connector_id:
                raise ValidationError(
                    "connector_id is required",
                    error_code="MISSING_CONNECTOR_ID"
                )

            if not destination_path:
                raise ValidationError(
                    "destination_path is required",
                    error_code="MISSING_DESTINATION_PATH"
                )

            # Usar el UploadService directamente con el nuevo método
            result = self.upload_service.execute_batch_transfer(files, connector_id, destination_path)

            logger.info(
                "Batch upload completed: %s",
                result.transfer_id,
                extra={
                    "transfer_id": result.transfer_id,
                    "status": result.status.value,
                    "file_count": len(result.file_results)
                }
            )

            return result

        except Exception as e:
            logger.error("Batch upload failed: %s", e)
            if isinstance(e, (ValidationError, ConfigurationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Batch upload operation failed: {str(e)}",
                error_code="BATCH_UPLOAD_FAILED",
                context={"file_count": len(files), "original_error": str(e)}
            ) from e

    def upload_files(
        self,
        files: List[FileTransferRequest],
        connector_id: str
    ) -> TransferResult:
        """
        Carga múltiples archivos de S3 a SFTP.

        Implementa el requerimiento 6.1: API simple que oculta complejidad de lotes.

        Args:
            files: Lista de archivos a cargar (S3 → SFTP)
            connector_id: ID del conector (requerido)

        Returns:
            TransferResult: Resultado de la operación con estado y detalles

        Raises:
            ValidationError: Si los parámetros son inválidos
            ConfigurationError: Si hay problemas de configuración
            TransferLibraryError: Si ocurre un error durante la transferencia

        Example:
            ```python
            files = [
                FileTransferRequest(
                    source_path="s3://my-bucket/file1.txt",
                    destination_path="/remote/path/file1.txt"
                ),
                FileTransferRequest(
                    source_path="s3://my-bucket/file2.txt",
                    destination_path="/remote/path/file2.txt"
                )
            ]

            result = transfer_manager.upload_files(files)
            print(f"Transfer {result.transfer_id}: {result.status}")
            ```
        """
        logger.info(
            "Starting upload of %d files",
            len(files),
            extra={
                "file_count": len(files),
                "instance_id": self.instance_manager.instance_id
            }
        )

        try:
            # Validar parámetros
            self._validate_file_list(files, "upload")

            # Validar que connector_id esté presente
            if not connector_id: # pragma: no cover
                raise ValidationError(
                    "connector_id is required",
                    error_code="MISSING_CONNECTOR_ID"
                )

            # Crear solicitud de transferencia
            transfer_request = TransferRequest(
                files=files,
                connector_id=connector_id,
                transfer_type=TransferType.UPLOAD
            )

            # Ejecutar transferencia usando UploadService
            result = self.upload_service.execute_transfer(transfer_request)

            logger.info(
                "Upload completed: %s",
                result.transfer_id,
                extra={
                    "transfer_id": result.transfer_id,
                    "status": result.status.value,
                    "file_count": len(result.file_results)
                }
            )

            return result

        except Exception as e:
            logger.error("Upload failed: %s", e)
            if isinstance(e, (ValidationError, ConfigurationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Upload operation failed: {str(e)}",
                error_code="UPLOAD_FAILED",
                context={"file_count": len(files), "original_error": str(e)}
            ) from e


    def download_files_batch(
        self,
        sftp_files: List[str],
        connector_id: str,
        s3_destination_path: str
    ) -> TransferResult:
        """
        Descarga múltiples archivos de SFTP a S3 usando el formato del API boto3.

        Implementa el requerimiento de download basado en AWS Transfer Family start_file_transfer
        con RetrieveFilePaths y LocalDirectoryPath según la documentación oficial.
        Formato similar al API start_file_transfer de boto3.

        Args:
            sftp_files: Lista de rutas SFTP de archivos a descargar (RetrieveFilePaths)
            connector_id: ID del conector (ConnectorId)
            s3_destination_path: Ruta de destino en S3 (LocalDirectoryPath)

        Returns:
            TransferResult: Resultado de la operación con estado y detalles

        Raises:
            ValidationError: Si los parámetros son inválidos
            ConfigurationError: Si hay problemas de configuración
            TransferLibraryError: Si ocurre un error durante la transferencia

        Example:
            ```python
            sftp_files = [
                "/remote/source/file1.txt",
                "/remote/source/file2.txt"
            ]

            result = transfer_manager.download_files_batch(
                sftp_files=sftp_files,
                connector_id="c-6e6cb1ca1e174d669",
                s3_destination_path="/co-delfos-sandbox-input-634614730521-dev/downloads"
            )
            print(f"Transfer {result.transfer_id}: {result.status}")
            ```
        """
        logger.info(
            "Starting batch download of %d files",
            len(sftp_files),
            extra={
                "file_count": len(sftp_files),
                "s3_destination_path": s3_destination_path,
                "instance_id": self.instance_manager.instance_id
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

            # Usar el DownloadService directamente con el nuevo método
            result = self.download_service.execute_batch_download(
                sftp_files, connector_id, s3_destination_path
            )

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
            if isinstance(e, (ValidationError, ConfigurationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Batch download operation failed: {str(e)}",
                error_code="BATCH_DOWNLOAD_FAILED",
                context={"file_count": len(sftp_files), "original_error": str(e)}
            ) from e

    def list_directory(
        self,
        sftp_path: str,
        connector_id: str,
        max_items: Optional[int] = None,
        output_directory_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Lista el contenido de un directorio SFTP.

        Implementa el requerimiento 6.1: API simple para operaciones de directorio.

        Args:
            sftp_path: Ruta del directorio SFTP a listar
            connector_id: ID del conector (requerido)
            max_items: Número máximo de elementos a retornar (opcional)
            output_directory_path: Ruta donde guardar el archivo de salida (opcional)

        Returns:
            Dict[str, Any]: Información del listado con listing_id y output_filename

        Raises:
            ValidationError: Si los parámetros son inválidos
            ConfigurationError: Si hay problemas de configuración
            TransferLibraryError: Si ocurre un error durante el listado

        Example:
            ```python
            listing_info = transfer_manager.list_directory("/remote/directory")
            print(f"Listing ID: {listing_info['listing_id']}")
            print(f"Results saved to: {listing_info['output_filename']}")
            # Los resultados del listado están en el archivo S3 especificado
            ```
        """
        logger.info(
            "Listing directory: %s",
            sftp_path,
            extra={
                "sftp_path": sftp_path,
                "max_items": max_items,
                "output_directory_path": output_directory_path,
                "instance_id": self.instance_manager.instance_id
            }
        )

        try:
            # Validar parámetros
            if not sftp_path or not isinstance(sftp_path, str):
                raise ValidationError(
                    "sftp_path must be a non-empty string",
                    error_code="INVALID_SFTP_PATH"
                )

            # Validar que connector_id esté presente
            if not connector_id: # pragma: no cover
                raise ValidationError(
                    "connector_id is required",
                    error_code="MISSING_CONNECTOR_ID"
                )

            # Ejecutar listado usando ListingService
            listing = self.listing_service.list_directory(
                sftp_path=sftp_path,
                connector_id=connector_id,
                max_items=max_items,
                output_directory_path=output_directory_path
            )

            logger.info(
                "Directory listing completed and save in file: %s",
                listing.output_filename,
                extra={
                    "sftp_path": sftp_path,
                    "output_filename": listing.output_filename
                }
            )

            # Return the DirectoryListing object directly
            return listing

        except Exception as e:
            logger.error("Directory listing failed: %s", e)
            if isinstance(e, (ValidationError, ConfigurationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Directory listing failed: {str(e)}",
                error_code="DIRECTORY_LISTING_FAILED",
                context={"sftp_path": sftp_path, "original_error": str(e)}
            ) from e

    def get_transfer_status(self, transfer_id: str) -> Dict[str, Any]:
        """
        Obtiene el estado de una transferencia.

        Implementa el requerimiento 6.1: API simple para monitoreo de transferencias.

        Args:
            transfer_id: ID de la transferencia a consultar

        Returns:
            Dict[str, Any]: Estado de la transferencia con detalles

        Raises:
            ValidationError: Si el transfer_id es inválido
            TransferLibraryError: Si ocurre un error consultando el estado

        Example:
            ```python
            status = transfer_manager.get_transfer_status("execution-id-123")
            print(f"Status: {status['status']}")
            print(f"Progress: {status['completed_files']}/{status['total_files']}")

            for file_status in status['file_statuses']:
                print(f"  {file_status['file_path']}: {file_status['status']}")
            ```
        """
        logger.debug(
            "Getting transfer status: %s",
            transfer_id,
            extra={"transfer_id": transfer_id}
        )

        try:
            # Validar parámetros
            if not transfer_id or not isinstance(transfer_id, str):
                raise ValidationError(
                    "transfer_id must be a non-empty string",
                    error_code="INVALID_TRANSFER_ID"
                )

            # Obtener connector_id de la configuración
            connector_id = self.config_manager.get_connector_id()

            # Obtener estado usando MonitoringService
            status = self.monitoring_service.get_transfer_status(transfer_id, connector_id)

            logger.debug(
                "Transfer status retrieved: %s",
                status.get('status'),
                extra={
                    "transfer_id": transfer_id,
                    "status": status.get('status'),
                    "total_files": status.get('total_files', 0)
                }
            )

            return status

        except Exception as e:
            logger.error("Failed to get transfer status: %s", e)
            if isinstance(e, (ValidationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Failed to get transfer status: {str(e)}",
                error_code="STATUS_QUERY_FAILED",
                context={"transfer_id": transfer_id, "original_error": str(e)}
            ) from e

    def get_multiple_transfer_status(
        self,
        transfer_ids: List[str],
        connector_id: str
    ) -> Dict[str, Any]:
        """
        Obtiene el estado de múltiples transferencias.

        Args:
            transfer_ids: Lista de IDs de transferencias a consultar
            connector_id: ID del conector (requerido)

        Returns:
            Dict[str, Any]: Estado consolidado de las transferencias

        Raises:
            ValidationError: Si los parámetros son inválidos
            TransferLibraryError: Si ocurre un error consultando el estado

        Example:
            ```python
            transfer_ids = ["execution-id-123", "execution-id-456"]
            status = transfer_manager.get_multiple_transfer_status(transfer_ids, connector_id)
            print(f"Consulted {len(status['data'])} transfers")

            for transfer_status in status['data']:
                print(f"Transfer {transfer_status['transfer_id']}: {transfer_status['overall_status']}")
            ```
        """
        logger.debug(
            "Getting status for %d transfers",
            len(transfer_ids),
            extra={"transfer_ids": transfer_ids, "connector_id": connector_id}
        )

        try:
            # Validar parámetros
            if not transfer_ids or not isinstance(transfer_ids, list):
                raise ValidationError(
                    "transfer_ids must be a non-empty list of strings",
                    error_code="INVALID_TRANSFER_IDS"
                )

            if not connector_id:
                raise ValidationError(
                    "connector_id is required",
                    error_code="MISSING_CONNECTOR_ID"
                )

            # Validar cada transfer_id
            for i, transfer_id in enumerate(transfer_ids):
                if not transfer_id or not isinstance(transfer_id, str):
                    raise ValidationError(
                        f"transfer_id at index {i} must be a non-empty string",
                        error_code="INVALID_TRANSFER_ID",
                        context={"index": i, "transfer_id": transfer_id}
                    )

            # Obtener estado usando MonitoringService
            status = self.monitoring_service.get_multiple_transfer_status(
                transfer_ids=transfer_ids,
                connector_id=connector_id
            )

            logger.debug(
                "Multiple transfer status retrieved successfully",
                extra={
                    "transfer_count": len(transfer_ids),
                    "successful_queries": len([r for r in status['data'] if r.get("overall_status") != "ERROR"])
                }
            )

            return status

        except Exception as e:
            logger.error("Failed to get multiple transfer status: %s", e)
            if isinstance(e, (ValidationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Failed to get multiple transfer status: {str(e)}",
                error_code="MULTIPLE_STATUS_QUERY_FAILED",
                context={"transfer_ids": transfer_ids, "connector_id": connector_id, "original_error": str(e)}
            ) from e

    def wait_for_completion(
        self,
        transfer_id: str,
        timeout: Optional[int] = None,
        poll_interval: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Espera hasta que una transferencia se complete o falle.

        Método de conveniencia que combina polling con get_transfer_status.

        Args:
            transfer_id: ID de la transferencia a monitorear
            timeout: Timeout en segundos (opcional, usa default del servicio)
            poll_interval: Intervalo de polling en segundos (opcional)

        Returns:
            Dict[str, Any]: Estado final de la transferencia

        Raises:
            ValidationError: Si los parámetros son inválidos
            TimeoutError: Si se agota el timeout
            TransferLibraryError: Si ocurre un error durante el polling

        Example:
            ```python
            # Iniciar transferencia
            result = transfer_manager.upload_files(files)

            # Esperar a que complete
            final_status = transfer_manager.wait_for_completion(result.transfer_id)
            print(f"Final status: {final_status['status']}")
            ```
        """
        logger.info(
            "Waiting for transfer completion: %s",
            transfer_id,
            extra={
                "transfer_id": transfer_id,
                "timeout": timeout,
                "poll_interval": poll_interval
            }
        )

        try:
            # Obtener connector_id de la configuración
            connector_id = self.config_manager.get_connector_id()

            # Usar MonitoringService para polling
            final_status = self.monitoring_service.poll_until_complete(
                transfer_id=transfer_id,
                connector_id=connector_id,
                timeout=timeout,
                poll_interval=poll_interval
            )

            logger.info(
                "Transfer completed: %s",
                transfer_id,
                extra={
                    "transfer_id": transfer_id,
                    "final_status": final_status.get('status')
                }
            )

            return final_status

        except Exception as e:
            logger.error("Failed waiting for completion: %s", e)
            if isinstance(e, (ValidationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Failed waiting for transfer completion: {str(e)}",
                error_code="WAIT_FOR_COMPLETION_FAILED",
                context={"transfer_id": transfer_id, "original_error": str(e)}
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
            ConfigurationError: Si hay problemas de configuración
            TransferLibraryError: Si ocurre un error durante la eliminación

        Example:
            ```python
            delete_paths = [
                "/remote/path/file1.txt",
                "/remote/path/file2.txt"
            ]

            result = transfer_manager.delete_files_batch(
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
                "instance_id": self.instance_manager.instance_id
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

            # Ejecutar eliminación usando DeleteService
            result = self.delete_service.delete_files_batch(delete_paths, connector_id)

            logger.info(
                "Batch deletion completed: %s",
                result.execution_id,
                extra={
                    "execution_id": result.execution_id,
                    "status": result.status.value,
                    "file_count": len(result.file_results)
                }
            )

            return result

        except Exception as e:
            logger.error("Batch deletion failed: %s", e)
            if isinstance(e, (ValidationError, ConfigurationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Batch deletion operation failed: {str(e)}",
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

        Implementa el requerimiento 6.1: API simple que oculta complejidad de lotes.

        Args:
            files: Lista de archivos a eliminar del servidor SFTP
            connector_id: ID del conector (requerido)

        Returns:
            DeleteResult: Resultado de la operación con estado y detalles

        Raises:
            ValidationError: Si los parámetros son inválidos
            ConfigurationError: Si hay problemas de configuración
            TransferLibraryError: Si ocurre un error durante la eliminación

        Example:
            ```python
            files = [
                FileDeleteRequest(file_path="/remote/path/file1.txt"),
                FileDeleteRequest(file_path="/remote/path/file2.txt")
            ]

            result = transfer_manager.delete_files(files)
            print(f"Delete operation {result.transfer_id}: {result.status}")
            ```
        """
        logger.info(
            "Starting deletion of %d files",
            len(files),
            extra={
                "file_count": len(files),
                "instance_id": self.instance_manager.instance_id
            }
        )

        try:
            # Validar parámetros
            self._validate_delete_file_list(files)

            # Validar que connector_id esté presente
            if not connector_id:
                raise ValidationError(
                    "connector_id is required",
                    error_code="MISSING_CONNECTOR_ID"
                )

            # Ejecutar eliminación usando DeleteService
            result = self.delete_service.delete_files(files, connector_id)

            logger.info(
                "Delete operation completed",
                extra={
                    #"transfer_id": result.delete_id,
                    "status": result.status.value,
                    "file_count": len(result.file_results)
                }
            )

            return result

        except Exception as e:
            logger.error("Delete operation failed: %s", e)
            if isinstance(e, (ValidationError, ConfigurationError, TransferLibraryError)):
                raise
            raise TransferLibraryError(
                f"Delete operation failed: {str(e)}",
                error_code="DELETE_FAILED",
                context={"file_count": len(files), "original_error": str(e)}
            ) from e

    def get_configuration(self) -> Dict[str, Any]:
        """
        Obtiene la configuración actual del TransferManager.

        Útil para debugging y verificación de configuración.

        Returns:
            Dict[str, Any]: Configuración actual (sin valores sensibles)

        Example:
            ```python
            config = transfer_manager.get_configuration()
            print(f"Connector ID: {config['connector_id']}")
            print(f"Throughput limit: {config['throughput_limit']}")
            ```
        """
        try:
            config = self.config_manager.get_all_config()
            config['instance_id'] = self.instance_manager.instance_id
            return config
        except Exception as e:
            logger.error("Failed to get configuration: %s", e)
            raise TransferLibraryError(
                f"Failed to get configuration: {str(e)}",
                error_code="CONFIG_RETRIEVAL_FAILED",
                context={"original_error": str(e)}
            ) from e

    def _validate_file_list(self, files: List[FileTransferRequest], operation: str) -> None:
        """
        Valida una lista de archivos para transferencia.

        Implementa el requerimiento 6.3: Mensajes de error claros y accionables.

        Args:
            files: Lista de archivos a validar
            operation: Tipo de operación ("upload" o "download")

        Raises:
            ValidationError: Si la lista de archivos es inválida
        """
        if not files:
            raise ValidationError(
                f"File list cannot be empty for {operation} operation",
                error_code="EMPTY_FILE_LIST",
                context={"operation": operation}
            )

        if not isinstance(files, list):
            raise ValidationError(
                "Files must be a list of FileTransferRequest objects",
                error_code="INVALID_FILE_LIST_TYPE",
                context={"operation": operation, "type": type(files).__name__}
            )

        # Validar cada archivo
        for i, file_req in enumerate(files):
            if not isinstance(file_req, FileTransferRequest):
                raise ValidationError(
                    f"File {i} must be a FileTransferRequest object",
                    error_code="INVALID_FILE_REQUEST_TYPE",
                    context={
                        "operation": operation,
                        "file_index": i,
                        "type": type(file_req).__name__
                    }
                )

            if not file_req.source_path:
                raise ValidationError(
                    f"Source path is required for file {i}",
                    error_code="MISSING_SOURCE_PATH",
                    context={"operation": operation, "file_index": i}
                )

            if not file_req.destination_path:
                raise ValidationError(
                    f"Destination path is required for file {i}",
                    error_code="MISSING_DESTINATION_PATH",
                    context={"operation": operation, "file_index": i}
                )

    def _validate_delete_file_list(self, files: List[FileDeleteRequest]) -> None:
        """
        Valida una lista de archivos para eliminación.

        Implementa el requerimiento 6.3: Mensajes de error claros y accionables.

        Args:
            files: Lista de archivos a validar

        Raises:
            ValidationError: Si la lista de archivos es inválida
        """
        if not files:
            raise ValidationError(
                "File list cannot be empty for delete operation",
                error_code="EMPTY_FILE_LIST",
                context={"operation": "delete"}
            )

        if not isinstance(files, list):
            raise ValidationError(
                "Files must be a list of FileDeleteRequest objects",
                error_code="INVALID_FILE_LIST_TYPE",
                context={"operation": "delete", "type": type(files).__name__}
            )

        # Validar cada archivo
        for i, file_req in enumerate(files):
            if not isinstance(file_req, FileDeleteRequest):
                raise ValidationError(
                    f"File {i} must be a FileDeleteRequest object",
                    error_code="INVALID_FILE_REQUEST_TYPE",
                    context={
                        "operation": "delete",
                        "file_index": i,
                        "type": type(file_req).__name__
                    }
                )

            if not file_req.file_path:
                raise ValidationError(
                    f"File path is required for file {i}",
                    error_code="MISSING_FILE_PATH",
                    context={"operation": "delete", "file_index": i}
                )

            # Validar que no sea una ruta de directorio
            if file_req.file_path.endswith('/'):
                raise ValidationError(
                    f"File path {i} appears to be a directory. Only files can be deleted.",
                    error_code="DIRECTORY_PATH_NOT_ALLOWED",
                    context={"operation": "delete", "file_index": i, "file_path": file_req.file_path}
                )

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources if needed."""
        # Currently no cleanup needed
        return None
