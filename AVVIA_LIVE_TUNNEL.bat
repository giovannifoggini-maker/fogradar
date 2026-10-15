@echo off
setlocal
cd /d "%~dp0"
title SKYTRACE - Radar live online
echo.
echo SKYTRACE prepara Python e Cloudflare Tunnel dentro questa cartella.
echo Nessuna installazione viene eseguita in Windows; serve Internet al primo avvio.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepara_runtime.ps1" -IncludeTunnel
if errorlevel 1 (
  echo.
  echo Preparazione non riuscita. Verifica la connessione Internet e riprova.
  pause
  exit /b 1
)
"%~dp0tools\python\python.exe" -c "import os,sys,runpy; sys.path.insert(0, os.getcwd()); runpy.run_path(os.path.join(os.getcwd(),'avvia_live_tunnel.py'), run_name='__main__')"
if errorlevel 1 pause
endlocal
