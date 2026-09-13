@echo off
setlocal enabledelayedexpansion
title Publicador de Versión Release

echo =================================================================
echo   Publicador de Versión Release para Usuarios Finales
echo =================================================================

python deploy_release.py

if errorlevel 1 (
    echo.
    echo ERROR: Ocurrió un problema durante la publicación de la versión release.
    pause
)
