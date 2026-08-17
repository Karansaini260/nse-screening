"""
Diagnostic tool: checks every environment / system / package
requirement for the NSE Screening app to work, especially the
live feed. Run with `python check_requirements.py` to see a
detailed report of what's installed, what's missing, and what
might be the cause if the live feed isn't working.

This script doesn't import any of the app's modules directly — it
only uses the standard library plus whatever packages are already
installed. Safe to run any time.
"""

import importlib
import importlib.metadata
import os
import platform
import socket
import sys
import urllib.request
import urllib.error


# --- Pretty-printing helpers ----------------------------------------

GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

USE_COLOR = sys.stdout.isatty()


def c(text, colour):
    if USE_COLOR:
        return f"{colour}{text}{RESET}"
    return text


def ok(msg):   return c("✓ " + msg, GREEN)
def warn(msg): return c("! " + msg, YELLOW)
def fail(msg): return c("✗ " + msg, RED)


# --- Checks --------------------------------------------------------

def check_python():
    """Need Python 3.9+ (the smartapi-python SDK uses modern type
    hints; 3.8 won't work)."""
    print(c(BOLD + "\n[ Python ]" + RESET, ""))
    v = sys.version_info
    if v >= (3, 9):
        print(ok(f"Python {v.major}.{v.minor}.{v.micro} (>= 3.9 required)"))
    elif v >= (3, 7):
        print(warn(f"Python {v.major}.{v.minor} — 3.9+ recommended"))
    else:
        print(fail(f"Python {v.major}.{v.minor} — too old; need 3.9+"))


def check_pip_packages():
    """The app needs these. Missing ones are highlighted."""
    print(c(BOLD + "\n[ Python packages ]" + RESET, ""))
    required = [
        # (name, what-it's-for, optional?)
        ("smartapi-python", "Angel One SDK — REQUIRED for live feed", False),
        ("websocket-client", "WebSocket transport for live feed", False),
        ("logzero", "Logging dependency of smartapi-python", False),
        ("pyotp", "TOTP code generation (optional, we have stdlib fallback)", True),
        ("pandas", "ML training data + CSV reading", False),
        ("scikit-learn", "Logistic Regression model for the AI filter", False),
        ("joblib", "Model persistence (saves/loads signal_model.pkl)", False),
        ("matplotlib", "Charts on Stock Detail + ML Stats pages", False),
    ]
    for name, desc, optional in required:
        try:
            v = importlib.metadata.version(name)
            print(ok(f"{name:20} {v:10} — {desc}"))
        except importlib.metadata.PackageNotFoundError:
            label = "MISSING (optional)" if optional else "MISSING (REQUIRED)"
            colour = YELLOW if optional else RED
            print(c(f"  {name:20} {'—':10} — {label}: {desc}", colour))


def check_imports():
    """Try to import the SDK and the WebSocket class — these are the
    two critical imports for the live feed path."""
    print(c(BOLD + "\n[ SDK imports ]" + RESET, ""))
    try:
        from SmartApi import SmartConnect
        print(ok(f"from SmartApi import SmartConnect"))
    except ImportError as e:
        print(fail(f"from SmartApi import SmartConnect — {e}"))
        print("    → Run: pip install smartapi-python")
        return

    try:
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        print(ok(f"from SmartApi.smartWebSocketV2 import SmartWebSocketV2"))
    except ImportError as e:
        print(fail(f"from SmartApi.smartWebSocketV2 import SmartWebSocketV2 — {e}"))
        print("    → The websocket class isn't importable. Some SDK versions")
        print("      expose it via the SmartConnect instance instead.")

    # Inspect the SmartConnect class for required methods.
    from SmartApi import SmartConnect
    for method in ("generateSession", "getfeedToken"):
        if hasattr(SmartConnect, method):
            print(ok(f"SmartConnect.{method}  exists"))
        else:
            print(fail(f"SmartConnect.{method}  MISSING"))


def check_network():
    """Three endpoints the app talks to. Each must be reachable."""
    print(c(BOLD + "\n[ Network ]" + RESET, ""))
    targets = [
        ("Angel One login API",  "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"),
        ("Scrip master file",   "https://margincalculator.angelone.in/OpenAPIScripMaster.json"),
        ("SmartAPI WebSocket",  "https://smartapisocket.angelone.in/"),
        ("PyPI (for pip)",      "https://pypi.org/simple/"),
    ]
    for label, url in targets:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=8) as resp:
                print(ok(f"{label:25} ({resp.status}) {url}"))
        except urllib.error.HTTPError as e:
            # 404 is OK for HEAD on some endpoints — we only care
            # that we can reach the host, not that the path is right.
            if e.code in (403, 405, 404):
                print(ok(f"{label:25} ({e.code}) {url}  (reachable)"))
            else:
                print(fail(f"{label:25} ({e.code}) {url}"))
        except Exception as e:
            print(fail(f"{label:25} {type(e).__name__}: {e}"))


def check_proxy():
    """If the user is behind a corporate proxy, the WebSocket may
    silently fail. Print env vars that affect proxying."""
    print(c(BOLD + "\n[ Proxy / firewall env vars ]" + RESET, ""))
    env_vars = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                "NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"]
    found = False
    for var in env_vars:
        val = os.environ.get(var)
        if val:
            print(warn(f"{var} = {val}"))
            found = True
    if not found:
        print(ok("No proxy env vars set (direct connection)"))


def check_tk():
    """The app is a tkinter GUI; needs a display."""
    print(c(BOLD + "\n[ Display / Tkinter ]" + RESET, ""))
    if "DISPLAY" in os.environ or platform.system() == "Windows" or platform.system() == "Darwin":
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            print(ok(f"Tk version {root.tk.eval('info patchlevel')}"))
            root.destroy()
        except Exception as e:
            print(fail(f"Tk failed to init: {e}"))
    else:
        print(warn("No DISPLAY env var — you're on a headless Linux box."))
        print("    The app needs a graphical session. Run it on a machine")
        print("    with a desktop (your laptop, a Windows RDP, etc.)")


def check_credentials_path():
    """Confirm the project's source files are all present. Just a
    quick sanity check — the app itself doesn't read any of them
    by name; it imports them as modules."""
    print(c(BOLD + "\n[ Project files ]" + RESET, ""))
    files = [
        "app.py", "shared.py", "theme.py", "design.py", "cards.py",
        "indicators.py", "websocket_client.py", "ai_model.py",
        "train_model.py", "trade_tracker.py",
        "pages/__init__.py",
    ]
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        print(fail(f"Missing project files: {', '.join(missing)}"))
    else:
        print(ok(f"All {len(files)} project files present"))


def check_angel_one_account():
    """Print a checklist for things only the user can verify."""
    print(c(BOLD + "\n[ Angel One account ]" + RESET, ""))
    print("  These can only be verified by you:")
    print("    □ API key generated from the Angel One developer dashboard")
    print("    □ Client code matches your Angel One login ID")
    print("    □ Password is the same as your Angel One login password")
    print("    □ TOTP secret (base32) is the same string as in your")
    print("      authenticator app (Google Authenticator, etc.)")
    print("    □ Market hours: Mon-Fri 09:15 - 15:30 IST. Outside this")
    print("      window, the feed connects but no ticks come in.")
    print("    □ Account has Market Data API access (some plans need")
    print("      explicit activation; check Angel One support).")


def check_market_hours():
    """The live feed only has data during NSE market hours. Show
    current IST time and whether the market is open."""
    print(c(BOLD + "\n[ Market hours (IST) ]" + RESET, ""))
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(IST)
    weekday = now_ist.weekday()  # 0 = Mon, 6 = Sun
    hour = now_ist.hour
    minute = now_ist.minute
    in_session = (
        weekday < 5
        and ((hour == 9 and minute >= 15) or hour in range(10, 15)
             or (hour == 15 and minute <= 30))
    )
    pre_open = weekday < 5 and hour == 9 and minute < 15
    print(f"Current IST time: {now_ist.strftime('%Y-%m-%d %H:%M:%S %A')}")
    if in_session:
        print(ok("Market is OPEN — live ticks should be flowing"))
    elif pre_open:
        print(warn("Pre-open session (09:00 - 09:15 IST)"))
    elif weekday < 5 and hour < 9:
        print(warn("Before market open (waiting for 09:15 IST)"))
    elif weekday < 5 and hour >= 16:
        print(warn("After market close (15:30 IST)"))
    else:
        print(warn("Weekend — market closed"))


def main():
    print(c(BOLD + "=" * 60 + RESET, ""))
    print(c(BOLD + "  NSE Screening — environment check" + RESET, ""))
    print(c(BOLD + "=" * 60 + RESET, ""))
    check_python()
    check_pip_packages()
    check_imports()
    check_network()
    check_proxy()
    check_tk()
    check_credentials_path()
    check_market_hours()
    check_angel_one_account()
    print(c(BOLD + "\n[ Done ]" + RESET, ""))
    print("If something above is red, that's likely why the live feed")
    print("isn't working. Most common fix: `pip install smartapi-python`")
    print("inside the same virtualenv you use for `python app.py`.")


if __name__ == "__main__":
    main()
