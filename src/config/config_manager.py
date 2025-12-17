"""
ConfigManager implementation for S3-SFTP Transfer Library.

Este módulo maneja toda la configuración de la librería a través de variables
de entorno, proporcionando validación y valores por defecto.
"""

import os
from typing import Dict, Optional

from src.exceptions.transfer_exceptions import ConfigurationError
from src.models.config_models import RetryConfig


class ConfigManager: # pragma: no cover
    """
    Gestiona toda la configuración de la librería desde variables de entorno.

    Implementa validación fail-fast y proporciona valores por defecto
    configurables para todos los parámetros del sistema.
    """

    def __init__(self, env_vars: Optional[Dict[str, str]] = None, connector_id: str = None):
        """
        Inicializa el ConfigManager.

        Args:
            env_vars: Diccionario opcional de variables de entorno para testing.
                     Si no se proporciona, usa os.environ.

        Raises:
            ConfigurationError: Si falta configuración requerida o hay valores inválidos.
        """
        self._env_vars = env_vars if env_vars is not None else dict(os.environ)
        self._config_cache: Dict[str, any] = {
            'connector_id': connector_id
        }

    def get_connector_id(self) -> Optional[str]:
        """
        Obtiene el ID del conector AWS Transfer Family desde variables de entorno.

        NOTA: Este método es opcional y solo para compatibilidad hacia atrás.
        El connector_id debe proporcionarse siempre en el request body.

        Returns:
            Optional[str]: ID del conector configurado o None si no está configurado.
        """
        if 'connector_id' not in self._config_cache:
            connector_id = self._env_vars.get('AWS_TRANSFER_CONNECTOR_ID')
            self._config_cache['connector_id'] = connector_id.strip() if connector_id else None

        return self._config_cache['connector_id']

    def get_throughput_limit(self) -> int:
        """
        Obtiene el límite de throughput en archivos por segundo.

        Returns:
            int: Límite de throughput (default: 100 archivos/segundo).

        Raises:
            ConfigurationError: Si el valor no es un entero válido.
        """
        if 'throughput_limit' not in self._config_cache:
            throughput_str = self._env_vars.get('AWS_TRANSFER_THROUGHPUT_LIMIT', '100')
            try:
                throughput_limit = int(throughput_str)
                if throughput_limit <= 0:
                    raise ValueError("Throughput limit must be positive")
                self._config_cache['throughput_limit'] = throughput_limit
            except ValueError as e:
                raise ConfigurationError(
                    f"Invalid throughput limit '{throughput_str}': {str(e)}",
                    error_code="CONFIG_INVALID_THROUGHPUT_LIMIT"
                ) from e

        return self._config_cache['throughput_limit']

    def get_max_concurrent_sessions(self) -> int:
        """
        Obtiene el número máximo de sesiones concurrentes.

        Returns:
            int: Número máximo de sesiones concurrentes (default: 5).

        Raises:
            ConfigurationError: Si el valor no es un entero válido.
        """
        if 'max_concurrent_sessions' not in self._config_cache:
            sessions_str = self._env_vars.get('AWS_TRANSFER_MAX_CONCURRENT_SESSIONS', '5')
            try:
                max_sessions = int(sessions_str)
                if max_sessions <= 0:
                    raise ValueError("Max concurrent sessions must be positive")
                if max_sessions > 5:  # AWS Transfer Family limit
                    raise ValueError("Max concurrent sessions cannot exceed 5")
                self._config_cache['max_concurrent_sessions'] = max_sessions
            except ValueError as e:
                raise ConfigurationError(
                    f"Invalid max concurrent sessions '{sessions_str}': {str(e)}",
                    error_code="CONFIG_INVALID_MAX_SESSIONS"
                ) from e

        return self._config_cache['max_concurrent_sessions']

    def get_retry_config(self) -> RetryConfig:
        """
        Obtiene la configuración de reintentos.

        Returns:
            RetryConfig: Configuración de reintentos con valores configurables.

        Raises:
            ConfigurationError: Si algún valor de configuración es inválido.
        """
        if 'retry_config' not in self._config_cache:
            try:
                max_attempts = int(self._env_vars.get('AWS_TRANSFER_RETRY_MAX_ATTEMPTS', '3'))
                base_delay = float(self._env_vars.get('AWS_TRANSFER_RETRY_BASE_DELAY', '1.0'))
                max_delay = float(self._env_vars.get('AWS_TRANSFER_RETRY_MAX_DELAY', '60.0'))
                exponential_base = float(self._env_vars.get('AWS_TRANSFER_RETRY_EXPONENTIAL_BASE', '2.0'))

                # Validaciones
                if max_attempts <= 0:
                    raise ValueError("Max attempts must be positive")
                if base_delay < 0:
                    raise ValueError("Base delay cannot be negative")
                if max_delay < base_delay:
                    raise ValueError("Max delay must be greater than or equal to base delay")
                if exponential_base <= 1.0:
                    raise ValueError("Exponential base must be greater than 1.0")

                retry_config = RetryConfig(
                    max_attempts=max_attempts,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    exponential_base=exponential_base
                )
                self._config_cache['retry_config'] = retry_config

            except ValueError as e:
                raise ConfigurationError(
                    f"Invalid retry configuration: {str(e)}",
                    error_code="CONFIG_INVALID_RETRY_CONFIG"
                ) from e

        return self._config_cache['retry_config']

    def get_s3_bucket_name(self) -> Optional[str]:
        """
        Obtiene el nombre del bucket S3 por defecto (opcional).

        Returns:
            Optional[str]: Nombre del bucket S3 o None si no está configurado.
        """
        return self._env_vars.get('AWS_S3_BUCKET_NAME')

    def get_sftp_base_path(self) -> Optional[str]:
        """
        Obtiene la ruta base SFTP por defecto (opcional).

        Returns:
            Optional[str]: Ruta base SFTP o None si no está configurada.
        """
        return self._env_vars.get('AWS_TRANSFER_SFTP_BASE_PATH')

    def is_debug_enabled(self) -> bool:
        """
        Verifica si el modo debug está habilitado.

        Returns:
            bool: True si debug está habilitado, False en caso contrario.
        """
        debug_value = self._env_vars.get('AWS_TRANSFER_DEBUG', 'false').lower()
        return debug_value in ('true', '1', 'yes', 'on')

    def get_log_level(self) -> str:
        """
        Obtiene el nivel de logging configurado.

        Returns:
            str: Nivel de logging (default: 'INFO').
        """
        return self._env_vars.get('AWS_TRANSFER_LOG_LEVEL', 'INFO').upper()


    def get_all_config(self) -> Dict[str, any]:
        """
        Obtiene toda la configuración como un diccionario.

        Útil para debugging y logging de configuración.

        Returns:
            Dict[str, any]: Diccionario con toda la configuración (sin valores sensibles).
        """
        return {
            'connector_id': self.get_connector_id(),  # Puede ser None
            'throughput_limit': self.get_throughput_limit(),
            'max_concurrent_sessions': self.get_max_concurrent_sessions(),
            'retry_config': self.get_retry_config(),
            's3_bucket_name': self.get_s3_bucket_name(),
            'sftp_base_path': self.get_sftp_base_path(),
            'debug_enabled': self.is_debug_enabled(),
            'log_level': self.get_log_level()
        }
