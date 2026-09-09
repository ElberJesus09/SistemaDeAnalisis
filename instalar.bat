@echo off
setlocal
chcp 65001 >nul
title Instalar - Sistema de Inscripciones CPU UNPRG
cd /d "%~dp0"

call :buscar_python
if not defined PY goto sin_python

%PY% instalar.py
exit /b 0

:sin_python
echo.
echo [X] No se encontro Python en esta computadora.
echo.
echo     Instala Python 3.10 o superior desde python.org
echo     y MARCA la casilla "Add Python to PATH" al instalar.
echo.
pause
exit /b 1

rem ---------------------------------------------------------------
rem Busca el interprete: primero el lanzador py, luego python en el
rem PATH y por ultimo las carpetas donde Windows lo suele instalar.
rem ---------------------------------------------------------------
:buscar_python
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY="%~dp0.venv\Scripts\python.exe""
    goto :eof
)
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto :eof
)
python --version >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto :eof
)
for %%V in (314 313 312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe""
        goto :eof
    )
    if exist "C:\Python%%V\python.exe" (
        set "PY="C:\Python%%V\python.exe""
        goto :eof
    )
    if exist "%ProgramFiles%\Python%%V\python.exe" (
        set "PY="%ProgramFiles%\Python%%V\python.exe""
        goto :eof
    )
)
goto :eof
