###############################################
# brainlog.py - the brain's log file
#
# Everything printed to the console also goes to
# logs/brain_YYYY-MM-DD.log, one timestamp per line,
# so problems can be read after the fact.
#
# The log holds SYSTEM EVENTS ONLY. Anything that
# carries conversation text, her replies, memory
# notes, search words or links is printed with
# private() instead of print(): it still shows on
# the console, but the log only gets a content-free
# placeholder (or nothing).
###############################################
import os
import sys
import threading
from datetime import datetime, timedelta

import config

_lock = threading.RLock()
_state = {"file": None, "date": None, "line_start": True, "console": None}


def _prune():
    """Delete logs older than LOG_KEEP_DAYS."""
    cutoff = datetime.now() - timedelta(days=config.LOG_KEEP_DAYS)
    try:
        for name in os.listdir(config.LOG_DIR):
            if not (name.startswith("brain_") and name.endswith(".log")):
                continue
            try:
                day = datetime.strptime(name[6:16], "%Y-%m-%d")
            except ValueError:
                continue
            if day < cutoff:
                os.remove(os.path.join(config.LOG_DIR, name))
    except Exception:
        pass


def _log_file():
    """Today's log file, opening a new one when the date changes."""
    today = datetime.now().strftime("%Y-%m-%d")
    if _state["date"] != today:
        if _state["file"]:
            try:
                _state["file"].close()
            except Exception:
                pass
        os.makedirs(config.LOG_DIR, exist_ok=True)
        path = os.path.join(config.LOG_DIR, f"brain_{today}.log")
        _state["file"] = open(path, "a", encoding="utf-8", errors="replace",
                              buffering=1)
        _state["date"] = today
        _state["line_start"] = True
        _prune()
    return _state["file"]


def _to_log(text):
    """Write to the log, stamping the start of every line."""
    if not text:
        return
    try:
        f = _log_file()
        stamp = datetime.now().strftime("[%H:%M:%S] ")
        out = []
        for piece in text.splitlines(keepends=True):
            if _state["line_start"]:
                out.append(stamp)
            out.append(piece)
            _state["line_start"] = piece.endswith("\n")
        f.write("".join(out))
        f.flush()
    except Exception:
        pass            # a broken log must never break the brain


class _Tee:
    """Stands in for the console: writes to it and to the log."""

    def __init__(self, console):
        self._console = console

    def write(self, text):
        with _lock:
            self._console.write(text)
            _to_log(text)
        return len(text)

    def flush(self):
        with _lock:
            self._console.flush()

    def __getattr__(self, name):
        return getattr(self._console, name)


def start():
    """Send everything printed from now on to the log as well."""
    if _state["console"] is not None:
        return
    _state["console"] = sys.stdout
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)
    with _lock:
        _to_log("\n" + "=" * 50 + "\n  BRAIN STARTED\n" + "=" * 50 + "\n")


def private(text, log=None):
    """
    Print to the console only. 'log' is an optional content-free
    stand-in for the log, e.g. "<< Train: [reply, 84 chars]".
    """
    console = _state["console"]
    if console is None:          # logging not started - plain print
        print(text)
        return
    with _lock:
        console.write(str(text) + "\n")
        console.flush()
        if log:
            _to_log(str(log) + "\n")
