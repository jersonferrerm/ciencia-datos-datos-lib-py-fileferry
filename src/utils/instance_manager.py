"""
Implementación de InstanceManager para concurrencia Lambda-safe.
Gestiona estado específico de instancia y recursos para ejecución concurrente de Lambda.
"""

import os
import time
import uuid
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from queue import Queue, Empty
from contextlib import contextmanager

from src.utils.logger import StructuredLogger


@dataclass
class SessionPool:
    """Pool de sesiones local para esta instancia Lambda"""
    max_sessions: int = 5
    available_sessions: Queue = field(default_factory=lambda: Queue(maxsize=5))
    active_sessions: Dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        """Inicializa el pool de sesiones con sesiones disponibles"""
        for i in range(self.max_sessions):
            session_id = f"session-{i+1}"
            self.available_sessions.put(session_id)

    def mark_session_active(self, session_id: str, instance_id: str) -> None:
        """Marca una sesión como activa de forma thread-safe"""
        with self._lock:
            self.active_sessions[session_id] = {
                'acquired_at': time.time(),
                'instance_id': instance_id
            }

    def release_session(self, session_id: str) -> bool:
        """Libera una sesión de vuelta al pool de forma thread-safe"""
        with self._lock:
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
                self.available_sessions.put(session_id)
                return True
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del pool de forma thread-safe"""
        with self._lock:
            return {
                'total_sessions': self.max_sessions,
                'available_sessions': self.available_sessions.qsize(),
                'active_sessions': len(self.active_sessions),
                'active_session_ids': list(self.active_sessions.keys())
            }

    def clear_active_sessions(self) -> None:
        """Limpia todas las sesiones activas de forma thread-safe"""
        with self._lock:
            self.active_sessions.clear()


@dataclass
class ThrottleState:
    """Estado de throttle local para esta instancia Lambda"""
    current_rate: float = 0.0
    last_request_time: float = field(default_factory=time.time)
    request_count: int = 0
    window_start: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def update_state(self, files_processed: int) -> None:
        """Actualiza el estado de throttle de forma thread-safe"""
        current_time = time.time()

        with self._lock:
            # Resetear ventana si han pasado más de 1 segundo
            if current_time - self.window_start >= 1.0:
                self.request_count = 0
                self.window_start = current_time

            # Actualizar contadores
            self.request_count += files_processed
            self.last_request_time = current_time

            # Calcular tasa actual (archivos por segundo)
            window_duration = current_time - self.window_start
            if window_duration > 0:
                self.current_rate = self.request_count / window_duration

    def get_current_rate(self) -> float:
        """Obtiene la tasa actual de forma thread-safe"""
        current_time = time.time()

        with self._lock:
            window_duration = current_time - self.window_start

            # Si la ventana es muy antigua, resetear tasa
            if window_duration > 5.0:  # Ventana de 5 segundos
                self.current_rate = 0.0
                self.request_count = 0
                self.window_start = current_time

            return self.current_rate

    def reset_state(self) -> None:
        """Resetea el estado de throttle de forma thread-safe"""
        with self._lock:
            self.current_rate = 0.0
            self.request_count = 0
            self.window_start = time.time()


class InstanceManager:
    """
    Gestiona estado específico de instancia para concurrencia Lambda-safe.
    Implementa los requerimientos 8.1, 8.2, 8.3, 8.4, 8.5 para ejecución concurrente de Lambda.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Patrón singleton para asegurar una instancia por contenedor Lambda"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Inicializa el gestor de instancia con estado único de instancia"""
        if hasattr(self, '_initialized'):
            return

        self.instance_id = self._generate_instance_id()
        self.container_id = self._get_container_id()
        self.local_session_pool = SessionPool()
        self.local_throttle_state = ThrottleState()
        self.logger: Optional[StructuredLogger] = None
        self._initialized = True

        # Inicializar logger después de configurar la instancia
        self._setup_logger()

    def _generate_instance_id(self) -> str:
        """
        Genera un ID único para esta instancia Lambda.

        Returns:
            Identificador único de instancia
        """
        # Combinar UUID con timestamp para unicidad
        unique_part = str(uuid.uuid4())[:8]
        timestamp = int(time.time() * 1000)  # Precisión de milisegundos

        # Incluir info del contenedor si está disponible
        container_info = self._get_container_id()[:8] if self._get_container_id() else "unknown"

        return f"lambda-{container_info}-{unique_part}-{timestamp}"

    def _get_container_id(self) -> str:
        """
        Obtiene el identificador del contenedor Lambda del entorno.

        Returns:
            Identificador del contenedor o 'unknown'
        """
        # Intentar obtener el endpoint de runtime API de AWS Lambda que contiene info del contenedor
        runtime_api = os.environ.get('AWS_LAMBDA_RUNTIME_API', '')
        if runtime_api:
            # Extraer identificador tipo contenedor del runtime API
            return runtime_api.split('.')[0] if '.' in runtime_api else runtime_api[:16]

        # Fallback a otras variables de entorno
        request_id = os.environ.get('AWS_LAMBDA_LOG_GROUP_NAME', '')
        if request_id:
            return request_id.split('/')[-1][:16] if '/' in request_id else request_id[:16]

        return "unknown"

    def _setup_logger(self) -> None:
        """Configura el logger estructurado para esta instancia"""

        self.logger = StructuredLogger(self.instance_id)
        # Use a simple info log instead of the protected method
        self.logger.logger.info(
            f"Instance manager initialized for container {self.container_id} "
            f"with {self.local_session_pool.max_sessions} max sessions"
        )

    def get_instance_id(self) -> str:
        """
        Obtiene el identificador único de instancia.

        Returns:
            ID de instancia
        """
        return self.instance_id

    def get_container_id(self) -> str:
        """
        Obtiene el identificador del contenedor.

        Returns:
            ID del contenedor
        """
        return self.container_id

    @contextmanager
    def acquire_session(self, timeout: float = 30.0):
        """
        Context manager para adquirir una sesión del pool local.

        Args:
            timeout: Tiempo máximo a esperar por una sesión

        Yields:
            Identificador de sesión

        Raises:
            TimeoutError: Si ninguna sesión se vuelve disponible dentro del timeout
        """
        session_id = None
        start_time = time.time()

        try:
            # Intentar obtener una sesión del pool
            while time.time() - start_time < timeout:
                try:
                    session_id = self.local_session_pool.available_sessions.get(timeout=1.0)
                    break
                except Empty:
                    continue

            if session_id is None:
                raise TimeoutError(f"No session available within {timeout} seconds")

            # Marcar sesión como activa
            self.local_session_pool.mark_session_active(session_id, self.instance_id)

            if self.logger:
                self.logger.log_session_event(
                    "acquire",
                    session_id,
                    self.local_session_pool.available_sessions.qsize()
                )

            yield session_id

        finally:
            # Siempre liberar la sesión de vuelta al pool
            if session_id:
                self._release_session(session_id)

    def _release_session(self, session_id: str) -> None:
        """
        Libera una sesión de vuelta al pool.

        Args:
            session_id: Sesión a liberar
        """
        if self.local_session_pool.release_session(session_id):
            if self.logger:
                self.logger.log_session_event(
                    "release",
                    session_id,
                    self.local_session_pool.available_sessions.qsize()
                )

    def get_session_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas actuales del pool de sesiones.

        Returns:
            Diccionario con estadísticas de sesiones
        """
        return self.local_session_pool.get_stats()

    def update_throttle_state(self, files_processed: int) -> None:
        """
        Actualiza el estado de throttle local con actividad reciente.

        Args:
            files_processed: Número de archivos procesados en esta operación
        """
        self.local_throttle_state.update_state(files_processed)

    def get_current_rate(self) -> float:
        """
        Obtiene la tasa de transferencia actual para esta instancia.

        Returns:
            Tasa actual en archivos por segundo
        """
        return self.local_throttle_state.get_current_rate()

    def can_proceed_with_rate(self, files_count: int, max_rate: float = 100.0) -> bool:
        """
        Verifica si podemos proceder con una transferencia sin exceder límites de tasa.

        Args:
            files_count: Número de archivos a transferir
            max_rate: Tasa máxima permitida (archivos por segundo)

        Returns:
            True si podemos proceder sin exceder límites
        """
        current_rate = self.get_current_rate()
        projected_rate = current_rate + files_count

        return projected_rate <= max_rate

    def calculate_throttle_delay(self, files_count: int, max_rate: float = 100.0) -> float:
        """
        Calcula el retraso necesario para respetar límites de tasa.

        Args:
            files_count: Número de archivos a transferir
            max_rate: Tasa máxima permitida (archivos por segundo)

        Returns:
            Retraso en segundos (0 si no se necesita retraso)
        """
        current_rate = self.get_current_rate()

        if current_rate + files_count <= max_rate:
            return 0.0

        # Calcular retraso para mantener tasa dentro de límites
        excess_rate = (current_rate + files_count) - max_rate
        delay = excess_rate / max_rate

        return max(0.1, min(delay, 10.0))  # Entre 100ms y 10s

    def get_instance_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas comprensivas de la instancia.

        Returns:
            Diccionario con estadísticas de la instancia
        """
        session_stats = self.get_session_stats()
        current_rate = self.get_current_rate()

        return {
            'instance_id': self.instance_id,
            'container_id': self.container_id,
            'uptime_seconds': time.time() - (self.local_throttle_state.window_start - 1),
            'current_rate': round(current_rate, 2),
            'last_activity': self.local_throttle_state.last_request_time,
            'sessions': session_stats
        }

    def reset_instance_state(self) -> None:
        """
        Resetea el estado de la instancia (útil para testing o limpieza).
        """
        self.local_throttle_state.reset_state()

        # Resetear pool de sesiones
        self.local_session_pool.clear_active_sessions()

        # Reconstruir cola de sesiones disponibles
        while not self.local_session_pool.available_sessions.empty():
            try:
                self.local_session_pool.available_sessions.get_nowait()
            except Empty:
                break

        for i in range(self.local_session_pool.max_sessions):
            session_id = f"session-{i+1}"
            self.local_session_pool.available_sessions.put(session_id)

        if self.logger:
            self.logger.logger.info("Instance state reset")
