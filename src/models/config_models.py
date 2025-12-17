"""
Configuration data models.

Este módulo define los modelos de configuración para la librería,
incluyendo opciones de transferencia y configuración de reintentos.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RetryConfig:
    """
    Configuración para reintentos.

    Attributes:
        max_attempts: Número máximo de intentos
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        exponential_base: Base para backoff exponencial
        jitter: Agregar jitter aleatorio para prevenir thundering herd
    """
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


@dataclass
class TransferOptions:
    """
    Opciones adicionales para transferencias.

    Attributes:
        preserve_metadata: Preservar metadatos del archivo
        overwrite_existing: Sobrescribir archivos existentes
        verify_checksum: Verificar checksum después de transferencia
        timeout_seconds: Timeout en segundos para operaciones
        retry_config: Configuración de reintentos
    """
    preserve_metadata: bool = True
    overwrite_existing: bool = False
    verify_checksum: bool = True
    timeout_seconds: int = 300
    retry_config: Optional[RetryConfig] = None

    def __post_init__(self):
        """Inicializa retry_config con valores por defecto si no se proporciona."""
        if self.retry_config is None:
            self.retry_config = RetryConfig()
