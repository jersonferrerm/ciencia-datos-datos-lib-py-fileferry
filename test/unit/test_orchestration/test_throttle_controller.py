"""
Tests para ThrottleController.

Este módulo contiene tests unitarios para el controlador de throttling
que gestiona el rate limiting de transferencias.
"""

import pytest
import time
from unittest.mock import patch, MagicMock

from src.orchestration.throttle_controller import ThrottleController
from src.exceptions.transfer_exceptions import ThrottleError


class TestThrottleController:
    """Tests para la clase ThrottleController."""

    def test_initialization_default_values(self):
        """Test inicialización con valores por defecto."""
        controller = ThrottleController()

        assert controller.max_files_per_second == 100
        assert controller.current_rate == 0.0
        assert controller.last_request_time is None
        assert controller.request_count == 0
        assert controller.window_duration == 1.0
        assert controller.window_start > 0

    def test_initialization_custom_values(self):
        """Test inicialización con valores personalizados."""
        controller = ThrottleController(max_files_per_second=50)

        assert controller.max_files_per_second == 50
        assert controller.current_rate == 0.0
        assert controller.request_count == 0

    def test_initialization_invalid_max_files(self):
        """Test inicialización con max_files_per_second inválido."""
        with pytest.raises(ThrottleError) as exc_info:
            ThrottleController(max_files_per_second=0)

        assert exc_info.value.error_code == "INVALID_THROTTLE_CONFIG"
        assert "debe ser mayor que 0" in str(exc_info.value)

        with pytest.raises(ThrottleError):
            ThrottleController(max_files_per_second=-5)


class TestCanProceed:
    """Tests para el método can_proceed."""

    def test_can_proceed_empty_window(self):
        """Test can_proceed con ventana vacía."""
        controller = ThrottleController(max_files_per_second=100)

        # Primera solicitud en ventana vacía
        assert controller.can_proceed(10) is True
        assert controller.can_proceed(50) is True
        assert controller.can_proceed(100) is True

    def test_can_proceed_within_limit(self):
        """Test can_proceed dentro del límite."""
        controller = ThrottleController(max_files_per_second=100)

        # Simular algunas solicitudes previas
        controller.request_count = 50
        controller.window_start = time.time()

        # Debería poder proceder con 50 archivos más
        assert controller.can_proceed(50) is True
        assert controller.can_proceed(30) is True

    def test_can_proceed_exceeds_limit(self):
        """Test can_proceed cuando excede el límite."""
        controller = ThrottleController(max_files_per_second=100)

        # Simular ventana casi llena
        controller.request_count = 90
        controller.window_start = time.time()

        # No debería poder proceder con 20 archivos más
        assert controller.can_proceed(20) is False
        assert controller.can_proceed(11) is False

        # Pero sí con 10 o menos
        assert controller.can_proceed(10) is True
        assert controller.can_proceed(5) is True

    def test_can_proceed_invalid_files_count(self):
        """Test can_proceed con files_count inválido."""
        controller = ThrottleController()

        with pytest.raises(ThrottleError) as exc_info:
            controller.can_proceed(0)

        assert exc_info.value.error_code == "INVALID_FILE_COUNT"

        with pytest.raises(ThrottleError):
            controller.can_proceed(-5)

    @patch('time.time')
    def test_can_proceed_window_reset(self, mock_time):
        """Test can_proceed con reset de ventana."""
        controller = ThrottleController(max_files_per_second=100)

        # Configurar tiempo inicial
        initial_time = 1000.0
        mock_time.return_value = initial_time

        # Llenar la ventana
        controller.request_count = 100
        controller.window_start = initial_time

        # No debería poder proceder
        assert controller.can_proceed(1) is False

        # Avanzar el tiempo más allá de la ventana
        mock_time.return_value = initial_time + 1.5

        # Ahora debería poder proceder (ventana reseteada)
        assert controller.can_proceed(50) is True


class TestWaitIfNeeded:
    """Tests para el método wait_if_needed."""

    def test_wait_if_needed_no_wait_required(self):
        """Test wait_if_needed cuando no se requiere espera."""
        controller = ThrottleController(max_files_per_second=100)

        # No debería esperar para una solicitud pequeña
        start_time = time.time()
        controller.wait_if_needed(10)
        elapsed = time.time() - start_time

        # Debería ser casi instantáneo
        assert elapsed < 0.1

        # Verificar que se registró la solicitud
        assert controller.request_count == 10

    @patch('time.sleep')
    def test_wait_if_needed_with_wait(self, mock_sleep):
        """Test wait_if_needed cuando se requiere espera."""
        controller = ThrottleController(max_files_per_second=100)

        # Llenar la ventana
        controller.request_count = 95
        controller.window_start = time.time()

        # Mock can_proceed para simular que necesita esperar una vez
        with patch.object(controller, 'can_proceed', side_effect=[False, True]):
            controller.wait_if_needed(10)

        # Debería haber llamado sleep una vez
        mock_sleep.assert_called_once()

        # Verificar que se registró la solicitud
        assert controller.request_count == 105

    def test_wait_if_needed_invalid_files_count(self):
        """Test wait_if_needed con files_count inválido."""
        controller = ThrottleController()

        with pytest.raises(ThrottleError) as exc_info:
            controller.wait_if_needed(0)

        assert exc_info.value.error_code == "INVALID_FILE_COUNT"

    @patch('time.sleep')
    def test_wait_if_needed_max_attempts_exceeded(self, mock_sleep):
        """Test wait_if_needed cuando se exceden los intentos máximos."""
        controller = ThrottleController(max_files_per_second=100)

        # Mock can_proceed para que siempre retorne False
        with patch.object(controller, 'can_proceed', return_value=False):
            with pytest.raises(ThrottleError) as exc_info:
                controller.wait_if_needed(10)

        assert exc_info.value.error_code == "THROTTLE_MAX_ATTEMPTS_EXCEEDED"
        assert "10 intentos" in str(exc_info.value)

        # Debería haber intentado 10 veces
        assert mock_sleep.call_count == 10


class TestCalculateDelay:
    """Tests para el método _calculate_delay."""

    def test_calculate_delay_progression(self):
        """Test progresión del delay con backoff exponencial."""
        controller = ThrottleController()

        # Los delays deberían incrementar exponencialmente
        delay_0 = controller._calculate_delay(0)
        delay_1 = controller._calculate_delay(1)
        delay_2 = controller._calculate_delay(2)

        # Verificar que incrementan (considerando jitter)
        assert delay_0 >= 0.01  # Mínimo
        assert delay_1 > delay_0 * 0.8  # Permitir algo de jitter
        assert delay_2 > delay_1 * 0.8

    def test_calculate_delay_max_limit(self):
        """Test que el delay no excede el máximo."""
        controller = ThrottleController()

        # Con intentos altos, debería limitarse a max_delay
        delay_high = controller._calculate_delay(10)

        # Debería estar cerca del máximo (2.0s) considerando jitter
        assert delay_high <= 2.2  # 2.0 + 10% jitter

    def test_calculate_delay_minimum(self):
        """Test que el delay nunca es menor al mínimo."""
        controller = ThrottleController()

        # Incluso con jitter negativo, debería respetar el mínimo
        for attempt in range(5):
            delay = controller._calculate_delay(attempt)
            assert delay >= 0.01


class TestRegisterRequest:
    """Tests para el método _register_request."""

    def test_register_request_basic(self):
        """Test registro básico de solicitud."""
        controller = ThrottleController()
        initial_count = controller.request_count

        controller._register_request(5)

        assert controller.request_count == initial_count + 5
        assert controller.last_request_time is not None
        assert controller.current_rate >= 0

    @patch('time.time')
    def test_register_request_rate_calculation(self, mock_time):
        """Test cálculo de rate al registrar solicitud."""
        controller = ThrottleController()

        # Configurar tiempo inicial
        initial_time = 1000.0
        mock_time.return_value = initial_time
        controller.window_start = initial_time

        # Registrar solicitud después de 0.5 segundos
        mock_time.return_value = initial_time + 0.5
        controller._register_request(10)

        # Rate debería ser 10 archivos / 0.5 segundos = 20 archivos/segundo
        assert controller.current_rate == 20.0

    @patch('time.time')
    def test_register_request_window_reset(self, mock_time):
        """Test reset de ventana al registrar solicitud."""
        controller = ThrottleController()

        # Configurar tiempo inicial
        initial_time = 1000.0
        mock_time.return_value = initial_time
        controller.window_start = initial_time
        controller.request_count = 50

        # Avanzar tiempo más allá de la ventana
        mock_time.return_value = initial_time + 2.0
        controller._register_request(10)

        # La ventana debería haberse reseteado
        assert controller.request_count == 10  # Solo la nueva solicitud
        assert controller.window_start == initial_time + 2.0


class TestGetCurrentRate:
    """Tests para el método get_current_rate."""

    def test_get_current_rate_empty_window(self):
        """Test get_current_rate con ventana vacía."""
        controller = ThrottleController()

        rate = controller.get_current_rate()
        assert rate == 0.0

    @patch('time.time')
    def test_get_current_rate_with_requests(self, mock_time):
        """Test get_current_rate con solicitudes registradas."""
        controller = ThrottleController()

        # Configurar tiempo y solicitudes
        initial_time = 1000.0
        mock_time.return_value = initial_time
        controller.window_start = initial_time
        controller.request_count = 50

        # Calcular rate después de 0.5 segundos
        mock_time.return_value = initial_time + 0.5
        rate = controller.get_current_rate()

        # 50 archivos / 0.5 segundos = 100 archivos/segundo
        assert rate == 100.0

    @patch('time.time')
    def test_get_current_rate_expired_window(self, mock_time):
        """Test get_current_rate con ventana expirada."""
        controller = ThrottleController()

        # Configurar ventana con datos
        initial_time = 1000.0
        mock_time.return_value = initial_time
        controller.window_start = initial_time
        controller.request_count = 50

        # Avanzar tiempo más allá de la ventana
        mock_time.return_value = initial_time + 2.0
        rate = controller.get_current_rate()

        # Debería retornar 0 y resetear la ventana
        assert rate == 0.0
        assert controller.request_count == 0


class TestGetRemainingCapacity:
    """Tests para el método get_remaining_capacity."""

    def test_get_remaining_capacity_empty_window(self):
        """Test get_remaining_capacity con ventana vacía."""
        controller = ThrottleController(max_files_per_second=100)

        capacity = controller.get_remaining_capacity()
        # La capacidad puede ser ligeramente menor debido al tiempo transcurrido
        assert capacity >= 99
        assert capacity <= 100

    @patch('time.time')
    def test_get_remaining_capacity_partial_window(self, mock_time):
        """Test get_remaining_capacity con ventana parcialmente usada."""
        controller = ThrottleController(max_files_per_second=100)

        # Configurar ventana con algunas solicitudes
        initial_time = 1000.0
        mock_time.return_value = initial_time
        controller.window_start = initial_time
        controller.request_count = 30

        # Calcular capacidad después de 0.5 segundos
        mock_time.return_value = initial_time + 0.5
        capacity = controller.get_remaining_capacity()

        # Tiempo restante: 0.5s, capacidad máxima en ese tiempo: 50 archivos
        # Capacidad restante: 50 - 30 = 20
        assert capacity == 20

    @patch('time.time')
    def test_get_remaining_capacity_expired_window(self, mock_time):
        """Test get_remaining_capacity con ventana expirada."""
        controller = ThrottleController(max_files_per_second=100)

        # Configurar ventana expirada
        initial_time = 1000.0
        mock_time.return_value = initial_time
        controller.window_start = initial_time
        controller.request_count = 80

        # Avanzar tiempo más allá de la ventana
        mock_time.return_value = initial_time + 2.0
        capacity = controller.get_remaining_capacity()

        # Debería retornar la capacidad máxima
        assert capacity == 100

    def test_get_remaining_capacity_negative(self):
        """Test get_remaining_capacity cuando sería negativo."""
        controller = ThrottleController(max_files_per_second=100)

        # Configurar ventana que excede la capacidad
        controller.window_start = time.time()
        controller.request_count = 150  # Más del máximo

        capacity = controller.get_remaining_capacity()

        # Nunca debería ser negativo
        assert capacity >= 0


# Tests de integración
class TestThrottleControllerIntegration:
    """Tests de integración para ThrottleController."""

    def test_realistic_usage_pattern(self):
        """Test patrón de uso realista."""
        controller = ThrottleController(max_files_per_second=10)  # Límite bajo para testing

        # Procesar varios lotes pequeños
        for i in range(5):
            controller.wait_if_needed(2)
            time.sleep(0.1)  # Simular procesamiento

        # Verificar que se registraron todas las solicitudes
        assert controller.request_count == 10

    def test_burst_then_wait_pattern(self):
        """Test patrón de ráfaga seguida de espera."""
        controller = ThrottleController(max_files_per_second=20)

        # Ráfaga inicial
        controller.wait_if_needed(15)

        # Intentar otra ráfaga inmediatamente (debería esperar)
        start_time = time.time()
        controller.wait_if_needed(10)
        elapsed = time.time() - start_time

        # Debería haber esperado algo de tiempo
        assert elapsed > 0.05  # Al menos 50ms

    @patch('time.sleep')
    @patch('time.time')
    def test_concurrent_usage_simulation(self, mock_time, mock_sleep):
        """Test simulación de uso concurrente."""
        controller = ThrottleController(max_files_per_second=50)

        # Configurar tiempo fijo para evitar variaciones
        fixed_time = 1000.0
        mock_time.return_value = fixed_time

        # Resetear la ventana con tiempo fijo
        controller.window_start = fixed_time
        controller.request_count = 0

        # Simular múltiples threads haciendo solicitudes
        total_files = 0

        for _ in range(10):  # 10 "threads"
            files_in_batch = 4  # Reducir el tamaño para evitar exceder límites

            # Verificar si puede proceder
            if controller.can_proceed(files_in_batch):
                controller._register_request(files_in_batch)
                total_files += files_in_batch
            else:
                # En uso real, esperaría, pero aquí solo verificamos la lógica
                pass

        # Verificar que no se excedió el límite significativamente
        rate = controller.get_current_rate()
        assert rate <= controller.max_files_per_second * 1.1  # 10% de tolerancia