import os
import sys
import io
import subprocess
import webbrowser
import time
from pathlib import Path

# Force UTF-8 encoding on Windows console streams to prevent UnicodeEncodeError with emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT_DIR = Path(__file__).parent.resolve()

def print_banner():
    print("=" * 65)
    print("🚀 WhatsApp Multi-Account Platform v5.0")
    print("   Orquestador de Automatización & Gestión de Cuentas")
    print("=" * 65)

def check_python_dependencies():
    print("\n[1/4] Verificando dependencias de Python...")
    req_file = ROOT_DIR / "requirements.txt"
    if req_file.exists():
        try:
            import flask
            import flask_cors
            import playwright
            print("  ✅ Dependencias de Python verificadas.")
        except ImportError:
            print("  ⏳ Instalando dependencias de Python desde requirements.txt...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)], check=True)

    print("  ⏳ Verificando navegador Chromium (Playwright)...")
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("  ✅ Navegador Chromium listo.")
    except Exception as e:
        print(f"  ⚠️ Advertencia al verificar Chromium: {e}")

def build_frontend_if_needed():
    print("\n[2/4] Verificando compilación del Frontend (React)...")
    frontend_dir = ROOT_DIR / "frontend"
    dist_dir = ROOT_DIR / "static" / "dist"
    
    if frontend_dir.exists():
        node_modules = frontend_dir / "node_modules"
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        
        if not node_modules.exists():
            print("  ⏳ Instalando dependencias de Node.js en ./frontend...")
            subprocess.run([npm_cmd, "install"], cwd=str(frontend_dir), check=True)
            
        print("  ⏳ Compilando aplicación React para producción...")
        subprocess.run([npm_cmd, "run", "build"], cwd=str(frontend_dir), check=True)
        print("  ✅ Frontend compilado exitosamente en static/dist.")
    elif dist_dir.exists():
        print("  ✅ Archivos estáticos en static/dist listos.")
    else:
        print("  ⚠️ No se encontró la carpeta frontend ni static/dist.")

def init_database():
    print("\n[3/5] Verificando e inicializando la Base de Datos SQLite...")
    try:
        import database as db
        db.init_db()
        print("  ✅ Base de datos (data/whatsapp.db) verificada e inicializada.")
    except Exception as e:
        print(f"  ❌ Error al inicializar la base de datos: {e}")
        sys.exit(1)

def check_git_updates_on_startup():
    print("\n[4/5] Verificando si existen actualizaciones en el repositorio remoto Git...")
    git_dir = ROOT_DIR / ".git"
    if not git_dir.exists():
        print("  ℹ️ El sistema se está ejecutando desde un archivo comprimido ZIP (sin repositorio Git activo).")
        return

    try:
        subprocess.run(["git", "fetch", "origin"], capture_output=True, text=True, timeout=8)
        current_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip() or "release"
        local_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        remote_hash = subprocess.check_output(["git", "rev-parse", "--short", f"origin/{current_branch}"], text=True, stderr=subprocess.DEVNULL).strip()
        if local_hash != remote_hash:
            print(f"  🔔 ¡NUEVA ACTUALIZACIÓN DISPONIBLE EN GITHUB [{current_branch}]! ({local_hash} -> {remote_hash})")
            print("  💡 Podrás descargarla e instalarla con 1 solo click desde la interfaz web.")
        else:
            print(f"  ✅ El sistema está completamente actualizado en la rama [{current_branch}] ({local_hash}).")
    except Exception as e:
        print(f"  ⚠️ No se pudo verificar la actualización remota de Git.")

def run_application():
    print("\n[5/5] Iniciando el servidor Backend Flask en http://127.0.0.1:5000...")
    print("  🌐 La interfaz web se abrirá automáticamente en tu navegador.\n")
    
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:5000")

    import threading
    threading.Thread(target=open_browser, daemon=True).start()
    
    from app import app
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

if __name__ == "__main__":
    print_banner()
    check_python_dependencies()
    build_frontend_if_needed()
    init_database()
    check_git_updates_on_startup()
    run_application()

