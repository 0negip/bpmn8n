"""Run: .venv-models/bin/python -m unittest discover tools (no models needed)."""
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from models_server import MicroBatcher


class MicroBatcherTest(unittest.TestCase):
    def test_concurrent_calls_share_a_batch_and_get_their_own_result(self):
        sizes = []

        def run(items):
            sizes.append(len(items))
            time.sleep(0.01)
            return [i * 10 for i in items]

        batcher = MicroBatcher(run, max_batch=16, max_wait=0.02)
        with ThreadPoolExecutor(16) as pool:
            results = list(pool.map(batcher.submit, range(16)))
        self.assertEqual(results, [i * 10 for i in range(16)])
        self.assertLess(len(sizes), 16)  # batched, not one call per item
        self.assertLessEqual(max(sizes), 16)

    def test_a_failing_batch_fails_its_callers_and_the_batcher_keeps_working(self):
        calls = threading.Event()

        def run(items):
            if not calls.is_set():
                calls.set()
                raise RuntimeError("model crashed")
            return items

        batcher = MicroBatcher(run, max_wait=0)
        with self.assertRaises(RuntimeError):
            batcher.submit(1)
        self.assertEqual(batcher.submit(2), 2)


if __name__ == "__main__":
    unittest.main()
