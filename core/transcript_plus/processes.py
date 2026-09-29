import os
import signal
import subprocess
import threading
import time


def terminate_tree(process):
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        # Only descendants of the exact PID created by this application.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def monitor_parent():
    """Protect POSIX worker groups when the core is forcibly killed."""
    if os.name == "nt":
        return  # Windows host owns the Job Object for the entire process tree.
    parent = os.getppid()

    def watch():
        while True:
            time.sleep(1)
            if os.getppid() != parent:
                os.killpg(os.getpgrp(), signal.SIGKILL)
    threading.Thread(target=watch, daemon=True).start()
