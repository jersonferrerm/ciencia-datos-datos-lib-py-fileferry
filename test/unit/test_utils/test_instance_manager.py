"""
Tests for InstanceManager utility class.
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from queue import Queue, Empty

from src.utils.instance_manager import (
    InstanceManager,
    SessionPool,
    ThrottleState
)
from src.utils.logger import StructuredLogger, LogLevel


class TestSessionPool:
    """Tests for SessionPool dataclass"""

    def test_default_session_pool(self):
        """Test default session pool initialization"""
        pool = SessionPool()
        assert pool.max_sessions == 5
        assert pool.available_sessions.qsize() == 5
        assert len(pool.active_sessions) == 0
        assert pool._lock is not None

    def test_custom_session_pool(self):
        """Test custom session pool initialization"""
        pool = SessionPool(max_sessions=3)
        assert pool.max_sessions == 3
        assert pool.available_sessions.qsize() == 3

        # Check session IDs
        sessions = []
        while not pool.available_sessions.empty():
            sessions.append(pool.available_sessions.get())

        assert sessions == ["session-1", "session-2", "session-3"]

    def test_post_init_creates_sessions(self):
        """Test that __post_init__ creates the correct number of sessions"""
        pool = SessionPool(max_sessions=2)

        # Verify sessions were created
        session1 = pool.available_sessions.get()
        session2 = pool.available_sessions.get()

        assert session1 == "session-1"
        assert session2 == "session-2"
        assert pool.available_sessions.empty()


class TestThrottleState:
    """Tests for ThrottleState dataclass"""

    def test_default_throttle_state(self):
        """Test default throttle state initialization"""
        state = ThrottleState()
        assert state.current_rate == 0.0
        assert isinstance(state.last_request_time, float)
        assert state.request_count == 0
        assert isinstance(state.window_start, float)
        assert state._lock is not None

    def test_throttle_state_timing(self):
        """Test throttle state timing fields"""
        start_time = time.time()
        state = ThrottleState()
        end_time = time.time()

        # Verify timing is reasonable
        assert start_time <= state.last_request_time <= end_time
        assert start_time <= state.window_start <= end_time


class TestInstanceManager:
    """Tests for InstanceManager class"""

    def setUp(self):
        """Reset singleton for each test"""
        InstanceManager._instance = None

    def tearDown(self):
        """Clean up after each test"""
        InstanceManager._instance = None

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test"""
        InstanceManager._instance = None
        yield
        InstanceManager._instance = None

    def test_singleton_pattern(self):
        """Test that InstanceManager follows singleton pattern"""
        manager1 = InstanceManager()
        manager2 = InstanceManager()

        assert manager1 is manager2
        assert id(manager1) == id(manager2)

    @patch.dict('os.environ', {'AWS_LAMBDA_RUNTIME_API': 'test-runtime-api.amazonaws.com'})
    def test_initialization_with_runtime_api(self):
        """Test initialization with AWS Lambda runtime API"""
        manager = InstanceManager()

        assert manager.instance_id is not None
        assert manager.container_id == "test-runtime-api"
        assert manager.local_session_pool is not None
        assert manager.local_throttle_state is not None
        assert manager.logger is not None

    @patch.dict('os.environ', {'AWS_LAMBDA_LOG_GROUP_NAME': '/aws/lambda/test-function'})
    def test_initialization_with_log_group(self):
        """Test initialization with log group name"""
        manager = InstanceManager()

        assert manager.container_id == "test-function"

    @patch.dict('os.environ', {}, clear=True)
    def test_initialization_without_env_vars(self):
        """Test initialization without AWS environment variables"""
        manager = InstanceManager()

        assert manager.container_id == "unknown"
        assert manager.instance_id is not None
        assert "unknown" in manager.instance_id

    def test_generate_instance_id_format(self):
        """Test instance ID generation format"""
        manager = InstanceManager()
        instance_id = manager.instance_id

        # Should start with "lambda-"
        assert instance_id.startswith("lambda-")

        # Should contain container info, UUID part, and timestamp
        parts = instance_id.split("-")
        assert len(parts) >= 4  # lambda-container-uuid-timestamp

    def test_get_instance_id(self):
        """Test get_instance_id method"""
        manager = InstanceManager()

        assert manager.get_instance_id() == manager.instance_id

    def test_get_container_id(self):
        """Test get_container_id method"""
        manager = InstanceManager()

        assert manager.get_container_id() == manager.container_id

    def test_acquire_session_success(self):
        """Test successful session acquisition"""
        manager = InstanceManager()

        with manager.acquire_session() as session_id:
            assert session_id is not None
            assert session_id.startswith("session-")

            # Verify session is marked as active
            assert session_id in manager.local_session_pool.active_sessions

            # Verify available sessions decreased
            assert manager.local_session_pool.available_sessions.qsize() == 4

        # After context exit, session should be released
        assert session_id not in manager.local_session_pool.active_sessions
        assert manager.local_session_pool.available_sessions.qsize() == 5

    def test_acquire_session_timeout(self):
        """Test session acquisition timeout"""
        manager = InstanceManager()

        # Acquire all sessions
        sessions = []
        for _ in range(5):
            session = manager.local_session_pool.available_sessions.get()
            manager.local_session_pool.active_sessions[session] = {"test": True}
            sessions.append(session)

        # Try to acquire another session with short timeout
        with pytest.raises(TimeoutError):
            with manager.acquire_session(timeout=0.1):
                pass

    def test_acquire_session_concurrent(self):
        """Test concurrent session acquisition"""
        manager = InstanceManager()
        results = []

        def acquire_session_worker():
            try:
                with manager.acquire_session(timeout=1.0) as session_id:
                    results.append(session_id)
                    time.sleep(0.1)  # Hold session briefly
            except Exception as e:
                results.append(f"error: {e}")

        # Start multiple threads
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=acquire_session_worker)
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All should succeed
        assert len(results) == 3
        assert all(isinstance(r, str) and r.startswith("session-") for r in results)
        assert len(set(results)) == 3  # All different sessions

    def test_get_session_stats(self):
        """Test session statistics"""
        manager = InstanceManager()

        # Initial stats
        stats = manager.get_session_stats()
        assert stats['total_sessions'] == 5
        assert stats['available_sessions'] == 5
        assert stats['active_sessions'] == 0
        assert stats['active_session_ids'] == []

        # Acquire a session
        with manager.acquire_session() as session_id:
            stats = manager.get_session_stats()
            assert stats['available_sessions'] == 4
            assert stats['active_sessions'] == 1
            assert stats['active_session_ids'] == [session_id]

    def test_update_throttle_state(self):
        """Test throttle state updates"""
        manager = InstanceManager()

        # Initial state
        assert manager.local_throttle_state.current_rate == 0.0
        assert manager.local_throttle_state.request_count == 0

        # Update with some files
        manager.update_throttle_state(10)

        assert manager.local_throttle_state.request_count == 10
        assert manager.local_throttle_state.current_rate > 0

        # Update again
        time.sleep(0.1)  # Small delay
        manager.update_throttle_state(5)

        assert manager.local_throttle_state.request_count == 15

    def test_update_throttle_state_window_reset(self):
        """Test throttle state window reset"""
        manager = InstanceManager()

        # Set old window start time
        manager.local_throttle_state.window_start = time.time() - 2.0
        manager.local_throttle_state.request_count = 100

        # Update should reset the window
        manager.update_throttle_state(5)

        assert manager.local_throttle_state.request_count == 5
        assert abs(manager.local_throttle_state.window_start - time.time()) < 0.1

    def test_get_current_rate(self):
        """Test current rate calculation"""
        manager = InstanceManager()

        # Initially zero
        assert manager.get_current_rate() == 0.0

        # After processing files
        manager.update_throttle_state(10)
        rate = manager.get_current_rate()
        assert rate > 0

        # Rate should be files per second
        # With 10 files in a very short time, rate should be high
        assert rate >= 10

    def test_get_current_rate_old_window(self):
        """Test current rate with old window (should reset)"""
        manager = InstanceManager()

        # Set old activity
        manager.local_throttle_state.window_start = time.time() - 10.0
        manager.local_throttle_state.current_rate = 50.0

        # Getting current rate should reset due to old window
        rate = manager.get_current_rate()
        assert rate == 0.0

    def test_can_proceed_with_rate(self):
        """Test rate limit checking"""
        manager = InstanceManager()

        # Initially should be able to proceed
        assert manager.can_proceed_with_rate(10, max_rate=100.0) is True

        # After high activity, might not be able to proceed
        manager.local_throttle_state.current_rate = 95.0
        assert manager.can_proceed_with_rate(10, max_rate=100.0) is False
        assert manager.can_proceed_with_rate(5, max_rate=100.0) is True

    def test_calculate_throttle_delay(self):
        """Test throttle delay calculation"""
        manager = InstanceManager()

        # No delay needed initially
        delay = manager.calculate_throttle_delay(10, max_rate=100.0)
        assert delay == 0.0

        # Delay needed when rate is high
        manager.local_throttle_state.current_rate = 95.0
        delay = manager.calculate_throttle_delay(10, max_rate=100.0)
        assert delay > 0.0
        assert delay <= 10.0  # Should be capped

    def test_calculate_throttle_delay_bounds(self):
        """Test throttle delay calculation bounds"""
        manager = InstanceManager()

        # Very high rate should give reasonable delay
        manager.local_throttle_state.current_rate = 200.0
        delay = manager.calculate_throttle_delay(50, max_rate=100.0)

        assert delay >= 0.1  # Minimum delay
        assert delay <= 10.0  # Maximum delay

    def test_get_instance_stats(self):
        """Test comprehensive instance statistics"""
        manager = InstanceManager()

        # Update some state
        manager.update_throttle_state(5)

        stats = manager.get_instance_stats()

        assert 'instance_id' in stats
        assert 'container_id' in stats
        assert 'uptime_seconds' in stats
        assert 'current_rate' in stats
        assert 'last_activity' in stats
        assert 'sessions' in stats

        assert stats['instance_id'] == manager.instance_id
        assert stats['container_id'] == manager.container_id
        assert isinstance(stats['uptime_seconds'], float)
        assert isinstance(stats['current_rate'], float)
        assert isinstance(stats['sessions'], dict)

    def test_reset_instance_state(self):
        """Test instance state reset"""
        manager = InstanceManager()

        # Set some state
        manager.update_throttle_state(10)

        # Acquire a session
        session_id = manager.local_session_pool.available_sessions.get()
        manager.local_session_pool.active_sessions[session_id] = {"test": True}

        # Reset state
        manager.reset_instance_state()

        # Verify reset
        assert manager.local_throttle_state.current_rate == 0.0
        assert manager.local_throttle_state.request_count == 0
        assert len(manager.local_session_pool.active_sessions) == 0
        assert manager.local_session_pool.available_sessions.qsize() == 5

    @patch('src.utils.instance_manager.StructuredLogger')
    def test_setup_logger_called(self, mock_logger_class):
        """Test that logger setup is called during initialization"""
        mock_logger = Mock()
        mock_logger_class.return_value = mock_logger

        # Clear any existing instance to ensure fresh initialization
        InstanceManager._instance = None

        manager = InstanceManager()

        # Verify logger was created
        mock_logger_class.assert_called_once_with(manager.instance_id)

    def test_thread_safety(self):
        """Test thread safety of InstanceManager operations"""
        manager = InstanceManager()
        results = []
        errors = []

        def worker():
            try:
                # Mix of operations
                manager.update_throttle_state(1)
                stats = manager.get_session_stats()
                rate = manager.get_current_rate()
                can_proceed = manager.can_proceed_with_rate(5)

                results.append({
                    'stats': stats,
                    'rate': rate,
                    'can_proceed': can_proceed
                })
            except Exception as e:
                errors.append(e)

        # Run multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Should have no errors and all results
        assert len(errors) == 0
        assert len(results) == 10

    def test_multiple_instance_calls_same_object(self):
        """Test that multiple InstanceManager() calls return same object"""
        manager1 = InstanceManager()
        manager2 = InstanceManager()
        manager3 = InstanceManager()

        assert manager1 is manager2 is manager3
        assert manager1.instance_id == manager2.instance_id == manager3.instance_id