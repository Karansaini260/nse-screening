# 02 — Project Setup

This document walks you through getting the source code and
installing all the dependencies.

> **Time:** ~5 minutes.
> **Prerequisites:** completed [01_INSTALL.md](01_INSTALL.md).

---

## 1. Get the source code

### Option A — clone with Git (recommended)

```bash
git clone <repo-url> nse-screening
cd nse-screening
```

Replace `<repo-url>` with the actual Git URL provided by your
team. If you don't have one yet, ask your project lead.

### Option B — download a ZIP

1. Go to the repository's GitHub/GitLab page.
2. Click **Code → Download ZIP**.
3. Extract the ZIP to a folder, e.g. `C:\Users\you\nse-screening\`
   or `~/nse-screening/`.
4. Open a terminal in that folder.

```bash
cd nse-screening
ls                # you should see app.py, README.md, etc.
```

---

## 2. Create a virtual environment

Inside the project folder:

### Windows (Command Prompt)

```bat
python -m venv .venv
.venv\Scripts\activate
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script with a permission error, run
once as admin:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

After activation, your prompt should be prefixed with `(.venv)`.

---

## 3. Upgrade pip

```bash
python -m pip install --upgrade pip
```

This ensures pip is recent enough to handle the modern package
format.

---

## 4. Install runtime dependencies

```bash
pip install -r requirements.txt
```

This installs:

| Package | Why |
|---------|-----|
| `numpy` | Array math (the app uses it for the ML training) |
| `pandas` | CSV reading + DataFrame for the ML pipeline |
| `scikit-learn` | Logistic Regression + Random Forest model |
| `joblib` | Save / load the trained model |
| `matplotlib` | Charts on Stock Detail + ML Stats pages |

Expected time: 30-90 seconds.

---

## 5. (Optional) Install live-feed dependencies

Only required if you plan to use the **Connect to Angel One**
button. Skip this if you'll only use the mock feed.

```bash
pip install smartapi-python websocket-client
```

Expected time: 10-20 seconds.

---

## 6. Verify the installation

Run the diagnostic tool — it checks every dependency:

```bash
python check_requirements.py
```

You should see a list of green checkmarks. If anything is red,
see [07_TROUBLESHOOTING.md](07_TROUBLESHOOTING.md).

---

## 7. (Optional) Install the build tool

Only needed if you plan to package the app as a Windows `.exe`
(covered in [05_BUILD_EXE.md](05_BUILD_EXE.md)).

```bash
pip install "pyinstaller>=5.13"
```

---

## File layout after setup

```
nse-screening/
├── .venv/                  ← your virtual environment
├── app.py                  ← entry point
├── requirements.txt        ← dependency list
├── check_requirements.py   ← dependency checker
├── build.bat               ← Windows build script
├── nse_screener.spec       ← PyInstaller spec
├── BUILD.md                ← build guide
├── INSTRUCTIONS.md         ← you are here
├── docs/                   ← detailed guides
├── ai_model.py             ← ML model code
├── analytics.py            ← training + metrics
├── cards.py                ← UI widgets
├── chatbot.py              ← chat assistant
├── ...                     ← other modules
└── pages/
    ├── dashboard_page.py
    ├── detail_page.py
    └── ...
```

---

## Next step

Continue to **[03_RUN.md](03_RUN.md)** to start the app.
