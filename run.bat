@echo off
setlocal enabledelayedexpansion
title WhatsApp Multi-Account Platform v5.0

echo =================================================================
echo   WhatsApp Multi-Account Platform v5.0
echo   Orquestador de Automatizacion ^& Gestion de Cuentas
echo =================================================================

REM [1/2] Verificando entorno Python...
echo.
echo [1/2] Verificando entorno Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado o no se encuentra en el PATH de Windows.
    pause
    exit /b 1
)
echo OK - Python detectado correctamente.

REM [2/2] Ejecutando el orquestador principal (run.py)
echo.
echo [2/2] Iniciando plataforma y servidor web en http://127.0.0.1:5000 ...
python run.py

if errorlevel 1 (
    echo.
    echo ERROR: Ocurrio un fallo al ejecutar la plataforma.
    pause
)
