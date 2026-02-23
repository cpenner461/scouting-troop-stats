@echo off
REM Build the bundled Python sync binary for Windows (x64).
REM
REM Requirements (all managed by uv — no system Python needed):
REM   uv  https://docs.astral.sh/uv/getting-started/installation/
REM
REM Run from the repo root or any subdirectory:
REM   native-app\build-scripts\build-python-win.bat
REM
REM Output: native-app\python-bin\sync.exe
REM         (electron-builder picks this up via extraResources in package.json)

setlocal EnableDelayedExpansion

SET "SCRIPT_DIR=%~dp0"
SET "NATIVE_APP_DIR=%SCRIPT_DIR%.."
SET "PROJECT_ROOT=%NATIVE_APP_DIR%\.."

echo =^> Installing PyInstaller into project venv...
cd /d "%PROJECT_ROOT%"
uv pip install pyinstaller
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to install PyInstaller
    exit /b 1
)

echo.
echo =^> Building sync binary...
cd /d "%NATIVE_APP_DIR%"

uv run pyinstaller sync-runner.spec ^
    --distpath python-bin ^
    --workpath build\pyinstaller ^
    --clean ^
    --noconfirm
if %ERRORLEVEL% neq 0 (
    echo ERROR: PyInstaller build failed
    exit /b 1
)

echo.
echo =^> Build complete!
echo     Binary: %NATIVE_APP_DIR%\python-bin\sync.exe
echo.
echo     Next step:  cd native-app ^&^& npm run build:win

endlocal
