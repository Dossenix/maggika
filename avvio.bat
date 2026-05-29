@echo off
title Maggika Bot
cd /d "%~dp0"

echo Avvio Maggika Bot...
echo.

if exist ".venv\Scripts\activate.bat" (
    echo Venv trovata, la attivo...
    call ".venv\Scripts\activate.bat"
) else (
    echo Nessuna venv trovata, uso Python installato nel PC.
)

echo.
py -3 main.py

echo.
echo Il bot si e chiuso o ha dato errore.
pause
