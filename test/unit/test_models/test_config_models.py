"""
Tests para modelos de configuración.

Este módulo contiene tests unitarios para todos los dataclasses
relacionados con configuración de la librería.
"""

import pytest

from src.models.config_models import RetryConfig, TransferOptions


class TestRetryConfig:
    """Tests para el dataclass RetryConfig."""

    def test_retry_config_defaults(self):
        """Test valores por defecto de RetryConfig."""
        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0

    def test_retry_config_custom_values(self):
        """Test RetryConfig con valores personalizados."""
        config = RetryConfig(
            max_attempts=5,
            base_delay=2.0,
            max_delay=120.0,
            exponential_base=1.5
        )

        assert config.max_attempts == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 120.0
        assert config.exponential_base == 1.5

    def test_retry_config_partial_override(self):
        """Test RetryConfig con override parcial de valores."""
        config = RetryConfig(max_attempts=10, max_delay=300.0)

        assert config.max_attempts == 10
        assert config.base_delay == 1.0  # Valor por defecto
        assert config.max_delay == 300.0
        assert config.exponential_base == 2.0  # Valor por defecto

    def test_retry_config_equality(self):
        """Test igualdad entre instancias de RetryConfig."""
        config1 = RetryConfig(max_attempts=3, base_delay=1.0)
        config2 = RetryConfig(max_attempts=3, base_delay=1.0)
        config3 = RetryConfig(max_attempts=5, base_delay=1.0)

        assert config1 == config2
        assert config1 != config3

    def test_retry_config_edge_values(self):
        """Test RetryConfig con valores extremos."""
        # Valores mínimos
        config_min = RetryConfig(
            max_attempts=1,
            base_delay=0.1,
            max_delay=0.5,
            exponential_base=1.1
        )

        assert config_min.max_attempts == 1
        assert config_min.base_delay == 0.1
        assert config_min.max_delay == 0.5
        assert config_min.exponential_base == 1.1

        # Valores altos
        config_max = RetryConfig(
            max_attempts=100,
            base_delay=10.0,
            max_delay=3600.0,
            exponential_base=10.0
        )

        assert config_max.max_attempts == 100
        assert config_max.base_delay == 10.0
        assert config_max.max_delay == 3600.0
        assert config_max.exponential_base == 10.0


class TestTransferOptions:
    """Tests para el dataclass TransferOptions."""

    def test_transfer_options_defaults(self):
        """Test valores por defecto de TransferOptions."""
        options = TransferOptions()

        assert options.preserve_metadata is True
        assert options.overwrite_existing is False
        assert options.verify_checksum is True
        assert options.timeout_seconds == 300
        assert options.retry_config is not None
        assert isinstance(options.retry_config, RetryConfig)

    def test_transfer_options_custom_values(self):
        """Test TransferOptions con valores personalizados."""
        custom_retry = RetryConfig(max_attempts=5, base_delay=2.0)

        options = TransferOptions(
            preserve_metadata=False,
            overwrite_existing=True,
            verify_checksum=False,
            timeout_seconds=600,
            retry_config=custom_retry
        )

        assert options.preserve_metadata is False
        assert options.overwrite_existing is True
        assert options.verify_checksum is False
        assert options.timeout_seconds == 600
        assert options.retry_config == custom_retry

    def test_transfer_options_partial_override(self):
        """Test TransferOptions con override parcial."""
        options = TransferOptions(
            overwrite_existing=True,
            timeout_seconds=900
        )

        assert options.preserve_metadata is True  # Valor por defecto
        assert options.overwrite_existing is True
        assert options.verify_checksum is True  # Valor por defecto
        assert options.timeout_seconds == 900
        assert options.retry_config is not None  # Auto-inicializado

    def test_transfer_options_post_init(self):
        """Test que __post_init__ inicializa retry_config correctamente."""
        # Sin retry_config explícito
        options1 = TransferOptions()
        assert options1.retry_config is not None
        assert isinstance(options1.retry_config, RetryConfig)
        assert options1.retry_config.max_attempts == 3  # Valor por defecto de RetryConfig

        # Con retry_config explícito
        custom_retry = RetryConfig(max_attempts=10)
        options2 = TransferOptions(retry_config=custom_retry)
        assert options2.retry_config == custom_retry
        assert options2.retry_config.max_attempts == 10

    def test_transfer_options_none_retry_config(self):
        """Test que retry_config None se inicializa en __post_init__."""
        options = TransferOptions(retry_config=None)

        # __post_init__ debe haber creado un RetryConfig por defecto
        assert options.retry_config is not None
        assert isinstance(options.retry_config, RetryConfig)
        assert options.retry_config.max_attempts == 3

    def test_transfer_options_equality(self):
        """Test igualdad entre instancias de TransferOptions."""
        retry_config = RetryConfig(max_attempts=5)

        options1 = TransferOptions(
            preserve_metadata=True,
            overwrite_existing=False,
            retry_config=retry_config
        )

        options2 = TransferOptions(
            preserve_metadata=True,
            overwrite_existing=False,
            retry_config=retry_config
        )

        options3 = TransferOptions(
            preserve_metadata=False,
            overwrite_existing=False,
            retry_config=retry_config
        )

        assert options1 == options2
        assert options1 != options3

    def test_transfer_options_timeout_values(self):
        """Test diferentes valores de timeout."""
        # Timeout corto
        options_short = TransferOptions(timeout_seconds=30)
        assert options_short.timeout_seconds == 30

        # Timeout largo
        options_long = TransferOptions(timeout_seconds=3600)
        assert options_long.timeout_seconds == 3600

        # Timeout por defecto
        options_default = TransferOptions()
        assert options_default.timeout_seconds == 300


# Tests de integración entre modelos de configuración
class TestConfigModelIntegration:
    """Tests de integración entre modelos de configuración."""

    def test_transfer_options_with_custom_retry_config(self):
        """Test integración completa entre TransferOptions y RetryConfig."""
        # Crear configuración de reintentos personalizada
        retry_config = RetryConfig(
            max_attempts=10,
            base_delay=0.5,
            max_delay=30.0,
            exponential_base=1.5
        )

        # Crear opciones de transferencia con la configuración personalizada
        options = TransferOptions(
            preserve_metadata=False,
            overwrite_existing=True,
            verify_checksum=True,
            timeout_seconds=1800,
            retry_config=retry_config
        )

        # Verificar que todo está conectado correctamente
        assert options.retry_config == retry_config
        assert options.retry_config.max_attempts == 10
        assert options.retry_config.base_delay == 0.5
        assert options.retry_config.max_delay == 30.0
        assert options.retry_config.exponential_base == 1.5

        # Verificar que las opciones de transferencia son independientes
        assert options.preserve_metadata is False
        assert options.overwrite_existing is True
        assert options.verify_checksum is True
        assert options.timeout_seconds == 1800

    def test_multiple_transfer_options_with_shared_retry_config(self):
        """Test múltiples TransferOptions compartiendo la misma RetryConfig."""
        shared_retry = RetryConfig(max_attempts=7, base_delay=2.0)

        # Opciones para uploads
        upload_options = TransferOptions(
            preserve_metadata=True,
            overwrite_existing=False,
            retry_config=shared_retry
        )

        # Opciones para downloads
        download_options = TransferOptions(
            preserve_metadata=False,
            overwrite_existing=True,
            retry_config=shared_retry
        )

        # Ambas deben compartir la misma configuración de reintentos
        assert upload_options.retry_config is shared_retry
        assert download_options.retry_config is shared_retry
        assert upload_options.retry_config == download_options.retry_config

        # Pero tener diferentes opciones de transferencia
        assert upload_options.preserve_metadata != download_options.preserve_metadata
        assert upload_options.overwrite_existing != download_options.overwrite_existing

    def test_config_modification_scenarios(self):
        """Test escenarios de modificación de configuración."""
        # Configuración inicial
        initial_retry = RetryConfig(max_attempts=3)
        options = TransferOptions(retry_config=initial_retry)

        assert options.retry_config.max_attempts == 3

        # Modificar configuración de reintentos
        # Nota: Los dataclasses son inmutables por defecto, pero podemos crear nuevos
        new_retry = RetryConfig(
            max_attempts=5,
            base_delay=initial_retry.base_delay,
            max_delay=initial_retry.max_delay,
            exponential_base=initial_retry.exponential_base
        )

        new_options = TransferOptions(
            preserve_metadata=options.preserve_metadata,
            overwrite_existing=options.overwrite_existing,
            verify_checksum=options.verify_checksum,
            timeout_seconds=options.timeout_seconds,
            retry_config=new_retry
        )

        assert new_options.retry_config.max_attempts == 5
        assert options.retry_config.max_attempts == 3  # Original no modificado