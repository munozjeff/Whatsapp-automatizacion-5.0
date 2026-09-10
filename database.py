import sqlite3
import json
import time
import functools
from pathlib import Path

DB_PATH = Path("./data/whatsapp.db")
DB_PATH.parent.mkdir(exist_ok=True)


def get_db_connection():
    """Conexión SQLite robusta para uso multi-hilo:
    - WAL mode: permite lecturas concurrentes mientras hay una escritura activa.
    - busy_timeout: espera hasta 10 s antes de lanzar OperationalError por lock.
    - check_same_thread=False: permite usar la conexión desde cualquier hilo.
    """
    conn = sqlite3.connect(
        DB_PATH,
        timeout=10,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _db_retry(fn):
    """Decorador: reintenta la función hasta 5 veces si SQLite lanza OperationalError
    (típicamente 'database is locked'). Espera incremental entre intentos."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if attempt == max_attempts:
                    print(f"[DB] ❌ Error persistente en '{fn.__name__}' tras {max_attempts} intentos: {e}")
                    raise
                wait = attempt * 0.5
                print(f"[DB] ⚠️ '{fn.__name__}' intento {attempt}/{max_attempts} – {e}. Reintentando en {wait:.1f}s...")
                time.sleep(wait)
    return wrapper


@_db_retry
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Tabla de campañas (Estáticas y Dinámicas con {variables})
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'estatica', -- 'estatica' o 'dinamica'
            template_message TEXT NOT NULL,
            variables_json TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabla de perfiles de envío (Configuración de ritmo, rotación y tandas)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS send_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            campaign_id INTEGER,
            delay_min_sec INTEGER DEFAULT 15,
            delay_max_sec INTEGER DEFAULT 45,
            messages_per_session INTEGER DEFAULT 10,
            messages_per_interval INTEGER DEFAULT 2,
            rest_time_minutes INTEGER DEFAULT 30,
            accounts_for_sending INTEGER DEFAULT 5,
            accounts_for_history INTEGER DEFAULT 5,
            history_msgs_per_turn INTEGER DEFAULT 2,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE SET NULL
        )
    """)

    # Migración segura para bases de datos existentes
    cursor.execute("PRAGMA table_info(send_profiles)")
    cols = [col["name"] for col in cursor.fetchall()]
    if "accounts_for_sending" not in cols:
        cursor.execute("ALTER TABLE send_profiles ADD COLUMN accounts_for_sending INTEGER DEFAULT 5")
    if "accounts_for_history" not in cols:
        cursor.execute("ALTER TABLE send_profiles ADD COLUMN accounts_for_history INTEGER DEFAULT 5")
    if "history_msgs_per_turn" not in cols:
        cursor.execute("ALTER TABLE send_profiles ADD COLUMN history_msgs_per_turn INTEGER DEFAULT 2")

    # Tabla de estado de cuentas (para contadores del dashboard)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_states (
            account_id TEXT PRIMARY KEY,
            phone TEXT DEFAULT '',
            status_state TEXT DEFAULT 'disponible',
            -- estados posibles: 'disponible', 'enviando', 'haciendo_historial', 'restringido', 'bloqueado'
            notes TEXT DEFAULT '',
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabla de notificaciones de clientes reales (mensajes entrantes de clientes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS client_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            client_phone TEXT NOT NULL,
            client_name TEXT DEFAULT '',
            message_text TEXT DEFAULT '',
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending' -- 'pending' o 'resolved'
        )
    """)

    # Tabla de jobs de automatización
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS automation_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER,
            campaign_id INTEGER,
            account_ids_json TEXT DEFAULT '[]',
            contacts_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            -- status: pending, running, paused, completed, error
            progress INTEGER DEFAULT 0,
            total_contacts INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT DEFAULT ''
        )
    """)

    conn.commit()
    conn.close()


# --- CRUD CAMPAÑAS ---

@_db_retry
def create_campaign(name: str, campaign_type: str, template_message: str, variables: list) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO campaigns (name, type, template_message, variables_json)
        VALUES (?, ?, ?, ?)
    """, (name, campaign_type, template_message, json.dumps(variables)))
    conn.commit()
    campaign_id = cursor.lastrowid
    conn.close()
    return campaign_id

@_db_retry
def get_campaigns() -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM campaigns ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        try:
            item["variables"] = json.loads(item.get("variables_json") or "[]")
        except Exception:
            item["variables"] = []
        result.append(item)
    return result

@_db_retry
def delete_campaign(campaign_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected


# --- CRUD PERFILES DE ENVÍO ---

@_db_retry
def create_send_profile(name: str, campaign_id: int, delay_min: int, delay_max: int,
                         msgs_session: int, msgs_interval: int, rest_mins: int,
                         acc_sending: int = 5, acc_history: int = 5, hist_msgs: int = 2) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO send_profiles
        (name, campaign_id, delay_min_sec, delay_max_sec, messages_per_session,
         messages_per_interval, rest_time_minutes, accounts_for_sending,
         accounts_for_history, history_msgs_per_turn)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, campaign_id, delay_min, delay_max, msgs_session, msgs_interval,
          rest_mins, acc_sending, acc_history, hist_msgs))
    conn.commit()
    profile_id = cursor.lastrowid
    conn.close()
    return profile_id

@_db_retry
def get_send_profiles() -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, c.name as campaign_name
        FROM send_profiles p
        LEFT JOIN campaigns c ON p.campaign_id = c.id
        ORDER BY p.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@_db_retry
def update_send_profile(profile_id: int, name: str, campaign_id: int, delay_min: int,
                          delay_max: int, msgs_session: int, msgs_interval: int, rest_mins: int,
                          acc_sending: int = 5, acc_history: int = 5, hist_msgs: int = 2) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE send_profiles SET
            name = ?,
            campaign_id = ?,
            delay_min_sec = ?,
            delay_max_sec = ?,
            messages_per_session = ?,
            messages_per_interval = ?,
            rest_time_minutes = ?,
            accounts_for_sending = ?,
            accounts_for_history = ?,
            history_msgs_per_turn = ?
        WHERE id = ?
    """, (name, campaign_id, delay_min, delay_max, msgs_session, msgs_interval,
          rest_mins, acc_sending, acc_history, hist_msgs, profile_id))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected

@_db_retry
def delete_send_profile(profile_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM send_profiles WHERE id = ?", (profile_id,))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected


# --- ESTADOS Y MÉTRICAS DE CUENTAS ---

@_db_retry
def update_account_state(account_id: str, status_state: str, phone: str = "", notes: str = "", force: bool = False):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Si NO es forzado (force=False), proteger estados 'bloqueado' y 'restringido' contra sobreescritura accidental por rutinas de background
    if not force and status_state in ("disponible", "enviando", "haciendo_historial"):
        cursor.execute("SELECT status_state FROM account_states WHERE account_id = ?", (account_id,))
        row = cursor.fetchone()
        if row and row["status_state"] in ("bloqueado", "restringido"):
            conn.close()
            return

    cursor.execute("""
        INSERT INTO account_states (account_id, phone, status_state, notes, last_updated)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(account_id) DO UPDATE SET
            status_state=excluded.status_state,
            phone=COALESCE(NULLIF(excluded.phone, ''), account_states.phone),
            notes=excluded.notes,
            last_updated=CURRENT_TIMESTAMP
    """, (account_id, phone, status_state, notes))
    conn.commit()
    conn.close()

@_db_retry
def get_all_account_states() -> dict[str, dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM account_states")
    rows = cursor.fetchall()
    conn.close()
    return {r["account_id"]: dict(r) for r in rows}

@_db_retry
def delete_account_state(account_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM account_states WHERE account_id = ?", (account_id,))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected


# --- NOTIFICACIONES DE CLIENTES REALES ---

@_db_retry
def add_client_notification(account_id: str, client_phone: str, client_name: str, message_text: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO client_notifications (account_id, client_phone, client_name, message_text, status)
        VALUES (?, ?, ?, ?, 'pending')
    """, (account_id, client_phone, client_name, message_text))
    conn.commit()
    notif_id = cursor.lastrowid
    conn.close()
    return notif_id

@_db_retry
def get_client_notifications(status: str = "pending", limit: int = 50) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if status == "all":
        cursor.execute("SELECT * FROM client_notifications ORDER BY id DESC LIMIT ?", (limit,))
    else:
        cursor.execute(
            "SELECT * FROM client_notifications WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@_db_retry
def resolve_client_notification(notification_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE client_notifications SET status = 'resolved' WHERE id = ?", (notification_id,))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected


# --- CRUD AUTOMATION JOBS ---

@_db_retry
def create_automation_job(profile_id: int, campaign_id: int, account_ids: list, contacts: list) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO automation_jobs
        (profile_id, campaign_id, account_ids_json, contacts_json, status, total_contacts, started_at)
        VALUES (?, ?, ?, ?, 'running', ?, CURRENT_TIMESTAMP)
    """, (profile_id, campaign_id, json.dumps(account_ids), json.dumps(contacts), len(contacts)))
    conn.commit()
    job_id = cursor.lastrowid
    conn.close()
    return job_id

@_db_retry
def get_automation_jobs(limit: int = 20) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT j.*,
               p.name as profile_name,
               c.name as campaign_name
        FROM automation_jobs j
        LEFT JOIN send_profiles p ON j.profile_id = p.id
        LEFT JOIN campaigns c ON j.campaign_id = c.id
        ORDER BY j.id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        item = dict(r)
        try:
            item["account_ids"] = json.loads(item.get("account_ids_json") or "[]")
            item["contacts"] = json.loads(item.get("contacts_json") or "[]")
        except Exception:
            item["account_ids"] = []
            item["contacts"] = []
        result.append(item)
    return result

@_db_retry
def get_automation_job(job_id: int) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT j.*,
               p.name as profile_name,
               c.name as campaign_name
        FROM automation_jobs j
        LEFT JOIN send_profiles p ON j.profile_id = p.id
        LEFT JOIN campaigns c ON j.campaign_id = c.id
        WHERE j.id = ?
    """, (job_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    try:
        item["account_ids"] = json.loads(item.get("account_ids_json") or "[]")
        item["contacts"] = json.loads(item.get("contacts_json") or "[]")
    except Exception:
        item["account_ids"] = []
        item["contacts"] = []
    return item

@_db_retry
def update_automation_job_status(job_id: int, status: str, sent: int = None,
                                  errors: int = None, progress: int = None, notes: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    fields = ["status = ?"]
    values = [status]
    if sent is not None:
        fields.append("sent_count = ?")
        values.append(sent)
    if errors is not None:
        fields.append("error_count = ?")
        values.append(errors)
    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if notes is not None:
        fields.append("notes = ?")
        values.append(notes)
    if status in ('completed', 'error', 'paused'):
        fields.append("finished_at = CURRENT_TIMESTAMP")
    values.append(job_id)
    cursor.execute(f"UPDATE automation_jobs SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()

@_db_retry
def delete_automation_job(job_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM automation_jobs WHERE id = ?", (job_id,))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected


# Inicializar BD al importar
init_db()
