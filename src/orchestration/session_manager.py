"""
SessionManager para gestión de sesiones concurrentes.

Este módulo implementa la gestión de un pool de sesiones concurrentes
para AWS Transfer Family, respetando el límite de 5 sesiones por conector.
"""

import time
import uuid
from queue import Queue, Empty, Full
from threading import Lock, RLock
from typing import Set, Optional
from dataclasses import dataclass
from src.exceptions.transfer_exceptions import TransferError, ThrottleError


@dataclass
class Session:
    """
    Representa una sesión de transferencia.

    Attributes:
        session_id: Identificador único de la sesión
        connector_id: ID del conector AWS Transfer Family
        created_at: Timestamp de creación
        last_used: Timestamp del último uso
        is_active: Indica si la sesión está activa
    """
    session_id: str
    connector_id: str
    created_at: float
    last_used: float
    is_active: bool = True

    def __post_init__(self):
        """Inicializa campos calculados."""
        if not self.session_id:
            self.session_id = str(uuid.uuid4())


class SessionManager:
    """
    Gestor de sesiones concurrentes para AWS Transfer Family.

    Implementa un pool de sesiones con un máximo de 5 sesiones concurrentes
    por conector, con gestión de queue y balanceador de carga.

    Attributes:
        max_sessions: Número máximo de sesiones concurrentes (default: 5)
        connector_id: ID del conector AWS Transfer Family
        available_sessions: Queue de sesiones disponibles
        active_sessions: Set de sesiones activas
        session_timeout: Timeout para sesiones inactivas en segundos
    """

    def __init__(self, connector_id: str, max_sessions: int = 5, session_timeout: int = 300):
        """
        Inicializa el SessionManager.

        Args:
            connector_id: ID del conector AWS Transfer Family
            max_sessions: Número máximo de sesiones concurrentes
            session_timeout: Timeout para sesiones inactivas en segundos

        Raises:
            TransferError: Si los parámetros son inválidos
        """
        if not connector_id:
            raise TransferError(
                "connector_id no puede estar vacío",
                error_code="INVALID_CONNECTOR_ID"
            )

        if max_sessions <= 0 or max_sessions > 5:
            raise TransferError(
                "max_sessions debe estar entre 1 y 5",
                error_code="INVALID_MAX_SESSIONS"
            )

        if session_timeout <= 0:
            raise TransferError(
                "session_timeout debe ser mayor que 0",
                error_code="INVALID_SESSION_TIMEOUT"
            )

        self.connector_id = connector_id
        self.max_sessions = max_sessions
        self.session_timeout = session_timeout

        # Thread-safe collections
        self.available_sessions: Queue[Session] = Queue(maxsize=max_sessions)
        self.active_sessions: Set[str] = set()

        # Locks para thread safety
        self._lock = RLock()
        self._active_lock = Lock()

        # Inicializar pool de sesiones
        self._initialize_session_pool()

    def acquire_session(self, timeout: Optional[float] = None) -> Session:
        """
        Adquiere una sesión del pool.

        Args:
            timeout: Tiempo máximo de espera en segundos (None = sin límite)

        Returns:
            Sesión adquirida

        Raises:
            ThrottleError: Si no hay sesiones disponibles en el tiempo especificado
            TransferError: Si hay un error interno
        """
        start_time = time.time()

        while True:
            try:
                with self._lock:
                    # Limpiar sesiones expiradas
                    self._cleanup_expired_sessions()

                    # Intentar obtener sesión disponible
                    try:
                        session = self.available_sessions.get_nowait()

                        # Marcar como activa
                        with self._active_lock:
                            self.active_sessions.add(session.session_id)

                        # Actualizar timestamp
                        session.last_used = time.time()
                        session.is_active = True

                        return session

                    except Empty:
                        # No hay sesiones disponibles
                        pass

                    # Verificar si podemos crear una nueva sesión
                    total_sessions = len(self.active_sessions) + self.available_sessions.qsize()
                    if total_sessions < self.max_sessions:
                        session = self._create_session()

                        with self._active_lock:
                            self.active_sessions.add(session.session_id)

                        return session

                # Verificar timeout
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= timeout:
                        raise ThrottleError(
                            f"Timeout esperando sesión después de {timeout}s",
                            error_code="SESSION_ACQUIRE_TIMEOUT",
                            context={
                                "active_sessions": len(self.active_sessions),
                                "available_sessions": self.available_sessions.qsize(),
                                "max_sessions": self.max_sessions
                            }
                        )

                # Esperar un poco antes de reintentar
                time.sleep(0.1)

            except Exception as e:
                if isinstance(e, (ThrottleError, TransferError)):
                    raise

                raise TransferError(
                    f"Error adquiriendo sesión: {str(e)}",
                    error_code="SESSION_ACQUIRE_ERROR",
                    context={"original_error": str(e)}
                ) from e

    def release_session(self, session: Session) -> None:
        """
        Libera una sesión de vuelta al pool.

        Args:
            session: Sesión a liberar

        Raises:
            TransferError: Si la sesión es inválida
        """
        if not session or not session.session_id:
            raise TransferError(
                "Sesión inválida para liberar",
                error_code="INVALID_SESSION_RELEASE"
            )

        try:
            with self._lock:
                # Remover de sesiones activas
                with self._active_lock:
                    if session.session_id in self.active_sessions:
                        self.active_sessions.remove(session.session_id)

                # Verificar si la sesión sigue siendo válida
                if self._is_session_valid(session):
                    # Actualizar estado y devolver al pool
                    session.is_active = False
                    session.last_used = time.time()

                    try:
                        self.available_sessions.put_nowait(session)
                    except Full:
                        # Pool lleno, descartar sesión
                        pass
                else:
                    # Sesión expirada, no la devolvemos al pool
                    pass

        except Exception as e:
            raise TransferError(
                f"Error liberando sesión: {str(e)}",
                error_code="SESSION_RELEASE_ERROR",
                context={"session_id": session.session_id, "original_error": str(e)}
            ) from e

    def get_available_sessions(self) -> int:
        """
        Obtiene el número de sesiones disponibles.

        Returns:
            Número de sesiones disponibles
        """
        with self._lock:
            self._cleanup_expired_sessions()
            return self.available_sessions.qsize()

    def get_active_sessions(self) -> int:
        """
        Obtiene el número de sesiones activas.

        Returns:
            Número de sesiones activas
        """
        with self._active_lock:
            return len(self.active_sessions)

    def get_total_sessions(self) -> int:
        """
        Obtiene el número total de sesiones (activas + disponibles).

        Returns:
            Número total de sesiones
        """
        with self._lock:
            return len(self.active_sessions) + self.available_sessions.qsize()

    def _initialize_session_pool(self) -> None:
        """Inicializa el pool de sesiones con sesiones pre-creadas."""
        # Crear algunas sesiones iniciales (no todas para permitir crecimiento dinámico)
        initial_sessions = min(2, self.max_sessions)

        for _ in range(initial_sessions):
            session = self._create_session()
            session.is_active = False
            self.available_sessions.put(session)

    def _create_session(self) -> Session:
        """
        Crea una nueva sesión.

        Returns:
            Nueva sesión creada
        """
        current_time = time.time()

        return Session(
            session_id=str(uuid.uuid4()),
            connector_id=self.connector_id,
            created_at=current_time,
            last_used=current_time,
            is_active=True
        )

    def _is_session_valid(self, session: Session) -> bool:
        """
        Verifica si una sesión sigue siendo válida.

        Args:
            session: Sesión a verificar

        Returns:
            True si la sesión es válida
        """
        if not session or not session.session_id:
            return False

        current_time = time.time()

        # Verificar timeout
        if float(current_time) - float(session.last_used) > self.session_timeout:
            return False

        # Verificar que pertenezca al conector correcto
        if session.connector_id != self.connector_id:
            return False

        return True

    def _cleanup_expired_sessions(self) -> None:
        """Limpia sesiones expiradas del pool."""

        # Limpiar sesiones disponibles expiradas
        valid_sessions = []

        while not self.available_sessions.empty():
            try:
                session = self.available_sessions.get_nowait()
                if self._is_session_valid(session):
                    valid_sessions.append(session)
            except Empty:
                break

        # Devolver sesiones válidas al pool
        for session in valid_sessions:
            try:
                self.available_sessions.put_nowait(session)
            except Full:
                # Pool lleno, descartar
                break

    def shutdown(self) -> None:
        """
        Cierra el SessionManager y limpia recursos.
        """
        with self._lock:
            # Limpiar sesiones disponibles
            while not self.available_sessions.empty():
                try:
                    self.available_sessions.get_nowait()
                except Empty:
                    break

            # Limpiar sesiones activas
            with self._active_lock:
                self.active_sessions.clear()
