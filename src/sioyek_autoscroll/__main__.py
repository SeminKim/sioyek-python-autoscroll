import sys
from sioyek.sioyek import Sioyek, clean_path
import time
import threading
from pynput import mouse

# ---------------------------------
# Parameters
# ---------------------------------
BASE_HZ = 60          # loop frequency
DEAD_ZONE_PX = 8       # ignore small jitters near anchor
GAIN = 0.3             # pixels -> steps per second
MAX_RATE = 60         # max calls per second to avoid flooding
DEBUG = False          # do not call sioyek if DEBUG flag set

INACTIVITY_TIMEOUT_SEC = 3  # exit if no MMB click (press/release) for N seconds while *not* holding

# ---------------------------------
# State
# ---------------------------------
anchor = None
stop_worker = threading.Event()
worker_thread = None
mouse_ctrl = mouse.Controller()

hold_start_ts = None          # when current hold started (for HOLD_MAX_SEC safety below; set 0 to disable)
HOLD_MAX_SEC = 60             # max allowed time for a single hold/drag (0 = disabled)

last_mmb_event_ts = time.time()  # last time we saw a middle button press/release
middle_held = False               # are we currently holding the middle button?


def signed_excess(val, dead):
    if abs(val) <= dead:
        return 0.0
    return (abs(val) - dead) * (1 if val > 0 else -1)


def autoscroll_loop(sioyek):
    """Continuously call sioyek.move_up/move_down depending on drag distance."""
    period = 1.0 / BASE_HZ
    step_accum = 0.0  # fractional step accumulator

    while not stop_worker.is_set():
        # Optional per-hold safety
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


def make_on_click(sioyek):
    """Return an on_click callback bound to the given sioyek object."""
    def on_click(x, y, button, pressed):
        global anchor, worker_thread, hold_start_ts, last_mmb_event_ts, middle_held

        if button == mouse.Button.middle:
            last_mmb_event_ts = time.time()

            if pressed:
                # Enter autoscroll mode
                middle_held = True
                anchor = (x, y)
                hold_start_ts = time.time()
                stop_worker.clear()

                # Start worker if not running
                if worker_thread is None or not worker_thread.is_alive():
                    worker_thread = threading.Thread(
                        target=autoscroll_loop, args=(sioyek,), daemon=True
                    )
                    worker_thread.start()
            else:
                # Exit autoscroll mode; keep listener alive for future holds
                middle_held = False
                stop_worker.set()
    return on_click


def run_autoscroll(sioyek):
    """Run the autoscroll listener with a single inactivity watchdog."""
    listener = mouse.Listener(on_click=make_on_click(sioyek))
    listener.start()

    # Single watchdog: exit if no MMB events for INACTIVITY_TIMEOUT_SEC while *not* holding
    def inactivity_watchdog():
        if INACTIVITY_TIMEOUT_SEC <= 0:
            return
        while listener.running:
            if not middle_held and (time.time() - last_mmb_event_ts) >= INACTIVITY_TIMEOUT_SEC:
                try:
                    listener.stop()
                except Exception:
                    pass
                break
            time.sleep(0.2)

    t = None
    if INACTIVITY_TIMEOUT_SEC > 0:
        t = threading.Thread(target=inactivity_watchdog, daemon=True)
        t.start()

    # Block until listener stops (inactivity or external stop)
    listener.join()

    # Ensure worker ends
    stop_worker.set()
    if t:
        t.join(timeout=0.1)


# -------------------- main --------------------
if __name__ == '__main__':
    if DEBUG:
        class Mock:
            def move_up(self): print("↑ move_up()")
            def move_down(self): print("↓ move_down()")
        mock = Mock()
        print("[DEBUG] Starting autoscroll (Mock).")
        run_autoscroll(mock)
        print("[autoscroll stopped]")
    else:
        SIOYEK_PATH = clean_path(sys.argv[1])
        sioyek = Sioyek(SIOYEK_PATH)
        sioyek.set_status_string("Scrolling...")
        run_autoscroll(sioyek)
        sioyek.clear_status_string()
        time.sleep(0.5)  # give the status clear a moment
