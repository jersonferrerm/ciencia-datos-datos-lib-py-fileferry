"""
AWS Transfer Family client implementation.

Este módulo implementa el cliente para interactuar con AWS Transfer Family,
proporcionando funcionalidades de transferencia de archivos y monitoreo de estado.
"""

import time
import logging
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError, BotoCoreError
import boto3

from src.services.interfaces import IAWSClient
from src.exceptions.transfer_exceptions import (
    TransferError,
    ConnectionError as TransferConnectionError,
    AuthenticationError,
    ValidationError,
    TimeoutError as TransferTimeoutError,
    ThrottleError
)
from src.models.config_models import RetryConfig


logger = logging.getLogger(__name__)


class AWSTransferClient(IAWSClient):
    """
    Cliente para AWS Transfer Family API.

    Encapsula todas las llamadas a boto3 para Transfer Family y proporciona
    manejo robusto de errores con lógica de reintentos.
    """

    def __init__(self, retry_config: Optional[RetryConfig] = None):
        """
        Inicializa el cliente AWS Transfer Family.

        Args:
            retry_config: Configuración de reintentos. Si no se proporciona,
                         se usan valores por defecto.
        """
        self.retry_config = retry_config or RetryConfig()
        self._client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """
        Inicializa el cliente boto3 para AWS Transfer Family.

        Raises:
            AuthenticationError: Si hay problemas con las credenciales AWS
            TransferConnectionError: Si no se puede establecer conexión con AWS
        """
        try:
            self._client = boto3.client('transfer')
            logger.debug("AWS Transfer Family client initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize AWS Transfer Family client: %s", e)
            if "credentials" in str(e).lower():
                raise AuthenticationError(
                    "Failed to authenticate with AWS. Check your credentials.",
                    error_code="AUTH_FAILED",
                    context={"original_error": str(e)}
                ) from e
            raise TransferConnectionError(
                "Failed to connect to AWS Transfer Family service.",
                error_code="CONNECTION_FAILED",
                context={"original_error": str(e)}
            ) from e

    def start_file_transfer(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inicia una transferencia de archivos usando AWS Transfer Family.

        Implementa retry logic con backoff exponencial para manejar errores
        transitorios de la API.

        Args:
            request: Diccionario con parámetros de la transferencia según boto3 API:
                - ConnectorId (string, requerido): ID del conector AWS Transfer Family
                - SendFilePaths (list, opcional): Lista de strings con rutas S3 para upload
                - RetrieveFilePaths (list, opcional): Lista de strings con rutas SFTP para download
                - LocalDirectoryPath (string, opcional): Directorio local para inbound transfers
                - RemoteDirectoryPath (string, opcional): Directorio remoto para outbound transfers

        Returns:
            Dict[str, Any]: Respuesta de la API con TransferId

        Raises:
            ValidationError: Si los parámetros de la solicitud son inválidos
            TransferError: Si la API devuelve un error
            TransferConnectionError: Si hay problemas de conectividad con AWS
            ThrottleError: Si se exceden los límites de rate de la API
        """
        self._validate_transfer_request(request)

        for attempt in range(self.retry_config.max_attempts):
            try:
                logger.info(
                    "Starting file transfer (attempt %d/%d)",
                    attempt + 1, self.retry_config.max_attempts,
                    extra={
                        "connector_id": request.get("ConnectorId"),
                        "file_count": (
                            len(request.get("SendFilePaths", [])) +
                            len(request.get("RetrieveFilePaths", []))
                        )
                    }
                )

                response = self._client.start_file_transfer(**request)

                logger.info(
                    "File transfer started successfully",
                    extra={
                        "transfer_id": response.get("TransferId"),
                        "connector_id": request.get("ConnectorId")
                    }
                )

                return response

            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                error_message = e.response.get('Error', {}).get('Message', str(e))

                logger.warning(
                    "AWS API error on attempt %d: %s - %s", attempt + 1, error_code, error_message,
                    extra={"error_code": error_code, "attempt": attempt + 1}
                )

                # Determinar si el error es retriable
                if self._is_retriable_error(error_code):
                    if attempt < self.retry_config.max_attempts - 1:
                        delay = self._calculate_backoff_delay(attempt)
                        logger.info("Retrying in %s seconds...", delay)
                        time.sleep(delay)
                        continue

                # Mapear errores específicos a excepciones apropiadas
                self._handle_api_error(e, error_code, error_message)

            except BotoCoreError as e:
                logger.error("BotoCore error on attempt %d: %s", attempt + 1, e)
                if attempt < self.retry_config.max_attempts - 1:
                    delay = self._calculate_backoff_delay(attempt)
                    logger.info("Retrying in %s seconds...", delay)
                    time.sleep(delay)
                    continue
                else:
                    raise TransferConnectionError(
                        "Failed to communicate with AWS Transfer Family after multiple attempts.",
                        error_code="CONNECTION_FAILED",
                        context={"original_error": str(e), "attempts": self.retry_config.max_attempts}
                    ) from e

        # Si llegamos aquí, todos los intentos fallaron
        raise TransferError(
            f"Failed to start file transfer after {self.retry_config.max_attempts} attempts.",
            error_code="TRANSFER_START_FAILED"
        )

    def list_file_transfer_results(
        self,
        connector_id: str,
        transfer_id: str,
        next_token: Optional[str] = None,
        max_results: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Lista los resultados de una transferencia de archivos.

        Args:
            connector_id: ID del conector AWS Transfer Family
            transfer_id: ID de ejecución devuelto por start_file_transfer
            next_token: Token para paginación (opcional)
            max_results: Número máximo de resultados a retornar (opcional)

        Returns:
            Dict[str, Any]: Resultados de la transferencia incluyendo:
                - FileTransferResults: Lista de resultados por archivo
                - NextToken: Token para siguiente página (si aplica)

        Raises:
            ValidationError: Si los parámetros no son válidos
            TransferConnectionError: Si hay problemas de conectividad con AWS
            TransferError: Si la API devuelve un error
        """
        # Validar parámetros requeridos
        if not connector_id or not isinstance(connector_id, str) or not connector_id.strip():
            raise ValidationError(
                "connector_id must be a non-empty string",
                error_code="INVALID_CONNECTOR_ID"
            )

        if not transfer_id or not isinstance(transfer_id, str) or not transfer_id.strip():
            raise ValidationError(
                "transfer_id must be a non-empty string",
                error_code="INVALID_TRANSFER_ID"
            )

        # Preparar parámetros de la llamada
        params = {
            "ConnectorId": connector_id,
            "TransferId": transfer_id
        }

        if next_token:
            params["NextToken"] = next_token

        if max_results is not None:
            if not isinstance(max_results, int) or max_results <= 0:
                raise ValidationError(
                    "max_results must be a positive integer",
                    error_code="INVALID_MAX_RESULTS"
                )
            params["MaxResults"] = max_results

        for attempt in range(self.retry_config.max_attempts):
            try:
                logger.debug(
                    "Listing file transfer results (attempt %d/%d)", attempt + 1, self.retry_config.max_attempts,
                    extra={
                        "connector_id": connector_id,
                        "transfer_id": transfer_id,
                        "max_results": max_results
                    }
                )

                response = self._client.list_file_transfer_results(**params)

                logger.debug(
                    "File transfer results listed successfully",
                    extra={
                        "connector_id": connector_id,
                        "transfer_id": transfer_id,
                        "results_count": len(response.get("FileTransferResults", []))
                    }
                )

                return response

            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                error_message = e.response.get('Error', {}).get('Message', str(e))

                logger.warning(
                    "AWS API error listing file transfer results on attempt %d: %s - %s", attempt + 1, error_code, error_message,
                    extra={
                        "error_code": error_code,
                        "connector_id": connector_id,
                        "transfer_id": transfer_id,
                        "attempt": attempt + 1
                    }
                )

                # Algunos errores no son retriables
                if error_code in ['TransferNotFound', 'InvalidParameterValue']:
                    raise ValidationError(
                        f"Invalid transfer parameters: {error_message}",
                        error_code=error_code,
                        context={"connector_id": connector_id, "transfer_id": transfer_id}
                    ) from e

                if self._is_retriable_error(error_code):
                    if attempt < self.retry_config.max_attempts - 1:
                        delay = self._calculate_backoff_delay(attempt)
                        logger.info("Retrying in %s seconds...", delay)
                        time.sleep(delay)
                        continue

                self._handle_api_error(e, error_code, error_message)

            except BotoCoreError as e:
                logger.error("BotoCore error listing file transfer results on attempt %d: %s", attempt + 1, e)
                if attempt < self.retry_config.max_attempts - 1:
                    delay = self._calculate_backoff_delay(attempt)
                    logger.info("Retrying in %s seconds...", delay)
                    time.sleep(delay)
                    continue
                else:
                    raise TransferConnectionError(
                        "Failed to list file transfer results after multiple attempts.",
                        error_code="CONNECTION_FAILED",
                        context={
                            "original_error": str(e),
                            "connector_id": connector_id,
                            "transfer_id": transfer_id
                        }
                    ) from e

        # Si llegamos aquí, todos los intentos fallaron
        raise TransferError(
            f"Failed to list file transfer results after {self.retry_config.max_attempts} attempts.",
            error_code="LIST_FILE_TRANSFER_RESULTS_FAILED",
            context={"connector_id": connector_id, "transfer_id": transfer_id}
        )

    def start_directory_listing(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inicia una operación de listado de directorio usando AWS Transfer Family.

        Args:
            request: Diccionario con parámetros del listado incluyendo:
                - ConnectorId: ID del conector AWS Transfer Family
                - RemoteDirectoryPath: Ruta del directorio remoto a listar
                - MaxItems: Número máximo de elementos a retornar (opcional)
                - OutputDirectoryPath: Ruta donde guardar el archivo de salida (opcional)

        Returns:
            Dict[str, Any]: Respuesta de la API con ListingId y OutputFileName

        Raises:
            ValidationError: Si los parámetros de la solicitud son inválidos
            TransferError: Si la API devuelve un error
            TransferConnectionError: Si hay problemas de conectividad con AWS
            ThrottleError: Si se exceden los límites de rate de la API
        """
        self._validate_directory_listing_request(request)

        for attempt in range(self.retry_config.max_attempts):
            try:
                logger.info(
                    "Starting directory listing (attempt %d/%d)", attempt + 1, self.retry_config.max_attempts,
                    extra={
                        "connector_id": request.get("ConnectorId"),
                        "directory_path": request.get("RemoteDirectoryPath")
                    }
                )

                response = self._client.start_directory_listing(**request)

                logger.info(
                    "Directory listing started successfully",
                    extra={
                        "listing_id": response.get("ListingId"),
                        "output_filename": response.get("OutputFileName"),
                        "connector_id": request.get("ConnectorId"),
                        "directory_path": request.get("RemoteDirectoryPath")
                    }
                )

                return response

            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                error_message = e.response.get('Error', {}).get('Message', str(e))

                logger.warning(
                    "AWS API error on attempt %d: %s - %s", attempt + 1, error_code, error_message,
                    extra={"error_code": error_code, "attempt": attempt + 1}
                )

                # Determinar si el error es retriable
                if self._is_retriable_error(error_code):
                    if attempt < self.retry_config.max_attempts - 1:
                        delay = self._calculate_backoff_delay(attempt)
                        logger.info("Retrying in %s seconds...", delay)
                        time.sleep(delay)
                        continue

                # Mapear errores específicos a excepciones apropiadas
                self._handle_api_error(e, error_code, error_message)

            except BotoCoreError as e:
                logger.error("BotoCore error on attempt %d: %s", attempt + 1, e)
                if attempt < self.retry_config.max_attempts - 1:
                    delay = self._calculate_backoff_delay(attempt)
                    logger.info("Retrying in %s seconds...", delay)
                    time.sleep(delay)
                    continue
                else:
                    raise TransferConnectionError(
                        "Failed to communicate with AWS Transfer Family after multiple attempts.",
                        error_code="CONNECTION_FAILED",
                        context={"original_error": str(e), "attempts": self.retry_config.max_attempts}
                    ) from e

        # Si llegamos aquí, todos los intentos fallaron
        raise TransferError(
            f"Failed to start directory listing after {self.retry_config.max_attempts} attempts.",
            error_code="DIRECTORY_LISTING_START_FAILED"
        )

    def start_remote_delete(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inicia una operación de eliminación de archivo/directorio remoto usando AWS Transfer Family.

        Args:
            request: Diccionario con parámetros de la eliminación incluyendo:
                - ConnectorId: ID del conector AWS Transfer Family
                - DeletePath: Ruta del archivo o directorio a eliminar en el servidor SFTP

        Returns:
            Dict[str, Any]: Respuesta de la API con DeleteId y otros metadatos

        Raises:
            ValidationError: Si los parámetros de la solicitud son inválidos
            TransferError: Si la API devuelve un error
            TransferConnectionError: Si hay problemas de conectividad con AWS
            ThrottleError: Si se exceden los límites de rate de la API
        """
        self._validate_remote_delete_request(request)

        for attempt in range(self.retry_config.max_attempts):
            try:
                logger.info(
                    "Starting remote file deletion (attempt %d/%d)", attempt + 1, self.retry_config.max_attempts,
                    extra={
                        "connector_id": request.get("ConnectorId"),
                        "delete_path": request.get("DeletePath")
                    }
                )

                response = self._client.start_remote_delete(**request)

                logger.info(
                    "Remote file deletion started successfully",
                    extra={
                        "delete_id": response.get("DeleteId"),
                        "connector_id": request.get("ConnectorId"),
                        "delete_path": request.get("DeletePath")
                    }
                )

                return response

            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                error_message = e.response.get('Error', {}).get('Message', str(e))

                logger.warning(
                    "AWS API error on attempt %d: %s - %s", attempt + 1, error_code, error_message,
                    extra={"error_code": error_code, "attempt": attempt + 1}
                )

                # Determinar si el error es retriable
                if self._is_retriable_error(error_code):
                    if attempt < self.retry_config.max_attempts - 1:
                        delay = self._calculate_backoff_delay(attempt)
                        logger.info("Retrying in %s seconds...", delay)
                        time.sleep(delay)
                        continue

                # Mapear errores específicos a excepciones apropiadas
                self._handle_api_error(e, error_code, error_message)

            except BotoCoreError as e:
                logger.error("BotoCore error on attempt %d: %s", attempt + 1, e)
                if attempt < self.retry_config.max_attempts - 1:
                    delay = self._calculate_backoff_delay(attempt)
                    logger.info("Retrying in %s seconds...", delay)
                    time.sleep(delay)
                    continue
                else:
                    raise TransferConnectionError(
                        "Failed to communicate with AWS Transfer Family after multiple attempts.",
                        error_code="CONNECTION_FAILED",
                        context={"original_error": str(e), "attempts": self.retry_config.max_attempts}
                    ) from e

        # Si llegamos aquí, todos los intentos fallaron
        raise TransferError(
            f"Failed to start remote file deletion after {self.retry_config.max_attempts} attempts.",
            error_code="REMOTE_DELETE_START_FAILED"
        )

    def _validate_transfer_request(self, request: Dict[str, Any]) -> None:
        """
        Valida los parámetros de una solicitud de transferencia.

        Valida según los parámetros correctos del API de boto3:
        - ConnectorId (requerido)
        - SendFilePaths: Lista de strings (rutas S3 para upload)
        - RetrieveFilePaths: Lista de strings (rutas SFTP para download)
        - LocalDirectoryPath: String (directorio local)
        - RemoteDirectoryPath: String (directorio remoto)

        Args:
            request: Diccionario con parámetros de la transferencia

        Raises:
            ValidationError: Si los parámetros son inválidos
        """
        if not isinstance(request, dict):
            raise ValidationError(
                "Transfer request must be a dictionary",
                error_code="INVALID_REQUEST_TYPE"
            )

        if not request.get("ConnectorId"):
            raise ValidationError(
                "ConnectorId is required",
                error_code="MISSING_CONNECTOR_ID"
            )

        send_files = request.get("SendFilePaths", [])
        retrieve_files = request.get("RetrieveFilePaths", [])

        if not send_files and not retrieve_files:
            raise ValidationError(
                "Either SendFilePaths or RetrieveFilePaths must be provided",
                error_code="NO_FILES_SPECIFIED"
            )

        # Validar que SendFilePaths y RetrieveFilePaths no se usen simultáneamente
        if send_files and retrieve_files:
            raise ValidationError(
                "Cannot specify both SendFilePaths and RetrieveFilePaths in the same request",
                error_code="CONFLICTING_FILE_PATHS"
            )

        # Validar límite de 10 archivos por lote (requerimiento 1.1, 2.1)
        total_files = len(send_files) + len(retrieve_files)
        if total_files > 10:
            raise ValidationError(
                f"Cannot transfer more than 10 files per batch. Got {total_files} files.",
                error_code="BATCH_SIZE_EXCEEDED",
                context={"file_count": total_files, "max_files": 10}
            )

        # Validar que las listas contengan strings
        if send_files:
            for i, path in enumerate(send_files):
                if not isinstance(path, str) or not path.strip():
                    raise ValidationError(
                        f"SendFilePaths[{i}] must be a non-empty string",
                        error_code="INVALID_SEND_FILE_PATH",
                        context={"file_index": i, "path": path}
                    )

        if retrieve_files:
            for i, path in enumerate(retrieve_files):
                if not isinstance(path, str) or not path.strip():
                    raise ValidationError(
                        f"RetrieveFilePaths[{i}] must be a non-empty string",
                        error_code="INVALID_RETRIEVE_FILE_PATH",
                        context={"file_index": i, "path": path}
                    )

        # Validar directorios opcionales
        local_dir = request.get("LocalDirectoryPath")
        if local_dir is not None and (not isinstance(local_dir, str) or not local_dir.strip()):
            raise ValidationError(
                "LocalDirectoryPath must be a non-empty string if provided",
                error_code="INVALID_LOCAL_DIRECTORY_PATH",
                context={"local_directory_path": local_dir}
            )

        remote_dir = request.get("RemoteDirectoryPath")
        if remote_dir is not None and (not isinstance(remote_dir, str) or not remote_dir.strip()):
            raise ValidationError(
                "RemoteDirectoryPath must be a non-empty string if provided",
                error_code="INVALID_REMOTE_DIRECTORY_PATH",
                context={"remote_directory_path": remote_dir}
            )

    def _validate_directory_listing_request(self, request: Dict[str, Any]) -> None:
        """
        Valida los parámetros de una solicitud de listado de directorio.

        Args:
            request: Diccionario con parámetros del listado

        Raises:
            ValidationError: Si los parámetros son inválidos
        """
        if not isinstance(request, dict):
            raise ValidationError(
                "Directory listing request must be a dictionary",
                error_code="INVALID_REQUEST_TYPE"
            )

        if not request.get("ConnectorId"):
            raise ValidationError(
                "ConnectorId is required",
                error_code="MISSING_CONNECTOR_ID"
            )

        if not request.get("RemoteDirectoryPath"):
            raise ValidationError(
                "RemoteDirectoryPath is required",
                error_code="MISSING_DIRECTORY_PATH"
            )

        # Validar longitud de ruta
        directory_path = request.get("RemoteDirectoryPath", "")
        if len(directory_path) > 1024:
            raise ValidationError(
                f"Directory path too long (max 1024 characters). Got {len(directory_path)} characters.",
                error_code="DIRECTORY_PATH_TOO_LONG",
                context={"path_length": len(directory_path), "max_length": 1024}
            )

        # Validar MaxItems si está presente
        max_items = request.get("MaxItems")
        if max_items is not None:
            if not isinstance(max_items, int) or max_items <= 0:
                raise ValidationError(
                    "MaxItems must be a positive integer",
                    error_code="INVALID_MAX_ITEMS",
                    context={"max_items": max_items}
                )

            if max_items > 1000:
                raise ValidationError(
                    f"MaxItems cannot exceed 1000. Got {max_items}.",
                    error_code="MAX_ITEMS_EXCEEDED",
                    context={"max_items": max_items, "max_allowed": 1000}
                )

        # Validar OutputDirectoryPath si está presente
        output_dir = request.get("OutputDirectoryPath")
        if output_dir is not None:
            if not isinstance(output_dir, str) or not output_dir.strip():
                raise ValidationError(
                    "OutputDirectoryPath must be a non-empty string",
                    error_code="INVALID_OUTPUT_DIRECTORY",
                    context={"output_directory": output_dir}
                )

            if len(output_dir) > 1024:
                raise ValidationError(
                    f"OutputDirectoryPath too long (max 1024 characters). Got {len(output_dir)} characters.",
                    error_code="OUTPUT_DIRECTORY_TOO_LONG",
                    context={"path_length": len(output_dir), "max_length": 1024}
                )

    def _validate_remote_delete_request(self, request: Dict[str, Any]) -> None:
        """
        Valida los parámetros de una solicitud de eliminación remota.

        Args:
            request: Diccionario con parámetros de la eliminación

        Raises:
            ValidationError: Si los parámetros son inválidos
        """
        if not isinstance(request, dict):
            raise ValidationError(
                "Remote delete request must be a dictionary",
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

        # Validar que no esté vacío después de strip
        if not delete_path.strip():
            raise ValidationError(
                "DeletePath must be a non-empty string",
                error_code="EMPTY_DELETE_PATH"
            )

        # Validar longitud de ruta
        if len(delete_path) > 1024:
            raise ValidationError(
                f"Delete path too long (max 1024 characters). Got {len(delete_path)} characters.",
                error_code="DELETE_PATH_TOO_LONG",
                context={"path_length": len(delete_path), "max_length": 1024}
            )

    def _is_retriable_error(self, error_code: str) -> bool:
        """
        Determina si un error de la API AWS es retriable.

        Args:
            error_code: Código de error de la API AWS

        Returns:
            bool: True si el error es retriable
        """
        retriable_errors = {
            'Throttling',
            'ThrottlingException',
            'RequestLimitExceeded',
            'ServiceUnavailable',
            'InternalServerError',
            'InternalError',
            'RequestTimeout',
            'RequestTimeoutException'
        }
        return error_code in retriable_errors

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """
        Calcula el delay para backoff exponencial.

        Args:
            attempt: Número de intento (0-based)

        Returns:
            float: Delay en segundos
        """
        delay = min(
            self.retry_config.base_delay * (self.retry_config.exponential_base ** attempt),
            self.retry_config.max_delay
        )
        return delay

    def _handle_api_error(self, error: ClientError, error_code: str, error_message: str) -> None:
        """
        Maneja errores específicos de la API AWS mapeándolos a excepciones apropiadas.

        Args:
            error: Error original de boto3
            error_code: Código de error de AWS
            error_message: Mensaje de error de AWS

        Raises:
            Excepción específica basada en el tipo de error
        """
        context = {
            "aws_error_code": error_code,
            "aws_error_message": error_message,
            "request_id": error.response.get('ResponseMetadata', {}).get('RequestId')
        }

        if error_code in ['Throttling', 'ThrottlingException', 'RequestLimitExceeded']:
            raise ThrottleError(
                f"API rate limit exceeded: {error_message}",
                error_code=error_code,
                context=context
            ) from error
        elif error_code in ['AccessDenied', 'UnauthorizedOperation']:
            raise AuthenticationError(
                f"Access denied: {error_message}",
                error_code=error_code,
                context=context
            ) from error
        elif error_code in ['InvalidParameterValue', 'ValidationException']:
            raise ValidationError(
                f"Invalid parameters: {error_message}",
                error_code=error_code,
                context=context
            ) from error
        elif error_code in ['RequestTimeout', 'RequestTimeoutException']:
            raise TransferTimeoutError(
                f"Request timeout: {error_message}",
                error_code=error_code,
                context=context
            ) from error
        elif error_code in ['ServiceUnavailable', 'InternalServerError']:
            raise TransferConnectionError(
                f"AWS service unavailable: {error_message}",
                error_code=error_code,
                context=context
            ) from error
        else:
            # Error genérico de transferencia
            raise TransferError(
                f"AWS Transfer Family API error: {error_message}",
                error_code=error_code,
                context=context
            ) from error
