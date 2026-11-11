@echo off
rem DriverPrecision - sem argumentos abre a janela; com argumentos usa a linha de comando.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -X utf8 driverprecision.py %*) || (python -X utf8 driverprecision.py %*)
