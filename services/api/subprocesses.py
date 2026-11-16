"""One way to run a background worker process: logged, time-limited, stoppable.

Every long-running worker (TripoSR/Hunyuan inference, SAM 2, PartCrafter, Blender renders,
part regeneration) goes through run_worker so that cancellation, timeouts and cleanup of
the child process behave the same everywhere. Short synchronous checks that answer an HTTP
request directly may still use subprocess.run with a timeout.
"""

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def stop_child(process, grace=10):
    """Stop a child (and on Windows its whole tree); safe to call on a finished process."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    else:
        process.terminate()
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=grace)


def last_error(log_path, markers=("ValueError: ", "RuntimeError: "), limit=300):
    """The last `ValueError: ...` style message a worker printed, for user-facing errors."""
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        for marker in markers:
            if marker in line:
                return line.split(marker, 1)[1][:limit]
    return None


def run_worker(
    command,
    log_path,
    *,
    timeout,
    should_stop=None,
    on_poll=None,
    timeout_message="本地处理超时，已停止",
    cwd=ROOT,
    env=None,
    poll_seconds=0.25,
):
    """Run `command` with stdout+stderr in `log_path`; return its exit code.

    should_stop(): called every poll; raise from it (e.g. Cancelled) to stop the worker.
    on_poll(): optional progress hook, called every poll while the worker runs.
    The child is always stopped before this function returns or raises.
    """
    started = time.monotonic()
    with Path(log_path).open("wb") as log:
        process = subprocess.Popen(
            [str(part) for part in command],
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(cwd),
            env={**os.environ, "PYTHONUTF8": "1", **(env or {})},
            creationflags=NO_WINDOW,
        )
        try:
            while process.poll() is None:
                if should_stop:
                    should_stop()
                if on_poll:
                    on_poll()
                if time.monotonic() - started > timeout:
                    raise ValueError(timeout_message)
                time.sleep(poll_seconds)
            if should_stop:
                should_stop()
            if on_poll:
                on_poll()
        finally:
            stop_child(process)
    return process.returncode
