import sys
from sioyek.sioyek import Sioyek, clean_path
import time
import threading
from pynput import mouse

# ---------------------------------
# Parameters
# ---------------------------------
BASE_HZ = 240          # loop frequency
DEAD_ZONE_PX = 8       # ignore small jitters near anchor
GAIN = 0.3             # pixels -> steps per second
MAX_RATE = 240         # max calls per second to avoid flooding
DEBUG = False          # do not call sioyek if DEBUG flag set

# Timeouts (set to 0 to disable that timeout)
GLOBAL_TIMEOUT_SEC = 30     # exit if autoscroll never starts within N seconds (0 = disabled)
HOLD_MAX_SEC = 60           # max allowed time for a single hold/drag (0 = disabled)

# ---------------------------------
# State
# ---------------------------------
anchor = None
stop_worker = threading.Event()
worker_thread = None
mouse_ctrl = mouse.Controller()

# When did we last ENTER autoscroll (middle press)?
hold_start_ts = None

# Used by the global watchdog
autoscroll_started_evt = threading.Event()


def signed_excess(val, dead):
    if abs(val) <= dead:
        return 0.0
    return (abs(val) - dead) * (1 if val > 0 else -1)


def autoscroll_loop(sioyek):
    """Continuously call sioyek.move_up/move_down depending on drag distance."""
    period = 1.0 / BASE_HZ
    step_accum = 0.0  # fractional step accumulator

    while not stop_worker.is_set():
        # HOLD_MAX_SEC safety stop
        if HOLD_MAX_SEC > 0 and hold_start_ts is not None:
            if time.time() - hold_start_ts > HOLD_MAX_SEC:
                stop_worker.set()
                break

        # Current mouse position
        x, y = mouse_ctrl.position
        ax, ay = anchor

        dy = y - ay
        dy_excess = signed_excess(dy, DEAD_ZONE_PX)

        # Convert to step rate (steps per second)
        rate = dy_excess * GAIN
        rate = max(-MAX_RATE, min(MAX_RATE, rate))  # clamp

        # Accumulate fractional steps
        step_accum += rate * period

        # Emit integer steps, keep fractional part
        while step_accum >= 1.0:
            sioyek.move_down()
            step_accum -= 1.0
        while step_accum <= -1.0:
            sioyek.move_up()
            step_accum += 1.0

        time.sleep(period)


def make_on_click(sioyek, listener_ref):
    """Return an on_click callback bound to the given sioyek object."""
    def on_click(x, y, button, pressed):
        nonlocal listener_ref
        global anchor, worker_thread, hold_start_ts

        if button == mouse.Button.middle:
            if pressed:
                # Enter autoscroll mode
                anchor = (x, y)
                hold_start_ts = time.time()
                autoscroll_started_evt.set()  # tell watchdog we started
                stop_worker.clear()
                if worker_thread is None or not worker_thread.is_alive():
                    worker_thread = threading.Thread(
                        target=autoscroll_loop, args=(sioyek,), daemon=True
                    )
                    worker_thread.start()
            else:
                # Exit autoscroll mode
                stop_worker.set()
                # Stop the mouse listener to end the program
                if listener_ref is not None:
                    listener_ref.stop()
                return False  # quit
    return on_click


def run_autoscroll(sioyek):
    """Run the autoscroll listener for the given sioyek object with timeouts."""
    listener_ref = None

    # Start mouse listener
    listener = mouse.Listener(on_click=make_on_click(sioyek, listener_ref))
    listener_ref = listener
    listener.start()

    # Global watchdog: exit if no autoscroll ever starts within GLOBAL_TIMEOUT_SEC
    def watchdog():
        if GLOBAL_TIMEOUT_SEC <= 0:
            return
        if not autoscroll_started_evt.wait(timeout=GLOBAL_TIMEOUT_SEC):
            # Never started; stop listener so program exits
            try:
                listener.stop()
            except Exception:
                pass

    wd_thread = None
    if GLOBAL_TIMEOUT_SEC > 0:
        wd_thread = threading.Thread(target=watchdog, daemon=True)
        wd_thread.start()

    # Block until listener is done
    listener.join()

    # Ensure worker ends
    stop_worker.set()
    if wd_thread:
        wd_thread.join(timeout=0.1)


# -------------------- main --------------------
if __name__ == '__main__':
    if DEBUG:
        class Mock:
            def move_up(self): print("↑ move_up()")
            def move_down(self): print("↓ move_down()")
        mock = Mock()
        run_autoscroll(mock)
        print("[autoscroll stopped]")
    else:
        SIOYEK_PATH = clean_path(sys.argv[1])
        sioyek = Sioyek(SIOYEK_PATH)
        sioyek.set_status_string("Scrolling...")
        run_autoscroll(sioyek)
        sioyek.clear_status_string()
