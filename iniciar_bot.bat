@echo off
:: Usar el directorio del script para mayor portabilidad
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
	.venv\Scripts\python.exe bot_yt.py
) else (
	echo No se encontró .venv\Scripts\python.exe. Activa el entorno virtual o crea uno con: python -m venv .venv
	exit /b 1
)

pause