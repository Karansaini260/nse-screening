# Building the NSE Screening App as a Windows `.exe`

This guide walks you through packaging the app as a standalone
Windows executable that runs on any Windows 10/11 machine
**without a separate Python install**.

---

## Prerequisites

* **Windows 10 or 11** (build environment + target)
* **Python 3.9+** — [python.org/downloads](https://www.python.org/downloads/)
  * During install, tick **"Add Python to PATH"**.
* **~2 GB free disk space** for the build
* **Optional: UPX** — [upx.sourceforge.net](https://upx.sourceforge.net/)
  for ~30% smaller `.exe`. Not required; PyInstaller will skip
  it if not present.

---

## Quick start (one command)

Open a Command Prompt in the project root and run:

```bat
build.bat
```

That script does everything in one go:

1. Verifies Python is installed.
2. Installs PyInstaller.
3. Cleans any previous build.
4. Builds the `.exe` using `nse_screener.spec` (one-folder mode).
5. Prints the final path to the artefact.

Default output: `dist\NSE_Screener\NSE_Screener.exe` plus a folder
of supporting `.dll` / `.pyd` files. Zip the entire
`dist\NSE_Screener\` folder and ship it.

For a single self-contained `.exe`:

```bat
set ONE_FILE=1
build.bat
```

For a version-stamped build:

```bat
set BUILD_VERSION=1.0.0
build.bat
```

For a debug build (keep the console window):

```bat
set CONSOLE=1
build.bat
```

All three options can be combined:

```bat
set ONE_FILE=1
set BUILD_VERSION=1.0.0
set CONSOLE=1
build.bat
```

---

## What gets built

| Spec file | Output | Mode | Startup | Distribution |
|-----------|--------|------|---------|--------------|
| `nse_screener.spec` (default) | `dist\NSE_Screener\NSE_Screener.exe` + `_internal\` | One-folder | ~2 s | Zip the folder |
| `nse_screener_onefile.spec` | `dist\NSE_Screener.exe` (single file) | One-file | ~5–10 s | Ship one file |

**Recommendation: one-folder.** The `.exe` itself is tiny (~25 MB
uncompressed bootloader); the rest is in sibling files. Startup
is 3-5× faster because the loader doesn't unpack a temp archive
on every launch.

`build.bat` defaults to the one-folder spec. Set `ONE_FILE=1` to
use the one-file spec instead.

---

## Manual build (step by step)

If you'd rather run each step yourself:

### 1. Create a clean virtual environment

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

### 2. Install runtime + build dependencies

```bat
pip install -r requirements.txt
pip install "pyinstaller>=5.13"
```

If you're shipping the live Angel One feed (not just the mock
feed), also uncomment the three SDK lines in `requirements.txt`
and re-run `pip install -r requirements.txt`.

### 3. Build

One-folder (default, faster startup):

```bat
pyinstaller nse_screener.spec --clean
```

One-file (single .exe, slower startup):

```bat
pyinstaller nse_screener_onefile.spec --clean
```

Build takes 1–3 minutes the first time, ~30 s on rebuilds.

> **Note:** PyInstaller does not allow `--onefile` / `--onedir`
> on the command line when a `.spec` file is given — the spec
> itself controls the mode. To switch modes, use the
> appropriate spec file.

### 4. Test

One-folder:

```bat
dist\NSE_Screener\NSE_Screener.exe
```

One-file:

```bat
dist\NSE_Screener.exe
```

Verify:

* The **Login** page appears.
* **Use Mock Feed** starts the mock feed without errors.
* Sidebar navigation reaches every page.
* **Stock Detail** chart renders (matplotlib bundled correctly).
* **ML Stats → Refresh Metrics** trains a model (sklearn bundled
  correctly).

### 5. Ship

For one-folder builds, zip the entire `dist\NSE_Screener\` folder.
End users un-zip and double-click `NSE_Screener.exe`.

For one-file builds, ship `NSE_Screener.exe` directly.

No Python install required on the user's machine.

---

## Distribution size

These are typical sizes on a Windows build with Python 3.11:

| Configuration | Approx. size |
|---------------|--------------|
| One-folder, uncompressed | ~480 MB |
| One-folder, with UPX | ~330 MB |
| One-file, uncompressed | ~480 MB |
| One-file, with UPX | ~340 MB |
| Mock-feed-only (no SDK) | ~150-200 MB smaller |

This is normal for an ML app — scikit-learn and pandas are
inherently large. UPX compression is the easiest ~30% saving.

---

## Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'SmartApi'` at runtime | The Angel One SDK isn't in `hiddenimports` | Uncomment the SDK lines in `nse_screener.spec` (or leave them in if your build needs the live feed) |
| `ModuleNotFoundError: No module named 'sklearn'` | ML libs not bundled | Confirm `pip install scikit-learn` ran in the same venv you're building from |
| Matplotlib chart shows blank canvas | Backend not bundled | `hiddenimports` already includes `matplotlib.backends.backend_tkagg`; rebuild with `--clean` |
| App opens then closes silently | An unhandled exception | Set `CONSOLE=1` before `build.bat` to see the error |
| `OSError: [WinError 123]` on a path with spaces | Old PyInstaller bug | Use PyInstaller ≥ 5.13 (the spec already requires this) |
| Windows Defender flags the `.exe` as malware | Unsigned binary | Sign with a code-signing certificate, or have users click "More info → Run anyway" |
| `.exe` is 400+ MB | sklearn + pandas are large | This is normal for an ML app. Use UPX to compress, and add the `excludes` list from the spec to drop Qt/IPython/etc. |
| First launch is slow (one-file mode only) | Temp-archive extraction | Switch to one-folder mode, or accept the ~5 s one-time cost |
| `ERROR: option(s) not allowed: --onedir/--onefile` | Trying to override mode on the command line | Use a different `.spec` file (one-folder vs one-file) |

---

## Advanced: install UPX for smaller builds

[UPX](https://upx.sourceforge.net/) is a free executable
compressor. PyInstaller uses it automatically if it's on
PATH.

1. Download from [upx.sourceforge.net](https://upx.sourceforge.net/).
2. Extract the ZIP.
3. Add the folder to your system PATH, or copy `upx.exe`
   next to `pyinstaller.exe`.
4. Rebuild — the output will be ~30% smaller.

Verify UPX is detected:

```bat
pyinstaller nse_screener.spec --clean --log-level INFO 2>&1 | findstr /i upx
```

You should see something like `UPX is available`.

---

## Advanced: signing the executable

To remove the "Unknown publisher" warning, sign the `.exe` with a
code-signing certificate (e.g. from DigiCert, Sectigo, or
Certum). Once you have a `.pfx` file:

```bat
signtool sign /f MyCert.pfx /p MyPassword /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\NSE_Screener\NSE_Screener.exe
```

Then verify:

```bat
signtool verify /pa dist\NSE_Screener\NSE_Screener.exe
```

The output should say `Successfully verified`.

---

## Building on macOS / Linux

The spec files are Windows-oriented (the `EXE` block produces
a Windows `.exe`). To build on macOS or Linux:

* **macOS:** create a separate `nse_screener_mac.spec` with a
  `BUNDLE` block instead of (or in addition to) the `EXE`
  block. PyInstaller will then produce a `.app` bundle.
* **Linux:** the `EXE` block produces a Linux ELF binary
  directly. Just run PyInstaller on a Linux host. Output is
  a self-contained Linux executable, not a `.exe`.

The build process is otherwise identical.

---

## Building for different Python versions

Each Python version produces a different `.exe`. For maximum
Windows compatibility (Windows 10 1809+), use Python 3.9 in a
separate venv:

```bat
python3.9 -m venv .venv-py39
.venv-py39\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
pyinstaller nse_screener.spec --clean
```

For modern Windows 11 only, Python 3.11 or 3.12 is fine.

---

## Versioning

`build.bat` supports version stamping via the `BUILD_VERSION`
environment variable:

```bat
set BUILD_VERSION=1.0.0
build.bat
```

Output:

* One-folder: `dist\NSE_Screener_v1.0.0\NSE_Screener.exe`
* One-file: `dist\NSE_Screener_v1.0.0.exe`

This makes it easy to ship multiple versions side by side
without overwriting previous builds.

---

## See also

* [INSTRUCTIONS.md](INSTRUCTIONS.md) — master entry point
* [docs/05_BUILD_EXE.md](docs/05_BUILD_EXE.md) — same content,
  this file is the canonical reference for the build process
* [docs/06_DEPLOY.md](docs/06_DEPLOY.md) — how to distribute
  the build to clients
* [docs/07_TROUBLESHOOTING.md](docs/07_TROUBLESHOOTING.md) —
  common build / runtime errors
