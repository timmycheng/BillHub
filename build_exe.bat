@echo off
REM ============================================
REM WZBill - Windows Build Script
REM Run on a Windows PC WITH internet access
REM Produces: dist\WZBill.exe
REM ============================================
echo.
echo ==========================================
echo   Building WZBill (one-file exe)
echo ==========================================
echo.

REM 1. Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.9+ and check "Add to PATH"
    pause
    exit /b 1
)

REM 2. Install dependencies (requires internet ONCE)
echo [1/3] Installing dependencies...
python -m pip install PyQt6 openpyxl rapidocr-onnxruntime pymupdf Pillow pyinstaller -q
if %errorlevel% neq 0 (
    echo [ERROR] Dependency install failed. Check network.
    pause
    exit /b 1
)

REM 3. Copy OCR models to local models\ folder
echo [2/3] Preparing OCR models...
python -c "import rapidocr_onnxruntime, os, shutil; src=os.path.join(os.path.dirname(rapidocr_onnxruntime.__file__),'models'); dst=os.path.join(os.getcwd(),'models'); os.makedirs(dst,exist_ok=True); [shutil.copy2(os.path.join(src,f),os.path.join(dst,f)) for f in os.listdir(src) if f.endswith('.onnx')]; print('[OK] Models copied')"
if %errorlevel% neq 0 (
    echo [ERROR] Model copy failed.
    pause
    exit /b 1
)

REM 4. PyInstaller build (windowed mode: no console)
echo [3/3] Building exe (2-4 minutes)...
pyinstaller --noconfirm --onefile --windowed --name WZBill ^
  --add-data "templates;templates" ^
  --add-data "models;models" ^
  --hidden-import PyQt6.QtCore ^
  --hidden-import PyQt6.QtGui ^
  --hidden-import PyQt6.QtWidgets ^
  --hidden-import pymupdf ^
  --hidden-import openpyxl ^
  --hidden-import rapidocr_onnxruntime ^
  --hidden-import onnxruntime ^
  main.py

if %errorlevel% neq 0 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   BUILD COMPLETE!
echo   File: dist\WZBill.exe
echo.
echo   Usage:
echo   1. Copy WZBill.exe to the offline PC
echo   2. Double-click to run
echo   3. Data saved to bill.db next to exe
echo   4. Reports auto-saved to "bill-shenpi" folder
echo ==========================================
pause
