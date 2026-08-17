# 07 — Troubleshooting

A reference for common problems and how to fix them.

---

## Setup & Installation

### `python: command not found` (macOS / Linux)

macOS doesn't ship Python 3 by default (only Python 2). Install:

```bash
brew install python@3.11
```

Or use the official installer from
[python.org](https://www.python.org/downloads/macos/).

### `python is not recognized as an internal or external command` (Windows)

Python wasn't added to PATH. Re-run the installer and tick
**"Add Python to PATH"** on the first screen.

Alternatively, use the Python launcher:

```bat
py -3 app.py
```

### `pip install` fails with "Permission denied"

You're trying to install into the system Python. Activate the
virtual environment first:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### `pip install` fails with "Microsoft Visual C++ 14.0 or greater is required"

Some packages (mostly older ones) need a C compiler to build
from source on Windows. Install **Build Tools for Visual
Studio**:

* [visualstudio.microsoft.com/downloads](https://visualstudio.microsoft.com/downloads/)
  → "Build Tools for Visual Studio" → "Desktop development
  with C++"

If you hit this with the NSE Screening app, the most likely
culprit is `pandas` or `numpy`. Pre-built wheels exist for
both on PyPI, so `pip install pandas` should "just work" on
modern Windows. If it doesn't:

```bash
python -m pip install --upgrade pip setuptools wheel
pip install pandas
```

### Tkinter not found (Linux)

```bash
sudo apt install python3-tk
```

Verify:

```bash
python3 -c "import tkinter; tkinter.Tk(); print('OK')"
```

---

## Running the app

### App opens then closes silently

An unhandled exception. Run from the terminal to see it:

```bash
python app.py
```

Read the traceback — it tells you exactly which line failed.

### `ModuleNotFoundError: No module named 'pandas'` (or any other module)

You didn't install the requirements in this environment, or
the wrong environment is active.

```bash
# Confirm the venv is active (prompt should start with .venv)
which python    # macOS / Linux
where python    # Windows

# Should point to .venv, not /usr/bin/python or C:\Python311\
```

If wrong:

```bash
source .venv/bin/activate     # macOS / Linux
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### Dashboard shows "—" for every symbol

The feed hasn't populated yet. With the mock feed, this
resolves in ~0.5 seconds. With the live feed, it resolves in
~1 second after the first tick.

If it persists for 30+ seconds, check the **Debug Log** page —
look for `Mock pre-population complete` (mock) or `Subscribed
batch 0` (live).

### Charts don't render

* **TkAgg backend missing:** install matplotlib
  (`pip install matplotlib`)
* **Missing fonts:** matplotlib ships with its own fonts; on
  rare Linux setups you may need `sudo apt install
  fonts-dejavu`
* **Black canvas on dark mode:** toggle dark mode off in
  Settings, or restart the app

### App freezes on the Trade Log page

You have a very large `trade_log.csv` (>10,000 rows). The page
loads it on first visit; subsequent loads use a cache. Wait
~5 seconds for the first load, then it'll be fast.

### ML Stats page shows "Need at least 20 closed trades"

You haven't collected enough data yet. The model needs
20+ trades with **both winners AND losers** to train. Run
the dashboard for a few days and let trades accumulate, or
manually create some by going to Settings → Restart Mock
Feed and waiting for crossovers.

---

## Live feed

For live-feed specific issues, see
**[04_LIVE_FEED.md](04_LIVE_FEED.md)**. The most common
issues:

| Error | Fix |
|-------|-----|
| `No module named 'SmartConnect'` | `pip install smartapi-python` |
| `Login failed: Invalid Token` | Re-copy TOTP secret; no leading spaces |
| `TOTP secret is not valid base32` | Re-copy from authenticator app |
| `Could not download scrip master` | Check internet / corporate firewall |
| `SmartWebSocketV2 class not found` | `pip install --upgrade smartapi-python` |
| No ticks arriving | Check market hours (09:15-15:30 IST, Mon-Fri) |

---

## Building the .exe

### `RecursionError` during build

A dependency has a circular import. Common offenders:

* `tensorflow` (don't install this — the app doesn't use it)
* `pydantic` with version conflicts

The fix is usually to add the offending package to `excludes`
in `nse_screener.spec` (yes, this sometimes works) or
`hiddenimports`.

### App opens then closes (built .exe)

Rebuild with the console enabled to see the error:

```bat
set CONSOLE=1
build.bat
```

The most common cause is a missing `data` file or
`ModuleNotFoundError` for a hidden import.

### Windows Defender flags the .exe as malware

* **For personal / small-team use:** sign the .exe (see
  [05_BUILD_EXE.md](05_BUILD_EXE.md) step 8)
* **For one-off distribution:** tell the user to click
  "More info → Run anyway"
* **For enterprise:** submit the .exe to Microsoft's
  [Microsoft Defender Security Intelligence portal](https://www.microsoft.com/en-us/wdsi/filesubmission)
  for whitelisting

### `pyinstaller` command not found after install

* Make sure the virtual environment is active.
* On some systems, `pyinstaller` isn't on PATH immediately
  after `pip install`. Try:

  ```bash
  python -m PyInstaller nse_screener.spec --clean
  ```

### UPX warnings during build

`UPX is not available` is a warning, not an error. The build
still succeeds — the .exe just isn't compressed. Install UPX
for a smaller output (see [05_BUILD_EXE.md](05_BUILD_EXE.md)
step 7).

---

## Common error messages

### `OSError: [Errno 28] No space left on device`

The build needs ~2 GB free. Free up space or build to a
different drive.

### `Permission denied` during build

Another process has the output folder open. Close any
`dist\NSE_Screener\` windows in Explorer, or any running
instance of the .exe.

### `RecursionError: maximum recursion depth exceeded`

A deep import chain. Set the recursion limit before running
PyInstaller:

```bash
PYTHONUNBUFFERED=1 python -c "import sys; sys.setrecursionlimit(5000); import PyInstaller.__main__; PyInstaller.__main__.run(['nse_screener.spec', '--clean'])"
```

### `UnicodeDecodeError` during build

A file in your project has non-UTF-8 bytes. PyInstaller
expects UTF-8 everywhere. Common culprits:

* CSV files with weird encoding (re-save as UTF-8)
* PNG/JPG with non-ASCII metadata
* Comments in `.py` files using exotic characters

Find the offender:

```bash
pyinstaller nse_screener.spec --clean --log-level DEBUG 2>&1 | grep -i "unicode\|encoding"
```

---

## Performance

### App is slow to start (one-file .exe only)

This is by design — PyInstaller extracts the bundle to `%TEMP%`
on every launch. Use **one-folder** mode for faster startup.

### App uses a lot of RAM (> 500 MB)

The ML model + the chart history are the biggest consumers.
The app should plateau at 300-500 MB after a few minutes.
If it grows unbounded, you may have a leak — restart the
app.

### Dashboard refresh stutters

Lower the refresh rate: **Settings → Refresh interval → 2000 ms**.

### ML Stats "Refresh Metrics" takes 30+ seconds

You have a large `trade_log.csv` (>1,000 rows). The default
hyperparameters are tuned for 100-500 rows. For larger
datasets, the cross-validation dominates the time. Run
`python train_model.py` separately to train the model, then
just use "Refresh Metrics" to re-compute the analytics.

---

## Getting more help

1. **Run the diagnostic:** `python check_requirements.py`
2. **Check the Debug Log page** for live-feed issues
3. **Check the Alerts page** for in-app errors
4. **Search the issue tracker** for the exact error message
5. **Open a new issue** with:
   * The full error message (traceback preferred)
   * Your OS and Python version
   * The output of `python check_requirements.py`
   * Steps to reproduce
