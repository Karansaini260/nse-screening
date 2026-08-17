@echo off
REM ===========================================================================
REM open_venv.bat — Open a Command Prompt with the project's venv activated.
REM
REM Double-click this file to get a Command Prompt where:
REM   * python     -> .venv\ Python (3.11)
REM   * pip        -> .venv\ pip
REM   * pyinstaller-> .venv\ pyinstaller
REM
REM Useful for running `python app.py` to test the app, or running
REM `build.bat` to make the .exe.
REM ===========================================================================

setlocal

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] .venv\ not found in %CD%.
    echo Run `python -m venv .venv` first, OR double-click build.bat
    echo which will create .venv\ for you.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo.
echo === venv activated ===
echo.
echo You can now run:
echo     python app.py          (test the app)
echo     pyinstaller --version  (verify PyInstaller)
echo     build.bat              (build the .exe)
echo.
echo Type `deactivate` to leave the venv.
echo.

cmd /k
