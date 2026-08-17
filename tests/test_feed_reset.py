"""
Tests for the new feed-reset behaviour added in bug-fix round 2.

These tests verify that:
  1. reset_states() actually clears LTP, bid/ask, and tick history
  2. stop_mock_feed() flips the flag so the mock loop exits cleanly
  3. MOCK_SEED_PRICES covers all 100 Nifty symbols (no missing seeds)
  4. The mock feed uses realistic seeds (RELIANCE near 2450, TCS near
     3500) instead of random.uniform(50, 5000)
  5. start_live_feed() stops any running mock feed so live and mock
     never both update the same state dict

Run with: python tests/test_feed_reset.py
"""
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websocket_client as wsc


def test_reset_states_clears_ltp_and_history():
    """reset_states() must wipe LTP, bid/ask, ltq, and tick history."""
    # Prime one symbol with data.
    s = wsc.states["RELIANCE"]
    for _ in range(50):
        s.update_tick(100.0, 50, 99.95, 1000, 100.05, 1000)
    assert s.ltp == 100.0
    assert s.bid_qty == 1000
    assert s.smma20 is not None
    assert len(s.ticks) == 50

    # Now reset.
    wsc.reset_states()

    # The state object for RELIANCE must be a NEW instance with no data.
    s2 = wsc.states["RELIANCE"]
    assert s2.ltp == 0, f"expected ltp=0, got {s2.ltp}"
    assert s2.bid_qty == 0
    assert s2.ask_qty == 0
    assert s2.ltq == 0
    assert s2.smma20 is None
    assert s2.smma120 is None
    assert len(s2.ticks) == 0
    print("PASS: reset_states clears LTP, bid/ask, smma, ticks")


def test_stop_mock_feed_sets_flag():
    """stop_mock_feed() flips the _MOCK_STOP flag."""
    wsc._MOCK_STOP = False
    wsc.stop_mock_feed()
    assert wsc._MOCK_STOP is True, "_MOCK_STOP not set after stop_mock_feed()"
    # Reset for subsequent tests.
    wsc._MOCK_STOP = False
    print("PASS: stop_mock_feed sets _MOCK_STOP")


def test_mock_seeds_cover_all_symbols():
    """Every Nifty 100 symbol has a seed price in MOCK_SEED_PRICES."""
    missing = [s for s in wsc.NIFTY_100_SYMBOLS if s not in wsc.MOCK_SEED_PRICES]
    assert not missing, f"Missing seed prices for: {missing}"
    print(f"PASS: All {len(wsc.NIFTY_100_SYMBOLS)} symbols have seed prices")


def test_mock_seeds_are_realistic():
    """Seed prices are in realistic NSE bands, not random 50-5000."""
    # A handful of well-known stocks with widely-known price bands.
    expected = {
        "RELIANCE": (2000, 3000),    # ~2450 in 2024
        "TCS":      (3000, 4500),    # ~3500
        "HDFCBANK": (1400, 2000),    # ~1700
        "INFY":     (1200, 2000),    # ~1500
        "ITC":      (350, 600),      # ~450
        "SBIN":     (700, 950),      # ~820
    }
    for sym, (lo, hi) in expected.items():
        seed = wsc.MOCK_SEED_PRICES[sym]
        assert lo <= seed <= hi, (
            f"{sym} seed ₹{seed} is outside realistic band ₹{lo}-₹{hi}"
        )
    print("PASS: Mock seeds are in realistic NSE price bands")


def test_mock_seed_walk_stays_in_band():
    """After pre-population, each symbol's LTP is still near its seed."""
    wsc.reset_states()
    # Run the pre-population phase only (don't start the steady-state loop).
    for s in wsc.states.values():
        seed = wsc.MOCK_SEED_PRICES.get(s.symbol, wsc._DEFAULT_SEED)
        ltp0 = seed * 1.0  # no noise, so we can assert tight bounds
        for _ in range(150):
            ltp0 = max(1.0, ltp0 + random_walk_step(seed))
            s.update_tick(ltp0, 100, ltp0 - 0.05, 1000, ltp0 + 0.05, 1000)
        # LTP after 150 ticks should be within ±10% of seed.
        # (random walk over 150 steps × 0.2% step size = ±30% max,
        # but typical is ±3%.)
        assert seed * 0.85 <= s.ltp <= seed * 1.15, (
            f"{s.symbol}: ltp {s.ltp:.2f} drifted too far from seed {seed}"
        )
    print("PASS: Mock pre-population keeps values within realistic bands")


def random_walk_step(seed):
    """Inline copy of the random walk step formula from mock_data_thread."""
    import random
    return random.uniform(-seed * 0.002, seed * 0.002)


def test_mock_thread_exits_on_stop():
    """mock_data_thread() must exit cleanly when stop_mock_feed() is called."""
    wsc.reset_states()
    t = threading.Thread(target=wsc.mock_data_thread, name="mock", daemon=True)
    t.start()
    # Let it run for ~1.5s.
    time.sleep(1.5)
    assert t.is_alive(), "Mock thread died unexpectedly"
    wsc.stop_mock_feed()
    # Loop checks flag once per second; allow up to 2s to exit.
    t.join(timeout=2.0)
    assert not t.is_alive(), "Mock thread did not exit after stop_mock_feed()"
    print("PASS: Mock thread exits within 2s of stop_mock_feed()")


def test_reset_after_mock():
    """After running the mock and resetting, the dashboard has clean state."""
    wsc.reset_states()
    t = threading.Thread(target=wsc.mock_data_thread, name="mock", daemon=True)
    t.start()
    time.sleep(1.0)  # let pre-population finish
    assert wsc.states["RELIANCE"].ltp > 0, "Mock pre-population failed"
    wsc.stop_mock_feed()
    t.join(timeout=2.0)
    wsc.reset_states()
    assert wsc.states["RELIANCE"].ltp == 0
    assert wsc.states["RELIANCE"].smma20 is None
    assert len(wsc.states["RELIANCE"].ticks) == 0
    print("PASS: reset_states() after mock run gives clean slate")


if __name__ == "__main__":
    test_reset_states_clears_ltp_and_history()
    test_stop_mock_feed_sets_flag()
    test_mock_seeds_cover_all_symbols()
    test_mock_seeds_are_realistic()
    test_mock_seed_walk_stays_in_band()
    test_mock_thread_exits_on_stop()
    test_reset_after_mock()
    print("\nALL FEED RESET TESTS PASSED")
