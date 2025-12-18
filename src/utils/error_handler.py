"""
Implementación de ErrorHandler con estrategias de retry.
Proporciona categorización de errores y lógica inteligente de reintentos.
"""

import secrets
import time
from typing import Any, Dict, Optional, Type, Callable
from enum import Enum
from dataclasses import dataclass

from src.exceptions.transfer_exceptions import (
    TransferLibraryError,
    ConfigurationError,
    TransferError,
    ValidationError,
    ThrottleError,
    ConnectionError as TransferConnectionError,
    AuthenticationError,
    TimeoutError as TransferTimeoutError,
    FileNotFoundError as TransferFileNotFoundError,
    InsufficientPermissionsError
)
from src.models.config_models import RetryConfig
from src.utils.logger import StructuredLogger


class ErrorCategory(Enum):
    """Categorías de errores para diferentes estrategias de manejo"""
    RETRYABLE_TRANSIENT = "retryable_transient"  # Problemas de red, problemas temporales de AWS
    RETRYABLE_THROTTLE = "retryable_throttle"    # Limitación de tasa, throttling
    NON_RETRYABLE = "non_retryable"              # Errores de configuración, validación
    AUTHENTICATION = "authentication"            # Errores de autenticación/permisos
    NOT_FOUND = "not_found"                     # Archivo/recurso no encontrado



@dataclass
class ErrorContext:
    """Contexto enriquecido para manejo de errores"""
    instance_id: str
    transfer_id: Optional[str] = None
    batch_id: Optional[str] = None
    file_path: Optional[str] = None
    operation: str = "unknown"
    retry_attempt: int = 0
    aws_request_id: Optional[str] = None
    additional_context: Optional[Dict[str, Any]] = None


class ErrorHandler:
    """
    Manejador de errores comprensivo con estrategias de retry.
    """

    def __init__(self, logger: StructuredLogger, default_retry_config: Optional[RetryConfig] = None):
        """
        Inicializa el manejador de errores.

        Args:
            logger: Logger estructurado para logging de errores
            default_retry_config: Configuración de retry por defecto
        """
        self.logger = logger
        self.default_retry_config = default_retry_config or RetryConfig()

        # Mapeo de categorización de errores
        self._error_categories = self._build_error_categories()

    def _build_error_categories(self) -> Dict[Type[Exception], ErrorCategory]:
        """Construye el mapeo de tipos de excepción a categorías de error"""
        return {
            # Errores no reintentables
            ConfigurationError: ErrorCategory.NON_RETRYABLE,
            ValidationError: ErrorCategory.NON_RETRYABLE,

            # Errores de autenticación
            AuthenticationError: ErrorCategory.AUTHENTICATION,
            InsufficientPermissionsError: ErrorCategory.AUTHENTICATION,

            # Errores de no encontrado
            TransferFileNotFoundError: ErrorCategory.NOT_FOUND,

            # Errores de throttling
            ThrottleError: ErrorCategory.RETRYABLE_THROTTLE,

            # Errores transitorios reintentables
            TransferConnectionError: ErrorCategory.RETRYABLE_TRANSIENT,
            TransferError: ErrorCategory.RETRYABLE_TRANSIENT,
            TransferTimeoutError: ErrorCategory.RETRYABLE_TRANSIENT,

            # Errores específicos del SDK de AWS (boto3)
            Exception: ErrorCategory.RETRYABLE_TRANSIENT  # Fallback por defecto
        }

    def categorize_error(self, error: Exception) -> ErrorCategory:
        """
        Categoriza un error para la estrategia de manejo apropiada.

        Args:
            error: La excepción a categorizar

        Returns:
            ErrorCategory para el error
        """
        # Verificar tipos de error específicos primero
        for error_type, category in self._error_categories.items():
            if isinstance(error, error_type):
                return category

        # Verificar errores específicos del SDK de AWS
        error_message = str(error).lower()

        # Errores de throttling de AWS
        if any(keyword in error_message for keyword in ['throttling', 'rate exceeded', 'too many requests']):
            return ErrorCategory.RETRYABLE_THROTTLE

        # Errores de autenticación de AWS
        if any(keyword in error_message for keyword in ['access denied', 'unauthorized', 'invalid credentials']):
            return ErrorCategory.AUTHENTICATION

        # Errores de no encontrado de AWS
        if any(keyword in error_message for keyword in ['not found', 'does not exist', 'no such']):
            return ErrorCategory.NOT_FOUND

        # Errores transitorios de AWS
        if any(keyword in error_message for keyword in ['service unavailable', 'internal error', 'timeout']):
            return ErrorCategory.RETRYABLE_TRANSIENT

        # Por defecto no reintentable para errores desconocidos
        return ErrorCategory.NON_RETRYABLE

    def should_retry(self, error: Exception, attempt: int, max_attempts: int) -> bool:
        """
        Determina si un error debe ser reintentado.

        Args:
            error: La excepción que ocurrió
            attempt: Número de intento actual (basado en 1)
            max_attempts: Número máximo de intentos permitidos

        Returns:
            True si el error debe ser reintentado
        """
        if attempt >= max_attempts:
            return False

        category = self.categorize_error(error)

        # Solo reintentar ciertas categorías de errores
        return category in [
            ErrorCategory.RETRYABLE_TRANSIENT,
            ErrorCategory.RETRYABLE_THROTTLE
        ]

    def calculate_delay(self, attempt: int, retry_config: Optional[RetryConfig] = None,
                       error_category: Optional[ErrorCategory] = None) -> float:
        """
        Calcula el retraso antes del próximo intento de retry usando backoff exponencial.

        Args:
            attempt: Número de intento actual (basado en 1)
            retry_config: Configuración de retry a usar
            error_category: Categoría de error para cálculo de retraso especializado

        Returns:
            Retraso en segundos antes del próximo intento
        """
        config = retry_config or self.default_retry_config

        # Backoff exponencial base
        delay = config.base_delay * (config.exponential_base ** (attempt - 1))

        # Aplicar ajustes específicos por categoría
        if error_category == ErrorCategory.RETRYABLE_THROTTLE:
            # Retrasos más largos para errores de throttling
            delay *= 2

        # Limitar al retraso máximo
        delay = min(delay, config.max_delay)

        # Agregar jitter para prevenir thundering herd
        if config.jitter:
            jitter_range = delay * 0.1  # 10% jitter
            # Usar secrets para generar jitter criptográficamente seguro
            jitter = (secrets.randbelow(2001) - 1000) / 1000.0 * jitter_range
            delay += jitter

        return max(0.1, delay)  # Retraso mínimo de 100ms

    def handle_error(self, error: Exception, context: ErrorContext,
                    retry_config: Optional[RetryConfig] = None) -> None:
        """
        Maneja un error con logging apropiado y enriquecimiento de contexto.

        Args:
            error: La excepción que ocurrió
            context: Información de contexto del error
            retry_config: Configuración de retry opcional
        """
        category = self.categorize_error(error)

        # Enriquecer contexto con categorización de error
        enriched_context = {
            "error_category": category.value,
            "transfer_id": context.transfer_id,
            "batch_id": context.batch_id,
            "file_path": context.file_path,
            "operation": context.operation,
            "retry_attempt": context.retry_attempt,
            "aws_request_id": context.aws_request_id
        }

        if context.additional_context:
            enriched_context.update(context.additional_context)

        # Registrar el error con contexto enriquecido
        self.logger.log_error(error, enriched_context)

        # Registrar información de retry si este es un intento de retry
        if context.retry_attempt > 0:
            config = retry_config or self.default_retry_config
            should_retry = self.should_retry(error, context.retry_attempt, config.max_attempts)

            if should_retry:
                delay = self.calculate_delay(context.retry_attempt + 1, config, category)
                self.logger.log_retry_attempt(
                    context.operation,
                    context.retry_attempt + 1,
                    config.max_attempts,
                    delay,
                    str(error)
                )

    def execute_with_retry(self, operation: Callable[[], Any], operation_name: str,
                          context: ErrorContext, retry_config: Optional[RetryConfig] = None) -> Any:
        """
        Ejecuta una operación con lógica de retry.

        Args:
            operation: Función a ejecutar
            operation_name: Nombre de la operación para logging
            context: Contexto de error
            retry_config: Configuración de retry opcional

        Returns:
            Resultado de la operación

        Raises:
            La última excepción si todos los intentos de retry fallan
        """
        config = retry_config or self.default_retry_config
        last_exception = None

        for attempt in range(1, config.max_attempts + 1):
            try:
                context.retry_attempt = attempt - 1
                return operation()

            except Exception as e:
                last_exception = e
                context.retry_attempt = attempt - 1

                # Manejar el error (logging, etc.)
                self.handle_error(e, context, config)

                # Verificar si debemos reintentar
                if not self.should_retry(e, attempt, config.max_attempts):
                    break

                # No dormir después del último intento
                if attempt < config.max_attempts:
                    category = self.categorize_error(e)
                    delay = self.calculate_delay(attempt + 1, config, category)
                    time.sleep(delay)

        # Todos los intentos fallaron, lanzar la última excepción
        raise last_exception

    def wrap_aws_error(self, aws_error: Exception, operation: str,
                      context: Optional[Dict[str, Any]] = None) -> TransferLibraryError:
        """
        Envuelve errores del SDK de AWS en excepciones específicas de la librería.

        Args:
            aws_error: Excepción original del SDK de AWS
            operation: Operación que falló
            context: Contexto adicional

        Returns:
            Excepción envuelta
        """
        error_message = str(aws_error)
        error_name = type(aws_error).__name__

        # Extraer ID de request de AWS si está disponible
        aws_request_id = getattr(aws_error, 'response', {}).get('ResponseMetadata', {}).get('RequestId')

        # Crear contexto enriquecido
        enriched_context = {
            "aws_error_type": error_name,
            "aws_request_id": aws_request_id,
            "operation": operation
        }
        if context:
            enriched_context.update(context)

        # Mapear a excepción apropiada de la librería
        category = self.categorize_error(aws_error)

        if category == ErrorCategory.AUTHENTICATION:
            return AuthenticationError(
                f"Authentication failed for {operation}: {error_message}",
                error_code="AUTH_FAILED",
                context=enriched_context
            )
        elif category == ErrorCategory.NOT_FOUND:
            return TransferFileNotFoundError(
                f"Resource not found for {operation}: {error_message}",
                error_code="NOT_FOUND",
                context=enriched_context
            )
        elif category == ErrorCategory.RETRYABLE_THROTTLE:
            return ThrottleError(
                f"Rate limit exceeded for {operation}: {error_message}",
                error_code="THROTTLED",
                context=enriched_context
            )
        elif category == ErrorCategory.RETRYABLE_TRANSIENT:
            return TransferConnectionError(
                f"Connection error for {operation}: {error_message}",
                error_code="CONNECTION_ERROR",
                context=enriched_context
            )
        else:
            return TransferError(
                f"Transfer error for {operation}: {error_message}",
                error_code="TRANSFER_ERROR",
                context=enriched_context
            )
