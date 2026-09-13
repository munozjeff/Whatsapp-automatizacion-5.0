@echo off
chcp 65001 >nul
title Publicador de Versión Release

echo =================================================================
echo   🚀 Publicador Automático de Versión Release para Usuarios
echo =================================================================

echo.
echo [1/5] Compilando frontend React para producción...
cd frontend && call npm run build && cd ..
if errorlevel 1 (
    echo   ❌ Error durante la compilación del frontend.
    pause
    exit /b 1
)
echo   ✅ Frontend compilado exitosamente en static/dist.

echo.
echo [2/5] Guardando cambios en rama de desarrollo (main)...
git add .
git commit -m "build: preparación de versión para distribución release" >nul 2>&1
git push origin main
echo   ✅ Rama main actualizada en GitHub.

echo.
echo [3/5] Sincronizando con rama release...
git checkout release >nul 2>&1
if errorlevel 1 (
    echo   ⏳ Creando rama release...
    git checkout -b release
)

git merge main --no-edit
git rm -r frontend >nul 2>&1
git commit -m "release: versión de producción empaquetada para usuario final" >nul 2>&1

echo.
echo [4/5] Subiendo rama release a GitHub...
git push origin release
echo   ✅ Rama release publicada exitosamente en GitHub.

echo.
echo [5/5] Regresando a rama de desarrollo main...
git checkout main >nul 2>&1
echo   ✅ De vuelta en la rama main para continuar desarrollando.

echo.
echo =================================================================
echo   🎉 ¡Publicación completada! Tus usuarios finales ya pueden actualizar.
echo =================================================================
pause
