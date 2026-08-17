# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for the NSE Screening Tkinter app.

Build with:
    pyinstaller nse_screener.spec --clean

Output:
    dist/NSE_Screener/NSE_Screener.exe        (one-folder mode)

This spec is tuned for a client-facing build:

  * One-folder mode for faster startup (no temp-archive unpack).
  * Windowed (no console window flashes for the user).
  * Lazy-imported modules explicitly listed so PyInstaller's
    static analysis doesn't drop them.
  * Heavy non-runtime libs (Qt, IPython, pytest) excluded to
    keep the binary small.
  * UPX compression enabled if UPX is on PATH.
  * The COLLECT block assembles everything into a single
    `dist/NSE_Screener/` folder ready to ZIP and ship.

Why so many hiddenimports?
--------------------------
The app uses `importlib.import_module()` to lazy-load page
modules on first navigation. PyInstaller's static analysis
cannot see dynamic imports, so it doesn't bundle:

  * `pages.dashboard_page` (uses `from ai_model import predict_signal`)
  * `pages.detail_page`
  * `pages.ai_signals_page`
  * `pages.trade_log_page` (uses `from ai_model import get_model`)
  * `pages.ml_stats_page` (uses `from ai_model import MODEL_PATH`)
  * `pages.settings_page`
  * `pages.alerts_page`
  * `pages.debug_log_page`
  * `pages.help_page`
  * `pages.chatbot_window`
  * `ai_model` (because no top-level file imports it directly)
  * `analytics` (lazy-imported inside ml_stats_page)
  * `websocket_client` (referenced by PAGES tuple but lazy-loaded)

Without these, you get:
    Failed to execute script 'app' due to unhandled exception:
    No module named 'ai_model'

at runtime, as soon as the user logs in and the dashboard
is built.

If you want a single .exe instead of a folder, use the
sibling `nse_screener_onefile.spec` instead.

Notes
-----
  * The Angel One SmartAPI SDK (`SmartApi`, `SmartApi.smartWebSocketV2`)
    is OPTIONAL. The app's mock feed works without it. We probe
    for the SDK at build time and only add it to hiddenimports if
    it's installed — this lets the same spec work for both
    mock-only and live-feed builds.
"""

import importlib.util
import sys
from pathlib import Path

block_cipher = None

# SPECPATH is the directory containing this .spec file.
PROJECT_ROOT = Path(SPECPATH).resolve()  # noqa: F821 (provided by PyInstaller)


def _is_module_installed(module_name: str) -> bool:
    """Return True if the named module is importable in the
    current Python environment.

    Used to make optional dependencies truly optional in the
    spec — we only add `SmartApi` to hiddenimports if it's
    actually installed.
    """
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


# Probe for the live-feed SDK. If present, include it in
# hiddenimports so PyInstaller's static analysis doesn't drop
# the lazy import. If absent, the app falls back to the mock
# feed and the build still succeeds.
_optional_sdk_imports = []
if _is_module_installed("SmartApi"):
    _optional_sdk_imports.append("SmartApi")
    if _is_module_installed("SmartApi.smartWebSocketV2"):
        _optional_sdk_imports.append("SmartApi.smartWebSocketV2")


# ---------------------------------------------------------------------------
# Analysis — what to bundle
# ---------------------------------------------------------------------------
a = Analysis(
    [str(PROJECT_ROOT / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # The 'pages' package is imported by app.py via
        # `pages.theme_subscribe.themed`, but several page modules
        # are also lazy-loaded (PAGES tuple). Be explicit so
        # PyInstaller doesn't miss any.
        (str(PROJECT_ROOT / "pages"), "pages"),
        # If you ship a README / licence / icon, add them here:
        # (str(PROJECT_ROOT / "README.md"), "."),
        # (str(PROJECT_ROOT / "assets" / "app.ico"), "assets"),
    ],
    hiddenimports=[
        # ---- ML stack ----
        "sklearn",
        "sklearn.linear_model",
        "sklearn.ensemble",
        "sklearn.model_selection",
        "sklearn.metrics",
        "sklearn.preprocessing",
        "sklearn.utils",
        # ---- Data ----
        "pandas",
        "numpy",
        "joblib",
        # ---- Charts ----
        "matplotlib",
        "matplotlib.backends.backend_tkagg",
        # ---- App modules (lazy-loaded via importlib.import_module) ----
        # The dashboard, ML stats, and trade log pages import
        # `ai_model`. Without these, the .exe crashes with
        # `No module named 'ai_model'` the moment the user logs
        # in and the dashboard is built.
        "ai_model",
        "analytics",        # lazy-imported by ml_stats_page
        "websocket_client", # referenced by PAGES tuple
        # ---- Page modules (all lazy-loaded by app.py) ----
        "pages",
        "pages.dashboard_page",
        "pages.detail_page",
        "pages.ai_signals_page",
        "pages.trade_log_page",
        "pages.ml_stats_page",
        "pages.settings_page",
        "pages.alerts_page",
        "pages.debug_log_page",
        "pages.help_page",
        "pages.chatbot_window",
        "pages.theme_subscribe",
        "pages.background",
        "pages.figures",
        # ---- Optional: Angel One SDK (live feed) ----
        # Only included if `smartapi-python` is installed in the
        # build environment. If you see a "Hidden import not
        # found" warning for SmartApi in the build log, that's
        # expected if you don't have the SDK installed — the
        # mock feed still works.
        *_optional_sdk_imports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Drop heavy libs the app does not use to shrink the binary.
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "IPython", "jupyter", "notebook",
        "pytest", "sphinx",
        "PyYAML", "pytest_asyncio",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


# ---------------------------------------------------------------------------
# EXE — the actual .exe
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,           # binaries go in _internal/ (COLLECT)
    name="NSE_Screener",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                        # compress with UPX if it's on PATH
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                   # GUI app — no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(PROJECT_ROOT / "assets" / "app.ico"),  # optional
)


# ---------------------------------------------------------------------------
# COLLECT — assembles the one-folder layout
# ---------------------------------------------------------------------------
# In one-folder mode, the .exe is tiny and the heavy bits (numpy,
# pandas, sklearn, etc.) live in `_internal/`. Startup is 3-5x
# faster than one-file because the loader doesn't have to unpack
# a temp archive.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NSE_Screener",
)
