@echo off
rem Wdraza frontend do XAMPP i uruchamia backend FastAPI.
cd /d "%~dp0"

set "XAMPP_DIR=C:\xampp"
set "WEB_DIR=%XAMPP_DIR%\htdocs\hackathon"

if not exist "%XAMPP_DIR%\htdocs" (
    echo Nie znaleziono C:\xampp\htdocs.
    echo Zainstaluj XAMPP albo zmien XAMPP_DIR w start.bat.
    pause
    exit /b 1
)

if not exist "%WEB_DIR%" mkdir "%WEB_DIR%"
copy /Y "login.html" "%WEB_DIR%\login.html" >nul
copy /Y "kreator-bohatera.html" "%WEB_DIR%\kreator-bohatera.html" >nul
copy /Y "arena.html" "%WEB_DIR%\arena.html" >nul
if exist "lobby.html" copy /Y "lobby.html" "%WEB_DIR%\lobby.html" >nul
if exist "Characters" xcopy /E /I /Y "Characters" "%WEB_DIR%\Characters" >nul
if exist "Potwory" xcopy /E /I /Y "Potwory" "%WEB_DIR%\Potwory" >nul
if exist "Wizard" xcopy /E /I /Y "Wizard" "%WEB_DIR%\Wizard" >nul
if exist "the-tower-is-jammed-ost" xcopy /E /I /Y "the-tower-is-jammed-ost" "%WEB_DIR%\the-tower-is-jammed-ost" >nul
if exist "ui-assets" xcopy /E /I /Y "ui-assets" "%WEB_DIR%\ui-assets" >nul
copy /Y ".htaccess" "%WEB_DIR%\.htaccess" >nul
if exist "index.html" copy /Y "index.html" "%WEB_DIR%\index.html" >nul
if exist "README.md" copy /Y "README.md" "%WEB_DIR%\README.md" >nul

if not exist .venv\Scripts\python.exe (
    echo Tworze srodowisko wirtualne...
    py -m venv .venv
    if errorlevel 1 (
        echo Nie znaleziono Pythona. Zainstaluj go z python.org i zaznacz "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

.venv\Scripts\python.exe -m pip install -q -r requirements.txt
echo.
echo Frontend XAMPP: http://10.132.198.126/hackathon/
echo Backend: http://10.132.198.126:8765  (dokumentacja: /docs). Zatrzymanie: Ctrl+C
start "" http://10.132.198.126/hackathon/
echo FastAPI uruchamia sie na wszystkich interfejsach sieciowych (0.0.0.0).
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8765
pause
