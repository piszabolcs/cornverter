@echo off
REM ===========================================================================
REM  CornVerter launcher (Windows)
REM  - first run: creates a local Python virtual environment (.venv)
REM  - installs the dependencies, later only when requirements.txt changes
REM  - starts the window; arguments are passed on (command line mode)
REM  No administrator rights are needed inside your own folders.
REM ===========================================================================

setlocal
cd /d "%~dp0"
set "PYEXE=.venv\Scripts\python.exe"

echo.
echo  CornVerter - anything to PDF
echo.

if exist "%PYEXE%" goto deps

set "BOOT="
where py >nul 2>nul && set "BOOT=py -3"
if not defined BOOT where python >nul 2>nul && set "BOOT=python"
if not defined BOOT goto nopython

echo [1/3] Creating the virtual environment in .venv ...
%BOOT% -m venv .venv
if errorlevel 1 goto venvfail

:deps
REM Install only when requirements.txt differs from the last installed copy.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if not errorlevel 1 goto start
echo [2/3] Installing the dependencies - first run or requirements.txt changed ...
"%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail
copy /y requirements.txt ".venv\requirements.installed" >nul

:start
set "HAVE_LO="
where soffice >nul 2>nul && set "HAVE_LO=1"
if exist "C:\Program Files\LibreOffice\program\soffice.exe" set "HAVE_LO=1"
if not defined HAVE_LO (
    echo [NOTE] LibreOffice was not found. Spreadsheets, Word, PowerPoint and RTF
    echo        files are converted by the built-in renderer - content without
    echo        formatting. .doc, .ppt, .xlsb, .odt, .ods and .odp need LibreOffice:
    echo        https://www.libreoffice.org/download/
    echo.
)

echo [3/3] Starting CornVerter ...
"%PYEXE%" main.py %*
if errorlevel 1 goto apperror
exit /b 0

:nopython
echo [ERROR] Python was not found. Install Python 3.12 or newer from
echo         https://www.python.org/downloads/ and tick "Add Python to PATH".
pause
exit /b 1

:venvfail
echo [ERROR] Could not create the virtual environment.
pause
exit /b 1

:pipfail
echo [ERROR] Installing the dependencies failed - check the internet connection.
pause
exit /b 1

:apperror
echo.
echo [ERROR] CornVerter exited with an error - see the messages above.
pause
exit /b 1
