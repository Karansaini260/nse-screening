@echo off
REM ===========================================================================
REM NSE Screener — Windows build script
REM
REM Double-click this file in Windows Explorer, OR run from a Command Prompt:
REM     build.bat
REM
REM IMPORTANT: This script uses the local .venv\ Python (3.11) by default.
REM If your .venv\ doesn't exist, the script will create it and install
REM the pinned Python 3.11 dependencies.
REM
REM Options (set as environment variables before calling build.bat):
REM     set ONE_FILE=1      -> produce a single .exe (slower startup)
REM     set CONSOLE=1       -> keep the console window for debugging
REM     set SKIP_PIP=1      -> don't run pip install (use existing env)
REM     set BUILD_VERSION=x -> append x to the output folder name
REM                            (e.g. NSE_Screener_v1.0.0)
REM
REM Why no --noconsole / --console on the command line?
REM   PyInstaller does NOT allow --console / --noconsole (or
REM   --onefile / --onedir) on the command line when a .spec file
REM   is also given. These options must live INSIDE the .spec file.
REM   This script therefore edits the spec's EXE() block to set
REM   console=True/False before invoking PyInstaller.
REM ===========================================================================

setlocal enabledelayedexpansion

echo.
echo === NSE Screener build ===
echo.

REM --- Step 0: Detect / activate the local .venv -------------------------
set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PYINSTALLER=.venv\Scripts\pyinstaller.exe"

if not exist "%VENV_PY%" (
    echo.
    echo [INFO] No .venv\ found. Looking for system Python 3.11+ to create one...
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do set SYS_PY_VER=%%V
    if not defined SYS_PY_VER (
        echo [ERROR] Python is not on PATH at all.
        echo Install Python 3.11+ from https://www.python.org/downloads/
        echo and tick "Add Python to PATH" in the installer.
        exit /b 1
    )
    echo [OK] Found system Python !SYS_PY_VER!.
    echo Creating .venv\ with this Python...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv\. See the message above.
        exit /b 1
    )
    echo [OK] .venv\ created.
)

REM --- Step 1: Verify venv Python ---------------------------------------
for /f "tokens=2" %%V in ('"%VENV_PY%" --version 2^>^&1') do set VENV_VER=%%V
echo [OK] Using venv Python: !VENV_VER!

REM --- Step 2: Install PyInstaller into the venv -----------------------
if not defined SKIP_PIP (
    echo.
    echo Upgrading pip in .venv\...
    "%VENV_PY%" -m pip install --upgrade pip >nul
    if errorlevel 1 (
        echo [ERROR] pip upgrade failed.
        exit /b 1
    )

    echo Installing project dependencies from requirements.txt...
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install -r requirements.txt failed.
        exit /b 1
    )

    echo Installing PyInstaller into .venv\...
    "%VENV_PY%" -m pip install "pyinstaller>=5.13"
    if errorlevel 1 (
        echo [ERROR] pip install pyinstaller failed.
        exit /b 1
    )
    echo [OK] Dependencies ready.
)

REM --- Step 3: Sanity check pyinstaller in the venv --------------------
if not exist "%VENV_PYINSTALLER%" (
    echo.
    echo [ERROR] pyinstaller.exe not found at %VENV_PYINSTALLER%.
    echo Re-run without SKIP_PIP=1 to install it.
    exit /b 1
)
for /f "tokens=*" %%V in ('"%VENV_PYINSTALLER%" --version 2^>^&1') do set PYI_VER=%%V
echo [OK] PyInstaller: !PYI_VER!

REM --- Step 4: Clean previous build -------------------------------------
echo.
echo Cleaning previous build artefacts...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
echo [OK] Cleaned.

REM --- Step 5: Pick spec + adjust console flag inside the spec ---------
echo.

if defined ONE_FILE (
    echo Mode: ONE-FILE ^(single .exe, slower startup^)
    set SPEC_FILE=nse_screener_onefile.spec
) else (
    echo Mode: ONE-FOLDER ^(folder with .exe, faster startup^)
    set SPEC_FILE=nse_screener.spec
)

REM Decide the console flag we want in the spec's EXE() block.
REM Default: GUI app, no console window.
REM Set CONSOLE=1 to keep the console window for debugging.
if defined CONSOLE (
    set WANT_CONSOLE=True
    echo Console: ON ^(debug build - terminal window will appear^)
) else (
    set WANT_CONSOLE=False
    echo Console: OFF ^(standard GUI build^)
)

REM Patch the spec file in place: replace `console=False` or
REM `console=True` inside the EXE() block with the value we want.
REM We use a Python one-liner so we don't depend on extra tools
REM like sed / PowerShell, both of which behave differently
REM across Windows versions.
echo.
echo Patching spec file to set console=!WANT_CONSOLE!...
"%VENV_PY%" -c "import re,sys; p=sys.argv[1]; v=sys.argv[2]; s=open(p).read(); s=re.sub(r'console=(True|False)', 'console='+v, s); open(p,'w').write(s)" "%SPEC_FILE%" "!WANT_CONSOLE!"
if errorlevel 1 (
    echo [ERROR] Failed to patch the spec file.
    exit /b 1
)

REM --- Step 6: Run PyInstaller ----------------------------------------
echo.
echo Building NSE_Screener.exe (this takes 1-3 minutes)...
echo.

REM IMPORTANT: do NOT pass --noconsole / --onefile / --onedir on
REM the command line when a spec file is given. PyInstaller
REM rejects them with "option(s) not allowed".
"%VENV_PYINSTALLER%" "%SPEC_FILE%" --clean
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed. See the log above.
    exit /b 1
)

REM --- Step 7: Optional rename by version ------------------------------
if defined BUILD_VERSION (
    if exist "dist\NSE_Screener.exe" (
        ren "dist\NSE_Screener.exe" "NSE_Screener_v%BUILD_VERSION%.exe"
    )
    if exist "dist\NSE_Screener" (
        ren "dist\NSE_Screener" "NSE_Screener_v%BUILD_VERSION%"
    )
)

REM --- Step 8: Report --------------------------------------------------
echo.
echo === Build complete ===
if defined BUILD_VERSION (
    if exist "dist\NSE_Screener_v%BUILD_VERSION%.exe" (
        echo One-file build ^(versioned^):
        echo     dist\NSE_Screener_v%BUILD_VERSION%.exe
    )
    if exist "dist\NSE_Screener_v%BUILD_VERSION%\NSE_Screener.exe" (
        echo One-folder build ^(versioned^):
        echo     dist\NSE_Screener_v%BUILD_VERSION%\NSE_Screener.exe
        echo   Zip the entire dist\NSE_Screener_v%BUILD_VERSION%\ folder for distribution.
    )
) else (
    if exist "dist\NSE_Screener.exe" (
        echo One-file build:
        echo     dist\NSE_Screener.exe
    )
    if exist "dist\NSE_Screener\NSE_Screener.exe" (
        echo One-folder build:
        echo     dist\NSE_Screener\NSE_Screener.exe
        echo   Zip the entire dist\NSE_Screener\ folder for distribution.
    )
)
echo.
echo Ship the build to your clients.
endlocal
