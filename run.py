"""
XYZTradingAE — process supervisor.

Runs dashboard.py and main.py as child processes, restarts either if it
crashes (with exponential backoff capped at 30s), and shuts both down
cleanly on SIGTERM / SIGINT. Designed for Procfile-style hosts where the
foreground process is the dyno.
"""
import os
import signal
import subprocess
import sys
import threading
import time

CHILDREN = [
    ("dashboard", [sys.executable, "-u", "dashboard.py"]),
    ("main",      [sys.executable, "-u", "main.py"]),
]

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 30.0

_shutdown = threading.Event()
_procs: dict[str, subprocess.Popen] = {}
_procs_lock = threading.Lock()


def _log(name: str, msg: str) -> None:
    print(f"[supervisor:{name}] {msg}", flush=True)


def _pipe_output(name: str, stream) -> None:
    for raw in iter(stream.readline, b""):
        try:
            line = raw.decode("utf-8", errors="replace").rstrip()
        except Exception:
            line = repr(raw)
        print(f"[{name}] {line}", flush=True)


def _run_child(name: str, cmd: list[str]) -> None:
    backoff = INITIAL_BACKOFF
    while not _shutdown.is_set():
        _log(name, f"starting: {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
        except Exception as e:
            _log(name, f"failed to spawn: {e}; retrying in {backoff:.1f}s")
            if _shutdown.wait(backoff):
                return
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue

        with _procs_lock:
            _procs[name] = proc

        threading.Thread(target=_pipe_output, args=(name, proc.stdout), daemon=True).start()
        rc = proc.wait()

        with _procs_lock:
            _procs.pop(name, None)

        if _shutdown.is_set():
            _log(name, f"exited rc={rc} during shutdown")
            return

        if rc == 0:
            _log(name, "exited cleanly (rc=0); restarting after 1s")
            backoff = INITIAL_BACKOFF
        else:
            _log(name, f"crashed rc={rc}; restarting in {backoff:.1f}s")
        if _shutdown.wait(backoff):
            return
        backoff = min(backoff * 2, MAX_BACKOFF)


def _shutdown_handler(signum, _frame) -> None:
    _log("supervisor", f"received signal {signum}, terminating children")
    _shutdown.set()
    with _procs_lock:
        children = list(_procs.items())
    for name, proc in children:
        try:
            proc.terminate()
        except Exception as e:
            _log(name, f"terminate failed: {e}")

    # Give children a moment to exit, then SIGKILL stragglers
    deadline = time.time() + 5.0
    while time.time() < deadline:
        with _procs_lock:
            if not _procs:
                return
        time.sleep(0.1)
    with _procs_lock:
        for name, proc in list(_procs.items()):
            try:
                proc.kill()
                _log(name, "force-killed after grace period")
            except Exception:
                pass


def main() -> None:
    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    threads = []
    for name, cmd in CHILDREN:
        t = threading.Thread(target=_run_child, args=(name, cmd), daemon=False, name=name)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
    _log("supervisor", "all children exited")


if __name__ == "__main__":
    main()
