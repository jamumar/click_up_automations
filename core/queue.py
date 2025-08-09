import asyncio
from typing import Callable, Awaitable, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class _WorkerState:
    def __init__(self):
        self.signal = asyncio.Event()
        self.task: Optional[asyncio.Task] = None

class CoalescingQueue:
    """
    Per-key coalescing queue:
      - enqueue(key, job_factory): schedules a run for the key
      - Multiple enqueues within debounce_window collapse into one run
      - If signals arrive while a run is executing, we run exactly once more
      - Worker exits after idle_timeout if no new signals
    """
    def __init__(self, debounce_window: float = 0.8, idle_timeout: float = 5.0, max_concurrent_keys: int = 20):
        self._states: Dict[str, _WorkerState] = {}
        self._lock = asyncio.Lock()
        self.debounce_window = debounce_window
        self.idle_timeout = idle_timeout
        # Limit concurrent keys overall to avoid global overload
        self._key_semaphore = asyncio.Semaphore(max_concurrent_keys)

    async def enqueue(self, key: str, job_factory: Callable[[], Awaitable[None]]) -> None:
        async with self._lock:
            state = self._states.get(key)
            if state is None:
                state = _WorkerState()
                self._states[key] = state
                state.task = asyncio.create_task(self._run_worker(key, state, job_factory))
            # Signal (or re-signal) the worker
            state.signal.set()

    async def _run_worker(self, key: str, state: _WorkerState, job_factory: Callable[[], Awaitable[None]]):
        try:
            while True:
                try:
                    # Wait for first signal or idle timeout
                    await asyncio.wait_for(state.signal.wait(), timeout=self.idle_timeout)
                except asyncio.TimeoutError:
                    # No signals during idle period: stop the worker
                    break

                # Debounce period to absorb bursts
                await asyncio.sleep(self.debounce_window)
                # Clear signal so we can detect any new arrivals during run
                state.signal.clear()

                async with self._key_semaphore:
                    try:
                        await job_factory()
                    except Exception as e:
                        logger.exception(f"Queued job for key={key} failed: {e}")

                # If another signal was set during run/debounce, loop again immediately
                if not state.signal.is_set():
                    # No pending signals; go back to waiting with idle timeout
                    continue
        finally:
            # Clean up worker entry
            async with self._lock:
                self._states.pop(key, None)

# Global singleton instance
queue = CoalescingQueue()