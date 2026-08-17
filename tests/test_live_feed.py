"""
Diagnostic test for the live Angel One feed.

Simulates what happens when the user clicks "Connect to Angel One"
with valid credentials but without the SDK installed (which is the
most common failure mode based on the user's history).

Run: python test_live_feed.py
"""
import sys
import time
sys.path.insert(0, '/home/user')

import websocket_client as wsc
from shared import alerts


def test_scenario(label, **creds):
    """Run a single connect_live scenario and report the result."""
    print(f"\n=== {label} ===")
    print(f"  Credentials: {creds}")

    # Reset state for a clean test
    wsc.reset_states()
    alerts._buf.clear()

    start = time.time()
    success = wsc.start_live_feed(**creds)
    elapsed = time.time() - start

    print(f"  start_live_feed() returned: {success}  (took {elapsed:.1f}s)")
    print(f"  LIVE_FEED_AVAILABLE: {wsc.LIVE_FEED_AVAILABLE}")

    # Show the most recent alerts
    recent = alerts.all()[-3:]
    print(f"  Recent alerts (last 3 of {len(alerts.all())}):")
    for a in recent:
        print(f"    [{a.kind}] {a.message[:120]}")


# Scenario 1: Empty credentials
test_scenario("Empty credentials (should fail fast)")

# Scenario 2: Only partial credentials
test_scenario("Partial credentials (should fail fast)",
              api_key="abc123", client_code="AAK736675")

# Scenario 3: SDK not installed (most common)
test_scenario("Full credentials but SDK not installed",
              api_key="abc123",
              client_code="AAK736675",
              password="somepassword",
              totp_secret="JBSWY3DPEHPK3PXP")

# Scenario 4: Check what happens if user has only the secret in
# the wrong format (TOTP secret should be 16-32 base32 chars)
test_scenario("Invalid TOTP secret",
              api_key="abc123",
              client_code="AAK736675",
              password="somepassword",
              totp_secret="not-a-valid-base32-secret-!")

print()
print("=== SUMMARY ===")
print("If all four scenarios show 'start_live_feed() returned: False'")
print("with informative alert messages, the live feed code is correct.")
print("The only thing that can make the live feed work is:")
print("  1. Run: pip install smartapi-python websocket-client logzero")
print("  2. Enter your actual API key, client code, password, TOTP secret")
print("  3. Click 'Connect to Angel One' on the Login page")
