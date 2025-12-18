"""
ThrottleController para control de throughput.

Este módulo implementa el control de rate limiting para respetar
el límite de 100 archivos por segundo de AWS Transfer Family.
"""

import time
import secrets
from typing import Optional
from src.exceptions.transfer_exceptions import ThrottleError


class ThrottleController:
    """
    Controlador de throttling para gestionar el throughput de transferencias.

    Implementa rate limiting inteligente para respetar el límite de 100 archivos
    por segundo de AWS Transfer Family, con backoff exponencial cuando es necesario.

    Attributes:
        max_files_per_second: Límite máximo de archivos por segundo (default: 100)
        current_rate: Rate actual de archivos por segundo
        last_request_time: Timestamp de la última solicitud
        request_count: Contador de solicitudes en la ventana actual
        window_start: Inicio de la ventana de tiempo actual
        window_duration: Duración de la ventana en segundos (default: 1.0)
    """

    def __init__(self, max_files_per_second: int = 100):
        """
        Inicializa el ThrottleController.

        Args:
            max_files_per_second: Límite máximo de archivos por segundo
        """
        if max_files_per_second <= 0:
            raise ThrottleError(
                "max_files_per_second debe ser mayor que 0",
                error_code="INVALID_THROTTLE_CONFIG"
            )

        self.max_files_per_second = max_files_per_second
        self.current_rate = 0.0
        self.last_request_time: Optional[float] = None
        self.request_count = 0
        self.window_start = time.time()
        self.window_duration = 1.0  # 1 segundo

    def can_proceed(self, files_count: int) -> bool:
        """
        Verifica si se puede proceder con la transferencia de archivos.

        Args:
            files_count: Número de archivos a transferir

        Returns:
            True si se puede proceder, False si se debe esperar

        Raises:
            ThrottleError: Si files_count es inválido
        """
        if files_count <= 0:
            raise ThrottleError(
                "files_count debe ser mayor que 0",
                error_code="INVALID_FILE_COUNT"
            )

        current_time = time.time()

        # Resetear ventana si ha pasado el tiempo
        if current_time - self.window_start >= self.window_duration:
            self._reset_window(current_time)

        # Verificar si agregar estos archivos excedería el límite
        projected_count = self.request_count + files_count
        projected_rate = projected_count / self.window_duration

        return projected_rate <= self.max_files_per_second

    def wait_if_needed(self, files_count: int) -> None:
        """
        Espera si es necesario para respetar el rate limit.

        Args:
            files_count: Número de archivos a transferir

        Raises:
            ThrottleError: Si files_count es inválido
        """
        if files_count <= 0:
            raise ThrottleError(
                "files_count debe ser mayor que 0",
                error_code="INVALID_FILE_COUNT"
            )

        attempt = 0
        max_attempts = 10  # Evitar loops infinitos

        while not self.can_proceed(files_count) and attempt < max_attempts:
            delay = self._calculate_delay(attempt)
            time.sleep(delay)
            attempt += 1

        if attempt >= max_attempts:
            raise ThrottleError(
                f"No se pudo proceder después de {max_attempts} intentos",
                error_code="THROTTLE_MAX_ATTEMPTS_EXCEEDED",
                context={"files_count": files_count, "current_rate": self.current_rate}
            )

        # Registrar la solicitud
        self._register_request(files_count)

    def _calculate_delay(self, attempt: int) -> float:
        """
        Calcula el delay necesario usando backoff exponencial.

        Args:
            attempt: Número del intento actual

        Returns:
            Delay en segundos
        """
        # Backoff exponencial con jitter
        base_delay = 0.1  # 100ms base
        max_delay = 2.0   # 2 segundos máximo
        exponential_base = 2.0

        # Calcular delay exponencial
        exponential_delay = base_delay * (exponential_base ** attempt)

        # Aplicar límite máximo
        delay = min(exponential_delay, max_delay)

        # Agregar jitter (±10% del delay)
        # Generar jitter criptográficamente seguro entre -10% y +10%
        jitter = delay * 0.1 * (2 * (secrets.randbelow(1001) / 1000.0) - 1)

        return max(0.01, delay + jitter)  # Mínimo 10ms

    def _register_request(self, files_count: int) -> None:
        """
        Registra una solicitud en el contador de rate limiting.

        Args:
            files_count: Número de archivos en la solicitud
        """
        current_time = time.time()

        # Resetear ventana si es necesario
        if current_time - self.window_start >= self.window_duration:
            self._reset_window(current_time)

        # Registrar la solicitud
        self.request_count += files_count
        self.last_request_time = current_time

        # Actualizar rate actual
        elapsed = current_time - self.window_start
        if elapsed > 0:
            self.current_rate = self.request_count / elapsed

    def _reset_window(self, current_time: float) -> None:
        """
        Resetea la ventana de tiempo para el rate limiting.

        Args:
            current_time: Tiempo actual
        """
        self.window_start = current_time
        self.request_count = 0
        self.current_rate = 0.0

    def get_current_rate(self) -> float:
        """
        Obtiene el rate actual de archivos por segundo.

        Returns:
            Rate actual en archivos por segundo
        """
        current_time = time.time()

        # Resetear ventana si ha expirado
        if current_time - self.window_start >= self.window_duration:
            self._reset_window(current_time)
            return 0.0

        elapsed = current_time - self.window_start
        if elapsed > 0:
            return self.request_count / elapsed

        return 0.0

    def get_remaining_capacity(self) -> int:
        """
        Obtiene la capacidad restante en la ventana actual.

        Returns:
            Número de archivos que se pueden procesar sin exceder el límite
        """
        current_time = time.time()

        # Resetear ventana si ha expirado
        if current_time - self.window_start >= self.window_duration:
            self._reset_window(current_time)
            return self.max_files_per_second

        elapsed = current_time - self.window_start
        remaining_time = self.window_duration - elapsed

        if remaining_time <= 0:
            return self.max_files_per_second

        # Calcular capacidad restante basada en el rate actual
        max_in_remaining_time = int(self.max_files_per_second * remaining_time)
        return max(0, max_in_remaining_time - self.request_count)