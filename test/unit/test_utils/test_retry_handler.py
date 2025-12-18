"""
Tests for RetryHandler utility class.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock

from src.utils.retry_handler import (
    RetryHandler,
    RetryPolicy,
    retry
)
from src.utils.logger import StructuredLogger


class TestRetryPolicy:
    """Tests for RetryPolicy dataclass"""

    def test_default_retry_policy(self):
        """Test default retry policy values"""
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.base_delay == 1.0
        assert policy.max_delay == 60.0
        assert policy.exponential_base == 2.0
        assert policy.jitter is True
        assert policy.retryable_exceptions == (Exception,)

    def test_custom_retry_policy(self):
        """Test custom retry policy values"""
        policy = RetryPolicy(
            max_attempts=5,
            base_delay=2.0,
            max_delay=120.0,
            exponential_base=3.0,
            jitter=False,
            retryable_exceptions=(ValueError, TypeError)
        )
        assert policy.max_attempts == 5
        assert policy.base_delay == 2.0
        assert policy.max_delay == 120.0
        assert policy.exponential_base == 3.0
        assert policy.jitter is False
        assert policy.retryable_exceptions == (ValueError, TypeError)


class TestRetryHandler:
    """Tests for RetryHandler class"""

    @pytest.fixture
    def mock_logger(self):
        """Mock logger for testing"""
        return Mock(spec=StructuredLogger)

    @pytest.fixture
    def retry_handler(self, mock_logger):
        """RetryHandler instance for testing"""
        return RetryHandler(mock_logger)

    @pytest.fixture
    def retry_handler_no_logger(self):
        """RetryHandler instance without logger"""
        return RetryHandler()

    @pytest.fixture
    def basic_policy(self):
        """Basic retry policy for testing"""
        return RetryPolicy(max_attempts=3, base_delay=1.0, jitter=False)

    def test_init_with_logger(self, mock_logger):
        """Test RetryHandler initialization with logger"""
        handler = RetryHandler(mock_logger)
        assert handler.logger == mock_logger

    def test_init_without_logger(self):
        """Test RetryHandler initialization without logger"""
        handler = RetryHandler()
        assert handler.logger is None

    def test_calculate_delay_exponential_backoff(self, retry_handler):
        """Test delay calculation with exponential backoff"""
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, jitter=False)

        delay1 = retry_handler.calculate_delay(1, policy)
        delay2 = retry_handler.calculate_delay(2, policy)
        delay3 = retry_handler.calculate_delay(3, policy)

        assert delay1 == 1.0  # 1.0 * 2^0
        assert delay2 == 2.0  # 1.0 * 2^1
        assert delay3 == 4.0  # 1.0 * 2^2

    def test_calculate_delay_max_limit(self, retry_handler):
        """Test delay calculation respects max limit"""
        policy = RetryPolicy(base_delay=10.0, max_delay=15.0, exponential_base=2.0, jitter=False)

        delay = retry_handler.calculate_delay(5, policy)  # Would be 10 * 2^4 = 160
        assert delay == 15.0  # Capped at max_delay

    @patch('secrets.randbelow')
    def test_calculate_delay_with_jitter(self, mock_randbelow, retry_handler):
        """Test delay calculation with jitter"""
        mock_randbelow.return_value = 1000  # Middle of range
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, jitter=True)

        delay = retry_handler.calculate_delay(1, policy)
        # Base delay is 1.0, jitter range is 0.1, middle value adds 0
        assert delay == 1.0

    def test_calculate_delay_minimum(self, retry_handler):
        """Test delay calculation minimum value"""
        policy = RetryPolicy(base_delay=0.01, jitter=False)

        delay = retry_handler.calculate_delay(1, policy)
        assert delay >= 0.1  # Minimum 100ms

    def test_should_retry_within_max_attempts(self, retry_handler):
        """Test should_retry within max attempts"""
        policy = RetryPolicy(max_attempts=3, retryable_exceptions=(ValueError,))

        # Should retry for retryable exceptions within max attempts
        assert retry_handler.should_retry(ValueError("test"), 1, policy) is True
        assert retry_handler.should_retry(ValueError("test"), 2, policy) is True

        # Should not retry when max attempts reached
        assert retry_handler.should_retry(ValueError("test"), 3, policy) is False
        assert retry_handler.should_retry(ValueError("test"), 4, policy) is False

    def test_should_retry_non_retryable_exception(self, retry_handler):
        """Test should_retry with non-retryable exceptions"""
        policy = RetryPolicy(max_attempts=3, retryable_exceptions=(ValueError,))

        # Should not retry for non-retryable exceptions
        assert retry_handler.should_retry(TypeError("test"), 1, policy) is False
        assert retry_handler.should_retry(RuntimeError("test"), 1, policy) is False

    def test_should_retry_multiple_retryable_exceptions(self, retry_handler):
        """Test should_retry with multiple retryable exception types"""
        policy = RetryPolicy(max_attempts=3, retryable_exceptions=(ValueError, TypeError))

        assert retry_handler.should_retry(ValueError("test"), 1, policy) is True
        assert retry_handler.should_retry(TypeError("test"), 1, policy) is True
        assert retry_handler.should_retry(RuntimeError("test"), 1, policy) is False

    def test_retry_with_backoff_success_first_attempt(self, retry_handler):
        """Test retry_with_backoff with successful first attempt"""
        operation = Mock(return_value="success")
        policy = RetryPolicy(max_attempts=3)

        result = retry_handler.retry_with_backoff(operation, policy, "test_op")

        assert result == "success"
        operation.assert_called_once()

    def test_retry_with_backoff_eventual_success(self, retry_handler):
        """Test retry_with_backoff with eventual success after retries"""
        operation = Mock(side_effect=[ValueError("fail"), ValueError("fail"), "success"])
        policy = RetryPolicy(max_attempts=3, base_delay=0.01, jitter=False)

        with patch('time.sleep'):  # Mock sleep to speed up test
            result = retry_handler.retry_with_backoff(operation, policy, "test_op")

        assert result == "success"
        assert operation.call_count == 3

    def test_retry_with_backoff_max_attempts_exceeded(self, retry_handler):
        """Test retry_with_backoff when max attempts exceeded"""
        error = ValueError("persistent error")
        operation = Mock(side_effect=error)
        policy = RetryPolicy(max_attempts=2, base_delay=0.01, jitter=False)

        with patch('time.sleep'):  # Mock sleep to speed up test
            with pytest.raises(ValueError):
                retry_handler.retry_with_backoff(operation, policy, "test_op")

        assert operation.call_count == 2

    def test_retry_with_backoff_non_retryable_error(self, retry_handler):
        """Test retry_with_backoff with non-retryable error"""
        error = TypeError("non-retryable error")
        operation = Mock(side_effect=error)
        policy = RetryPolicy(max_attempts=3, retryable_exceptions=(ValueError,))

        with pytest.raises(TypeError):
            retry_handler.retry_with_backoff(operation, policy, "test_op")

        # Should only try once for non-retryable errors
        operation.assert_called_once()

    def test_retry_with_backoff_logging(self, retry_handler, mock_logger):
        """Test retry_with_backoff with logging"""
        operation = Mock(side_effect=[ValueError("fail"), "success"])
        policy = RetryPolicy(max_attempts=3, base_delay=0.01, jitter=False)

        with patch('time.sleep'):  # Mock sleep to speed up test
            result = retry_handler.retry_with_backoff(operation, policy, "test_op")

        assert result == "success"
        mock_logger.log_retry_attempt.assert_called_once()

        # Verify log call arguments
        call_args = mock_logger.log_retry_attempt.call_args[0]
        assert call_args[0] == "test_op"  # operation_name
        assert call_args[1] == 2  # next attempt number
        assert call_args[2] == 3  # max_attempts
        assert isinstance(call_args[3], float)  # delay
        assert "fail" in call_args[4]  # error message

    def test_retry_with_backoff_no_logger(self, retry_handler_no_logger):
        """Test retry_with_backoff without logger (should not crash)"""
        operation = Mock(side_effect=[ValueError("fail"), "success"])
        policy = RetryPolicy(max_attempts=3, base_delay=0.01, jitter=False)

        with patch('time.sleep'):  # Mock sleep to speed up test
            result = retry_handler_no_logger.retry_with_backoff(operation, policy, "test_op")

        assert result == "success"
        assert operation.call_count == 2

    def test_retry_with_backoff_no_sleep_on_last_attempt(self, retry_handler):
        """Test that no sleep occurs after the last failed attempt"""
        error = ValueError("persistent error")
        operation = Mock(side_effect=error)
        policy = RetryPolicy(max_attempts=2, base_delay=1.0)

        with patch('time.sleep') as mock_sleep:
            with pytest.raises(ValueError):
                retry_handler.retry_with_backoff(operation, policy, "test_op")

        # Should only sleep once (between attempt 1 and 2, not after attempt 2)
        mock_sleep.assert_called_once()


class TestRetryDecorator:
    """Tests for retry decorator"""

    def test_retry_decorator_success(self):
        """Test retry decorator with successful function"""
        @retry(max_attempts=3, base_delay=0.01, jitter=False)
        def successful_function():
            return "success"

        result = successful_function()
        assert result == "success"

    def test_retry_decorator_eventual_success(self):
        """Test retry decorator with eventual success"""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, jitter=False)
        def eventually_successful_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "success"

        with patch('time.sleep'):  # Mock sleep to speed up test
            result = eventually_successful_function()

        assert result == "success"
        assert call_count == 3

    def test_retry_decorator_max_attempts_exceeded(self):
        """Test retry decorator when max attempts exceeded"""
        @retry(max_attempts=2, base_delay=0.01, jitter=False)
        def always_failing_function():
            raise ValueError("always fails")

        with patch('time.sleep'):  # Mock sleep to speed up test
            with pytest.raises(ValueError):
                always_failing_function()

    def test_retry_decorator_non_retryable_exception(self):
        """Test retry decorator with non-retryable exception"""
        call_count = 0

        @retry(max_attempts=3, retryable_exceptions=(ValueError,))
        def function_with_non_retryable_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("non-retryable")

        with pytest.raises(TypeError):
            function_with_non_retryable_error()

        # Should only be called once
        assert call_count == 1

    def test_retry_decorator_custom_parameters(self):
        """Test retry decorator with custom parameters"""
        call_count = 0

        @retry(
            max_attempts=5,
            base_delay=0.5,
            max_delay=10.0,
            exponential_base=3.0,
            jitter=False,
            retryable_exceptions=(ValueError, TypeError)
        )
        def custom_retry_function():
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                raise ValueError("retry me")
            return "success"

        with patch('time.sleep'):  # Mock sleep to speed up test
            result = custom_retry_function()

        assert result == "success"
        assert call_count == 4

    def test_retry_decorator_preserves_function_metadata(self):
        """Test that retry decorator preserves function metadata"""
        @retry(max_attempts=3)
        def documented_function():
            """This is a documented function."""
            return "result"

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a documented function."

    def test_retry_decorator_with_arguments(self):
        """Test retry decorator with function that takes arguments"""
        @retry(max_attempts=3, base_delay=0.01, jitter=False)
        def function_with_args(x, y, z=None):
            if x < 2:
                raise ValueError("x too small")
            return f"{x}-{y}-{z}"

        # Should succeed on first try
        result = function_with_args(5, "test", z="optional")
        assert result == "5-test-optional"

        # Should retry and eventually succeed
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, jitter=False)
        def function_with_retry_logic(x, y):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return x + y

        with patch('time.sleep'):
            result = function_with_retry_logic(10, 20)

        assert result == 30
        assert call_count == 3

    def test_retry_decorator_exception_inheritance(self):
        """Test retry decorator with exception inheritance"""
        class CustomError(ValueError):
            pass

        @retry(max_attempts=3, retryable_exceptions=(ValueError,), base_delay=0.01, jitter=False)
        def function_with_inherited_exception():
            raise CustomError("inherited from ValueError")

        with patch('time.sleep'):
            with pytest.raises(CustomError):
                function_with_inherited_exception()

    def test_retry_decorator_multiple_exception_types(self):
        """Test retry decorator with multiple retryable exception types"""
        call_count = 0

        @retry(max_attempts=4, retryable_exceptions=(ValueError, TypeError), base_delay=0.01, jitter=False)
        def function_with_multiple_exceptions():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first error")
            elif call_count == 2:
                raise TypeError("second error")
            elif call_count == 3:
                raise ValueError("third error")
            return "success"

        with patch('time.sleep'):
            result = function_with_multiple_exceptions()

        assert result == "success"
        assert call_count == 4


class TestRetryIntegration:
    """Integration tests for retry functionality"""

    def test_retry_handler_and_decorator_consistency(self):
        """Test that RetryHandler and decorator produce consistent results"""
        # Setup identical policies
        policy = RetryPolicy(max_attempts=3, base_delay=0.01, jitter=False, retryable_exceptions=(ValueError,))
        handler = RetryHandler()

        # Test function that fails twice then succeeds
        call_count_handler = 0
        call_count_decorator = 0

        def operation_for_handler():
            nonlocal call_count_handler
            call_count_handler += 1
            if call_count_handler < 3:
                raise ValueError("fail")
            return "success"

        @retry(max_attempts=3, base_delay=0.01, jitter=False, retryable_exceptions=(ValueError,))
        def operation_with_decorator():
            nonlocal call_count_decorator
            call_count_decorator += 1
            if call_count_decorator < 3:
                raise ValueError("fail")
            return "success"

        with patch('time.sleep'):
            # Test handler
            result_handler = handler.retry_with_backoff(operation_for_handler, policy)

            # Test decorator
            result_decorator = operation_with_decorator()

        # Both should succeed with same number of attempts
        assert result_handler == "success"
        assert result_decorator == "success"
        assert call_count_handler == 3
        assert call_count_decorator == 3

    @patch('time.time')
    def test_retry_timing_behavior(self, mock_time):
        """Test that retry timing behaves as expected"""
        # Mock time to control timing
        mock_time.side_effect = [0, 1, 2, 3, 4]  # Simulate time progression

        call_times = []

        @retry(max_attempts=3, base_delay=1.0, jitter=False)
        def timed_function():
            call_times.append(mock_time.return_value)
            if len(call_times) < 3:
                raise ValueError("not yet")
            return "success"

        with patch('time.sleep') as mock_sleep:
            result = timed_function()

        assert result == "success"
        assert len(call_times) == 3

        # Verify sleep was called with correct delays
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert len(sleep_calls) == 2  # Two sleeps between three attempts
        assert sleep_calls[0] == 2.0  # First retry delay: base_delay * 2^1
        assert sleep_calls[1] == 4.0  # Second retry delay: base_delay * 2^2