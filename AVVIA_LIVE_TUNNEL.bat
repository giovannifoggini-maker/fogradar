@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py avvia_live_tunnel.py
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python avvia_live_tunnel.py
  ) else (
    echo Python 3 non trovato. Installa Python da https://www.python.org/downloads/
    pause
  )
)
endlocal
