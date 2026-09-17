import os
import sys
import re
import io
import csv
import random
import asyncio
import subprocess
from pathlib import Path
from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
from session_manager import SessionManager
from whatsapp_runner import runner
import database as db

# ── Suprimir error inofensivo de asyncio en Windows al cerrar navegadores ──────
# Bug conocido de Python en Windows: _ProactorBasePipeTransport._call_connection_lost
# lanza AttributeError cuando Playwright cierra procesos del navegador.
if sys.platform == "win32":
    _original_proactor_handler = None
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport

        def _silence_pipe_error(self, exc):
            try:
                _original_call = super(_ProactorBasePipeTransport, self)
                _original_call._call_connection_lost(exc)
            except AttributeError:
                pass

        _ProactorBasePipeTransport._call_connection_lost = _silence_pipe_error
    except Exception:
        pass

# --- TEELOGGER PARA GUARDAR LOGS EN ARCHIVO ---
LOG_FILE = Path("app.log")

class TeeLogger:
    def __init__(self, original_stream, log_filepath):
        self.original_stream = original_stream
        self.log_file = open(log_filepath, "a", encoding="utf-8", buffering=1)

    def write(self, message):
        if hasattr(self.original_stream, "write"):
            try:
                self.original_stream.write(message)
            except Exception:
                pass
        if self.log_file and not self.log_file.closed:
            try:
                self.log_file.write(message)
            except Exception:
                pass

    def flush(self):
        if hasattr(self.original_stream, "flush"):
            try:
                self.original_stream.flush()
            except Exception:
                pass
        if self.log_file and not self.log_file.closed:
            try:
                self.log_file.flush()
            except Exception:
                pass

sys.stdout = TeeLogger(sys.stdout, LOG_FILE)
sys.stderr = TeeLogger(sys.stderr, LOG_FILE)

STATIC_DIST = Path(__file__).parent / "static" / "dist"

if STATIC_DIST.exists():
    app = Flask(__name__, static_folder=str(STATIC_DIST), static_url_path="", template_folder="templates")
else:
    app = Flask(__name__, template_folder="templates", static_folder="static")

CORS(app)

@app.route("/api/logs", methods=["GET"])
def get_recent_logs():
    lines_count = request.args.get("lines", 100, type=int)
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                content = f.readlines()
                recent = content[-lines_count:]
                return jsonify({"status": "success", "logs": "".join(recent), "lines": len(recent)})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "success", "logs": "Sin logs aún.", "lines": 0})

@app.route("/")
def index():
    if STATIC_DIST.exists() and (STATIC_DIST / "index.html").exists():
        return app.send_static_file("index.html")
    return render_template("index.html")

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "message": "Endpoint no encontrado"}), 404
    if STATIC_DIST.exists() and (STATIC_DIST / "index.html").exists():
        return app.send_static_file("index.html")
    return render_template("index.html"), 404

# --- DASHBOARD STATS ---

@app.route("/api/dashboard/stats", methods=["GET"])
def get_dashboard_stats():
    accounts_in_disk = SessionManager.list_accounts()
    active_instances = runner.get_status_all(accounts_in_disk)
    db_states = db.get_all_account_states()
    disk_metrics = SessionManager.get_total_disk_usage()

    total_registered = len(accounts_in_disk)
    en_ejecucion = sum(1 for acc in active_instances if acc["is_active"])
    
    # Clasificación por estado
    enviando = 0
    haciendo_historial = 0
    restringidos = 0
    bloqueados = 0
    disponibles = 0

    active_services_list = []

    for acc in accounts_in_disk:
        acc_id = acc["account_id"]
        db_info = db_states.get(acc_id, {})
        status_state = db_info.get("status_state", "disponible")

        is_active = any(a["account_id"] == acc_id and a["is_active"] for a in active_instances)

        if is_active:
            if status_state == "enviando":
                enviando += 1
            elif status_state == "haciendo_historial":
                haciendo_historial += 1
            else:
                disponibles += 1
            
            active_services_list.append({
                "account_id": acc_id,
                "status_state": status_state,
                "size_mb": acc.get("size_mb", 0),
                "last_modified": acc.get("last_modified", "")
            })
        else:
            if status_state == "restringido":
                restringidos += 1
            elif status_state == "bloqueado":
                bloqueados += 1
            else:
                disponibles += 1

    return jsonify({
        "status": "success",
        "counters": {
            "total_registered": total_registered,
            "disponibles": disponibles,
            "en_ejecucion": en_ejecucion,
            "enviando": enviando,
            "haciendo_historial": haciendo_historial,
            "restringidos": restringidos,
            "bloqueados": bloqueados
        },
        "active_services": active_services_list,
        "disk_metrics": disk_metrics
    })

# --- CRUD CAMPAÑAS ---

@app.route("/api/campaigns", methods=["GET", "POST"])
def manage_campaigns():
    if request.method == "POST":
        data = request.get_json() or {}
        name = data.get("name", "").strip()
        campaign_type = data.get("type", "estatica").strip()
        template_message = data.get("template_message", "").strip()

        if not name or not template_message:
            return jsonify({"status": "error", "message": "Nombre y mensaje de la campaña son obligatorios."}), 400

        # Extraer variables automáticamente entre corchetes {variable}
        variables = re.findall(r"\{(\w+)\}", template_message)
        # Eliminar duplicados manteniendo orden
        unique_vars = list(dict.fromkeys(variables))

        if campaign_type == "dinamica" and not unique_vars:
            return jsonify({"status": "error", "message": "Una campaña dinámica debe incluir al menos una variable entre corchetes, ej: {nombre}."}), 400

        campaign_id = db.create_campaign(name, campaign_type, template_message, unique_vars)
        return jsonify({"status": "success", "campaign_id": campaign_id, "variables": unique_vars, "message": "Campaña creada correctamente."})

    campaigns = db.get_campaigns()
    return jsonify({"status": "success", "campaigns": campaigns})

@app.route("/api/campaigns/<int:campaign_id>", methods=["DELETE"])
def delete_campaign_endpoint(campaign_id):
    deleted = db.delete_campaign(campaign_id)
    if deleted:
        return jsonify({"status": "success", "message": "Campaña eliminada correctamente."})
    return jsonify({"status": "error", "message": "No se pudo eliminar la campaña."}), 400

# --- CRUD PERFILES DE ENVÍO ---

@app.route("/api/send_profiles", methods=["GET", "POST"])
def manage_send_profiles():
    if request.method == "POST":
        data = request.get_json() or {}
        name = data.get("name", "").strip()
        campaign_id = data.get("campaign_id")
        delay_min = int(data.get("delay_min_sec", 15))
        delay_max = int(data.get("delay_max_sec", 45))
        msgs_session = int(data.get("messages_per_session", 10))
        msgs_interval = int(data.get("messages_per_interval", 2))
        rest_mins = int(data.get("rest_time_minutes", 30))
        acc_sending = int(data.get("accounts_for_sending", 5))
        acc_history = int(data.get("accounts_for_history", 5))
        hist_msgs = int(data.get("history_msgs_per_turn", 2))
        auto_reply_enabled = 1 if data.get("auto_reply_enabled") else 0
        auto_reply_message = str(data.get("auto_reply_message", "")).strip()

        if not name:
            return jsonify({"status": "error", "message": "El nombre del perfil es obligatorio."}), 400
        if acc_sending < 0 or acc_history < 0:
            return jsonify({"status": "error", "message": "Las tandas de cuentas no pueden ser negativas."}), 400
        if acc_sending == 0 and acc_history == 0:
            return jsonify({"status": "error", "message": "No puedes establecer ambas tandas en 0 al mismo tiempo. Al menos una debe ser mayor a 0."}), 400

        profile_id = db.create_send_profile(
            name, campaign_id, delay_min, delay_max, msgs_session, msgs_interval, rest_mins,
            acc_sending, acc_history, hist_msgs, auto_reply_enabled, auto_reply_message
        )
        return jsonify({"status": "success", "profile_id": profile_id, "message": "Perfil de envío creado correctamente."})

    profiles = db.get_send_profiles()
    return jsonify({"status": "success", "profiles": profiles})

@app.route("/api/send_profiles/<int:profile_id>", methods=["PUT", "POST"])
def update_send_profile_endpoint(profile_id):
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    campaign_id = data.get("campaign_id")
    delay_min = int(data.get("delay_min_sec", 15))
    delay_max = int(data.get("delay_max_sec", 45))
    msgs_session = int(data.get("messages_per_session", 10))
    msgs_interval = int(data.get("messages_per_interval", 2))
    rest_mins = int(data.get("rest_time_minutes", 30))
    acc_sending = int(data.get("accounts_for_sending", 5))
    acc_history = int(data.get("accounts_for_history", 5))
    hist_msgs = int(data.get("history_msgs_per_turn", 2))
    auto_reply_enabled = 1 if data.get("auto_reply_enabled") else 0
    auto_reply_message = str(data.get("auto_reply_message", "")).strip()

    if not name:
        return jsonify({"status": "error", "message": "El nombre del perfil es obligatorio."}), 400
    if acc_sending < 0 or acc_history < 0:
        return jsonify({"status": "error", "message": "Las tandas de cuentas no pueden ser negativas."}), 400
    if acc_sending == 0 and acc_history == 0:
        return jsonify({"status": "error", "message": "No puedes establecer ambas tandas en 0 al mismo tiempo. Al menos una debe ser mayor a 0."}), 400

    updated = db.update_send_profile(
        profile_id, name, campaign_id, delay_min, delay_max, msgs_session, msgs_interval, rest_mins,
        acc_sending, acc_history, hist_msgs, auto_reply_enabled, auto_reply_message
    )
    if updated:
        return jsonify({"status": "success", "message": "Perfil de envío actualizado correctamente."})
    return jsonify({"status": "error", "message": "No se pudo actualizar el perfil de envío."}), 400

@app.route("/api/send_profiles/<int:profile_id>", methods=["DELETE"])
def delete_send_profile_endpoint(profile_id):
    deleted = db.delete_send_profile(profile_id)
    if deleted:
        return jsonify({"status": "success", "message": "Perfil de envío eliminado correctamente."})
    return jsonify({"status": "error", "message": "No se pudo eliminar el perfil de envío."}), 400

# --- NOTIFICACIONES DE CLIENTES REALES ---

@app.route("/api/notifications", methods=["GET"])
def get_notifications():
    status = request.args.get("status", "pending")
    notifications = db.get_client_notifications(status=status, limit=50)
    return jsonify({"status": "success", "notifications": notifications})

@app.route("/api/notifications/<int:notif_id>/resolve", methods=["POST"])
def resolve_notification(notif_id):
    resolved = db.resolve_client_notification(notif_id)
    if resolved:
        return jsonify({"status": "success", "message": "Notificación marcada como atendida."})
    return jsonify({"status": "error", "message": "No se pudo actualizar la notificación."}), 400

@app.route("/api/notifications/resolve_all", methods=["POST"])
def resolve_all_notifications_endpoint():
    count = db.resolve_all_client_notifications()
    return jsonify({"status": "success", "message": f"{count} notificación(es) marcadas como atendidas.", "resolved_count": count})

# --- GESTIÓN DE CUENTAS EXISTENTE ---

@app.route("/api/accounts", methods=["GET"])
def get_accounts():
    accounts_in_disk = SessionManager.list_accounts()
    accounts_with_status = runner.get_status_all(accounts_in_disk)
    db_states = db.get_all_account_states()
    disk_metrics = SessionManager.get_total_disk_usage()

    # Construir lista final con TODOS los campos de DB incluidos explícitamente
    final_accounts = []
    for acc in accounts_with_status:
        acc_id = acc["account_id"]
        info = db_states.get(acc_id, {})
        final_accounts.append({
            "account_id":    acc_id,
            "file_path":     acc.get("file_path", ""),
            "size_kb":       acc.get("size_kb", 0),
            "size_mb":       acc.get("size_mb", 0),
            "last_modified": acc.get("last_modified", ""),
            "has_session":   acc.get("has_session", False),
            "is_active":     acc.get("is_active", False),
            "status":        acc.get("status", ""),
            "pending_qr":    acc.get("pending_qr"),
            # Campos de base de datos — siempre incluidos
            "status_state":  info.get("status_state", "disponible"),
            "notes":         info.get("notes", "") or "",
            "phone":         info.get("phone", "") or "",
            "first_name":    info.get("first_name", "") or "",
            "last_name":     info.get("last_name", "") or "",
        })

    return jsonify({
        "status": "success",
        "accounts": final_accounts,
        "disk_metrics": disk_metrics
    })

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

@app.route("/api/accounts/export_contacts", methods=["GET"])
def export_accounts_contacts_csv():
    accounts_in_disk = SessionManager.list_accounts()
    db_states = db.get_all_account_states()
    
    headers = [
        "First Name", "Middle Name", "Last Name", "Phonetic First Name",
        "Phonetic Middle Name", "Phonetic Last Name", "Name Prefix",
        "Name Suffix", "Nickname", "File As", "Organization Name",
        "Organization Title", "Organization Department", "Birthday",
        "Notes", "Photo", "Labels", "E-mail 1 - Label", "E-mail 1 - Value",
        "Phone 1 - Label", "Phone 1 - Value", "Phone 2 - Label",
        "Phone 2 - Value", "Website 1 - Label", "Website 1 - Value"
    ]
    
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow(headers)
    
    used_full_names = set()
    
    for acc in accounts_in_disk:
        acc_id = acc["account_id"]
        info = db_states.get(acc_id, {})
        raw_phone = info.get("phone", "") or ""
        
        # Limpiar caracteres no numéricos
        clean_phone = "".join(filter(str.isdigit, str(raw_phone)))
        
        # Si tiene prefijo 57 (Colombia) y tiene más de 10 dígitos, quitar el 57 inicial
        if clean_phone.startswith("57") and len(clean_phone) > 10:
            phone_val = clean_phone[2:]
        else:
            phone_val = clean_phone
            
        if not phone_val:
            continue
            
        # Obtener o asignar nombre estructurado persistente para el contacto
        fn = info.get("first_name", "")
        ln = info.get("last_name", "")
        if not fn or not ln:
            fn, ln = db.generate_random_contact_name(used_full_names)
            db.update_account_state(acc_id, info.get("status_state", "disponible"), raw_phone, info.get("notes", ""), first_name=fn, last_name=ln)
        else:
            used_full_names.add(f"{fn} {ln}")
                
        row = [
            fn,                 # First Name
            "",                 # Middle Name
            ln,                 # Last Name
            "",                 # Phonetic First Name
            "",                 # Phonetic Middle Name
            "",                 # Phonetic Last Name
            "",                 # Name Prefix
            "",                 # Name Suffix
            "",                 # Nickname
            "",                 # File As
            "",                 # Organization Name
            "",                 # Organization Title
            "",                 # Organization Department
            "",                 # Birthday
            "",                 # Notes
            "",                 # Photo
            "* myContacts",     # Labels
            "",                 # E-mail 1 - Label
            "",                 # E-mail 1 - Value
            "Mobile",           # Phone 1 - Label
            phone_val,          # Phone 1 - Value
            "",                 # Phone 2 - Label
            "",                 # Phone 2 - Value
            "",                 # Website 1 - Label
            ""                  # Website 1 - Value
        ]
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()
    
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=contactos_cuentas_whatsapp.csv",
            "Content-Type": "text/csv; charset=utf-8-sig"
        }
    )

@app.route("/api/accounts/status", methods=["POST"])
def update_account_status_endpoint():
    data = request.get_json() or {}
    account_id = data.get("account_id", "").strip()
    status_state = data.get("status_state", "disponible").strip()
    phone = data.get("phone", "").strip()
    notes = data.get("notes", "").strip()

    if not account_id:
        return jsonify({"status": "error", "message": "account_id es requerido."}), 400

    db.update_account_state(account_id, status_state, phone, notes, force=True)
    return jsonify({"status": "success", "message": f"Estado de '{account_id}' actualizado a '{status_state}'."})

@app.route("/api/accounts/add", methods=["POST"])
def add_account():
    data = request.get_json() or {}
    account_name = data.get("account_name", "").strip()
    
    if not account_name:
        return jsonify({"status": "error", "message": "Debes proporcionar un nombre para la cuenta."}), 400

    account_id = account_name.lower().replace(" ", "_")
    success, message = runner.start_qr_login(account_id)
    if success:
        db.update_account_state(account_id, "disponible", force=True)
        return jsonify({"status": "success", "account_id": account_id, "message": message})
    return jsonify({"status": "error", "message": message}), 400

@app.route("/api/accounts/<account_id>/open", methods=["POST"])
def open_account(account_id):
    success, message = runner.open_session(account_id)
    if success:
        return jsonify({"status": "success", "message": message})
    return jsonify({"status": "error", "message": message}), 400

@app.route("/api/accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    success, message = runner.close_instance(account_id)
    if success:
        return jsonify({"status": "success", "message": message})
    return jsonify({"status": "error", "message": message}), 400

@app.route("/api/accounts/<account_id>/delete", methods=["DELETE", "POST"])
def delete_account(account_id):
    runner.close_instance(account_id)
    deleted = SessionManager.delete_session(account_id)
    # Limpiar registro en BD independientemente de si existía la carpeta
    db.delete_account_state(account_id)
    if deleted:
        return jsonify({"status": "success", "message": f"Cuenta '{account_id}' eliminada correctamente."})
    # Si la carpeta ya no existía, igualmente consideramos éxito
    return jsonify({"status": "success", "message": f"Cuenta '{account_id}' removida del sistema."})

@app.route("/api/accounts/<account_id>/rescan", methods=["POST"])
def rescan_account(account_id):
    """Re-escanea una cuenta existente: cierra sesión actual, borra perfil Chromium y lanza nuevo QR.
    Si se conecta, el número nuevo reemplaza al anterior en BD."""
    # Cerrar instancia activa si la hay
    runner.close_instance(account_id)
    import time as _time
    _time.sleep(1)
    # Borrar datos de perfil Chromium para forzar nuevo login
    SessionManager.delete_session(account_id)
    _time.sleep(0.5)
    # Lanzar nuevo proceso QR (el número se actualizará automáticamente al conectarse)
    success, message = runner.start_qr_login(account_id)
    if success:
        db.update_account_state(account_id, "disponible", force=True)
        return jsonify({"status": "success", "account_id": account_id, "message": message})
    return jsonify({"status": "error", "message": message}), 400

@app.route("/api/accounts/<account_id>/send", methods=["POST"])
def send_message(account_id):
    data = request.get_json() or {}
    phone = data.get("phone", "").strip()
    text = data.get("message", "").strip()

    if not phone or not text:
        return jsonify({"status": "error", "message": "Teléfono y mensaje son requeridos."}), 400

    db.update_account_state(account_id, "enviando")
    success, message = runner.send_test_message(account_id, phone, text)
    db.update_account_state(account_id, "disponible")
    
    if success:
        return jsonify({"status": "success", "message": message})
    return jsonify({"status": "error", "message": message}), 400

@app.route("/api/qr_status/<account_id>", methods=["GET"])
def get_qr_status(account_id):
    status_info = runner.pending_qrs.get(account_id, {"status": "unknown", "message": "Sin información."})
    return jsonify(status_info)

from automation_engine import automation_engine

# --- AUTOMATIZACIÓN ---

@app.route("/api/automation/launch", methods=["POST"])
def launch_automation():
    """Lanza un trabajo de automatización de envío masivo."""
    data = request.get_json() or {}
    profile_id   = data.get("profile_id")
    account_ids  = data.get("account_ids", [])
    contacts_raw = data.get("contacts", "")  # texto plano: un número por línea

    if not profile_id:
        return jsonify({"status": "error", "message": "Debes seleccionar un perfil de envío."}), 400
    if not account_ids:
        return jsonify({"status": "error", "message": "Debes seleccionar al menos una cuenta."}), 400

    # Obtener el perfil para verificar su configuración de tandas
    profiles = db.get_send_profiles()
    profile = next((p for p in profiles if p["id"] == int(profile_id)), None)
    if not profile:
        return jsonify({"status": "error", "message": "Perfil de envío no encontrado."}), 404

    acc_sending_count = profile.get("accounts_for_sending", 5)

    if acc_sending_count > 0 and not contacts_raw.strip():
        return jsonify({"status": "error", "message": "La lista de contactos es obligatoria para envíos reales."}), 400

    # Parsear contactos (soporte CSV: teléfono,nombre,empresa... o solo teléfono)
    contacts = []
    if contacts_raw.strip():
        for line in contacts_raw.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            phone = parts[0]
            if phone:
                contacts.append({"phone": phone, "cols": parts[1:] if len(parts) > 1 else []})

    if acc_sending_count > 0 and not contacts:
        return jsonify({"status": "error", "message": "No se encontraron números válidos en la lista de contactos."}), 400

    campaign_id = profile.get("campaign_id")

    # Crear el job en BD
    job_id = db.create_automation_job(int(profile_id), campaign_id, account_ids, contacts)

    # Iniciar motor de automatización en segundo plano con rotación y reposo
    automation_engine.start_job(job_id)

    msg = f"✅ Automatización de Solo Historial iniciada con {len(account_ids)} cuenta(s)." if acc_sending_count == 0 else f"✅ Automatización lanzada: {len(contacts)} contactos con {len(account_ids)} cuenta(s)."

    return jsonify({
        "status": "success",
        "job_id": job_id,
        "message": msg,
        "total_contacts": len(contacts),
        "profile_name": profile["name"],
    })

@app.route("/api/automation/jobs", methods=["GET"])
def get_automation_jobs():
    jobs = db.get_automation_jobs(limit=30)
    return jsonify({"status": "success", "jobs": jobs})

@app.route("/api/automation/jobs/<int:job_id>", methods=["GET"])
def get_automation_job(job_id):
    job = db.get_automation_job(job_id)
    if not job:
        return jsonify({"status": "error", "message": "Job no encontrado."}), 404
    return jsonify({"status": "success", "job": job})

@app.route("/api/automation/jobs/<int:job_id>/status", methods=["POST"])
def update_job_status(job_id):
    data = request.get_json() or {}
    new_status = data.get("status", "paused")
    
    if new_status == "running":
        db.update_automation_job_status(job_id, "running")
        automation_engine.start_job(job_id)
    elif new_status in ("paused", "completed", "error"):
        automation_engine.stop_job(job_id)
        db.update_automation_job_status(job_id, new_status)
        job = db.get_automation_job(job_id)
        if job:
            for acc_id in job.get("account_ids", []):
                db.update_account_state(acc_id, "disponible")

    return jsonify({"status": "success", "message": f"Job #{job_id} actualizado a '{new_status}'."})

@app.route("/api/automation/jobs/<int:job_id>", methods=["DELETE"])
def delete_automation_job(job_id):
    deleted = db.delete_automation_job(job_id)
    if deleted:
        return jsonify({"status": "success", "message": f"Job #{job_id} eliminado."})
    return jsonify({"status": "error", "message": "No se pudo eliminar el job."}), 400

# ── SISTEMA DE ACTUALIZACIONES GIT DE 1-CLICK ───────────────────────────
def ensure_git_repo_app():
    root_dir = Path(__file__).parent.resolve()
    git_dir = root_dir / ".git"
    if git_dir.exists():
        return True
    try:
        res = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return False
        subprocess.run(["git", "init"], cwd=str(root_dir), capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/munozjeff/Whatsapp-automatizacion-5.0.git"], cwd=str(root_dir), capture_output=True)
        subprocess.run(["git", "fetch", "origin"], cwd=str(root_dir), capture_output=True)
        subprocess.run(["git", "checkout", "-B", "release", "origin/release"], cwd=str(root_dir), capture_output=True)
        return git_dir.exists()
    except Exception:
        return False

@app.route("/api/updates/check", methods=["GET"])
def check_for_updates():
    root_dir = Path(__file__).parent.resolve()
    if not (root_dir / ".git").exists():
        ensure_git_repo_app()

    git_dir = root_dir / ".git"
    if not git_dir.exists():
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.github.com/repos/munozjeff/Whatsapp-automatizacion-5.0/commits/release",
                headers={"User-Agent": "WhatsAppAutoPlatform"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                import json
                data = json.loads(response.read().decode('utf-8'))
                remote_sha = data.get("sha", "")[:7]
                commit_msg = data.get("commit", {}).get("message", "").split("\n")[0]
                return jsonify({
                    "status": "success",
                    "update_available": True,
                    "is_git_repo": False,
                    "branch": "release",
                    "remote_commit": remote_sha,
                    "behind_count": 1,
                    "commit_messages": [f"Actualización remota disponible: {commit_msg}"],
                    "message": "Actualización disponible en GitHub."
                })
        except Exception:
            return jsonify({
                "status": "success",
                "update_available": False,
                "is_git_repo": False,
                "message": "Instalación local. Para habilitar actualizaciones en 1-click, instala Git CLI en tu equipo."
            })

    try:
        subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/munozjeff/Whatsapp-automatizacion-5.0.git"], cwd=str(root_dir), capture_output=True)
        subprocess.run(["git", "fetch", "origin"], cwd=str(root_dir), capture_output=True, text=True, timeout=10)
        
        current_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL).strip() or "release"
        local_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL).strip()
        
        try:
            remote_hash = subprocess.check_output(["git", "rev-parse", "--short", f"origin/{current_branch}"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            remote_hash = subprocess.check_output(["git", "rev-parse", "--short", "origin/release"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL).strip()

        if local_hash != remote_hash:
            try:
                commit_logs = subprocess.check_output(
                    ["git", "log", f"HEAD..origin/{current_branch}", "--oneline", "-n", "10"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL
                ).strip().split("\n")
            except Exception:
                commit_logs = [f"Actualización remota disponible: {remote_hash}"]

            return jsonify({
                "status": "success",
                "update_available": True,
                "is_git_repo": True,
                "branch": current_branch,
                "local_commit": local_hash,
                "remote_commit": remote_hash,
                "behind_count": len(commit_logs),
                "commit_messages": [msg.strip() for msg in commit_logs if msg.strip()]
            })

        return jsonify({
            "status": "success",
            "update_available": False,
            "is_git_repo": True,
            "branch": current_branch,
            "local_commit": local_hash,
            "remote_commit": remote_hash,
            "behind_count": 0,
            "commit_messages": []
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "update_available": False,
            "is_git_repo": True,
            "message": f"Error al verificar actualizaciones: {str(e)}"
        }), 200


@app.route("/api/updates/apply", methods=["POST"])
def apply_updates():
    root_dir = Path(__file__).parent.resolve()
    if not (root_dir / ".git").exists():
        ensure_git_repo_app()

    if not (root_dir / ".git").exists():
        return jsonify({
            "status": "error",
            "message": "No se pudo inicializar Git. Por favor instala Git en tu equipo o clona el repositorio desde GitHub para usar actualizaciones de 1-click."
        }), 400

    try:
        subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/munozjeff/Whatsapp-automatizacion-5.0.git"], cwd=str(root_dir), capture_output=True)
        subprocess.run(["git", "fetch", "origin"], cwd=str(root_dir), capture_output=True, timeout=15)

        try:
            current_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(root_dir), text=True).strip() or "release"
        except Exception:
            current_branch = "release"

        res = subprocess.run(["git", "reset", "--hard", f"origin/{current_branch}"], cwd=str(root_dir), capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            res = subprocess.run(["git", "reset", "--hard", "origin/release"], cwd=str(root_dir), capture_output=True, text=True, timeout=30)

        frontend_dir = root_dir / "frontend"
        build_output = ""
        if frontend_dir.exists():
            npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
            build_res = subprocess.run(
                [npm_cmd, "run", "build"], cwd=str(frontend_dir), capture_output=True, text=True, timeout=60
            )
            build_output = build_res.stdout or build_res.stderr

        return jsonify({
            "status": "success",
            "message": f"¡Sistema actualizado correctamente en 1-click!",
            "branch": current_branch,
            "git_output": res.stdout,
            "build_output": build_output
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Excepción durante la actualización: {str(e)}"
        }), 500

def check_python_dependencies_app():
    root_dir = Path(__file__).parent.resolve()
    req_file = root_dir / "requirements.txt"
    if req_file.exists():
        try:
            import flask
            import flask_cors
            import playwright
        except ImportError:
            print("  ⏳ Instalando dependencias de Python desde requirements.txt...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)], check=True)

    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, check=False)
    except Exception:
        pass

def check_git_updates_startup_app():
    root_dir = Path(__file__).parent.resolve()
    print("\n[4/5] Verificando si existen actualizaciones en el repositorio remoto Git...")
    git_dir = root_dir / ".git"
    if not git_dir.exists():
        if not ensure_git_repo_app():
            print("  ℹ️ El sistema se está ejecutando en modo ejecutable ZIP local (sin Git CLI instalado).")
            return

    try:
        subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/munozjeff/Whatsapp-automatizacion-5.0.git"], cwd=str(root_dir), capture_output=True)
        subprocess.run(["git", "fetch", "origin"], cwd=str(root_dir), capture_output=True, text=True, timeout=12)
        
        current_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL).strip() or "release"
        local_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL).strip()
        
        try:
            remote_hash = subprocess.check_output(["git", "rev-parse", "--short", f"origin/{current_branch}"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            remote_hash = subprocess.check_output(["git", "rev-parse", "--short", "origin/release"], cwd=str(root_dir), text=True, stderr=subprocess.DEVNULL).strip()

        if local_hash != remote_hash:
            print(f"  🔔 ¡NUEVA ACTUALIZACIÓN DISPONIBLE EN GITHUB [{current_branch}]! ({local_hash} -> {remote_hash})")
            print("  💡 Podrás descargarla e instalarla con 1 solo click desde la interfaz web.")
        else:
            print(f"  ✅ El sistema está completamente actualizado en la rama [{current_branch}] ({local_hash}).")
    except Exception as e:
        print(f"  ⚠️ No se pudo verificar la actualización remota de Git.")

if __name__ == "__main__":
    print("=" * 65)
    print("🚀 WhatsApp Multi-Account Platform v5.0")
    print("   Orquestador de Automatización & Gestión de Cuentas")
    print("=" * 65)
    
    check_python_dependencies_app()
    check_git_updates_startup_app()

    print("\n🌐 Iniciando el servidor Backend Flask en http://127.0.0.1:5000...")
    print("  La interfaz web se abrirá automáticamente en tu navegador.\n")

    def open_browser():
        import time, webbrowser
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:5000")

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

