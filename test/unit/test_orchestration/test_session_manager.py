"""
Tests para SessionManager.

Este módulo contiene tests unitarios para el gestor de sesiones concurrentes
que maneja el pool de sesiones para AWS Transfer Family.
"""

import pytest
import time
import threading
from unittest.mock import patch, MagicMock
from queue import Empty

from src.orchestration.session_manager import SessionManager, Session
from src.exceptions.transfer_exceptions import TransferError, ThrottleError


class TestSession:
    """Tests para la clase Session."""

    def test_session_creation_basic(self):
        """Test creación básica de Session."""
        session = Session(
            session_id="test-session-123",
            connector_id="connector-456",
            created_at=1000.0,
            last_used=1000.0
        )

        assert session.session_id == "test-session-123"
        assert session.connector_id == "connector-456"
        assert session.created_at == 1000.0
        assert session.last_used == 1000.0
        assert session.is_active is True

    def test_session_creation_with_defaults(self):
        """Test creación de Session con valores por defecto."""
        session = Session(
            session_id="test-session",
            connector_id="connector-123",
            created_at=1000.0,
            last_used=1000.0,
            is_active=False
        )

        assert session.is_active is False

    def test_session_post_init_generates_id(self):
        """Test que __post_init__ genera ID si está vacío."""
        session = Session(
            session_id="",
            connector_id="connector-123",
            created_at=1000.0,
            last_used=1000.0
        )

        # Debería haber generado un UUID
        assert session.session_id != ""
        assert len(session.session_id) > 10  # UUIDs son largos


class TestSessionManagerInitialization:
    """Tests para la inicialización de SessionManager."""

    def test_initialization_default_values(self):
        """Test inicialización con valores por defecto."""
        manager = SessionManager("connector-123")

        assert manager.connector_id == "connector-123"
        assert manager.max_sessions == 5
        assert manager.session_timeout == 300
        assert manager.available_sessions.qsize() == 2  # Sesiones iniciales
        assert len(manager.active_sessions) == 0

    def test_initialization_custom_values(self):
        """Test inicialización con valores personalizados."""
        manager = SessionManager(
            connector_id="connector-456",
            max_sessions=3,
            session_timeout=600
        )

        assert manager.connector_id == "connector-456"
        assert manager.max_sessions == 3
        assert manager.session_timeout == 600
        assert manager.available_sessions.qsize() == 2  # min(2, 3)

    def test_initialization_invalid_connector_id(self):
        """Test inicialización con connector_id inválido."""
        with pytest.raises(TransferError) as exc_info:
            SessionManager("")

        assert exc_info.value.error_code == "INVALID_CONNECTOR_ID"

        with pytest.raises(TransferError):
            SessionManager(None)

    def test_initialization_invalid_max_sessions(self):
        """Test inicialización con max_sessions inválido."""
        with pytest.raises(TransferError) as exc_info:
            SessionManager("connector-123", max_sessions=0)

        assert exc_info.value.error_code == "INVALID_MAX_SESSIONS"

        with pytest.raises(TransferError):
            SessionManager("connector-123", max_sessions=6)

    def test_initialization_invalid_session_timeout(self):
        """Test inicialización con session_timeout inválido."""
        with pytest.raises(TransferError) as exc_info:
            SessionManager("connector-123", session_timeout=0)

        assert exc_info.value.error_code == "INVALID_SESSION_TIMEOUT"

        with pytest.raises(TransferError):
            SessionManager("connector-123", session_timeout=-10)


class TestAcquireSession:
    """Tests para el método acquire_session."""

    def test_acquire_session_from_available_pool(self):
        """Test adquisición de sesión del pool disponible."""
        manager = SessionManager("connector-123", max_sessions=3)

        # Debería haber sesiones disponibles
        initial_available = manager.available_sessions.qsize()
        assert initial_available > 0

        session = manager.acquire_session()

        assert session is not None
        assert session.connector_id == "connector-123"
        assert session.is_active is True
        assert session.session_id in manager.active_sessions
        assert manager.available_sessions.qsize() == initial_available - 1

    def test_acquire_session_create_new_when_needed(self):
        """Test creación de nueva sesión cuando es necesario."""
        manager = SessionManager("connector-123", max_sessions=5)

        # Vaciar el pool disponible
        sessions = []
        while not manager.available_sessions.empty():
            sessions.append(manager.available_sessions.get())

        # Adquirir sesión debería crear una nueva
        session = manager.acquire_session()

        assert session is not None
        assert session.connector_id == "connector-123"
        assert session.session_id in manager.active_sessions

    def test_acquire_session_timeout(self):
        """Test timeout al adquirir sesión."""
        manager = SessionManager("connector-123", max_sessions=1)

        # Adquirir la única sesión disponible
        session1 = manager.acquire_session()

        # Intentar adquirir otra con timeout corto debería fallar
        with pytest.raises(ThrottleError) as exc_info:
            manager.acquire_session(timeout=0.1)

        assert exc_info.value.error_code == "SESSION_ACQUIRE_TIMEOUT"

    def test_acquire_session_concurrent_access(self):
        """Test acceso concurrente a acquire_session."""
        manager = SessionManager("connector-123", max_sessions=3)
        sessions_acquired = []
        errors = []

        def acquire_session_thread():
            try:
                session = manager.acquire_session(timeout=1.0)
                sessions_acquired.append(session)
                time.sleep(0.1)  # Simular uso
                manager.release_session(session)
            except Exception as e:
                errors.append(e)

        # Lanzar múltiples threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=acquire_session_thread)
            threads.append(thread)
            thread.start()

        # Esperar a que terminen
        for thread in threads:
            thread.join()

        # Verificar resultados
        assert len(errors) == 0  # No debería haber errores
        assert len(sessions_acquired) == 5  # Todas deberían haber adquirido sesión

    @patch('time.time')
    def test_acquire_session_cleanup_expired(self, mock_time):
        """Test limpieza de sesiones expiradas al adquirir."""
        manager = SessionManager("connector-123", max_sessions=3, session_timeout=100)

        # Configurar tiempo inicial
        initial_time = 1000.0
        mock_time.return_value = initial_time

        # Crear sesión expirada manualmente con valores reales (no mocks)
        expired_session = Session(
            session_id="expired-session",
            connector_id="connector-123",
            created_at=initial_time - 200,  # Valores reales
            last_used=initial_time - 200,   # Valores reales
            is_active=False
        )
        manager.available_sessions.put(expired_session)

        # Avanzar el tiempo
        mock_time.return_value = initial_time + 50

        # Adquirir sesión debería limpiar la expirada
        session = manager.acquire_session()

        assert session.session_id != "expired-session"
        assert session.connector_id == "connector-123"


class TestReleaseSession:
    """Tests para el método release_session."""

    def test_release_session_basic(self):
        """Test liberación básica de sesión."""
        manager = SessionManager("connector-123", max_sessions=3)

        # Adquirir y liberar sesión
        session = manager.acquire_session()
        initial_active = len(manager.active_sessions)
        initial_available = manager.available_sessions.qsize()

        manager.release_session(session)

        assert session.session_id not in manager.active_sessions
        assert len(manager.active_sessions) == initial_active - 1
        assert manager.available_sessions.qsize() == initial_available + 1
        assert session.is_active is False

    def test_release_session_invalid_session(self):
        """Test liberación de sesión inválida."""
        manager = SessionManager("connector-123")

        # Sesión None
        with pytest.raises(TransferError) as exc_info:
            manager.release_session(None)

        assert exc_info.value.error_code == "INVALID_SESSION_RELEASE"

        # Sesión sin ID
        invalid_session = Session("", "connector-123", 1000.0, 1000.0)
        invalid_session.session_id = ""

        with pytest.raises(TransferError):
            manager.release_session(invalid_session)

    def test_release_session_not_in_active_set(self):
        """Test liberación de sesión que no está en el set activo."""
        manager = SessionManager("connector-123")

        # Crear sesión que no fue adquirida por el manager
        external_session = Session(
            session_id="external-session",
            connector_id="connector-123",
            created_at=1000.0,
            last_used=1000.0
        )

        # Debería manejar gracefully
        manager.release_session(external_session)

        # No debería estar en activas, pero podría estar en disponibles
        assert "external-session" not in manager.active_sessions

    @patch('time.time')
    def test_release_session_expired(self, mock_time):
        """Test liberación de sesión expirada."""
        manager = SessionManager("connector-123", session_timeout=100)

        # Configurar tiempo
        initial_time = 1000.0
        mock_time.return_value = initial_time

        session = manager.acquire_session()

        # Modificar manualmente los timestamps de la sesión para que expire
        session.created_at = initial_time - 200
        session.last_used = initial_time - 200

        # Avanzar tiempo para que expire
        mock_time.return_value = initial_time + 200

        # Liberar sesión expirada
        manager.release_session(session)

        # No debería volver al pool disponible
        assert session.session_id not in manager.active_sessions


class TestSessionManagerStats:
    """Tests para métodos de estadísticas."""

    def test_get_available_sessions(self):
        """Test get_available_sessions."""
        manager = SessionManager("connector-123", max_sessions=3)

        available = manager.get_available_sessions()
        assert available >= 0
        assert available <= manager.max_sessions

    def test_get_active_sessions(self):
        """Test get_active_sessions."""
        manager = SessionManager("connector-123", max_sessions=3)

        initial_active = manager.get_active_sessions()
        assert initial_active == 0

        # Adquirir sesión
        session = manager.acquire_session()

        active_after = manager.get_active_sessions()
        assert active_after == initial_active + 1

        # Liberar sesión
        manager.release_session(session)

        active_final = manager.get_active_sessions()
        assert active_final == initial_active

    def test_get_total_sessions(self):
        """Test get_total_sessions."""
        manager = SessionManager("connector-123", max_sessions=5)

        total = manager.get_total_sessions()
        assert total >= 0
        assert total <= manager.max_sessions

        # Adquirir sesión
        session = manager.acquire_session()

        total_after = manager.get_total_sessions()
        # El total podría ser igual o mayor dependiendo de si se creó nueva sesión
        assert total_after >= total


class TestSessionValidation:
    """Tests para validación de sesiones."""

    @patch('time.time')
    def test_is_session_valid_basic(self, mock_time):
        """Test validación básica de sesión."""
        manager = SessionManager("connector-123", session_timeout=300)

        current_time = 1000.0
        mock_time.return_value = current_time

        # Sesión válida
        valid_session = Session(
            session_id="valid-session",
            connector_id="connector-123",
            created_at=current_time - 100,
            last_used=current_time - 50
        )

        assert manager._is_session_valid(valid_session) is True

    @patch('time.time')
    def test_is_session_valid_expired(self, mock_time):
        """Test validación de sesión expirada."""
        manager = SessionManager("connector-123", session_timeout=300)

        current_time = 1000.0
        mock_time.return_value = current_time

        # Sesión expirada
        expired_session = Session(
            session_id="expired-session",
            connector_id="connector-123",
            created_at=current_time - 500,
            last_used=current_time - 400  # Más de 300s atrás
        )

        assert manager._is_session_valid(expired_session) is False

    def test_is_session_valid_wrong_connector(self):
        """Test validación de sesión con conector incorrecto."""
        manager = SessionManager("connector-123")

        # Sesión con conector diferente
        wrong_connector_session = Session(
            session_id="session-456",
            connector_id="different-connector",
            created_at=1000.0,
            last_used=1000.0
        )

        assert manager._is_session_valid(wrong_connector_session) is False

    def test_is_session_valid_none_or_empty(self):
        """Test validación de sesión None o vacía."""
        manager = SessionManager("connector-123")

        # Sesión None
        assert manager._is_session_valid(None) is False

        # Sesión sin ID
        empty_session = Session("", "connector-123", 1000.0, 1000.0)
        empty_session.session_id = ""
        assert manager._is_session_valid(empty_session) is False


class TestSessionCleanup:
    """Tests para limpieza de sesiones."""

    @patch('time.time')
    def test_cleanup_expired_sessions(self, mock_time):
        """Test limpieza de sesiones expiradas."""
        manager = SessionManager("connector-123", max_sessions=5, session_timeout=100)

        current_time = 1000.0
        mock_time.return_value = current_time

        # Agregar sesiones válidas y expiradas manualmente
        valid_session = Session(
            session_id="valid-session",
            connector_id="connector-123",
            created_at=current_time - 50,
            last_used=current_time - 30,
            is_active=False
        )

        expired_session = Session(
            session_id="expired-session",
            connector_id="connector-123",
            created_at=current_time - 200,
            last_used=current_time - 150,
            is_active=False
        )

        # Limpiar pool y agregar sesiones de prueba
        while not manager.available_sessions.empty():
            manager.available_sessions.get()

        manager.available_sessions.put(valid_session)
        manager.available_sessions.put(expired_session)

        initial_size = manager.available_sessions.qsize()
        assert initial_size == 2

        # Ejecutar limpieza
        manager._cleanup_expired_sessions()

        # Solo la sesión válida debería quedar
        final_size = manager.available_sessions.qsize()
        assert final_size == 1

        # Verificar que la sesión restante es la válida
        remaining_session = manager.available_sessions.get()
        assert remaining_session.session_id == "valid-session"


class TestSessionManagerShutdown:
    """Tests para el shutdown del SessionManager."""

    def test_shutdown_cleans_resources(self):
        """Test que shutdown limpia todos los recursos."""
        manager = SessionManager("connector-123", max_sessions=3)

        # Adquirir algunas sesiones
        session1 = manager.acquire_session()
        session2 = manager.acquire_session()

        initial_active = len(manager.active_sessions)
        initial_available = manager.available_sessions.qsize()

        assert initial_active > 0
        assert initial_available >= 0

        # Shutdown
        manager.shutdown()

        # Todo debería estar limpio
        assert len(manager.active_sessions) == 0
        assert manager.available_sessions.qsize() == 0


# Tests de integración
class TestSessionManagerIntegration:
    """Tests de integración para SessionManager."""

    def test_full_lifecycle(self):
        """Test ciclo de vida completo de sesiones."""
        manager = SessionManager("connector-123", max_sessions=2)

        # Adquirir sesiones hasta el límite
        session1 = manager.acquire_session()
        session2 = manager.acquire_session()

        assert manager.get_active_sessions() == 2
        assert manager.get_available_sessions() == 0

        # Intentar adquirir otra debería crear nueva o esperar
        try:
            session3 = manager.acquire_session(timeout=0.1)
            # Si se creó, liberar inmediatamente
            manager.release_session(session3)
        except ThrottleError:
            # Esperado si no se pudo crear nueva sesión
            pass

        # Liberar sesiones
        manager.release_session(session1)
        manager.release_session(session2)

        assert manager.get_active_sessions() == 0
        assert manager.get_available_sessions() >= 0

    def test_stress_test_acquire_release(self):
        """Test de estrés para acquire/release."""
        manager = SessionManager("connector-123", max_sessions=3)

        # Múltiples ciclos de acquire/release
        for i in range(10):
            sessions = []

            # Adquirir múltiples sesiones
            for j in range(2):
                try:
                    session = manager.acquire_session(timeout=0.5)
                    sessions.append(session)
                except ThrottleError:
                    # Esperado si no hay sesiones disponibles
                    break

            # Liberar todas las sesiones
            for session in sessions:
                manager.release_session(session)

            # Verificar estado consistente
            assert manager.get_active_sessions() == 0

    def test_concurrent_stress_test(self):
        """Test de estrés concurrente."""
        manager = SessionManager("connector-123", max_sessions=5)
        results = {"acquired": 0, "released": 0, "errors": 0}

        def worker():
            try:
                session = manager.acquire_session(timeout=1.0)
                results["acquired"] += 1
                time.sleep(0.01)  # Simular trabajo
                manager.release_session(session)
                results["released"] += 1
            except Exception:
                results["errors"] += 1

        # Lanzar múltiples workers
        threads = []
        for _ in range(20):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        # Esperar a que terminen
        for thread in threads:
            thread.join()

        # Verificar resultados
        assert results["acquired"] == results["released"]
        assert results["errors"] == 0
        assert manager.get_active_sessions() == 0