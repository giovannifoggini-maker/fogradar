@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py avvia_localhost.py
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python avvia_localhost.py
  ) else (
    echo Python non trovato. Installa Python 3 da https://www.python.org/downloads/ e riprova.
    pause
  )
)
endlocal
