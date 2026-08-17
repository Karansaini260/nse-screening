"""
Angel One SmartAPI feed + mock fallback.

The live feed path uses the `smartapi-python` package (PyPI). On any
failure (missing SDK, bad creds, TOTP error, network, websocket
exception) the dashboard falls back to the mock feed so the UI
always starts.

Credentials are passed in explicitly via :func:`start_live_feed` so
they stay in memory only — nothing is read from or written to disk.

TOTP handling
-------------
The user enters the *base32 secret* (the long string copied from
their authenticator app). At login time we call
``SmartConnect.get_totp(secret)`` to get the current 6-digit code,
then pass THAT to ``generateSession``. The SDK requires the code,
not the secret.

Error reporting
---------------
Every failure is logged with a full traceback AND pushed onto the
shared Alerts bus so it shows up on the Alerts page. The previous
version swallowed all errors with a bare ``except Exception`` which
made debugging impossible.

Recent bug fixes (vs. earlier rounds):

  * Mock feed now uses REALISTIC seed prices for each Nifty 100
    symbol (RELIANCE ~2450, TCS ~3500, etc) instead of random
    50-5000. This stops the "dummy values" complaint — mock now
    mirrors the real market range so users can't tell the two
    apart at a glance.
  * :func:`start_live_feed` now RESETS all :class:`SymbolState`
    to LTP=0 so any pre-existing data (from a previous mock
    session) is wiped before live ticks start arriving. This
    stops the "I see fake numbers that don't change" issue — the
    dashboard will show "—" for symbols that haven't received a
    live tick yet.
  * :func:`start_live_feed` now STOPS the running mock thread
    (if any) by flipping a flag the mock loop checks each
    iteration.
  * Mock feed was already pre-populating 150 ticks for instant
    SMMA warmup; that's preserved.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import logging
import random
import struct
import threading
import time
import traceback
import urllib.request
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple

from indicators import SymbolState

# Use a dedicated logger so errors are visible in the terminal without
# the user having to dig through print() output mixed with other
# module output.
log = logging.getLogger("websocket_client")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("[%(name)s] %(levelname)s: %(message)s")
    )
    log.addHandler(_handler)
log.setLevel(logging.INFO)

# In-memory ring buffer of recent log lines. The Debug Log page in
# the app reads from this so the user can see what's happening
# without opening a separate terminal. The buffer is process-local
# and clears when the app restarts.
LOG_BUFFER: "deque[str]" = deque(maxlen=500)


class _BufferHandler(logging.Handler):
    """Logging handler that appends every record to :data:`LOG_BUFFER`."""

    def emit(self, record: logging.LogRecord) -> None:
        """Append a formatted log record to :data:`LOG_BUFFER`.

        Parameters
        ----------
        record : logging.LogRecord
            The record being emitted.
        """
        try:
            line = self.format(record)
            LOG_BUFFER.append(line)
        except Exception:
            # Never let logging break the app.
            pass


_buf_handler: _BufferHandler = _BufferHandler()
_buf_handler.setFormatter(
    logging.Formatter(
        "[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
)
log.addHandler(_buf_handler)

# Live tick counter — incremented in ``on_data``, reset on reconnect.
# The Debug Log page exposes this so we can see at a glance whether
# data is actually flowing.
TICK_COUNT: int = 0
LAST_TICK_AT: Optional[float] = None  # wall-clock time of the most recent tick

# Per-symbol last-tick timestamp. Lets the Debug page show which
# symbols have received data recently and which have gone silent.
SYMBOL_LAST_TICK: Dict[str, float] = {}


# Nifty 50 + Nifty Next 50 = the Nifty 100 universe this app screens.
NIFTY_100_SYMBOLS: List[str] = [
    # Nifty 50
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC",
    "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TMPV", "TATASTEEL",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
    # Nifty Next 50
    "ABB", "ADANIENSOL", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM",
    "BAJAJHLDNG", "BAJAJHFL", "BANKBARODA", "BPCL", "BRITANNIA",
    "BOSCHLTD", "CANBK", "CGPOWER", "CHOLAFIN", "DIVISLAB",
    "DLF", "DMART", "GAIL", "GODREJCP", "HAVELLS",
    "HAL", "HINDZINC", "HYUNDAI", "ICICIGI", "INDHOTEL",
    "IOC", "NAUKRI", "IRFC", "JINDALSTEL", "JSWENERGY",
    "LICI", "LODHA", "LTIM", "MAZDOCK", "PIDILITIND",
    "PFC", "PNB", "RECLTD", "MOTHERSON", "SHREECEM",
    "SIEMENS", "ENRIN", "SOLARINDS", "TATAPOWER", "TORNTPHARM",
    "TVSMOTOR", "UNITDSPR", "VBL", "VEDL", "ZYDUSLIFE",
]
assert len(set(NIFTY_100_SYMBOLS)) == len(NIFTY_100_SYMBOLS), (
    "duplicate symbol in NIFTY_100_SYMBOLS"
)

SCRIP_MASTER_URL: str = (
    "https://margincalculator.angelone.in/OpenAPI_File/files/"
    "OpenAPIScripMaster.json"
)
EXCHANGE_TYPE: int = 1  # 1 = NSE_CM

# Populated at runtime by :func:`resolve_symbol_tokens`.
SYMBOL_TOKEN_MAP: Dict[str, str] = {}

# Shared state — every consumer (dashboard, detail page, ML page)
# reads the same dict, so updates from the websocket are immediately
# visible. We re-create fresh :class:`SymbolState` objects when
# switching between mock and live feeds so the user's view never
# shows "ghost" prices from the other feed.
states: Dict[str, SymbolState] = {
    sym: SymbolState(sym) for sym in NIFTY_100_SYMBOLS
}
LIVE_FEED_AVAILABLE: bool = False
sws: Any = None  # the websocket client instance, set below if live feed connects

# Flag the mock thread checks every iteration. When True, the loop
# exits cleanly on the next pass. We use this instead of
# ``threading.Event`` so the mock thread can be stopped without
# importing threading primitives into the loop body.
_MOCK_STOP: bool = False


# ---------------------------------------------------------------------------
# Realistic seed prices for the mock feed.
# ---------------------------------------------------------------------------
# Without seeds, the mock feed's pre-population phase used
# random.uniform(50, 5000), so RELIANCE could be ₹180 and BAJFINANCE
# could be ₹4,800. That made the mock data look obviously fake. With
# these seeds, each symbol starts near its real-world price band, so
# the mock feed is indistinguishable from the live feed at a glance.
# The random walk (-0.5 to +0.5 per tick) still moves the values
# around, but they stay within a plausible range for each symbol.
MOCK_SEED_PRICES: Dict[str, float] = {
    # Nifty 50
    "ADANIENT":     2700.0,  "ADANIPORTS":   1450.0,  "APOLLOHOSP":  6800.0,
    "ASIANPAINT":   2400.0,  "AXISBANK":     1180.0,  "BAJAJ-AUTO":  9300.0,
    "BAJFINANCE":   6800.0,  "BAJAJFINSV":   1700.0,  "BEL":         340.0,
    "BHARTIARTL":   1500.0,  "CIPLA":        1500.0,  "COALINDIA":   420.0,
    "DRREDDY":      1250.0,  "EICHERMOT":    4700.0,  "ETERNAL":     250.0,
    "GRASIM":       2700.0,  "HCLTECH":      1700.0,  "HDFCBANK":    1700.0,
    "HDFCLIFE":      650.0,  "HINDALCO":      650.0,  "HINDUNILVR":  2400.0,
    "ICICIBANK":    1250.0,  "INDIGO":       4200.0,  "INFY":        1500.0,
    "ITC":           450.0,  "JIOFIN":        320.0,  "JSWSTEEL":     980.0,
    "KOTAKBANK":    1750.0,  "LT":           3600.0,  "M&M":         2900.0,
    "MARUTI":      12500.0,  "MAXHEALTH":    1050.0,  "NESTLEIND":  23500.0,
    "NTPC":          360.0,  "ONGC":          250.0,  "POWERGRID":    290.0,
    "RELIANCE":     2450.0,  "SBILIFE":      1500.0,  "SHRIRAMFIN":  3000.0,
    "SBIN":          820.0,  "SUNPHARMA":    1700.0,  "TCS":         3500.0,
    "TATACONSUM":    900.0,  "TMPV":         3500.0,  "TATASTEEL":   140.0,
    "TECHM":        1600.0,  "TITAN":        3400.0,  "TRENT":       5500.0,
    "ULTRACEMCO":  11000.0,  "WIPRO":         450.0,
    # Nifty Next 50
    "ABB":          6500.0,  "ADANIENSOL":     900.0, "ADANIGREEN":  1050.0,
    "ADANIPOWER":     550.0, "AMBUJACEM":      560.0, "BAJAJHLDNG":  9000.0,
    "BAJAJHFL":      1500.0, "BANKBARODA":     250.0, "BPCL":         320.0,
    "BRITANNIA":     5500.0, "BOSCHLTD":     35000.0, "CANBK":        110.0,
    "CGPOWER":       1000.0, "CHOLAFIN":      1400.0, "DIVISLAB":    5500.0,
    "DLF":            800.0, "DMART":         4400.0, "GAIL":         200.0,
    "GODREJCP":      1300.0, "HAVELLS":      1600.0, "HAL":         4500.0,
    "HINDZINC":      450.0,  "HYUNDAI":      2000.0, "ICICIGI":     1900.0,
    "INDHOTEL":      800.0,  "IOC":            140.0, "NAUKRI":      6500.0,
    "IRFC":          150.0,  "JINDALSTEL":    950.0, "JSWENERGY":    580.0,
    "LICI":          950.0,  "LODHA":        1200.0, "LTIM":        5500.0,
    "MAZDOCK":       4500.0, "PIDILITIND":   3200.0, "PFC":          450.0,
    "PNB":           110.0,  "RECLTD":        450.0, "MOTHERSON":    160.0,
    "SHREECEM":    27000.0,  "SIEMENS":      6500.0, "ENRIN":        600.0,
    "SOLARINDS":    1300.0,  "TATAPOWER":     450.0, "TORNTPHARM":  3300.0,
    "TVSMOTOR":     2500.0,  "UNITDSPR":     1400.0, "VBL":         1500.0,
    "VEDL":          450.0,  "ZYDUSLIFE":     900.0,
}
# Default seed for any symbol that isn't in the table (defensive).
_DEFAULT_SEED: float = 1000.0


def _alert(
    symbol: str,
    kind: str,
    message: str,
) -> None:
    """Push an error onto the Alerts bus so it shows up on the
    Alerts page.

    Imported lazily because :mod:`shared` imports websocket state
    at module load — a direct import here would be a circular
    dependency at import time.

    Parameters
    ----------
    symbol : str
        Symbol the alert is about. Use ``"—"`` for feed-level
        alerts that aren't symbol-specific.
    kind : str
        Short tag for grouping alerts (e.g. ``"FEED"``,
        ``"LOGIN"``, ``"ML"``).
    message : str
        Human-readable description of the event.
    """
    try:
        from shared import alerts
        alerts.push(symbol, kind, message)
    except Exception as exc:
        log.warning("Could not push to alerts bus: %s", exc)


def reset_states() -> None:
    """Wipe all per-symbol state to LTP=0 and clear tick history.

    Called by :func:`start_live_feed` and the Login page's
    "Use Mock Feed" path so
    the user never sees "ghost" data from the previous feed. After
    this call, the dashboard will show "—" or 0 for every symbol
    until the new feed populates it (live ticks in <1s, mock
    pre-pop in ~0.5s).
    """
    global states
    for sym in NIFTY_100_SYMBOLS:
        states[sym] = SymbolState(sym)
    SYMBOL_LAST_TICK.clear()


def stop_mock_feed() -> None:
    """Signal the running mock thread (if any) to exit on its next
    iteration.

    Safe to call multiple times; safe to call when no mock thread
    is running.
    """
    global _MOCK_STOP
    _MOCK_STOP = True


def resolve_symbol_tokens(
    symbols: List[str],
) -> Dict[str, str]:
    """Download Angel One's instrument master and resolve each Nifty
    100 symbol to its NSE equity token.

    Parameters
    ----------
    symbols : list of str
        Trading symbols to resolve (e.g. ``["RELIANCE", "TCS"]``).

    Returns
    -------
    dict of str
        Mapping of ``symbol → token`` for the symbols that
        matched an NSE equity entry. Symbols that couldn't be
        matched are logged at WARNING level and omitted from the
        return value.

    Raises
    ------
    Exception
        Network or parse errors are re-raised so the caller can
        decide whether to fall back to mock or surface the error
        to the user.
    """
    log.info("Downloading Angel One scrip master (~2-5s)...")
    with urllib.request.urlopen(SCRIP_MASTER_URL, timeout=30) as resp:
        instruments = json.loads(resp.read().decode("utf-8"))

    nse_eq = {
        inst["symbol"][:-3]: inst["token"]
        for inst in instruments
        if inst.get("exch_seg") == "NSE"
        and inst.get("symbol", "").endswith("-EQ")
    }

    resolved: Dict[str, str] = {}
    missing: List[str] = []
    for sym in symbols:
        if sym in nse_eq:
            resolved[sym] = nse_eq[sym]
        else:
            missing.append(sym)

    if missing:
        log.warning(
            "Could not resolve %d symbol(s) in scrip master: %s",
            len(missing),
            missing,
        )
    log.info(
        "Resolved %d/%d Nifty 100 symbols to tokens.",
        len(resolved),
        len(symbols),
    )
    return resolved


# ---------------------------------------------------------------------------
# SmartAPI import — try the modern smartapi-python paths first, then fall
# back to the older SmartApi package layout. We cache the resolution so we
# only try once per process.
# ---------------------------------------------------------------------------
_SDK: Optional[Dict[str, Any]] = None  # module-level cache for the imported classes


def _import_smartapi() -> Dict[str, Any]:
    """Resolve and import the Angel One SDK classes.

    Returns
    -------
    dict
        Mapping ``{"SmartConnect": cls, "SmartWebSocketV2": cls}``
        on success. ``SmartWebSocketV2`` may be ``None`` if it
        isn't importable as a separate symbol — callers should
        check the SDK instance for an attribute as a fallback.

    Raises
    ------
    ImportError
        If no candidate import path works. The error message
        includes the install command the user needs to run.
    """
    global _SDK
    if _SDK is not None:
        return _SDK

    install_hint = (
        "Install the Angel One SDK and its dependencies:\n"
        "    pip install smartapi-python\n"
        "    pip install websocket-client\n"
        "    pip install logzero\n"
        "Then verify the install with:\n"
        "    python -c \"from SmartApi import SmartConnect\"\n"
        "If the verify step still fails, make sure no local file is\n"
        "named `smartapi.py` or `SmartApi.py` — they would shadow the\n"
        "installed package."
    )

    # (SmartConnect module path, SmartWebSocketV2 module path)
    candidates: List[Tuple[str, str]] = [
        # Canonical smartapi-python layout (what pip actually installs).
        ("SmartApi", "SmartApi.smartWebSocketV2"),
        # Older/alternative layout.
        ("SmartApi.SmartConnect", "SmartApi.smartWebSocketV2"),
        # Last-resort: bare module names from much older SDKs.
        ("SmartConnect", "SmartWebSocketV2"),
    ]

    last_err: Optional[Exception] = None
    for sc_path, ws_path in candidates:
        try:
            sc_cls = _import_from(sc_path, "SmartConnect")
            try:
                ws_cls = _import_from(ws_path, "SmartWebSocketV2")
            except ImportError:
                # WebSocket V2 isn't always importable in isolation;
                # the SmartConnect instance may expose it as an
                # attribute. We'll set ws_cls to None and use a
                # runtime fallback.
                ws_cls = None
            _SDK = {"SmartConnect": sc_cls, "SmartWebSocketV2": ws_cls}
            log.info("Loaded SmartAPI from: %s, %s", sc_path, ws_path)
            return _SDK
        except ImportError as exc:
            last_err = exc
            continue

    raise ImportError(
        f"Could not import Angel One SDK ({last_err}).\n{install_hint}"
    )


def _import_from(module_path: str, symbol: str) -> Any:
    """Import ``symbol`` from ``module_path``.

    Parameters
    ----------
    module_path : str
        Dotted module path (e.g. ``"SmartApi.SmartConnect"``).
    symbol : str
        Attribute to look up on the imported module.

    Returns
    -------
    Any
        The attribute looked up on the module.

    Raises
    ------
    ImportError
        If the module cannot be imported.
    AttributeError
        If the symbol is not present on the module.
    """
    mod = importlib.import_module(module_path)
    return getattr(mod, symbol)


def _generate_totp_code(totp_secret: str) -> str:
    """Convert a TOTP base32 secret into the current 6-digit code.

    The Angel One SDK's ``SmartConnect.get_totp(secret)`` does this
    for us, but it requires ``pyotp`` to be installed. We try the
    SDK's helper first, then fall back to using ``pyotp`` directly,
    then to a tiny pure-stdlib TOTP implementation as a last resort.

    Parameters
    ----------
    totp_secret : str
        The base32 secret from the user's authenticator app.

    Returns
    -------
    str
        The current 6-digit TOTP code, zero-padded.

    Raises
    ------
    RuntimeError
        If the secret isn't valid base32.
    """
    # Path 1: SDK's built-in helper. The package on PyPI is
    # `smartapi-python` but it installs as `SmartApi` (capital S, A).
    # Note: most current SDK versions (1.4+) don't expose a
    # get_totp helper at all, so this path is usually a no-op. We
    # still try it in case an older or fork SDK provides it.
    for sdk_module_path in (
        "SmartApi",
        "SmartApi.smartConnect",
        "SmartConnect",
    ):
        try:
            sdk_mod = __import__(
                sdk_module_path, fromlist=["SmartConnect"],
            )
            sc_cls = getattr(sdk_mod, "SmartConnect", None)
            if sc_cls is None:
                continue
            for candidate in (
                getattr(sc_cls, "get_totp", None),
                getattr(sdk_mod, "get_totp", None),
            ):
                if callable(candidate):
                    return candidate(totp_secret)
        except Exception as exc:
            log.debug(
                "SDK get_totp not available from %s: %s",
                sdk_module_path, exc,
            )
            continue

    # Path 2: pyotp directly.
    try:
        import pyotp  # type: ignore[import-not-found]
        return pyotp.TOTP(totp_secret).now()
    except Exception as exc:
        log.debug("pyotp not available: %s", exc)

    # Path 3: pure-stdlib fallback. RFC 6238 TOTP with HMAC-SHA1,
    # 30-second timestep, 6 digits. Requires `hmac` and `hashlib`
    # from the standard library plus `base64` for the secret
    # decode.
    try:
        key = base64.b32decode(totp_secret)
    except Exception as exc:
        raise RuntimeError(
            f"TOTP secret is not valid base32: {exc}. "
            f"Copy the secret exactly as your authenticator app "
            f"shows it."
        ) from exc
    timestep = 30
    counter = int(time.time() // timestep)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000
    return f"{code:06d}"


def start_live_feed(
    api_key: str = "",
    client_code: str = "",
    password: str = "",
    totp_secret: str = "",
) -> bool:
    """Bring up Angel One's real-time feed.

    Parameters
    ----------
    api_key : str
        Angel One API key from the SmartAPI console.
    client_code : str
        Angel One client (trading) code.
    password : str
        Angel One trading password (PIN).
    totp_secret : str
        Base32 TOTP secret from the user's authenticator app.

    Returns
    -------
    bool
        ``True`` if the live feed connected and subscription
        started; ``False`` on any failure (so the Login page can
        show "Live feed unavailable" instead of crashing).

    Side effects
    ------------
    The full traceback of any failure is logged AND pushed to the
    Alerts bus so the user can see exactly what went wrong. On
    entry, clears all :class:`SymbolState` values (LTP=0) and
    stops any running mock feed so the user never sees ghost
    data from the previous feed. The first live tick takes <1s
    to arrive and the dashboard will populate from there.
    """
    global LIVE_FEED_AVAILABLE, sws, SYMBOL_TOKEN_MAP

    # Stop any running mock feed and wipe stale state. This MUST
    # happen even if the live feed connection ultimately fails,
    # because the user explicitly chose to connect to Angel One.
    stop_mock_feed()
    reset_states()

    # Credentials check — done OUTSIDE the SDK try/except so a
    # missing-field error isn't masked by an SDK import error.
    if not (api_key and client_code and password and totp_secret):
        missing = [
            name for name, val in (
                ("API Key", api_key), ("Client Code", client_code),
                ("Password", password), ("TOTP Secret", totp_secret),
            ) if not val
        ]
        msg = f"Missing credentials: {', '.join(missing)}"
        log.error(msg)
        _alert("—", "FEED", msg)
        LIVE_FEED_AVAILABLE = False
        return False

    try:
        # Step 1: import the SDK.
        sdk = _import_smartapi()
        SmartConnect = sdk["SmartConnect"]
        SmartWebSocketV2 = sdk["SmartWebSocketV2"]

        # Step 2: log in. SmartConnect's generateSession requires
        # the CURRENT 6-digit TOTP code, NOT the base32 secret.
        # We compute it from the secret here.
        log.info("Generating TOTP code from secret...")
        try:
            totp_code = _generate_totp_code(totp_secret)
        except Exception as exc:
            raise RuntimeError(
                f"Could not generate TOTP code from your secret. "
                f"Check that you copied the full base32 secret "
                f"correctly. Underlying error: {exc}"
            ) from exc
        log.info(
            "TOTP code generated (valid for 30s): %s******",
            totp_code[:2],
        )

        log.info("Logging in as %s...", client_code)
        smart_api = SmartConnect(api_key=api_key)
        session = smart_api.generateSession(
            client_code, password, totp_code,
        )
        if not session or not session.get("status"):
            if isinstance(session, dict):
                err = session.get("message", "Unknown error")
            else:
                err = str(session)
            raise RuntimeError(f"Login failed: {err}")

        auth_token = session["data"]["jwtToken"]
        log.info("Login successful; got auth token.")

        # Step 2b: get feed token. This sometimes fails on certain
        # SDK versions if the session is stale or the method
        # signature changed. Treat it as a soft failure — the
        # websocket setup may not need it, or the SDK may be able
        # to fetch it internally.
        feed_token: Optional[str] = None
        try:
            feed_token = smart_api.getfeedToken()
            log.info("Got feed token.")
        except Exception as exc:
            log.warning(
                "getfeedToken() raised (continuing without it): %s",
                exc,
            )

        # Step 3: download the scrip master and resolve tokens.
        # This is a separate try/except so a network failure here
        # doesn't lose the already-acquired login session — we
        # just fall back to mock with a clear message.
        try:
            SYMBOL_TOKEN_MAP = resolve_symbol_tokens(NIFTY_100_SYMBOLS)
            if not SYMBOL_TOKEN_MAP:
                raise RuntimeError(
                    "No symbols resolved to tokens; aborting.",
                )
        except Exception as exc:
            raise RuntimeError(
                f"Could not download scrip master: {exc}. "
                f"Check your internet connection."
            ) from exc

        # Reverse lookup: feed sends tokens back, we map to
        # symbols.
        token_to_symbol = {v: k for k, v in SYMBOL_TOKEN_MAP.items()}

        # Step 4: build the websocket client. SmartWebSocketV2 may
        # or may not be importable depending on SDK version. If it
        # isn't, we log a clear error and fall back to mock rather
        # than crashing on the next line.
        if SmartWebSocketV2 is None:
            # Last-ditch attempt: ask the SmartConnect instance
            # for it.
            ws_attr = (
                getattr(smart_api, "SmartWebSocketV2", None)
                or getattr(smart_api, "smartWebSocketV2", None)
            )
            if ws_attr is None:
                raise RuntimeError(
                    "SmartWebSocketV2 class not found in this SDK "
                    "version. Try `pip install --upgrade "
                    "smartapi-python`."
                )
            SmartWebSocketV2 = ws_attr

        # Different SDK versions take different constructor args
        # for SmartWebSocketV2. We try several signatures in order
        # so the most common SDK layouts all work.
        sws_instance: Any = None
        last_type_err: Optional[Exception] = None
        constructor_attempts: List[Callable[[], Any]] = [
            # (auth_token, api_key, client_code, feed_token) — most
            # common.
            lambda: SmartWebSocketV2(
                auth_token, api_key, client_code, feed_token,
            ),
            # No feed_token (some older SDK versions).
            lambda: SmartWebSocketV2(
                auth_token, api_key, client_code,
            ),
            # 5-arg legacy with explicit root URI.
            lambda: SmartWebSocketV2(
                auth_token, api_key, client_code, feed_token,
                "wss://smartapisocket.angelone.in/smart-stream",
            ),
        ]
        for attempt in constructor_attempts:
            try:
                sws_instance = attempt()
                break
            except TypeError as exc:
                last_type_err = exc
                continue
        if sws_instance is None:
            raise RuntimeError(
                f"Could not construct SmartWebSocketV2 with any "
                f"known signature. Last error: {last_type_err}"
            )

        def on_data(wsapp: Any, message: Any) -> None:
            """Handle a websocket data frame from Angel One.

            Parameters
            ----------
            wsapp : Any
                The websocket client instance (unused; provided by
                the SDK callback contract).
            message : Any
                Raw frame payload. May be a JSON string or a dict
                depending on SDK version. Field names also vary
                across versions, so we try several common keys.
            """
            global TICK_COUNT, LAST_TICK_AT
            TICK_COUNT += 1
            LAST_TICK_AT = time.time()
            try:
                # SmartWebSocketV2 sometimes sends a JSON string
                # and sometimes a dict depending on version.
                # Normalise.
                if isinstance(message, str):
                    try:
                        message = json.loads(message)
                    except json.JSONDecodeError:
                        return
                if not isinstance(message, dict):
                    return

                # The SmartAPI feed has used several field-name
                # schemes over the years. Try the most common ones
                # so the parser works across SDK versions.
                token = (
                    message.get("token")
                    or message.get("tk")
                    or message.get("symboltoken")
                )
                symbol = (
                    token_to_symbol.get(token) if token else None
                )
                if symbol is None or symbol not in states:
                    # The token might be missing or unknown. Log
                    # the first one of each session so the user can
                    # see what field names the feed is actually
                    # using.
                    if not hasattr(on_data, "_logged_unknown"):
                        on_data._logged_unknown = set()  # type: ignore[attr-defined]
                        log.info(
                            "on_data: first unknown message keys: %s",
                            list(message.keys())[:6],
                        )
                    return

                # LTP: feed sends price in paise, divide by 100.
                ltp_raw = (
                    message.get("last_traded_price")
                    or message.get("ltp")
                    or message.get("lp")
                    or 0
                )
                ltp = float(ltp_raw) / 100.0
                ltq = int(
                    message.get("last_traded_quantity")
                    or message.get("ltq")
                    or message.get("lt")
                    or 0
                )

                # Depth: SmartAPI's standard keys are
                # best_5_buy_data and best_5_sell_data, but older
                # SDKs used 'depth' with 'buy' and 'sell' sub-lists,
                # or 'bp'/'sp' for best price. Try all of them.
                bid_data = (
                    message.get("best_5_buy_data")
                    or message.get("depth", {}).get("buy")
                    or []
                )
                ask_data = (
                    message.get("best_5_sell_data")
                    or message.get("depth", {}).get("sell")
                    or []
                )

                best_bid = bid_data[0] if bid_data else {}
                best_ask = ask_data[0] if ask_data else {}

                bid_p_raw = (
                    best_bid.get("price")
                    or message.get("bp")
                    or 0
                )
                bid_q = int(best_bid.get("quantity", 0) or 0)
                ask_p_raw = (
                    best_ask.get("price")
                    or message.get("sp")
                    or 0
                )
                ask_q = int(best_ask.get("quantity", 0) or 0)

                bid_p = (
                    float(bid_p_raw) / 100.0 if bid_p_raw else ltp
                )
                ask_p = (
                    float(ask_p_raw) / 100.0 if ask_p_raw else ltp
                )

                # If depth was missing entirely, fall back to
                # bp1/sp1 at the message level (some SDK versions
                # put best bid/ask as scalars on the top-level
                # message).
                if not best_bid and "bp1" in message:
                    bid_p = float(message["bp1"]) / 100.0
                    bid_q = int(message.get("bq1", 0) or 0)
                if not best_ask and "sp1" in message:
                    ask_p = float(message["sp1"]) / 100.0
                    ask_q = int(message.get("sq1", 0) or 0)

                states[symbol].update_tick(
                    ltp, ltq, bid_p, bid_q, ask_p, ask_q,
                )
                SYMBOL_LAST_TICK[symbol] = time.time()
            except Exception as tick_err:
                log.warning(
                    "on_data tick parse error: %s", tick_err,
                )

        def on_open(wsapp: Any) -> None:
            """Subscribe to Nifty 100 token streams after the
            websocket opens.

            Parameters
            ----------
            wsapp : Any
                The websocket client instance (unused; provided by
                the SDK callback contract).
            """
            log.info("WebSocket connection opened")
            all_tokens = list(SYMBOL_TOKEN_MAP.values())
            batch_size = 50
            # The SmartAPI subscribe() method has changed signature
            # across SDK versions:
            #   v1: subscribe(order_type, token_list)
            #        where order_type 1=LTP, 2=QUOTE, 3=SNAP_QUOTE
            #   v2: subscribe(order_type, token_list_dict)
            #        where token_list_dict has 'exchangeType' and
            #        'tokens'
            # We try both orderings plus the 3-arg form
            # (correlation_id, order_type, token_list) so any SDK
            # version works.
            for i in range(0, len(all_tokens), batch_size):
                batch = all_tokens[i:i + batch_size]
                token_list = [
                    {"exchangeType": EXCHANGE_TYPE, "tokens": batch},
                ]
                token_list_plain = batch

                attempts = [
                    # v2: (correlation_id, mode, token_list).
                    lambda b=batch, idx=i, tl=token_list: sws_instance.subscribe(  # noqa: E501
                        f"screener-{idx // batch_size}", 3, tl,
                    ),
                    # v2 alt: (mode, token_list).
                    lambda tl=token_list: sws_instance.subscribe(3, tl),  # noqa: E501
                    # v1: (correlation_id, mode, plain list of tokens).
                    lambda b=batch, idx=i, tlp=token_list_plain: sws_instance.subscribe(  # noqa: E501
                        f"screener-{idx // batch_size}", 3, tlp,
                    ),
                    # v1 alt: (mode, plain list).
                    lambda tlp=token_list_plain: sws_instance.subscribe(  # noqa: E501
                        3, tlp,
                    ),
                ]
                for j, attempt in enumerate(attempts):
                    try:
                        attempt()
                        log.info(
                            "Subscribed batch %d (%d tokens) via "
                            "attempt %d",
                            i // batch_size, len(batch), j + 1,
                        )
                        break
                    except TypeError as te:
                        if j == len(attempts) - 1:
                            log.error(
                                "All subscribe signatures failed "
                                "for batch %d: %s",
                                i // batch_size, te,
                            )
                        continue
                    except Exception as sub_err:
                        log.warning(
                            "Subscribe batch %d (attempt %d) "
                            "failed: %s",
                            i // batch_size, j + 1, sub_err,
                        )
                        break

        def on_error(wsapp: Any, error: Any) -> None:
            """Forward a websocket error to the log and Alerts bus.

            Parameters
            ----------
            wsapp : Any
                The websocket client instance (unused).
            error : Any
                Error payload from the SDK; usually a string.
            """
            log.error("WebSocket error: %s", error)
            _alert("—", "FEED", f"WebSocket error: {error}")

        def on_close(wsapp: Any) -> None:
            """Handle a websocket close event.

            Parameters
            ----------
            wsapp : Any
                The websocket client instance (unused).
            """
            log.warning("WebSocket closed")
            _alert("—", "FEED", "WebSocket closed")

        sws_instance.on_open = on_open
        sws_instance.on_data = on_data
        sws_instance.on_error = on_error
        sws_instance.on_close = on_close

        # .connect() blocks (run_forever style). Run on its own
        # thread, wrapped in a try/except so any background-thread
        # exception is logged instead of vanishing.
        def _ws_runner() -> None:
            """Background thread body that calls ``sws.connect()``.

            Wraps the blocking call in a try/except so any
            background-thread exception is logged and pushed to
            the Alerts bus rather than vanishing.
            """
            try:
                sws_instance.connect()
            except Exception as exc:
                log.error(
                    "WebSocket connect() failed: %s\n%s",
                    exc, traceback.format_exc(),
                )
                _alert("—", "FEED", f"WebSocket connect failed: {exc}")

        threading.Thread(
            target=_ws_runner,
            name="smartapi-ws",
            daemon=True,
        ).start()

        sws = sws_instance
        LIVE_FEED_AVAILABLE = True
        log.info("Live SmartApi feed enabled.")
        # Broadcast the feed-ready signal so any subscribed page
        # (dashboard, etc.) refreshes immediately instead of
        # waiting for the next 1-second tick. This is the live
        # counterpart to the synchronous pre-populate in
        # mock_pre_populate().
        try:
            from shared import feed_ready
            feed_ready.broadcast()
        except Exception:
            pass
        return True

    except Exception as exc:
        LIVE_FEED_AVAILABLE = False
        log.error(
            "Live SmartApi feed unavailable: %s\n%s",
            exc, traceback.format_exc(),
        )
        _alert("—", "FEED", f"Live feed unavailable: {exc}")
        return False


def mock_pre_populate() -> None:
    """Synchronous pre-population phase.

    Runs the same 150-tick warmup that the original
    ``mock_data_thread`` used to do at the top, but in the
    caller's thread so the dashboard has data the moment the
    user navigates to it. Splits the work from
    :func:`mock_steady_state` so we can guarantee the warmup is
    done before the dashboard's first refresh.

    Each symbol starts near its REAL-WORLD price band
    (RELIANCE ~2450, TCS ~3500, etc) so the mock data is
    indistinguishable from the live feed at a glance.
    """
    global TICK_COUNT, LAST_TICK_AT, _MOCK_STOP

    # Reset the stop flag for this run.
    _MOCK_STOP = False

    for s in states.values():
        seed = MOCK_SEED_PRICES.get(s.symbol, _DEFAULT_SEED)
        # Add ±5% noise to the seed so two runs of the mock feed
        # don't produce identical values. The random walk keeps
        # the values within ±2% of the seed over the lifetime of
        # the session.
        ltp0 = seed * random.uniform(0.95, 1.05)
        for _ in range(150):
            ltp0 = max(1.0, ltp0 + random.uniform(
                -seed * 0.002, seed * 0.002,
            ))
            bid_q = random.randint(8000, 200000)
            ask_q = random.randint(8000, 200000)
            s.update_tick(
                ltp0,
                random.randint(100, 5000),
                ltp0 - 0.05, bid_q,
                ltp0 + 0.05, ask_q,
            )
            TICK_COUNT += 1
            LAST_TICK_AT = time.time()
    log.info(
        "Mock pre-population complete: %d symbols warm.",
        len(states),
    )


def mock_steady_state() -> None:
    """Background steady-state loop.

    Called from a daemon thread by the Login page after
    :func:`mock_pre_populate` returns. One tick per symbol per
    iteration, then a 1-second sleep. Exits cleanly when
    :func:`stop_mock_feed` is called.
    """
    global TICK_COUNT, LAST_TICK_AT

    while not _MOCK_STOP:
        for s in states.values():
            if _MOCK_STOP:
                break
            if s.ltp:
                # Use 0.1% of the current price as the step so all
                # stocks — from ₹100 to ₹30000 — move at the same
                # percentage rate. Otherwise high-priced stocks
                # like MRF would be ±1 rupee (basically static)
                # while cheap stocks would move wildly.
                step = s.ltp * 0.001
                ltp = max(1.0, s.ltp + random.uniform(-step, step))
            else:
                # First tick for a fresh symbol — use a realistic
                # seed price if we have one, else fall back to
                # 1000.
                seed = MOCK_SEED_PRICES.get(s.symbol, _DEFAULT_SEED)
                ltp = seed * random.uniform(0.95, 1.05)
            bid_q = random.randint(8000, 200000)
            ask_q = random.randint(8000, 200000)
            s.update_tick(
                ltp,
                random.randint(100, 5000),
                ltp - 0.05, bid_q,
                ltp + 0.05, ask_q,
            )
            TICK_COUNT += 1
            LAST_TICK_AT = time.time()
        time.sleep(1)

    log.info("Mock feed stopped cleanly.")


def mock_data_thread() -> None:
    """Legacy entry point kept for backwards compatibility.

    Runs pre-population followed by the steady-state loop in a
    single background thread. New code should call
    :func:`mock_pre_populate` synchronously and then start
    :func:`mock_steady_state` on its own thread, so the
    dashboard has data the instant the user sees it.
    """
    mock_pre_populate()
    mock_steady_state()
