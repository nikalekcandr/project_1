@echo off
rem Build MindForge.exe (portable) and the MindForge\ folder (for the installer)
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% -m pip install --disable-pip-version-check -r requirements-dev.txt || goto :fail
%PY% -m PyInstaller MindForge.spec --noconfirm || goto :fail
set MINDFORGE_ONEDIR=1
%PY% -m PyInstaller MindForge.spec --noconfirm || goto :fail
echo.
echo Done: dist\MindForge.exe (portable) and dist\MindForge\ (folder)
echo To build the installer, install Inno Setup 6 and run: ISCC installer\MindForge.iss
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1
