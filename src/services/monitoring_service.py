"""
MonitoringService implementation.

Este módulo implementa el servicio de monitoreo de transferencias,
proporcionando funcionalidades para consultar el estado de transferencias
y archivos individuales usando AWS Transfer Family APIs.
"""

import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.services.interfaces import IAWSClient
from src.models.transfer_models import TransferStatus
from src.exceptions.transfer_exceptions import (
    ValidationError,
    TransferError,
    ConnectionError as TransferConnectionError
)

logger = logging.getLogger(__name__)


class MonitoringService: # pragma: no cover
    """
    Servicio de monitoreo de transferencias.

    Proporciona funcionalidades para consultar el estado de transferencias
    y archivos individuales usando AWS Transfer Family APIs.
    """

    def __init__(self, aws_client: IAWSClient):
        """
        Inicializa el MonitoringService.

        Args:
            aws_client: Cliente para AWS Transfer Family

        Raises:
            ValidationError: Si los parámetros son inválidos
        """
        if not aws_client:
            raise ValidationError(
                "aws_client es requerido",
                error_code="MISSING_AWS_CLIENT"
            )

        self.aws_client = aws_client

    def get_transfer_status(
        self,
        transfer_id: str,
        connector_id: str,
        next_token: Optional[str] = None,
        max_results: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Obtiene el estado de una transferencia usando list_file_transfer_results API.

        Args:
            transfer_id: ID de la transferencia
            connector_id: ID del conector AWS Transfer Family
            next_token: Token para paginación (opcional)
            max_results: Número máximo de resultados (opcional, máximo 10)

        Returns:
            Dict con el estado de la transferencia incluyendo:
                - transfer_id: ID de la transferencia
                - connector_id: ID del conector
                - overall_status: Estado general de la transferencia
                - file_results: Lista de resultados por archivo
                - next_token: Token para siguiente página (si aplica)
                - total_files: Total de archivos en la transferencia
                - completed_files: Archivos completados
                - failed_files: Archivos fallidos
                - in_progress_files: Archivos en progreso
                - queued_files: Archivos en cola

        Raises:
            ValidationError: Si los parámetros no son válidos
            TransferError: Si hay error en la API de AWS
            TransferConnectionError: Si hay problemas de conectividad
        """
        if not transfer_id:
            raise ValidationError(
                "transfer_id es requerido",
                error_code="MISSING_TRANSFER_ID"
            )

        if not connector_id:
            raise ValidationError(
                "connector_id es requerido",
                error_code="MISSING_CONNECTOR_ID"
            )

        # Validar max_results si se proporciona
        if max_results is not None and (max_results < 1 or max_results > 10):
            raise ValidationError(
                "max_results debe estar entre 1 y 10",
                error_code="INVALID_MAX_RESULTS"
            )

        try:
            logger.info(
                "Consultando estado de transferencia: %s",
                transfer_id,
                extra={
                    "transfer_id": transfer_id,
                    "connector_id": connector_id,
                    "max_results": max_results
                }
            )

            # Llamar a la API list_file_transfer_results
            response = self.aws_client.list_file_transfer_results(
                connector_id=connector_id,
                transfer_id=transfer_id,
                next_token=next_token,
                max_results=max_results
            )

            # Procesar la respuesta
            file_results = response.get("FileTransferResults", [])
            next_token_response = response.get("NextToken")

            # Calcular estadísticas
            stats = self._calculate_transfer_stats(file_results)

            # Determinar estado general de la transferencia
            overall_status = self._determine_overall_status(file_results, next_token_response)

            result = {
                "transfer_id": transfer_id,
                "connector_id": connector_id,
                "overall_status": overall_status,
                "file_results": [
                    {
                        "file_path": file_result.get("FilePath"),
                        "status": file_result.get("StatusCode"),
                        "failure_code": file_result.get("FailureCode"),
                        "failure_message": file_result.get("FailureMessage")
                    }
                    for file_result in file_results
                ],
                "next_token": next_token_response,
                "total_files": len(file_results),
                "completed_files": stats["completed"],
                "failed_files": stats["failed"],
                "in_progress_files": stats["in_progress"],
                "queued_files": stats["queued"],
                "timestamp": datetime.now().isoformat()
            }

            logger.info(
                "Estado de transferencia obtenido exitosamente: %s",
                transfer_id,
                extra={
                    "transfer_id": transfer_id,
                    "overall_status": overall_status,
                    "total_files": len(file_results),
                    "completed_files": stats["completed"],
                    "failed_files": stats["failed"]
                }
            )

            return result

        except Exception as e:
            if isinstance(e, (ValidationError, TransferError, TransferConnectionError)):
                raise
            logger.error(
                "Error consultando estado de transferencia %s: %s",
                transfer_id, e,
                extra={
                    "transfer_id": transfer_id,
                    "connector_id": connector_id,
                    "error": str(e)
                }
            )
            raise TransferError(
                f"Error consultando estado de transferencia: {str(e)}",
                error_code="TRANSFER_STATUS_QUERY_FAILED",
                context={
                    "transfer_id": transfer_id,
                    "connector_id": connector_id,
                    "original_error": str(e)
                }
            ) from e

    def _calculate_transfer_stats(self, file_results: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Calcula estadísticas de los archivos en la transferencia.

        Args:
            file_results: Lista de resultados de archivos de la API

        Returns:
            Dict con contadores por estado
        """
        stats = {
            "completed": 0,
            "failed": 0,
            "in_progress": 0,
            "queued": 0
        }

        for file_result in file_results:
            status = file_result.get("StatusCode", "").upper()

            if status == "COMPLETED":
                stats["completed"] += 1
            elif status == "FAILED":
                stats["failed"] += 1
            elif status == "IN_PROGRESS":
                stats["in_progress"] += 1
            elif status == "QUEUED":
                stats["queued"] += 1

        return stats

    def _determine_overall_status(
        self,
        file_results: List[Dict[str, Any]],
        next_token: Optional[str]
    ) -> str:
        """
        Determina el estado general de la transferencia basado en los archivos.

        Args:
            file_results: Lista de resultados de archivos
            next_token: Token de paginación (indica si hay más resultados)

        Returns:
            Estado general de la transferencia
        """
        if not file_results:
            return TransferStatus.PENDING.value

        # Si hay next_token, significa que hay más archivos por consultar
        # por lo que no podemos determinar el estado final
        if next_token:
            return TransferStatus.IN_PROGRESS.value

        stats = self._calculate_transfer_stats(file_results)

        # Si hay archivos en progreso o en cola, la transferencia está en progreso
        if stats["in_progress"] > 0 or stats["queued"] > 0:
            return TransferStatus.IN_PROGRESS.value

        # Si todos los archivos están completados
        if stats["completed"] > 0 and stats["failed"] == 0:
            return TransferStatus.COMPLETED.value

        # Si hay archivos fallidos
        if stats["failed"] > 0:
            # Si también hay archivos completados, es éxito parcial
            if stats["completed"] > 0:
                return "PARTIALLY_COMPLETED"  # Estado parcialmente completado cuando hay archivos fallidos y completados
            else:
                return TransferStatus.FAILED.value

        # Estado por defecto
        return TransferStatus.PENDING.value

    def poll_until_complete(
        self,
        transfer_id: str,
        connector_id: str,
        timeout: Optional[int] = 300,
        poll_interval: Optional[int] = 10
    ) -> Dict[str, Any]:
        """
        Hace polling hasta que la transferencia se complete o falle.

        Args:
            transfer_id: ID de la transferencia
            connector_id: ID del conector AWS Transfer Family
            timeout: Tiempo máximo de espera en segundos (default: 300)
            poll_interval: Intervalo entre consultas en segundos (default: 10)

        Returns:
            Estado final de la transferencia

        Raises:
            ValidationError: Si los parámetros no son válidos
            TransferError: Si la transferencia falla o hay timeout
        """
        if not transfer_id:
            raise ValidationError(
                "transfer_id es requerido",
                error_code="MISSING_TRANSFER_ID"
            )

        if not connector_id:
            raise ValidationError(
                "connector_id es requerido",
                error_code="MISSING_CONNECTOR_ID"
            )

        timeout = timeout or 300
        poll_interval = poll_interval or 10

        if timeout <= 0:
            raise ValidationError(
                "timeout debe ser mayor a 0",
                error_code="INVALID_TIMEOUT"
            )

        if poll_interval <= 0:
            raise ValidationError(
                "poll_interval debe ser mayor a 0",
                error_code="INVALID_POLL_INTERVAL"
            )

        start_time = time.time()

        logger.info(
            "Iniciando polling para transferencia: %s",
            transfer_id,
            extra={
                "transfer_id": transfer_id,
                "connector_id": connector_id,
                "timeout": timeout,
                "poll_interval": poll_interval
            }
        )

        while time.time() - start_time < timeout:
            try:
                status = self.get_transfer_status(transfer_id, connector_id)
                overall_status = status.get("overall_status")

                logger.debug(
                    "Polling status: %s",
                    overall_status,
                    extra={
                        "transfer_id": transfer_id,
                        "status": overall_status,
                        "elapsed_time": time.time() - start_time
                    }
                )

                # Verificar si la transferencia terminó
                if overall_status in [
                    TransferStatus.COMPLETED.value,
                    TransferStatus.FAILED.value,
                    TransferStatus.CANCELLED.value
                ]:
                    logger.info(
                        "Transferencia completada con estado: %s",
                        overall_status,
                        extra={
                            "transfer_id": transfer_id,
                            "final_status": overall_status,
                            "total_time": time.time() - start_time
                        }
                    )
                    return status

                # Esperar antes del siguiente polling
                time.sleep(poll_interval)

            except Exception as e:
                if isinstance(e, (ValidationError, TransferError, TransferConnectionError)):
                    raise
                logger.error(
                    "Error durante polling de transferencia %s: %s",
                    transfer_id, e,
                    extra={
                        "transfer_id": transfer_id,
                        "error": str(e),
                        "elapsed_time": time.time() - start_time
                    }
                )
                raise TransferError(
                    f"Error durante polling de transferencia: {str(e)}",
                    error_code="POLLING_ERROR",
                    context={
                        "transfer_id": transfer_id,
                        "connector_id": connector_id,
                        "original_error": str(e)
                    }
                ) from e

        # Timeout alcanzado
        logger.error(
            "Timeout alcanzado esperando transferencia: %s",
            transfer_id,
            extra={
                "transfer_id": transfer_id,
                "timeout": timeout,
                "elapsed_time": time.time() - start_time
            }
        )

        raise TransferError(
            f"Timeout alcanzado esperando transferencia {transfer_id}",
            error_code="POLLING_TIMEOUT",
            context={
                "transfer_id": transfer_id,
                "connector_id": connector_id,
                "timeout": timeout
            }
        )

    def get_multiple_transfer_status(
        self,
        transfer_ids: List[str],
        connector_id: str,
        next_token: Optional[str] = None,
        max_results: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Obtiene el estado de múltiples transferencias usando list_file_transfer_results API.

        Args:
            transfer_ids: Lista de IDs de transferencias
            connector_id: ID del conector AWS Transfer Family
            next_token: Token para paginación (opcional)
            max_results: Número máximo de resultados por transferencia (opcional, máximo 10)

        Returns:
            Dict con el estado consolidado de las transferencias incluyendo:
                - success: True si la operación fue exitosa
                - data: Lista de estados de transferencias
                - timestamp: Timestamp de la consulta

        Raises:
            ValidationError: Si los parámetros no son válidos
            TransferError: Si hay error en la API de AWS
            TransferConnectionError: Si hay problemas de conectividad
        """
        if not transfer_ids or not isinstance(transfer_ids, list):
            raise ValidationError(
                "transfer_ids debe ser una lista no vacía",
                error_code="INVALID_TRANSFER_IDS"
            )

        if not connector_id:
            raise ValidationError(
                "connector_id es requerido",
                error_code="MISSING_CONNECTOR_ID"
            )

        # Validar max_results si se proporciona
        if max_results is not None and (max_results < 1 or max_results > 10):
            raise ValidationError(
                "max_results debe estar entre 1 y 10",
                error_code="INVALID_MAX_RESULTS"
            )

        try:
            logger.info(
                "Consultando estado de %d transferencias",
                len(transfer_ids),
                extra={
                    "transfer_ids": transfer_ids,
                    "connector_id": connector_id,
                    "max_results": max_results
                }
            )

            transfer_results = []

            # Procesar cada transfer_id
            for transfer_id in transfer_ids:
                try:
                    # Obtener estado individual usando el método existente
                    transfer_status = self.get_transfer_status(
                        transfer_id=transfer_id,
                        connector_id=connector_id,
                        next_token=next_token,
                        max_results=max_results
                    )
                    transfer_results.append(transfer_status)

                except Exception as e:
                    logger.error(
                        "Error consultando transferencia %s: %s",
                        transfer_id, e,
                        extra={
                            "transfer_id": transfer_id,
                            "connector_id": connector_id,
                            "error": str(e)
                        }
                    )
                    # Agregar resultado de error para esta transferencia
                    transfer_results.append({
                        "transfer_id": transfer_id,
                        "connector_id": connector_id,
                        "overall_status": "ERROR",
                        "file_results": [],
                        "next_token": None,
                        "total_files": 0,
                        "completed_files": 0,
                        "failed_files": 0,
                        "in_progress_files": 0,
                        "queued_files": 0,
                        "timestamp": datetime.now().isoformat(),
                        "error_message": str(e)
                    })

            result = {
                "success": True,
                "data": transfer_results,
                "timestamp": datetime.now().isoformat()
            }

            logger.info(
                "Estado de %d transferencias obtenido exitosamente",
                len(transfer_ids),
                extra={
                    "transfer_count": len(transfer_ids),
                    "successful_queries": len([r for r in transfer_results if r.get("overall_status") != "ERROR"])
                }
            )

            return result

        except Exception as e:
            if isinstance(e, (ValidationError, TransferError, TransferConnectionError)):
                raise
            logger.error(
                "Error consultando estado de transferencias: %s",
                e,
                extra={
                    "transfer_ids": transfer_ids,
                    "connector_id": connector_id,
                    "error": str(e)
                }
            )
            raise TransferError(
                f"Error consultando estado de transferencias: {str(e)}",
                error_code="MULTIPLE_TRANSFER_STATUS_QUERY_FAILED",
                context={
                    "transfer_ids": transfer_ids,
                    "connector_id": connector_id,
                    "original_error": str(e)
                }
            ) from e
