import os
import sys
import io
import subprocess
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT_DIR = Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT_DIR / "frontend"

def run_cmd(cmd, cwd=None, check=True):
    print(f"  👉 Ejecutando: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and res.returncode != 0:
        print(f"  ❌ Error: {res.stderr or res.stdout}")
        sys.exit(1)
    return res.stdout.strip()

def main():
    print("=" * 65)
    print("🚀 Publicador Automático de Versión Release (Usuario Final)")
    print("=" * 65)

    # 1. Build frontend
    print("\n[1/5] Compilando frontend React para producción...")
    if FRONTEND_DIR.exists():
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        run_cmd([npm_cmd, "run", "build"], cwd=str(FRONTEND_DIR))
        print("  ✅ Frontend compilado exitosamente en static/dist.")

    # 2. Save changes in main
    print("\n[2/5] Guardando y asegurando la rama main en GitHub...")
    run_cmd(["git", "add", "."], cwd=str(ROOT_DIR))
    subprocess.run(["git", "commit", "-m", "build: preparacion de version release"], cwd=str(ROOT_DIR), capture_output=True)
    run_cmd(["git", "push", "origin", "main"], cwd=str(ROOT_DIR), check=False)
    print("  ✅ Rama main al día.")

    # 3. Switch/create release branch
    print("\n[3/5] Creando/Sincronizando rama 'release'...")
    branches = run_cmd(["git", "branch", "-a"], cwd=str(ROOT_DIR))
    if "release" in branches:
        run_cmd(["git", "checkout", "release"], cwd=str(ROOT_DIR))
    else:
        run_cmd(["git", "checkout", "-b", "release"], cwd=str(ROOT_DIR))

    # Merge main into release
    run_cmd(["git", "merge", "main", "--no-edit"], cwd=str(ROOT_DIR), check=False)

    # Remove uncompiled /frontend and dev scripts (deploy_release.*) from release branch
    print("  🧹 Limpiando fuentes y scripts de desarrollo de la rama release...")
    if (ROOT_DIR / "frontend").exists():
        subprocess.run(["git", "rm", "-r", "-f", "frontend"], cwd=str(ROOT_DIR), capture_output=True)
    if (ROOT_DIR / "deploy_release.py").exists():
        subprocess.run(["git", "rm", "-f", "deploy_release.py"], cwd=str(ROOT_DIR), capture_output=True)
    if (ROOT_DIR / "deploy_release.bat").exists():
        subprocess.run(["git", "rm", "-f", "deploy_release.bat"], cwd=str(ROOT_DIR), capture_output=True)
        
    subprocess.run(["git", "commit", "-m", "release: paquete limpio de producción para usuario final"], cwd=str(ROOT_DIR), capture_output=True)

    # 4. Push release branch to origin
    print("\n[4/5] Publicando la rama 'release' en GitHub...")
    run_cmd(["git", "push", "origin", "release"], cwd=str(ROOT_DIR))
    print("  ✅ Rama 'release' subida a GitHub exitosamente.")

    # 5. Switch back to main
    print("\n[5/5] Regresando a la rama de desarrollo 'main'...")
    run_cmd(["git", "checkout", "main"], cwd=str(ROOT_DIR))
    print("  ✅ De vuelta en la rama main. Entorno de desarrollo listo.")

    print("\n" + "=" * 65)
    print("🎉 ¡PROCESO DE PUBLICACIÓN RELEASE COMPLETADO EXITOSAMENTE!")
    print("   Tus usuarios finales ya pueden recibir actualizaciones en 1-click.")
    print("=" * 65)

if __name__ == "__main__":
    main()
