"""
AWS Lambda handler for S3-SFTP Transfer service.

Este módulo implementa el punto de entrada para la función Lambda,
proporcionando una interfaz HTTP para las operaciones de transferencia.
"""
import sys
import os
import json
import logging
from typing import Dict, Any, List
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.transfer_manager import TransferManager
from src.config.config_manager import ConfigManager
from src.exceptions.transfer_exceptions import (
    TransferLibraryError,
    ValidationError,
    ConfigurationError
)

# Configurar logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principal de la función Lambda.

    Args:
        event: Evento de Lambda con la solicitud HTTP
        context: Contexto de ejecución de Lambda

    Returns:
        Dict[str, Any]: Respuesta HTTP con el resultado de la operación
    """
    try:
        # Log del evento recibido
        logger.info(
            "Lambda invocation started",
            extra={
                "request_id": context.aws_request_id,
                "function_name": context.function_name,
                "remaining_time": context.get_remaining_time_in_millis()
            }
        )

        # Extraer parámetros directamente del event
        operation = event.get('operation')
        files = event.get('files', [])
        connector_id = event.get('connector_id')
        destination_path = event.get('destination_path')
        s3_destination_path = event.get('s3_destination_path')

        # Validar operación
        if not operation:
            return create_error_response(
                400,
                "MISSING_OPERATION",
                "Operation is required (upload, download, delete, list_directory, get_status)"
            )

        # Validar connector_id para operaciones que lo requieren
        operations_requiring_connector = {'upload', 'download', 'delete', 'list_directory'}
        if operation in operations_requiring_connector and not connector_id:
            return create_error_response(
                400,
                "MISSING_CONNECTOR_ID",
                "connector_id is required in request event for this operation"
            )

        # Crear TransferManager
        with TransferManager(config_manager=ConfigManager(connector_id=connector_id)) as transfer_manager:

            if operation == 'upload':
                return handle_upload(transfer_manager, files, connector_id, destination_path)

            elif operation == 'download':
                return handle_download(transfer_manager, files, connector_id, s3_destination_path)

            elif operation == 'delete':
                return handle_delete(transfer_manager, files, connector_id)

            elif operation == 'list_directory': # pragma: no cover
                sftp_path = event.get('sftp_path')
                max_items = event.get('max_items')
                output_directory_path = event.get('output_directory_path')
                return handle_list_directory(transfer_manager, sftp_path, connector_id, max_items, output_directory_path)

            elif operation == 'get_status':
                transfer_id = event.get('transfer_id')
                transfer_ids = event.get('transfer_ids')
                return handle_get_status(transfer_manager, transfer_id, transfer_ids, connector_id)

            elif operation == 'wait_for_completion': # pragma: no cover
                transfer_id = event.get('transfer_id')
                timeout = event.get('timeout')
                poll_interval = event.get('poll_interval')
                return handle_wait_for_completion(transfer_manager, transfer_id, timeout, poll_interval)

            else:
                return create_error_response(
                    400,
                    "INVALID_OPERATION",
                    f"Unknown operation: {operation}. Valid operations: upload, download, delete, list_directory, get_status, wait_for_completion"
                )

    except ValidationError as e:
        logger.error("Validation error: %s", e)
        return create_error_response(400, e.error_code, str(e))

    except ConfigurationError as e:
        logger.error("Configuration error: %s", e)
        return create_error_response(500, e.error_code, str(e))

    except TransferLibraryError as e:
        logger.error("Transfer error: %s", e)
        return create_error_response(500, e.error_code, str(e))

    except json.JSONDecodeError as e: # pragma: no cover
        logger.error("JSON decode error: %s", e)
        return create_error_response(400, "INVALID_JSON", "Invalid JSON in request event")

    except Exception as e: # pragma: no cover
        logger.error("Unexpected error: %s", e, exc_info=True)
        return create_error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


def handle_upload(
    transfer_manager: TransferManager,
    files: List[str],
    connector_id: str,
    destination_path: str
) -> Dict[str, Any]:
    """
    Maneja operaciones de upload S3 → SFTP.

    Args:
        transfer_manager: Instancia de TransferManager
        files: Lista de rutas S3 de archivos a transferir
        connector_id: ID del conector (requerido)
        destination_path: Ruta de destino en el servidor SFTP

    Returns:
        Dict[str, Any]: Respuesta HTTP con el resultado
    """
    if not files:
        return create_error_response(400, "EMPTY_FILE_LIST", "Files list cannot be empty")

    if not destination_path:
        return create_error_response(400, "MISSING_DESTINATION_PATH", "destination_path is required")

    try:
        # Ejecutar upload usando el nuevo método
        result = transfer_manager.upload_files_batch(files, connector_id, destination_path)

        # Convertir resultado a formato serializable con estructura de batch_results
        response_data = {
            "status": result.status.value,
            "error_message": result.error_message
        }


        response_data["batch_results"] = result.batch_results


        return create_success_response(response_data)

    except Exception as e: # pragma: no cover
        logger.error("Upload failed: %s", e)
        raise


def handle_download(
    transfer_manager: TransferManager,
    files: List[str],
    connector_id: str,
    s3_destination_path: str = None
) -> Dict[str, Any]:
    """
    Maneja operaciones de download SFTP → S3.

    Utiliza el formato batch simple basado en AWS Transfer Family start_file_transfer:
    - files: Lista de rutas SFTP (RetrieveFilePaths)
    - s3_destination_path: Ruta de destino S3 (LocalDirectoryPath)

    Args:
        transfer_manager: Instancia de TransferManager
        files: Lista de rutas SFTP a descargar
        connector_id: ID del conector (requerido)
        s3_destination_path: Ruta de destino S3 (requerido)

    Returns:
        Dict[str, Any]: Respuesta HTTP con el resultado
    """
    if not files:
        return create_error_response(400, "EMPTY_FILE_LIST", "Files list cannot be empty")

    if not s3_destination_path:
        return create_error_response(
            400,
            "MISSING_S3_DESTINATION",
            "s3_destination_path is required for download operations"
        )

    try:
        # Usar el método batch download
        result = transfer_manager.download_files_batch(
            sftp_files=files,
            connector_id=connector_id,
            s3_destination_path=s3_destination_path
        )

        # Convertir resultado a formato serializable con estructura consistente con upload
        response_data = {
            "status": result.status.value,
            "error_message": result.error_message
        }

        response_data["batch_results"] = result.batch_results

        return create_success_response(response_data)

    except Exception as e: # pragma: no cover
        logger.error("Download failed: %s", e)
        raise


def handle_delete(
    transfer_manager: TransferManager,
    files: List[str],
    connector_id: str
) -> Dict[str, Any]:
    """
    Maneja operaciones de eliminación de archivos SFTP.

    Args:
        transfer_manager: Instancia de TransferManager
        files: Lista de rutas SFTP a eliminar
        connector_id: ID del conector (requerido)

    Returns:
        Dict[str, Any]: Respuesta HTTP con el resultado
    """
    if not files:
        return create_error_response(400, "EMPTY_FILE_LIST", "Files list cannot be empty")

    try:
        # Ejecutar eliminación usando el nuevo método batch
        result = transfer_manager.delete_files_batch(files, connector_id)

        # Convertir resultado a formato serializable con estructura de batch_results
        response_data = {
            "status": result.status.value,
            "error_message": result.error_message
        }

        # Crear batch_results similar al formato de upload
        response_data["batch_results"] = [
            {
                "delete_id": fr.transfer_id,
                "delete_path": fr.file_path,
                "status": fr.status.value,
                "error_message": fr.error_message
            }
            for fr in result.file_results
        ]

        return create_success_response(response_data)

    except Exception as e: # pragma: no cover
        logger.error("Delete failed: %s", e)
        raise


def handle_list_directory(
    transfer_manager: TransferManager,
    sftp_path: str,
    connector_id: str,
    max_items: int = None,
    output_directory_path: str = None
) -> Dict[str, Any]:
    """
    Maneja operaciones de listado de directorio SFTP.

    Args:
        transfer_manager: Instancia de TransferManager
        sftp_path: Ruta del directorio SFTP
        connector_id: ID del conector (requerido)
        max_items: Número máximo de elementos (opcional)
        output_directory_path: Ruta donde guardar el archivo de salida (opcional)

    Returns:
        Dict[str, Any]: Respuesta HTTP con el listado
    """
    if not sftp_path:
        return create_error_response(400, "MISSING_SFTP_PATH", "SFTP path is required")

    try:
        # Ejecutar listado
        listing = transfer_manager.list_directory(sftp_path, connector_id, max_items, output_directory_path)

        # Convertir resultado a formato serializable
        return create_success_response({
            "listing_id": listing.listing_id,  # ListingId de start_directory_listing
            "output_filename": listing.output_filename,  # OutputFileName de start_directory_listing
            "path": listing.path
        })

    except Exception as e: # pragma: no cover
        logger.error("Directory listing failed: %s", e)
        raise


def handle_get_status(
    transfer_manager: TransferManager,
    transfer_id: str = None,
    transfer_ids: List[str] = None,
    connector_id: str = None
) -> Dict[str, Any]:
    """
    Maneja consultas de estado de transferencia.

    Args:
        transfer_manager: Instancia de TransferManager
        transfer_id: ID de una transferencia individual (opcional)
        transfer_ids: Lista de IDs de transferencias (opcional)
        connector_id: ID del conector (requerido para múltiples transferencias)

    Returns:
        Dict[str, Any]: Respuesta HTTP con el estado
    """
    # Validar que se proporcione al menos uno de los parámetros
    if not transfer_id and (transfer_ids is None):
        return create_error_response(
            400,
            "MISSING_TRANSFER_PARAMS",
            "Either transfer_id or transfer_ids is required"
        )

    # Si se proporcionan ambos, dar prioridad a transfer_ids
    if transfer_ids is not None and transfer_id:
        transfer_id = None

    try:
        if transfer_ids is not None:
            # Validar parámetros para múltiples transferencias
            error_response = _validate_multiple_transfer_params(transfer_ids, connector_id)
            if error_response:
                return error_response

            # Obtener estado de múltiples transferencias
            status = transfer_manager.get_multiple_transfer_status(transfer_ids, connector_id)
            return create_success_response(status)

        # Manejar transferencia individual
        if not transfer_id:
            return create_error_response(400, "MISSING_TRANSFER_ID", "Transfer ID is required")

        # Obtener estado individual
        status = transfer_manager.get_transfer_status(transfer_id)
        return create_success_response(status)

    except Exception as e: # pragma: no cover
        logger.error("Get status failed: %s", e)
        raise


def _validate_multiple_transfer_params(transfer_ids: List[str], connector_id: str) -> Dict[str, Any]:
    """
    Valida parámetros para consultas de múltiples transferencias.

    Args:
        transfer_ids: Lista de IDs de transferencias
        connector_id: ID del conector

    Returns:
        Dict[str, Any]: Respuesta de error si hay validación fallida, None si es válido
    """
    if not connector_id:
        return create_error_response(
            400,
            "MISSING_CONNECTOR_ID",
            "connector_id is required when using transfer_ids"
        )

    if not isinstance(transfer_ids, list):
        return create_error_response(
            400,
            "INVALID_TRANSFER_IDS",
            "transfer_ids must be a list"
        )

    if not transfer_ids:
        return create_error_response(
            400,
            "INVALID_TRANSFER_IDS",
            "transfer_ids must be a non-empty list"
        )

    return None


def handle_wait_for_completion(
    transfer_manager: TransferManager,
    transfer_id: str,
    timeout: int = None,
    poll_interval: int = None
) -> Dict[str, Any]:
    """
    Maneja espera hasta completación de transferencia.

    Args:
        transfer_manager: Instancia de TransferManager
        transfer_id: ID de la transferencia
        timeout: Timeout en segundos (opcional)
        poll_interval: Intervalo de polling en segundos (opcional)

    Returns:
        Dict[str, Any]: Respuesta HTTP con el estado final
    """
    if not transfer_id:
        return create_error_response(400, "MISSING_TRANSFER_ID", "Transfer ID is required")

    try:
        # Esperar completación
        final_status = transfer_manager.wait_for_completion(transfer_id, timeout, poll_interval)

        return create_success_response(final_status)

    except Exception as e: # pragma: no cover
        logger.error("Wait for completion failed: %s", e)
        raise


def create_success_response(data: Any) -> Dict[str, Any]:
    """
    Crea una respuesta HTTP exitosa.

    Args:
        data: Datos a incluir en la respuesta

    Returns:
        Dict[str, Any]: Respuesta HTTP formateada
    """
    # Para operaciones get_status con múltiples transferencias, envolver en "results"
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        response_data = {
            "success": True,
            "data": {
                "results": data["data"]
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        response_data = {
            "success": True,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization"
        },
        "body": json.dumps(response_data, default=str)
    }


def create_error_response(status_code: int, error_code: str, message: str) -> Dict[str, Any]:
    """
    Crea una respuesta HTTP de error.

    Args:
        status_code: Código de estado HTTP
        error_code: Código de error específico
        message: Mensaje de error

    Returns:
        Dict[str, Any]: Respuesta HTTP de error formateada
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization"
        },
        "body": json.dumps({
            "success": False,
            "error": {
                "code": error_code,
                "message": message
            },
            "timestamp": datetime.utcnow().isoformat()
        })
    }
