"""Subprocess wrapper for ``immunize run <cmd>``.

Fallback automation path for environments without the Claude Code hook
(Cursor, bare terminals, CI, Codex, etc.). ``run`` spawns the user's command,
tees stdout and stderr live to the caller's terminal so the user sees output
in real time, captures the same bytes into in-memory buffers, and on non-zero
exit feeds those bytes into the matcher pipeline — the same pipeline
``capture`` uses.

Design constraints:

- **Live streaming**: two reader threads tee from the child pipes to
  sys.stdout / sys.stderr as lines arrive. Each thread owns its buffer list
  exclusively; there are no shared mutable lists, so no locking is required.
  CPython's stream writes are atomic at the call granularity, and stdout /
  stderr are different streams, so cross-stream interleave is a terminal-
  level concern we don't try to serialize.

- **Signal forwarding**: first Ctrl-C forwards SIGINT to the child so it can
  clean up; a second Ctrl-C sends SIGKILL. The original SIGINT handler is
  always restored on exit, including on exception paths. If signal.signal()
  fails (e.g. called from a non-main thread inside a test harness), the
  forwarder is silently skipped — the subprocess still runs, it just won't
  relay Ctrl-C.

- **Exit code propagation**: the CLI command must exit with the subprocess's
  exit code, not with any code of its own. Timeouts use 124 (GNU timeout
  convention).

- **Timeout semantics**: a --timeout trip kills the child, sets timed_out,
  and the caller skips capture. A user-imposed deadline is not a runtime
  bug worth persisting an immunity against.
"""

from __future__ import annotations

import contextlib
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import IO

TIMEOUT_EXIT_CODE = 124  # matches GNU `timeout(1)` convention


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def _tee_stream(src: IO[str], buf: list[str], sink: IO[str]) -> None:
    """Read from src line-by-line until EOF, teeing each line to sink + buf.

    `readline()` returns '' on EOF; iter(..., '') turns that into a clean
    StopIteration. `flush()` after each write because the caller's stdout
    may be fully buffered (pipe to file) — we want live output even then.
    """
    try:
        for line in iter(src.readline, ""):
            if not line:
                break
            sink.write(line)
            sink.flush()
            buf.append(line)
    finally:
        with contextlib.suppress(OSError):
            src.close()


def run_with_capture(
    cmd: list[str],
    *,
    timeout: int | None = None,
) -> RunResult:
    """Spawn ``cmd``, tee output to caller's stdout/stderr, return captured text.

    Returns a RunResult with the subprocess's exit code (or TIMEOUT_EXIT_CODE
    on deadline), the two captured buffers, and a timed_out flag. Never raises
    for subprocess-level failures — command-not-found exits 127 with a short
    stderr message, same as shell convention.
    """
    stdout_buf: list[str] = []
    stderr_buf: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered from the child's perspective
        )
    except FileNotFoundError as exc:
        # Mirror shell behavior: "command not found" exits 127.
        msg = f"immunize run: {exc}\n"
        sys.stderr.write(msg)
        return RunResult(exit_code=127, stdout="", stderr=msg, timed_out=False)
    except OSError as exc:
        msg = f"immunize run: failed to spawn: {exc}\n"
        sys.stderr.write(msg)
        return RunResult(exit_code=126, stdout="", stderr=msg, timed_out=False)

    # proc.stdout / proc.stderr are typed Optional[IO] by Popen's stubs. We
    # passed PIPE for both, so both are non-None; assert to narrow for mypy.
    assert proc.stdout is not None and proc.stderr is not None

    t_out = threading.Thread(
        target=_tee_stream,
        args=(proc.stdout, stdout_buf, sys.stdout),
        daemon=True,
        name="immunize-run-stdout-tee",
    )
    t_err = threading.Thread(
        target=_tee_stream,
        args=(proc.stderr, stderr_buf, sys.stderr),
        daemon=True,
        name="immunize-run-stderr-tee",
    )
    t_out.start()
    t_err.start()

    sigint_hits = [0]

    def _sigint_handler(signum, frame):  # noqa: ARG001
        sigint_hits[0] += 1
        try:
            if sigint_hits[0] == 1:
                proc.send_signal(signal.SIGINT)
            else:
                proc.kill()
        except (OSError, ProcessLookupError):
            pass

    original_handler = None
    try:
        original_handler = signal.signal(signal.SIGINT, _sigint_handler)
    except (OSError, ValueError):
        # Not running in the main thread (e.g. test harness). No forwarder;
        # the subprocess still runs, just without Ctrl-C relay.
        original_handler = None

    timed_out = False
    try:
        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Deadline tripped. Kill the child and drain what we can.
            proc.kill()
            timed_out = True
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)
            exit_code = TIMEOUT_EXIT_CODE
    finally:
        # Always restore the original handler, even if wait raised
        # unexpectedly. Ctrl-C safety for the parent process depends on it.
        if original_handler is not None:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(signal.SIGINT, original_handler)

    # Tee threads exit on pipe close (child exit or kill); bound-join to avoid
    # a hang if a thread gets stuck on a partial line read.
    t_out.join(timeout=5)
    t_err.join(timeout=5)

    return RunResult(
        exit_code=exit_code,
        stdout="".join(stdout_buf),
        stderr="".join(stderr_buf),
        timed_out=timed_out,
    )
