# 06 — Deploy to Clients

This document covers shipping the built `.exe` to end
users — packaging, distribution, and updates.

> **Time:** ~5 minutes.
> **Prerequisites:** completed [05_BUILD_EXE.md](05_BUILD_EXE.md).

---

## 1. What to ship

After `build.bat` finishes, your build is in
`dist\NSE_Screener\`. That folder is your deliverable.

```
dist\NSE_Screener\
├── NSE_Screener.exe          ← the launcher
├── python311.dll             ← Python runtime
├── _internal\                ← bundled dependencies
│   ├── app.pyc
│   ├── numpy\
│   ├── pandas\
│   ├── ...
│   └── ...
└── (other .dll / .pyd files)
```

The user needs the **entire** folder, not just the `.exe`.

---

## 2. Create a ZIP

### Windows (built-in)

1. Right-click the `NSE_Screener` folder.
2. **Send to → Compressed (zipped) folder**.
3. Rename the ZIP to something meaningful, e.g.
   `NSE_Screener_v1.0.0_windows.zip`.

### Windows (with 7-Zip, smaller output)

```bat
7z a -tzip -mx=9 NSE_Screener_v1.0.0_windows.zip dist\NSE_Screener\*
```

`7z` typically produces a ZIP that's 10-20% smaller than
the built-in Windows ZIP.

### Windows (PowerShell)

```powershell
Compress-Archive -Path "dist\NSE_Screener" -DestinationPath "NSE_Screener_v1.0.0_windows.zip" -CompressionLevel Optimal
```

---

## 3. Create a self-extracting installer (optional)

A self-extracting `.exe` is more user-friendly than a ZIP
because the user double-clicks one file and the app installs
itself.

### Option A — IExpress (built into Windows)

1. Press `Win+R`, type `iexpress`, press Enter.
2. Choose **"Create new Self-Extracting Directive file"**.
3. Follow the wizard:
   * Package purpose: "Extract files and run an installation
     command"
   * Package title: `NSE Screener Setup`
   * Confirmation prompt: `Install NSE Screener v1.0.0?`
   * License: optionally include a LICENSE.txt
   * Packaged files: add the contents of `dist\NSE_Screener\`
   * Install program: `NSE_Screener.exe`
   * Show window: "Hidden"
   * Finish.

Output: a single `.exe` that the user double-clicks. The
extracted files end up in `%TEMP%` and the app runs
immediately. Not ideal for "real" install-on-disk behavior,
but perfect for a quick "send to a client" deploy.

### Option B — Inno Setup (recommended for production)

[Inno Setup](https://jrsoftware.org/isinfo.php) is a free,
scriptable installer generator. It produces a proper
installer that:

* Lets the user pick the install location
* Creates a Start Menu shortcut
* Creates a Desktop shortcut
* Adds an Uninstall entry in Control Panel
* Optionally checks for updates on launch

Example `installer.iss` script:

```iss
[Setup]
AppName=NSE Screener
AppVersion=1.0.0
AppPublisher=Your Company Name
DefaultDirName={autopf}\NSE Screener
DefaultGroupName=NSE Screener
OutputBaseFilename=NSE_Screener_v1.0.0_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\NSE_Screener\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\NSE Screener"; Filename: "{app}\NSE_Screener.exe"
Name: "{commondesktop}\NSE Screener"; Filename: "{app}\NSE_Screener.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional shortcuts"
```

Compile it:

```bat
iscc installer.iss
```

Output: `Output\NSE_Screener_v1.0.0_Setup.exe` — a single
file the user runs to install.

---

## 4. Distribute

### Small user base (< 50)

* Email the ZIP / installer as an attachment
* Or upload to Google Drive / Dropbox and share the link
* Or put it on a private S3 / Azure Blob bucket

### Larger user base

* GitHub Releases — free, automatic update notifications
* itch.io — free hosting for indie tools
* Your own web server with HTTPS

### Enterprise distribution

* Microsoft Intune / SCCM — push to managed devices
* Chocolatey — `choco install nse-screener`
* MSIX packaging — for Microsoft Store distribution

---

## 5. Update workflow

When you release a new version:

1. Bump the version in `nse_screener.spec`:
   ```python
   exe = EXE(
       ...
       name="NSE_Screener",
       ...
   )
   ```
   Or pass `--name "NSE_Screener_v1.0.1"` at build time.

2. Rebuild:
   ```bat
   build.bat
   ```

3. Tag the release in Git:
   ```bash
   git tag v1.0.1
   git push --tags
   ```

4. Upload the new ZIP / installer alongside the old one.

5. (Optional) Add a built-in updater — the simplest approach
   is to ship a small `version.txt` with the build number
   and have the app check it on startup against the running
   version. See the **"Built-in updater"** snippet below.

### Built-in updater snippet

Create `updater.py`:

```python
"""Check for updates against a remote version.txt file."""

import urllib.request
import logging

log = logging.getLogger(__name__)


CURRENT_VERSION = "1.0.0"
VERSION_URL = "https://your-server.com/nse-screener/version.txt"


def check_for_update() -> str | None:
    """Return the latest version string if newer, else None."""
    try:
        with urllib.request.urlopen(VERSION_URL, timeout=5) as r:
            latest = r.read().decode("utf-8").strip()
    except Exception as exc:
        log.debug("Update check failed: %s", exc)
        return None
    if latest > CURRENT_VERSION:
        return latest
    return None
```

Call it from `app.py` on startup (don't block the UI):

```python
import threading
import updater

def _check_updates():
    latest = updater.check_for_update()
    if latest:
        # Show a non-blocking banner: "Update available: v1.0.1"
        ...

threading.Thread(target=_check_updates, daemon=True).start()
```

---

## 6. License and credits

Before distributing, add a `LICENSE.txt` next to the `.exe`.
Most app directories should include:

* A copy of the license (MIT, Apache 2.0, proprietary, etc.)
* A `THIRD_PARTY.txt` listing every open-source dependency
  and its license (PyInstaller can do this with
  `--log-level INFO`)

Generate third-party credits:

```bash
pip install pip-licenses
pip-licenses --format=markdown --output-file=THIRD_PARTY_LICENSES.md
```

---

## 7. Pre-flight checklist

Before shipping any build, verify:

* [ ] **Smoke test:** `.exe` opens and reaches the Login page
* [ ] **Mock feed:** "Use Mock Feed" starts the feed
* [ ] **Navigation:** every sidebar page loads without error
* [ ] **ML training:** "Refresh Metrics" trains a model
* [ ] **Live feed:** (if shipping) "Connect to Angel One"
      succeeds with valid creds
* [ ] **Antivirus scan:** scan the build with Windows
      Defender; sign if it flags the file
* [ ] **File size:** the ZIP is reasonable (under 200 MB
      compressed, 500 MB uncompressed)
* [ ] **Version stamped:** the `.exe` name and `version.txt`
      (if used) match
* [ ] **README in the ZIP:** include a one-page `README.txt`
      that says: "Double-click NSE_Screener.exe to start. The
      first time, click 'Use Mock Feed' to try the UI. For
      live data, fill in Angel One credentials."

---

## Next step

For issues, continue to
**[07_TROUBLESHOOTING.md](07_TROUBLESHOOTING.md)**.
