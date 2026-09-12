@echo off
chcp 65001 >nul
title WhatsApp Multi-Account Platform v5.0

echo =================================================================
echo   WhatsApp Multi-Account Platform v5.0
echo   Orquestador de Automatizacion ^& Gestion de Cuentas
echo =================================================================

:: [1/3] Instalar dependencias de Python
echo.
echo [1/3] Instalando dependencias de Python...
pip install -r requirements.txt
if errorlevel 1 (
    echo   ERROR: Fallo la instalacion de dependencias Python.
    pause
    exit /b 1
)
echo   OK - Dependencias de Python instaladas.

:: [2/3] Instalar navegador Chromium (Playwright)
echo.
echo [2/3] Verificando navegador Chromium (Playwright)...
python -m playwright install chromium
if errorlevel 1 (
    echo   ADVERTENCIA: No se pudo instalar Chromium. Puede que ya este instalado.
)
echo   OK - Chromium listo.

:: [3/3] Iniciar servidor Flask
echo.
echo [3/3] Iniciando servidor Flask en http://127.0.0.1:5000 ...
echo   La interfaz web se abrira automaticamente en tu navegador.
echo.
python app.py

pause
