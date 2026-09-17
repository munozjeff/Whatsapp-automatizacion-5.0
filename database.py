import sqlite3
import json
import time
import random
import re
import functools
from pathlib import Path

DB_PATH = Path("./data/whatsapp.db")
DB_PATH.parent.mkdir(exist_ok=True)

FIRST_NAMES_BANK = [
    "Carlos", "Ana", "Juan", "Maria", "Luis", "Sofia", "Diego", "Valentina",
    "Mateo", "Camila", "Santiago", "Lucia", "Felipe", "Mariana", "Gabriel",
    "Andrea", "Daniel", "Isabella", "Alejandro", "Paula", "Andres", "Natalia",
    "Sebastian", "Daniela", "Nicolas", "Valeria", "Joaquin", "Elena", "Samuel",
    "Victoria", "David", "Gabriela", "Tomas", "Sara", "Lucas", "Manuela",
    "Simon", "Laura", "Emmanuel", "Antonia", "Martin", "Juliana", "Benjamin",
    "Salome", "Emanuel", "Jeronimo", "Julieta", "Agustin", "Guadalupe", "Thiago"
]

LAST_NAMES_BANK = [
    "Rodriguez", "Gomez", "Lopez", "Martinez", "Perez", "Gonzalez", "Sanchez",
    "Ramirez", "Torres", "Diaz", "Vargas", "Castro", "Morales", "Herrera",
    "Ruiz", "Jimenez", "Medina", "Silva", "Rojas", "Mendoza", "Guerrero",
    "Ortiz", "Gutierrez", "Cortes", "Moreno", "Muñoz", "Romero", "Alvarez",
    "Navarro", "Molina", "Rios", "Acosta", "Velasquez", "Salazar", "Guzman"
]

def generate_random_contact_name(used_names_set=None):
    if used_names_set is None:
        used_names_set = set()
    for _ in range(100):
        fn = random.choice(FIRST_NAMES_BANK)
        ln_base = random.choice(LAST_NAMES_BANK)
        rand_num = random.randint(1000, 9999)
        ln = f"{ln_base} {rand_num}"
        full = f"{fn} {ln}"
        if full not in used_names_set:
            used_names_set.add(full)
            return fn, ln
    return random.choice(FIRST_NAMES_BANK), f"{random.choice(LAST_NAMES_BANK)} {random.randint(1000, 9999)}"


# Conjuntos en minúsculas para búsqueda rápida
_FIRST_NAMES_LOWER = {n.lower() for n in FIRST_NAMES_BANK}
_LAST_NAMES_LOWER = {n.lower() for n in LAST_NAMES_BANK}

# Patrón: "Nombre Apellido NNNN" (nombre y apellido del banco, seguido de 3-4 dígitos)
_SYSTEM_NAME_PATTERN = re.compile(
    r'^(' + '|'.join(re.escape(n) for n in FIRST_NAMES_BANK) + r')\s+'
    r'(' + '|'.join(re.escape(n) for n in LAST_NAMES_BANK) + r')\s+\d{3,5}$',
    re.IGNORECASE
)

def is_system_generated_name(name: str) -> bool:
    """Retorna True si el nombre sigue el patrón de nombre autogenerado del sistema.
    Ej: 'Antonia Jimenez 8306' -> True, 'Juan Perez' -> False
    """
    return bool(_SYSTEM_NAME_PATTERN.match((name or "").strip()))




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
            auto_reply_enabled INTEGER DEFAULT 0,
            auto_reply_message TEXT DEFAULT '',
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
    if "auto_reply_enabled" not in cols:
        cursor.execute("ALTER TABLE send_profiles ADD COLUMN auto_reply_enabled INTEGER DEFAULT 0")
    if "auto_reply_message" not in cols:
        cursor.execute("ALTER TABLE send_profiles ADD COLUMN auto_reply_message TEXT DEFAULT ''")

    # Tabla de estado de cuentas (para contadores del dashboard)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_states (
            account_id TEXT PRIMARY KEY,
            phone TEXT DEFAULT '',
            status_state TEXT DEFAULT 'disponible',
            -- estados posibles: 'disponible', 'enviando', 'haciendo_historial', 'restringido', 'bloqueado'
            notes TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migraciones para account_states
    cursor.execute("PRAGMA table_info(account_states)")
    acc_cols = [col["name"] for col in cursor.fetchall()]
    if "first_name" not in acc_cols:
        cursor.execute("ALTER TABLE account_states ADD COLUMN first_name TEXT DEFAULT ''")
    if "last_name" not in acc_cols:
        cursor.execute("ALTER TABLE account_states ADD COLUMN last_name TEXT DEFAULT ''")

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
                         acc_sending: int = 5, acc_history: int = 5, hist_msgs: int = 2,
                         auto_reply_enabled: int = 0, auto_reply_message: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO send_profiles
        (name, campaign_id, delay_min_sec, delay_max_sec, messages_per_session,
         messages_per_interval, rest_time_minutes, accounts_for_sending,
         accounts_for_history, history_msgs_per_turn, auto_reply_enabled, auto_reply_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, campaign_id, delay_min, delay_max, msgs_session, msgs_interval,
          rest_mins, acc_sending, acc_history, hist_msgs, auto_reply_enabled, auto_reply_message))
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
                          acc_sending: int = 5, acc_history: int = 5, hist_msgs: int = 2,
                          auto_reply_enabled: int = 0, auto_reply_message: str = "") -> bool:
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
            history_msgs_per_turn = ?,
            auto_reply_enabled = ?,
            auto_reply_message = ?
        WHERE id = ?
    """, (name, campaign_id, delay_min, delay_max, msgs_session, msgs_interval,
          rest_mins, acc_sending, acc_history, hist_msgs, auto_reply_enabled, auto_reply_message, profile_id))
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
def update_account_state(account_id: str, status_state: str, phone: str = "", notes: str = "", force: bool = False, first_name: str = "", last_name: str = ""):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Preservar o asignar nombres estructurados persistentes para contactos de Google
    cursor.execute("SELECT status_state, first_name, last_name FROM account_states WHERE account_id = ?", (account_id,))
    row = cursor.fetchone()

    current_status = row["status_state"] if row else ""
    existing_fn = row["first_name"] if row and row["first_name"] else ""
    existing_ln = row["last_name"] if row and row["last_name"] else ""

    fn_final = first_name or existing_fn
    ln_final = last_name or existing_ln

    if not fn_final or not ln_final:
        cursor.execute("SELECT first_name, last_name FROM account_states")
        all_rows = cursor.fetchall()
        used = {f"{r['first_name']} {r['last_name']}" for r in all_rows if r['first_name']}
        auto_fn, auto_ln = generate_random_contact_name(used)
        if not fn_final: fn_final = auto_fn
        if not ln_final: ln_final = auto_ln

    # Si NO es forzado (force=False), proteger estados 'bloqueado' y 'restringido' contra sobreescritura accidental por rutinas de background
    if not force and status_state in ("disponible", "enviando", "haciendo_historial") and current_status in ("bloqueado", "restringido"):
        cursor.execute("UPDATE account_states SET first_name=?, last_name=? WHERE account_id=?", (fn_final, ln_final, account_id))
        conn.commit()
        conn.close()
        return

    cursor.execute("""
        INSERT INTO account_states (account_id, phone, status_state, notes, first_name, last_name, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(account_id) DO UPDATE SET
            status_state=excluded.status_state,
            phone=COALESCE(NULLIF(excluded.phone, ''), account_states.phone),
            notes=excluded.notes,
            first_name=COALESCE(NULLIF(excluded.first_name, ''), account_states.first_name),
            last_name=COALESCE(NULLIF(excluded.last_name, ''), account_states.last_name),
            last_updated=CURRENT_TIMESTAMP
    """, (account_id, phone, status_state, notes, fn_final, ln_final))
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
def get_all_account_phone_digits() -> set[str]:
    """Retorna los conjuntos de dígitos numéricos de todas las cuentas del sistema para filtrado estricto."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM account_states WHERE phone IS NOT NULL AND phone != ''")
    rows = cursor.fetchall()
    conn.close()

    digits_set = set()
    for r in rows:
        phone_str = r["phone"] or ""
        clean = re.sub(r"[^\d]", "", phone_str)
        if len(clean) >= 7:
            digits_set.add(clean)
            if len(clean) > 8:
                digits_set.add(clean[-8:])
                digits_set.add(clean[-10:])
    return digits_set

@_db_retry
def get_all_account_contact_names() -> set[str]:
    """Retorna los nombres completos concatenados (first_name + last_name) de todas las cuentas del sistema."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT first_name, last_name FROM account_states WHERE first_name IS NOT NULL AND first_name != ''")
    rows = cursor.fetchall()
    conn.close()
    names = set()
    for r in rows:
        fn = (r["first_name"] or "").strip()
        ln = (r["last_name"] or "").strip()
        if fn:
            names.add(fn.lower())
            if ln:
                names.add(f"{fn} {ln}".lower())
                # También el nombre completo sin el sufijo numérico si lo tiene
                ln_base = re.sub(r'\s*\d+$', '', ln).strip()
                if ln_base:
                    names.add(f"{fn} {ln_base}".lower())
    return names

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
def add_client_notification(account_id: str, client_phone: str, client_name: str, message_text: str) -> int | None:
    # ── FILTRADO ESTRICTO: comparar por número, nombre en BD y patrón autogenerado ──

    # 1) Filtro por dígitos de teléfono
    client_digits = re.sub(r"[^\d]", "", client_phone or "")
    if client_digits and len(client_digits) >= 7:
        system_phones = get_all_account_phone_digits()
        for sys_digits in system_phones:
            if sys_digits and (sys_digits in client_digits or client_digits in sys_digits):
                print(f"[DB Notification] 🛡️ Ignorando notificación (nro): '{client_phone}' es una cuenta propia del sistema.")
                return None

    # 2) Filtro por nombre registrado en BD (first_name + last_name de account_states)
    client_name_lower = (client_name or "").strip().lower()
    client_phone_lower = (client_phone or "").strip().lower()
    system_names = get_all_account_contact_names()
    for sys_name in system_names:
        if not sys_name:
            continue
        if sys_name in client_name_lower or sys_name in client_phone_lower:
            print(f"[DB Notification] 🛡️ Ignorando notificación (nombre BD): '{client_name}' coincide con cuenta propia '{sys_name}'.")
            return None

    # 3) Filtro por patrón de nombre autogenerado: "NombreBanco ApellidoBanco NNNN"
    #    Captura cuentas antiguas que ya no están en BD pero cuyo nombre fue autogenerado
    for candidate in [client_name, client_phone]:
        if candidate and is_system_generated_name(candidate):
            print(f"[DB Notification] 🛡️ Ignorando notificación (patrón auto): '{candidate}' sigue el patrón de nombre autogenerado del sistema.")
            return None

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
    query = """
        SELECT n.*, a.phone as account_phone, a.first_name as account_first_name, a.last_name as account_last_name
        FROM client_notifications n
        LEFT JOIN account_states a ON n.account_id = a.account_id
    """
    if status != "all":
        query += " WHERE n.status = ?"
        query += " ORDER BY n.id DESC LIMIT ?"
        cursor.execute(query, (status, limit))
    else:
        query += " ORDER BY n.id DESC LIMIT ?"
        cursor.execute(query, (limit,))
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

@_db_retry
def resolve_all_client_notifications() -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE client_notifications SET status = 'resolved' WHERE status = 'pending'")
    conn.commit()
    affected = cursor.rowcount
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
