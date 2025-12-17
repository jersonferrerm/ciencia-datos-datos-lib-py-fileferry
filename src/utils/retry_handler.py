"""
Implementación de RetryHandler para backoff exponencial y lógica de retry.
Proporciona utilidades para implementar patrones de retry con backoff.
"""

import secrets
import time
from typing import Any, Callable, Optional
from dataclasses import dataclass
from functools import wraps

from src.utils.logger import StructuredLogger


@dataclass
class RetryPolicy:
    """Configuración para comportamiento de retry"""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (Exception,)


class RetryHandler:
    """
    Manejador para implementar lógica de retry con backoff exponencial.
    Proporciona utilidades para reintentar operaciones con políticas configurables.
    """

    def __init__(self, logger: Optional[StructuredLogger] = None):
        """
        Inicializa el manejador de retry.

        Args:
            logger: Logger estructurado opcional para eventos de retry
        """
        self.logger = logger

    def calculate_delay(self, attempt: int, policy: RetryPolicy) -> float:
        """
        Calcula el retraso para backoff exponencial con jitter.

        Args:
            attempt: Número de intento actual (basado en 1)
            policy: Configuración de política de retry

        Returns:
            Retraso en segundos
        """
        # Backoff exponencial
        delay = policy.base_delay * (policy.exponential_base ** (attempt - 1))

        # Limitar al retraso máximo
        delay = min(delay, policy.max_delay)

        # Agregar jitter para prevenir thundering herd
        if policy.jitter:
            jitter_range = delay * 0.1  # 10% jitter
            # Usar secrets para generar jitter criptográficamente seguro
            jitter = (secrets.randbelow(2001) - 1000) / 1000.0 * jitter_range
            delay += jitter

        return max(0.1, delay)  # Retraso mínimo de 100ms

    def should_retry(self, exception: Exception, attempt: int, policy: RetryPolicy) -> bool:
        """
        Determina si una excepción debe disparar un retry.

        Args:
            exception: La excepción que ocurrió
            attempt: Número de intento actual (basado en 1)
            policy: Configuración de política de retry

        Returns:
            True si la operación debe ser reintentada
        """
        if attempt >= policy.max_attempts:
            return False

        return isinstance(exception, policy.retryable_exceptions)

    def retry_with_backoff(self, operation: Callable[[], Any], policy: RetryPolicy,
                          operation_name: str = "operation") -> Any:
        """
        Ejecuta una operación con retry y backoff exponencial.

        Args:
            operation: Función a ejecutar
            policy: Configuración de política de retry
            operation_name: Nombre para propósitos de logging

        Returns:
            Resultado de la operación

        Raises:
            La última excepción si todos los intentos de retry fallan
        """
        last_exception = None

        for attempt in range(1, policy.max_attempts + 1):
            try:
                return operation()

            except Exception as e:
                last_exception = e

                if not self.should_retry(e, attempt, policy):
                    break

                # No dormir después del último intento
                if attempt < policy.max_attempts:
                    delay = self.calculate_delay(attempt + 1, policy)

                    if self.logger:
                        self.logger.log_retry_attempt(
                            operation_name,
                            attempt + 1,
                            policy.max_attempts,
                            delay,
                            str(e)
                        )

                    time.sleep(delay)

        # Todos los intentos fallaron
        raise last_exception


def retry(max_attempts: int = 3, base_delay: float = 1.0, max_delay: float = 60.0,
          exponential_base: float = 2.0, jitter: bool = True,
          retryable_exceptions: tuple = (Exception,)) -> Callable:
    """
    Decorador para agregar lógica de retry a funciones.

    Args:
        max_attempts: Número máximo de intentos de retry
        base_delay: Retraso base en segundos
        max_delay: Retraso máximo en segundos
        exponential_base: Base para backoff exponencial
        jitter: Si agregar jitter a los retrasos
        retryable_exceptions: Tupla de excepciones que deben disparar retries

    Returns:
        Función decorada con lógica de retry
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            policy = RetryPolicy(
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter,
                retryable_exceptions=retryable_exceptions
            )

            handler = RetryHandler()
            return handler.retry_with_backoff(
                lambda: func(*args, **kwargs),
                policy,
                func.__name__
            )

        return wrapper
    return decorator
