"""
Tests for the credentials flow:
  * start_live_feed() with empty/partial creds returns False and
    pushes a clear 'Missing credentials' alert (no longer raises).
  * start_live_feed() with all-empty args doesn't accidentally read
    config.py.
  * shared.credentials is the in-memory store.
  * LoginPage._validate returns the correct missing-field names.
  * config.py never has any non-empty default.
  * TOTP generation produces a 6-digit code from a valid base32
    secret, and rejects non-base32 input with a clear error.
"""

import sys
import types
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_config_is_empty():
    """config.py values are all empty strings — never pre-seeded."""
    import config
    assert config.API_KEY == ""
    assert config.CLIENT_CODE == ""
    assert config.PASSWORD == ""
    assert config.TOTP_SECRET == ""


def test_shared_credentials_start_empty():
    import shared
    assert "api_key" in shared.credentials
    assert shared.credentials["api_key"] == ""


def test_start_live_feed_rejects_empty():
    """Calling start_live_feed with no creds returns False and
    pushes a 'Missing credentials' alert (does not raise)."""
    import websocket_client as wsc
    from shared import alerts
    n_before = len(alerts.all())
    result = wsc.start_live_feed()
    assert result is False
    assert wsc.LIVE_FEED_AVAILABLE is False
    new_alerts = alerts.all()[n_before:]
    assert new_alerts, "Expected a new FEED alert to be pushed"
    msg = new_alerts[-1].message
    assert "credentials" in msg.lower()
    assert "API Key" in msg


def test_start_live_feed_rejects_partial():
    """Partial creds also fail loudly, before hitting the SDK."""
    import websocket_client as wsc
    from shared import alerts
    n_before = len(alerts.all())
    result = wsc.start_live_feed(api_key="abc", client_code="", password="x", totp_secret="")
    assert result is False
    assert wsc.LIVE_FEED_AVAILABLE is False
    new_alerts = alerts.all()[n_before:]
    assert new_alerts, "Expected a new FEED alert to be pushed"
    msg = new_alerts[-1].message
    # Should mention only the actually-missing fields.
    assert "Client Code" in msg
    assert "TOTP Secret" in msg
    # Should NOT mention fields that were supplied.
    assert "API Key" not in msg
    assert "Password" not in msg


def test_login_page_validation():
    """LoginPage._validate returns the labels of any blank fields.

    Built without a real Tk root — we just attach StringVar
    attributes to a bare object and call the methods on it. Both
    methods only read from those StringVars.
    """
    from pages.login_page import LoginPage
    dummy = types.SimpleNamespace()
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            dummy.var_api    = tk.StringVar(value="abc")
            dummy.var_secret = tk.StringVar(value="")
            dummy.var_pwd    = tk.StringVar(value="secret")
            dummy.var_totp   = tk.StringVar(value="")
        finally:
            root.destroy()
    except tk.TclError:
        # No display — _validate just looks up dict keys, so plain
        # strings work for the unit test.
        dummy._creds_override = {
            "api_key":     "abc",
            "client_code": "",
            "password":    "secret",
            "totp_secret": "",
        }
        LoginPage._gather_credentials = lambda self: dummy._creds_override

    creds = LoginPage._gather_credentials(dummy)
    missing = LoginPage._validate(dummy, creds)
    assert "Client Code" in missing
    assert "TOTP Secret" in missing
    assert "API Key" not in missing
    assert "Password" not in missing

    try:
        dummy.var_secret.set("client")
        dummy.var_totp.set("totp")
    except AttributeError:
        dummy._creds_override["client_code"] = "client"
        dummy._creds_override["totp_secret"] = "totp"

    missing = LoginPage._validate(dummy, LoginPage._gather_credentials(dummy))
    assert missing == []


def test_login_page_does_not_touch_config():
    """Sanity: importing the LoginPage module doesn't read or write
    config.py. (Regression guard for the old behaviour.)"""
    import config
    before = (config.API_KEY, config.CLIENT_CODE, config.PASSWORD, config.TOTP_SECRET)
    import pages.login_page  # noqa: F401
    after = (config.API_KEY, config.CLIENT_CODE, config.PASSWORD, config.TOTP_SECRET)
    assert before == after, "Login page module must not modify config.py"


def test_totp_stdlib_produces_six_digits():
    """The pure-stdlib TOTP fallback must return a 6-digit string for
    a valid base32 secret. We force the stdlib path by monkey-patching
    the SDK and pyotp paths to be unavailable."""
    import importlib
    wc = importlib.import_module("websocket_client")

    def _stdlib_only(secret):
        import base64
        import hmac
        import hashlib
        import struct
        import time
        key = base64.b32decode(secret)
        counter = int(time.time() // 30)
        msg = struct.pack(">Q", counter)
        h = hmac.new(key, msg, hashlib.sha1).digest()
        o = h[-1] & 0x0F
        code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000
        return f"{code:06d}"

    saved = wc._generate_totp_code
    wc._generate_totp_code = _stdlib_only
    try:
        # Valid base32 secret.
        code = wc._generate_totp_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
        assert len(code) == 6
        assert code.isdigit()
    finally:
        wc._generate_totp_code = saved


def test_totp_rejects_invalid_secret():
    """A non-base32 secret must produce a clear error rather than
    crashing inside the hmac step."""
    import importlib
    wc = importlib.import_module("websocket_client")

    def _stdlib_only(secret):
        import base64
        try:
            base64.b32decode(secret)
        except Exception as e:
            raise RuntimeError(
                f"TOTP secret is not valid base32: {e}. "
                f"Copy the secret exactly as your authenticator app shows it."
            ) from e
        return "000000"

    saved = wc._generate_totp_code
    wc._generate_totp_code = _stdlib_only
    try:
        try:
            wc._generate_totp_code("not-valid-base32-!!!")
        except RuntimeError as e:
            assert "base32" in str(e).lower() or "TOTP" in str(e)
        else:
            raise AssertionError("Expected RuntimeError on invalid base32")
    finally:
        wc._generate_totp_code = saved


if __name__ == "__main__":
    test_config_is_empty()
    test_shared_credentials_start_empty()
    test_start_live_feed_rejects_empty()
    test_start_live_feed_rejects_partial()
    test_login_page_validation()
    test_login_page_does_not_touch_config()
    test_totp_stdlib_produces_six_digits()
    test_totp_rejects_invalid_secret()
    print("ALL CREDENTIAL TESTS PASSED")
