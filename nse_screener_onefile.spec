# -*- mode: python ; coding: utf-8 -*-
"""
One-file variant of the PyInstaller spec.

Build with:
    pyinstaller nse_screener_onefile.spec --clean

Output:
    dist/NSE_Screener.exe                  (single self-contained file)

Differences from the one-folder spec (nse_screener.spec):

  * No COLLECT block — everything is packed into a single .exe
  * The bootloader unpacks the bundle to %TEMP% on every launch
  * Startup is ~5-10 s slower than one-folder mode
  * Distribution is one file instead of a folder

Choose this mode if:

  * You want to ship a single .exe to clients
  * You don't mind the ~5-10 s startup cost
  * The folder layout would be confusing for non-technical users

Choose one-folder mode (nse_screener.spec) if:

  * You want the fastest possible startup
  * You're deploying internally where folder structure doesn't matter

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

Notes
-----
  * The Angel One SmartAPI SDK is OPTIONAL. The mock feed works
    without it. The spec probes for the SDK at build time and
    only adds it to hiddenimports if it's installed.
"""

import importlib.util
import sys
from pathlib import Path

block_cipher = None

# SPECPATH is the directory containing this .spec file.
PROJECT_ROOT = Path(SPECPATH).resolve()  # noqa: F821 (provided by PyInstaller)


def _is_module_installed(module_name: str) -> bool:
    """Return True if the named module is importable."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


# Probe for the live-feed SDK.
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
        (str(PROJECT_ROOT / "pages"), "pages"),
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
        "ai_model",
        "analytics",
        "websocket_client",
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
        # ---- Optional: Angel One SDK ----
        *_optional_sdk_imports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
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
# EXE — single self-contained file
# ---------------------------------------------------------------------------
# In one-file mode there's no COLLECT block. The bootloader
# unpacks the bundle to %TEMP% on first launch, then runs it
# from there.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="NSE_Screener",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(PROJECT_ROOT / "assets" / "app.ico"),  # optional
)
