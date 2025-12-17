"""
Configuración global para tests de pytest.

Este archivo configura el entorno de testing para la estructura Lambda,
incluyendo fixtures compartidos y configuración de paths.
"""
import pytest
from unittest.mock import patch

# Fixtures globales
@pytest.fixture
def mock_environment():
    """Fixture que configura variables de entorno para tests."""
    env_vars = {
        'AWS_TRANSFER_CONNECTOR_ID': 'test-connector-123',
        'AWS_TRANSFER_THROUGHPUT_LIMIT': '100',
        'AWS_TRANSFER_MAX_CONCURRENT_SESSIONS': '5'
    }

    with patch.dict('os.environ', env_vars):
        yield env_vars

# Configuración de pytest
def pytest_configure(config):
    """Configuración inicial de pytest."""
    config.addinivalue_line("markers", "unit: marca tests unitarios")
    config.addinivalue_line("markers", "integration: marca tests de integración")
    config.addinivalue_line("markers", "slow: marca tests que tardan mucho")

def pytest_collection_modifyitems(config, items):
    """Modifica la colección de tests para agregar marcadores automáticamente."""
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)

        if "end_to_end" in item.name or "large_batch" in item.name:
            item.add_marker(pytest.mark.slow)