"""The shared worker runner with real child processes."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

from services.api.subprocesses import last_error, run_worker


class Stop(Exception):
    pass


class RunWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.log = self.folder / "worker.log"

    def python(self, code):
        return [sys.executable, "-c", code]

    def test_exit_code_output_and_progress_hook(self):
        polls = []
        code = run_worker(
            self.python("import time;print('hello');time.sleep(0.4);raise SystemExit(3)"),
            self.log,
            timeout=10,
            on_poll=lambda: polls.append(1),
            poll_seconds=0.05,
        )
        self.assertEqual(code, 3)
        self.assertIn("hello", self.log.read_text())
        self.assertGreater(len(polls), 2)

    def test_timeout_stops_the_child(self):
        marker = self.folder / "late"
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, "too slow"):
            run_worker(
                self.python(f"import time,pathlib;time.sleep(3);pathlib.Path({str(marker)!r}).write_text('x')"),
                self.log,
                timeout=0.3,
                timeout_message="too slow",
            )
        self.assertLess(time.monotonic() - started, 2.5)
        time.sleep(3)
        self.assertFalse(marker.exists())

    def test_stop_request_propagates_and_stops_the_child(self):
        marker = self.folder / "late"
        deadline = time.monotonic() + 0.3

        def should_stop():
            if time.monotonic() > deadline:
                raise Stop()

        with self.assertRaises(Stop):
            run_worker(
                self.python(f"import time,pathlib;time.sleep(3);pathlib.Path({str(marker)!r}).write_text('x')"),
                self.log,
                timeout=10,
                should_stop=should_stop,
            )
        time.sleep(3)
        self.assertFalse(marker.exists())

    def test_last_error_reads_the_final_reason(self):
        self.log.write_text("Traceback\nValueError: first\nmore\nValueError: mask is empty\n", encoding="utf-8")
        self.assertEqual(last_error(self.log), "mask is empty")
        self.assertIsNone(last_error(self.folder / "missing.log"))


if __name__ == "__main__":
    unittest.main()
