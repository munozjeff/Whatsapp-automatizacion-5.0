@echo off
chcp 65001 >nul
title WhatsApp Multi-Account Platform v5.0

echo =================================================================
echo   🚀 WhatsApp Multi-Account Platform v5.0
echo   Orquestador de Automatización ^& Gestión de Cuentas
echo =================================================================

:: [1/5] Instalar dependencias de Python
echo.
echo [1/5] Verificando dependencias de Python...
pip install -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo   ⚠️ Advertencia al instalar algunas dependencias de Python.
) else (
    echo   ✅ Dependencias de Python verificadas.
)

:: [2/5] Instalar navegador Chromium (Playwright)
echo.
echo [2/5] Verificando navegador Chromium (Playwright)...
python -m playwright install chromium >nul 2>&1
echo   ✅ Navegador Chromium listo.

:: [3/5] Verificando compilación del Frontend (React)
echo.
echo [3/5] Verificando compilación del Frontend (React)...
if exist "frontend\package.json" (
    if not exist "frontend\node_modules" (
        echo   ⏳ Instalando dependencias de Node.js...
        cd frontend && call npm install && cd ..
    )
    if not exist "static\dist\index.html" (
        echo   ⏳ Compilando aplicación React para producción...
        cd frontend && call npm run build && cd ..
    ) else (
        echo   ✅ Frontend listo en static/dist.
    )
)

:: [4/5] Verificando actualizaciones en el repositorio remoto Git
echo.
echo [4/5] Verificando si existen actualizaciones en GitHub...
git fetch origin >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%a in ('git rev-parse --short HEAD 2^>nul') do set LOCAL_HASH=%%a
    for /f "tokens=*" %%b in ('git rev-parse --short origin/main 2^>nul') do set REMOTE_HASH=%%b
    if defined LOCAL_HASH if defined REMOTE_HASH (
        if not "%LOCAL_HASH%"=="%REMOTE_HASH%" (
            echo   🔔 ¡NUEVA ACTUALIZACIÓN DISPONIBLE EN GITHUB! (%LOCAL_HASH% -^> %REMOTE_HASH%)
            echo   💡 Podrás descargarla e instalarla con 1 solo click desde la interfaz web.
        ) else (
            echo   ✅ El sistema está completamente actualizado (%LOCAL_HASH%).
        )
    )
) else (
    echo   ⚠️ No se pudo conectar con GitHub para comprobar actualizaciones.
)

:: [5/5] Iniciar servidor mediante Python run.py
echo.
echo [5/5] Iniciando servidor y abriendo navegador...
python run.py

pause
