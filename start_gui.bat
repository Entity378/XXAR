@echo off
REM XXAR - Cross-game Audio Replacer - GUI Launcher (Windows)

echo ================================
echo XXAR - GUI Launcher
echo ================================
echo.

REM Check Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo X Python not found. Please install Python 3 from python.org
    pause
    exit /b 1
)
echo + Python found

REM Check PyQt6
python -c "import PyQt6" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo X PyQt6 not found
    echo.
    echo Installing PyQt6...
    python -m pip install PyQt6
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo Failed to install PyQt6
        echo Please run: pip install PyQt6
        pause
        exit /b 1
    )
)
echo + PyQt6 found

REM Check PyQt6.QtQml
python -c "from PyQt6.QtQml import QQmlApplicationEngine" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ! PyQt6.QtQml not found
    echo.
    echo The QML UI requires PyQt6 with QML support.
    echo Installing full PyQt6 package...
    python -m pip install --upgrade PyQt6
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo Failed to install PyQt6
        pause
        exit /b 1
    )
)
echo + PyQt6.QtQml found

echo.
echo Starting XXAR GUI...
echo.

REM Run the GUI (pushd handles UNC paths properly)
pushd "%~dp0"
python XXAR.py
set EXIT_CODE=%ERRORLEVEL%
popd

echo.
if %EXIT_CODE% NEQ 0 (
    echo.
    echo ========================================
    echo ERROR: Application exited with code %EXIT_CODE%
    echo ========================================
    echo.
    echo Press any key to close...
    pause >nul
    exit /b %EXIT_CODE%
)

echo GUI closed.
pause
