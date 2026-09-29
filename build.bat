@echo off
setlocal

rem Run from the project root (same folder as main.py).
rem Place requirements.txt and EasyMark.spec in this same folder first.

echo === 1/4: Installing dependencies ===
pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency install failed. Stopping.
    exit /b 1
)

echo === 2/4: Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo === 3/4: Building exe with PyInstaller ===
pyinstaller EasyMark.spec
if errorlevel 1 (
    echo Build failed. Stopping.
    exit /b 1
)

echo === 4/4: Copying data folders next to the exe ===
xcopy /E /I /Y img dist\EasyMark\img
xcopy /E /I /Y workfolder dist\EasyMark\workfolder

echo.
echo Done. Result is in dist\EasyMark\
echo Run dist\EasyMark\EasyMark.exe
endlocal