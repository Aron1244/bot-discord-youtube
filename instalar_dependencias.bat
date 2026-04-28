@echo off
cd /d C:\Desarrollo\bot-discord-youtube

echo Activando venv...
call .venv\Scripts\activate.bat

echo Instalando dependencias...
pip install -r requirements.txt

echo.
echo Dependencias instaladas correctamente!
pause
