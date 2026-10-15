@echo off
setlocal
cd /d "%~dp0"
title SKYTRACE - Radar locale
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepara_runtime.ps1"
if errorlevel 1 (
  echo.
  echo Preparazione non riuscita. Verifica la connessione Internet e riprova.
  pause
  exit /b 1
)
"%~dp0tools\python\python.exe" -c "import os,sys,runpy; sys.path.insert(0, os.getcwd()); runpy.run_path(os.path.join(os.getcwd(),'avvia_localhost.py'), run_name='__main__')"
if errorlevel 1 pause
endlocal
