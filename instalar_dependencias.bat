@echo off
:: Cambia al directorio del script para hacerlo portable
cd /d "%~dp0"

echo Activando venv...
if exist ".venv\Scripts\activate.bat" (
	call .venv\Scripts\activate.bat
) else (
	echo No se encontró el entorno virtual en .venv. Crealo con: python -m venv .venv
	exit /b 1
)

echo Instalando dependencias...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo Dependencias instaladas correctamente!
pause
