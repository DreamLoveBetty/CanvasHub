"""Stop a resident child if its owning HTTP process exits unexpectedly."""
import os
import threading
import time


def start_parent_watch():
    value = os.environ.get("CANVASHUB_IMAGE_PARENT_PID", "")
    if not value.isdigit() or os.name != "posix":
        return None
    parent = int(value)

    def watch():
        while os.getppid() == parent:
            time.sleep(.2)
        # Do not retain Metal memory while a replacement server admits a job.
        # This path only runs after the actual parent has exited.
        os._exit(0)

    thread = threading.Thread(target=watch, name="image-parent-watch", daemon=True)
    thread.start()
    return thread
