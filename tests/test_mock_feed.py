"""
Tests for the mock feed.

The mock feed is the user's "I just want to see the UI work"
fallback. It must:
  * populate every symbol with a non-zero LTP within a fraction
    of a second of starting,
  * set smma20 and smma120 quickly enough that the dashboard's
    Gainers / Losers cards have something to show on first paint,
  * increment TICK_COUNT and LAST_TICK_AT so the "Live data"
    indicator and the Debug Log work the same way they do with the
    live feed.

These tests run the mock feed in a background thread, give it a
moment, then assert the expected post-conditions.
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _wait_until(predicate, timeout=5.0, interval=0.05):
    """Spin until `predicate()` returns True or `timeout` seconds pass.
    Returns the final boolean value of the predicate."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_mock_feed_populates_every_symbol():
    """Within 1 second of starting, every symbol has a non-zero LTP."""
    import websocket_client as wsc
    # Reset state so prior tests don't influence the count.
    for s in wsc.states.values():
        s.ltp = 0
        s.smma20 = None
        s.smma120 = None
    # Start the mock feed in a daemon thread.
    t = threading.Thread(target=wsc.mock_data_thread, name="test_mock", daemon=True)
    t.start()
    try:
        # The pre-population pass should give every symbol a non-zero
        # LTP almost immediately. We allow up to 2s for the thread
        # to actually start running on a slow CI box.
        ok = _wait_until(
            lambda: sum(1 for s in wsc.states.values() if s.ltp > 0) == len(wsc.states),
            timeout=2.0,
        )
        assert ok, "Mock feed didn't populate every symbol within 2s"
    finally:
        # Daemon thread; just let it die when the test process exits.
        pass


def test_mock_feed_warms_up_smmas_quickly():
    """After the pre-population pass, every symbol should have both
    smma20 and smma120 set — the dashboard's Gainers / Losers
    cards need those values immediately on first paint."""
    import websocket_client as wsc
    for s in wsc.states.values():
        s.ltp = 0
        s.smma20 = None
        s.smma120 = None
    t = threading.Thread(target=wsc.mock_data_thread, name="test_mock_smmas", daemon=True)
    t.start()
    try:
        # The pre-population pass feeds 150 ticks per symbol. That
        # should be more than enough to populate smma20 (needs 20)
        # and smma120 (needs 120). Give the thread up to 3s.
        ok = _wait_until(
            lambda: all(
                s.smma20 is not None and s.smma120 is not None
                for s in wsc.states.values()
            ),
            timeout=3.0,
        )
        assert ok, "Mock feed didn't warm up smma20/smma120 within 3s"
    finally:
        pass


def test_mock_feed_increments_tick_counter():
    """The mock feed should bump TICK_COUNT and LAST_TICK_AT so
    the dashboard's "Live data: N ticks" indicator and the
    Debug Log page work without modification."""
    import websocket_client as wsc
    # Reset tick counter so we can verify the mock feed bumped it.
    wsc.TICK_COUNT = 0
    wsc.LAST_TICK_AT = None
    t = threading.Thread(target=wsc.mock_data_thread, name="test_mock_ticks", daemon=True)
    t.start()
    try:
        # The pre-population pass alone should bump TICK_COUNT by
        # at least len(states). After a couple of seconds the
        # steady-state loop has bumped it even more.
        ok = _wait_until(
            lambda: wsc.TICK_COUNT >= len(wsc.states) and wsc.LAST_TICK_AT is not None,
            timeout=3.0,
        )
        assert ok, f"TICK_COUNT/LAST_TICK_AT not updated by mock feed: "\
                    f"TICK_COUNT={wsc.TICK_COUNT}, LAST_TICK_AT={wsc.LAST_TICK_AT}"
    finally:
        pass


if __name__ == "__main__":
    test_mock_feed_populates_every_symbol()
    test_mock_feed_warms_up_smmas_quickly()
    test_mock_feed_increments_tick_counter()
    print("ALL MOCK FEED TESTS PASSED")
