@echo off
REM ============================================================
REM   Turpial Finanzas - arranque para Windows
REM   Hace: actualizar codigo -> dependencias -> servidor -> navegador
REM   Uso: doble clic en este archivo (start.bat)
REM ============================================================
setlocal
cd /d "%~dp0"
title Turpial Finanzas

echo.
echo ===============================================
echo    TURPIAL FINANZAS - iniciando plataforma
echo ===============================================
echo.

REM --- Detectar Python (py o python) ---
set PY=
where py >nul 2>nul && set PY=py
if "%PY%"=="" ( where python >nul 2>nul && set PY=python )
if "%PY%"=="" (
  echo [ERROR] No encontre Python. Instalalo desde https://www.python.org/downloads/
  echo         Acordate de tildar "Add Python to PATH" durante la instalacion.
  pause
  exit /b 1
)
echo [1/4] Python detectado: %PY%

REM --- Bajar la ultima version del codigo (si hay git) ---
where git >nul 2>nul
if %errorlevel%==0 (
  echo [2/4] Actualizando codigo desde GitHub...
  git pull origin claude/turpial-finanzas-agents-tjv6h3
) else (
  echo [2/4] Git no encontrado: salteo la actualizacion ^(uso el codigo local^).
)

REM --- Crear .env si no existe ---
if not exist ".env" (
  echo [info] No habia .env: creo uno desde la plantilla.
  copy ".env.example" ".env" >nul
  echo [IMPORTANTE] Abri el archivo .env y pega tu ANTHROPIC_API_KEY para activar el agente IA.
)

REM --- Instalar dependencias ---
echo [3/4] Instalando/actualizando dependencias...
%PY% -m pip install -q -r requirements.txt

REM --- Abrir el navegador y arrancar el servidor ---
echo [4/4] Abriendo el navegador y levantando el servidor...
echo.
echo    La plataforma estara en:  http://localhost:8000
echo    Para APAGARLA: cerra esta ventana o apreta Ctrl+C.
echo.
start "" http://localhost:8000
%PY% main.py

pause
