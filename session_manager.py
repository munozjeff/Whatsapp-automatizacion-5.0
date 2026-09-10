import os
import shutil
import time
import subprocess
from pathlib import Path

PROFILES_DIR = Path("./profiles").resolve()
PROFILES_DIR.mkdir(exist_ok=True)

class SessionManager:
    @staticmethod
    def get_profile_dir(account_id: str) -> Path:
        safe_id = "".join(c for c in account_id if c.isalnum() or c in ("_", "-")).strip()
        p_dir = PROFILES_DIR / safe_id
        try:
            p_dir.mkdir(exist_ok=True, parents=True)
        except Exception:
            pass
        return p_dir

    @staticmethod
    def has_session(account_id: str) -> bool:
        p_dir = SessionManager.get_profile_dir(account_id)
        indexed_db = p_dir / "Default" / "IndexedDB"
        local_storage = p_dir / "Default" / "Local Storage"
        return indexed_db.exists() or local_storage.exists()

    @staticmethod
    def kill_profile_processes(account_id: str):
        """Fuerza la terminacion de procesos chrome.exe asociados a este perfil en Windows."""
        try:
            safe_id = "".join(c for c in account_id if c.isalnum() or c in ("_", "-")).strip()
            ps_cmd = f"Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | Where-Object {{ $_.CommandLine -like '*{safe_id}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
            subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=5)
        except Exception as e:
            print(f"Error forzando cierre de procesos para {account_id}: {e}")

    @staticmethod
    def unlock_profile(account_id: str):
        """Elimina archivos de bloqueo residuales de Chromium (SingletonLock, SingletonCookie) en Windows si la ventana no está viva."""
        p_dir = SessionManager.get_profile_dir(account_id)
        lock_files = [
            p_dir / "SingletonLock",
            p_dir / "SingletonCookie",
            p_dir / "SingletonSocket",
            p_dir / "lockfile"
        ]
        for lock in lock_files:
            if lock.exists() or lock.is_symlink():
                try:
                    if lock.is_dir():
                        shutil.rmtree(lock)
                    else:
                        lock.unlink(missing_ok=True)
                except Exception as e:
                    pass

    @staticmethod
    def delete_session(account_id: str) -> bool:
        p_dir = SessionManager.get_profile_dir(account_id)
        SessionManager.kill_profile_processes(account_id)
        SessionManager.unlock_profile(account_id)
        if p_dir.exists():
            try:
                shutil.rmtree(p_dir)
                return True
            except Exception as e:
                print(f"Error eliminando perfil {account_id}: {e}")
                return False
        return False

    @staticmethod
    def prune_profile_cache(account_id: str):
        """Elimina archivos temporales de cache para mantener el tamano del perfil minimo (~5-10 MB)."""
        p_dir = SessionManager.get_profile_dir(account_id)
        default_dir = p_dir / "Default"
        
        cache_folders = [
            default_dir / "Cache",
            default_dir / "Code Cache",
            default_dir / "GPUCache",
            default_dir / "Service Worker" / "CacheStorage",
            default_dir / "Service Worker" / "ScriptCache"
        ]

        for folder in cache_folders:
            if folder.exists():
                try:
                    shutil.rmtree(folder)
                except Exception:
                    pass

    @staticmethod
    def get_dir_size_kb(path: Path) -> float:
        total_size = 0
        if not path.exists():
            return 0.0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total_size += os.path.getsize(fp)
                except OSError:
                    pass
        return round(total_size / 1024, 2)

    @staticmethod
    def list_accounts() -> list[dict]:
        accounts = []
        for item in PROFILES_DIR.iterdir():
            if item.is_dir():
                account_id = item.name
                size_kb = SessionManager.get_dir_size_kb(item)
                mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.stat().st_mtime))
                accounts.append({
                    "account_id": account_id,
                    "file_path": str(item),
                    "size_kb": size_kb,
                    "size_mb": round(size_kb / 1024, 2),
                    "last_modified": mtime,
                    "has_session": SessionManager.has_session(account_id)
                })
        accounts.sort(key=lambda x: x["account_id"])
        return accounts

    @staticmethod
    def get_total_disk_usage() -> dict:
        accounts = SessionManager.list_accounts()
        total_kb = sum(acc["size_kb"] for acc in accounts)
        count = len(accounts)
        
        estimated_chrome_mb = count * 350
        actual_mb = total_kb / 1024
        saved_mb = max(0, estimated_chrome_mb - actual_mb)
        
        return {
            "account_count": count,
            "actual_size_kb": round(total_kb, 2),
            "actual_size_mb": round(actual_mb, 2),
            "estimated_chrome_mb": round(estimated_chrome_mb, 2),
            "saved_mb": round(saved_mb, 2),
            "savings_percentage": round((saved_mb / estimated_chrome_mb * 100), 1) if estimated_chrome_mb > 0 else 0
        }
