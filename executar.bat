@echo off
rem DriverPrecision - atalho. Sem argumentos roda o scan (somente leitura).
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -X utf8 driverprecision.py %*) || (python -X utf8 driverprecision.py %*)
if "%~1"=="" pause
