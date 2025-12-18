"""
Implementación de StructuredLogger para logging comprensivo.
Proporciona logging estructurado con niveles configurables y contexto enriquecido.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum


class LogLevel(Enum):
    """Niveles de logging configurables"""
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"


class StructuredLogger: # pragma: no cover
    """
    Logger estructurado para debugging y monitoreo en producción.
    """

    def __init__(self, instance_id: str, correlation_id: Optional[str] = None):
        """
        Inicializa el logger estructurado con contexto de instancia.

        Args:
            instance_id: Identificador único para esta instancia Lambda
            correlation_id: ID de correlación opcional para trazabilidad de requests
        """
        self.instance_id = instance_id
        self.correlation_id = correlation_id or self._generate_correlation_id()

        # Configurar logger de Python
        self.logger = logging.getLogger(f"file_ferry.{instance_id}")
        self._configure_logger()

    def _configure_logger(self) -> None:
        """Configura el logger de Python subyacente con formato estructurado"""
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)  # Nivel por defecto

    def _generate_correlation_id(self) -> str:
        """Genera un ID de correlación único para trazabilidad de requests"""
        return f"corr-{int(time.time() * 1000)}"

    def _create_base_context(self) -> Dict[str, Any]:
        """Crea el contexto base que se incluye en todas las entradas de log"""
        return {
            "instance_id": self.instance_id,
            "correlation_id": self.correlation_id,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "file_ferry"
        }

    def _log_structured(self, level: LogLevel, message: str, context: Dict[str, Any]) -> None:
        """
        Registra un mensaje estructurado con contexto.

        Args:
            level: Nivel de log
            message: Mensaje legible para humanos
            context: Datos de contexto adicionales
        """
        log_entry = self._create_base_context()
        log_entry.update(context)
        log_entry["message"] = message

        structured_message = json.dumps(log_entry, default=str)

        # Mapear a niveles de logging de Python
        python_level = {
            LogLevel.ERROR: logging.ERROR,
            LogLevel.WARN: logging.WARNING,
            LogLevel.INFO: logging.INFO,
            LogLevel.DEBUG: logging.DEBUG
        }[level]

        self.logger.log(python_level, structured_message)

    def set_log_level(self, level: LogLevel) -> None:
        """
        Establece el nivel de logging.

        Args:
            level: Nivel de log deseado
        """
        python_levels = {
            LogLevel.ERROR: logging.ERROR,
            LogLevel.WARN: logging.WARNING,
            LogLevel.INFO: logging.INFO,
            LogLevel.DEBUG: logging.DEBUG
        }
        self.logger.setLevel(python_levels[level])

    def log_transfer_start(self, transfer_id: str, file_count: int) -> None:
        """
        Registra el inicio de una operación de transferencia.

        Args:
            transfer_id: Identificador único para la transferencia
            file_count: Número de archivos en la transferencia
        """
        context = {
            "event_type": "transfer_start",
            "transfer_id": transfer_id,
            "file_count": file_count
        }
        self._log_structured(
            LogLevel.INFO,
            f"Starting transfer {transfer_id} with {file_count} files",
            context
        )

    def log_batch_processing(self, batch_id: str, files: List[str]) -> None:
        """
        Registra el procesamiento de un lote de archivos.

        Args:
            batch_id: Identificador único para el lote
            files: Lista de rutas de archivos en el lote
        """
        context = {
            "event_type": "batch_processing",
            "batch_id": batch_id,
            "batch_size": len(files),
            "files": files
        }
        self._log_structured(
            LogLevel.INFO,
            f"Processing batch {batch_id} with {len(files)} files",
            context
        )

    def log_api_call(self, operation: str, duration: float, success: bool,
                     aws_request_id: Optional[str] = None) -> None:
        """
        Registra una llamada a API con métricas de rendimiento.

        Args:
            operation: Nombre de la operación de API
            duration: Duración de la llamada en segundos
            success: Si la llamada fue exitosa
            aws_request_id: ID de request de AWS opcional para trazabilidad
        """
        context = {
            "event_type": "api_call",
            "operation": operation,
            "duration_seconds": round(duration, 3),
            "success": success,
            "aws_request_id": aws_request_id
        }

        level = LogLevel.INFO if success else LogLevel.ERROR
        status = "succeeded" if success else "failed"

        self._log_structured(
            level,
            f"API call {operation} {status} in {duration:.3f}s",
            context
        )

    def log_error(self, error: Exception, context: Dict[str, Any]) -> None:
        """
        Registra un error con contexto enriquecido.

        Args:
            error: La excepción que ocurrió
            context: Contexto adicional sobre el error
        """
        error_context = {
            "event_type": "error",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "error_module": getattr(error, '__module__', 'unknown')
        }
        error_context.update(context)

        self._log_structured(
            LogLevel.ERROR,
            f"Error occurred: {type(error).__name__}: {str(error)}",
            error_context
        )

    def log_throttle_event(self, delay_seconds: float, current_rate: float,
                          target_rate: float) -> None:
        """
        Registra un evento de throttling.

        Args:
            delay_seconds: Cuánto tiempo esperará el sistema
            current_rate: Tasa de transferencia actual
            target_rate: Tasa de transferencia objetivo
        """
        context = {
            "event_type": "throttle",
            "delay_seconds": round(delay_seconds, 3),
            "current_rate": round(current_rate, 2),
            "target_rate": round(target_rate, 2)
        }
        self._log_structured(
            LogLevel.WARN,
            f"Throttling applied: waiting {delay_seconds:.3f}s (rate: {current_rate:.2f}/{target_rate:.2f})",
            context
        )

    def log_session_event(self, event_type: str, session_id: Optional[str] = None,
                         available_sessions: Optional[int] = None) -> None:
        """
        Registra eventos de gestión de sesiones.

        Args:
            event_type: Tipo de evento de sesión (acquire, release, wait)
            session_id: Identificador de sesión opcional
            available_sessions: Número de sesiones disponibles
        """
        context = {
            "event_type": "session_management",
            "session_event": event_type,
            "session_id": session_id,
            "available_sessions": available_sessions
        }
        self._log_structured(
            LogLevel.DEBUG,
            f"Session {event_type}: {session_id or 'N/A'} (available: {available_sessions or 'N/A'})",
            context
        )

    def log_validation_error(self, validation_type: str, file_path: str,
                           error_details: str) -> None:
        """
        Registra errores de validación.

        Args:
            validation_type: Tipo de validación que falló
            file_path: Ruta del archivo que falló la validación
            error_details: Detalles sobre la falla de validación
        """
        context = {
            "event_type": "validation_error",
            "validation_type": validation_type,
            "file_path": file_path,
            "error_details": error_details
        }
        self._log_structured(
            LogLevel.ERROR,
            f"Validation failed for {file_path}: {validation_type} - {error_details}",
            context
        )

    def log_retry_attempt(self, operation: str, attempt: int, max_attempts: int,
                         delay_seconds: float, error: Optional[str] = None) -> None:
        """
        Registra intentos de retry.

        Args:
            operation: Operación que se está reintentando
            attempt: Número de intento actual
            max_attempts: Número máximo de intentos
            delay_seconds: Retraso antes del próximo intento
            error: Error opcional que disparó el retry
        """
        context = {
            "event_type": "retry_attempt",
            "operation": operation,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "delay_seconds": round(delay_seconds, 3),
            "triggering_error": error
        }
        self._log_structured(
            LogLevel.WARN,
            f"Retry attempt {attempt}/{max_attempts} for {operation} (delay: {delay_seconds:.3f}s)",
            context
        )

    def log_transfer_complete(self, transfer_id: str, success_count: int,
                            failure_count: int, duration_seconds: float) -> None:
        """
        Registra la finalización de transferencia con estadísticas de resumen.

        Args:
            transfer_id: Identificador de transferencia
            success_count: Número de transferencias de archivos exitosas
            failure_count: Número de transferencias de archivos fallidas
            duration_seconds: Duración total de la transferencia
        """
        context = {
            "event_type": "transfer_complete",
            "transfer_id": transfer_id,
            "success_count": success_count,
            "failure_count": failure_count,
            "total_files": success_count + failure_count,
            "duration_seconds": round(duration_seconds, 3),
            "success_rate": round(success_count / (success_count + failure_count) * 100, 2) if (success_count + failure_count) > 0 else 0
        }

        level = LogLevel.INFO if failure_count == 0 else LogLevel.WARN
        self._log_structured(
            level,
            f"Transfer {transfer_id} completed: {success_count} success, {failure_count} failed in {duration_seconds:.3f}s",
            context
        )
