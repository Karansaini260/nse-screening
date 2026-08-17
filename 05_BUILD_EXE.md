# 05 — Build the Windows `.exe`

This document explains how to package the app as a
**standalone Windows executable** that runs on any
Windows 10/11 machine **without a separate Python install**.

> **Time:** ~15 minutes.
> **Prerequisites:** completed [01_INSTALL.md](01_INSTALL.md)
> and [02_SETUP.md](02_SETUP.md).

---

## What you're building

The output is a Windows `.exe` that bundles:

* A compiled bootloader (the small launcher)
* The Python runtime (the part of CPython needed to run
  the app)
* Every dependency (numpy, pandas, scikit-learn, matplotlib,
  joblib, optionally smartapi-python)
* Your source code

The user just unzips and double-clicks. No Python install
required on their machine.

---

## 1. Install PyInstaller

In your project folder, with the virtual environment active:

```bash
pip install "pyinstaller>=5.13"
```

Verify:

```bash
pyinstaller --version
```

Expected: `5.13.0` or higher.

---

## 2. Choose your output mode

The project ships with **two spec files** — one for each mode:

| Mode | Spec file | Output | Startup | Distribution |
|------|-----------|--------|---------|--------------|
| **One-folder** *(default)* | `nse_screener.spec` | `dist\NSE_Screener\` folder with `.exe` + supporting files | ~2 s | Zip the folder (~480 MB) |
| **One-file** | `nse_screener_onefile.spec` | Single `dist\NSE_Screener.exe` | ~5–10 s | Ship one file (~480 MB) |

**Recommendation:** one-folder. The `.exe` itself is tiny
(~25 MB bootloader); the rest is in sibling files. Startup
is 3-5× faster because the loader doesn't unpack a temp
archive on every launch.

---

## 3. Build (one command)

The project ships with a `build.bat` script that does
everything for you:

```bat
build.bat
```

For a single-file `.exe` instead of a folder:

```bat
set ONE_FILE=1
build.bat
```

For a version-stamped build (renames the output folder):

```bat
set BUILD_VERSION=1.0.0
build.bat
```

For debug builds (keep the console window so you can see
errors):

```bat
set CONSOLE=1
build.bat
```

To skip the `pip install` step (faster rebuilds):

```bat
set SKIP_PIP=1
build.bat
```

All four options can be combined.

Build time: 1-3 minutes the first time, ~30 s on rebuilds.

---

## 4. Manual build (step by step)

If you'd rather run each step yourself:

```bash
# Clean previous build
rm -rf build dist

# Run PyInstaller with the appropriate spec
# One-folder (default, faster startup):
pyinstaller nse_screener.spec --clean

# OR one-file (single .exe, slower startup):
pyinstaller nse_screener_onefile.spec --clean
```

> **Note:** PyInstaller does not allow `--onefile` / `--onedir`
> on the command line when a `.spec` file is given — the spec
> itself controls the mode. To switch modes, use a different
> spec file.

Each spec file is tuned for:

* Windowed (no terminal window flashes for users)
* Hidden imports for sklearn, pandas, matplotlib, SmartApi
* Excludes for PyQt, IPython, jupyter, pytest, sphinx
* UPX compression if UPX is on PATH

---

## 5. Test the build

One-folder:

```bat
dist\NSE_Screener\NSE_Screener.exe
```

One-file:

```bat
dist\NSE_Screener.exe
```

Verify:

* The **Login** page appears (no error dialog)
* **Use Mock Feed** starts the mock feed
* Sidebar navigation reaches every page
* **Stock Detail** chart renders (matplotlib bundled correctly)
* **ML Stats → Refresh Metrics** trains a model (sklearn
  bundled correctly)
* **Alerts** page is empty (no startup errors)

If anything fails, rebuild with `CONSOLE=1` to see the
error message.

---

## 6. Distribution size

| Configuration | Approx. size (Windows) |
|---------------|------------------------|
| One-folder, uncompressed | ~480 MB |
| One-folder, with UPX | ~330 MB |
| One-file, uncompressed | ~480 MB |
| One-file, with UPX | ~340 MB |
| Mock-feed-only (no SDK) | ~150-200 MB smaller |

This is normal for an ML app — scikit-learn and pandas are
inherently large. UPX compression is the easiest ~30% saving.

---

## 7. Optional: install UPX for smaller builds

[UPX](https://upx.sourceforge.net/) is a free executable
compressor. PyInstaller uses it automatically if it's on
PATH.

1. Download from [upx.sourceforge.net](https://upx.sourceforge.net/).
2. Extract the ZIP.
3. Add the folder to your system PATH, or copy `upx.exe`
   next to `pyinstaller.exe`.
4. Rebuild — the output will be ~30% smaller.

Verify UPX is detected:

```bash
pyinstaller nse_screener.spec --clean --log-level INFO 2>&1 | grep -i upx
```

You should see something like `UPX is available`.

---

## 8. Optional: code-sign the .exe

By default, Windows shows **"Unknown publisher"** when the
user runs the .exe, and some antivirus products flag
unsigned binaries. A code-signing certificate fixes both.

### Get a certificate

Code-signing certificates cost ~$70-300/year. Common vendors:

* [Certum](https://shop.certum.eu/) — cheapest, ~$30/year
* [Sectigo](https://www.sectigo.com/) — mid-range
* [DigiCert](https://www.digicert.com/) — premium

### Sign the .exe

Once you have a `.pfx` file:

```bat
signtool sign /f MyCert.pfx /p MyPassword /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\NSE_Screener\NSE_Screener.exe
```

Then verify:

```bat
signtool verify /pa dist\NSE_Screener\NSE_Screener.exe
```

The output should say `Successfully verified`.

---

## 9. Build for different Python versions

Each Python version produces a different `.exe`. If your
clients have a mix of Windows 10 (older) and Windows 11
(newer), use Python 3.9 for maximum compatibility:

```bash
# In a separate venv with Python 3.9
python3.9 -m venv .venv-py39
source .venv-py39/bin/activate
pip install -r requirements.txt
pip install pyinstaller
pyinstaller nse_screener.spec --clean
```

The resulting `.exe` runs on Windows 10 1809+.

---

## 10. Common build issues

### `ModuleNotFoundError: No module named 'SmartApi'` at runtime

The live-feed SDK isn't in `hiddenimports`. Open
`nse_screener.spec` and uncomment the two `SmartApi*` lines
under `hiddenimports`. Rebuild.

### Matplotlib chart shows blank canvas

Already handled in the spec — `matplotlib.backends.backend_tkagg`
is in `hiddenimports`. If you still see it, run
`pip install --upgrade matplotlib` and rebuild with `--clean`.

### App opens then closes silently

Rebuild with `CONSOLE=1` to see the error. The most common
cause is a missing `data` file (e.g. a model bundle that
should be in the same folder as the `.exe`).

### `ERROR: option(s) not allowed: --onedir/--onefile`

You're trying to override the build mode on the command
line, but PyInstaller doesn't allow that when using a spec
file. Use a different spec instead:

```bash
# One-folder
pyinstaller nse_screener.spec --clean

# One-file
pyinstaller nse_screener_onefile.spec --clean
```

### `RecursionError` during build

A dependency has a circular import that PyInstaller can't
resolve. Add the offending module to `excludes` (yes, this
sometimes works) or `hiddenimports`.

### `OSError: [WinError 123]` on a path with spaces

You're hitting an old PyInstaller bug. Update to ≥ 5.13
(the spec already requires this).

### `.exe` is 500+ MB

You've accidentally bundled Qt, IPython, or another heavy
library. Check the `excludes` list in the spec. Run
`pyinstaller nse_screener.spec --clean --log-level INFO`
and look for the largest modules in the output.

### Windows Defender flags the .exe

Either sign the .exe (see step 8) or document the warning
in your distribution. For personal use, the user can click
"More info → Run anyway".

---

## Next step

For shipping the build to clients, continue to
**[06_DEPLOY.md](06_DEPLOY.md)**.
