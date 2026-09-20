@echo off
rem ETL financial-data-pipeline - regenera Consolidado.csv + dCalendario.csv
rem Usa EXTRATOS_DIR/OUTPUT_DIR do .env (ou padroes do OneDrive em src\config.py)
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 main.py) else (python main.py)
pause
