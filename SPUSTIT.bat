@echo off
echo Instaluji potrebne balicky...
pip install -r requirements.txt
echo.
echo Spoustim CPC Analyzer...
echo Otevri prohlizec na: http://localhost:5000
echo Pro ukonceni stiskni Ctrl+C
echo.
python app.py
pause
