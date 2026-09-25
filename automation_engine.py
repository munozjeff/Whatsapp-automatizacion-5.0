import time
import json
import random
import threading
import database as db
from whatsapp_runner import runner
from anti_detection import human_delay, interruptible_sleep

class AutomationEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self.active_jobs: dict[int, threading.Thread] = {}   # job_id -> main Thread
        self.history_jobs: dict[int, threading.Thread] = {}  # job_id -> history Thread
        self.job_stop_flags: dict[int, bool] = {}            # job_id -> bool
        self.job_account_ids: dict[int, list] = {}           # job_id -> [account_ids]

    def start_job(self, job_id: int):
        """Inicia el hilo de ejecución principal para un job de automatización."""
        with self._lock:
            if job_id in self.active_jobs and self.active_jobs[job_id].is_alive():
                # Esperar hasta 2.5s por si el hilo anterior aún está terminando de pausarse
                wait_t = 0.0
                while self.active_jobs[job_id].is_alive() and wait_t < 2.5:
                    time.sleep(0.2)
                    wait_t += 0.2
                if self.active_jobs[job_id].is_alive():
                    return False, "El trabajo aún se está deteniendo. Intente de nuevo en un segundo."
            self.job_stop_flags[job_id] = False

        thread = threading.Thread(
            target=self._run_job_worker,
            args=(job_id,),
            daemon=True
        )
        with self._lock:
            self.active_jobs[job_id] = thread
        thread.start()
        return True, f"Trabajo #{job_id} iniciado en segundo plano."

    def stop_job(self, job_id: int):
        """Solicita la detención e inmediatamente libera los recursos del job."""
        return self.terminate_job(job_id)

    def terminate_job(self, job_id: int):
        """Termina INMEDIATAMENTE un job: pone el flag de parada, cierra todos los
        navegadores del job y marca el estado final en BD. Usa SessionManager.kill_profile_processes
        como medida de emergencia para matar los procesos Chrome si aún siguen corriendo.
        """
        from session_manager import SessionManager
        # 1. Activar flag de parada para que los loops internos salgan
        with self._lock:
            self.job_stop_flags[job_id] = True
            acc_ids = list(self.job_account_ids.get(job_id, []))

        # 2. Cerrar TODOS los navegadores asociados al job de forma forzada
        print(f"[AutomationEngine] \ud83d\uded1 TERMINATE Job #{job_id}: cerrando {len(acc_ids)} navegador(es)...")
        for acc_id in acc_ids:
            try:
                runner.close_instance(acc_id)
            except Exception as e:
                print(f"[AutomationEngine] Nota al cerrar '{acc_id}' en terminate: {e}")

        # 3. Método nuclear: matar procesos Chrome pendientes por perfil
        #    Esto garantiza que ningún navegador siga corriendo aunque Playwright no lo haya cerrado
        import time as _t
        _t.sleep(0.5)  # Dar tiempo a que Playwright intente cerrar primero
        for acc_id in acc_ids:
            try:
                if runner.active_instances.get(acc_id):   # si aún sigue abierto
                    print(f"[AutomationEngine] \ud83d\udc80 Forzando kill de procesos Chrome para '{acc_id}'...")
                SessionManager.kill_profile_processes(acc_id)
            except Exception as e:
                print(f"[AutomationEngine] Nota en kill_profile_processes para '{acc_id}': {e}")

        # 4. Actualizar BD: marcar cuentas como disponibles
        try:
            for acc_id in acc_ids:
                db_st = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
                if db_st not in ("bloqueado", "restringido"):
                    db.update_account_state(acc_id, "disponible", notes="Detenido por usuario")
        except Exception as e:
            print(f"[AutomationEngine] Error actualizando cuentas al terminar job #{job_id}: {e}")

        # 5. Marcar job como detenido en BD
        try:
            db.update_automation_job_status(
                job_id, "paused",
                notes="Detenido forzosamente por el usuario."
            )
        except Exception as e:
            print(f"[AutomationEngine] Error actualizando estado del job #{job_id}: {e}")

        print(f"[AutomationEngine] \ud83d\uded1 Job #{job_id} terminado forzosamente.")
        return True, f"Job #{job_id} detenido y recursos liberados."

    def _format_message(self, template: str, contact: dict, variables: list) -> str:
        """Formatea la plantilla reemplazando variables dinámicas."""
        cols = contact.get("cols", [])
        msg = template

        for idx, val in enumerate(cols):
            msg = msg.replace(f"{{{idx}}}", str(val))

        for idx, var_name in enumerate(variables):
            val = cols[idx] if idx < len(cols) else ""
            msg = msg.replace(f"{{{var_name}}}", str(val))

        if cols:
            msg = msg.replace("{nombre}", cols[0])
            msg = msg.replace("{col1}", cols[0])
        if len(cols) > 1:
            msg = msg.replace("{col2}", cols[1])
        if len(cols) > 2:
            msg = msg.replace("{col3}", cols[2])

        return msg

    def _run_job_worker(self, job_id: int):
        """Hilo principal que orquesta la Tanda de Envío Real y la Tanda de Hacer Historial.
        Divide el pool de cuentas en dos sub-pools exclusivos:
          - sending_pool: primeras acc_sending_count cuentas (uso exclusivo de envío real)
          - history_pool: siguientes acc_history_count cuentas (uso exclusivo de historial)
        Ambos pools operan en paralelo sin interferirse.
        """
        print(f"[AutomationEngine] Iniciando trabajo multitarea #{job_id}...")

        job = db.get_automation_job(job_id)
        if not job:
            print(f"[AutomationEngine] Error: Job #{job_id} no existe en la BD.")
            return

        profile_id = job.get("profile_id")
        campaign_id = job.get("campaign_id")
        account_ids = job.get("account_ids", [])
        contacts = job.get("contacts", [])
        sent_count = job.get("sent_count", 0)
        error_count = job.get("error_count", 0)

        if not account_ids:
            db.update_automation_job_status(job_id, "error", notes="Sin cuentas válidas.")
            return

        # Cargar perfil
        profiles = db.get_send_profiles()
        profile = next((p for p in profiles if p["id"] == profile_id), None)
        if not profile:
            profile = {
                "delay_min_sec": 15,
                "delay_max_sec": 45,
                "messages_per_session": 50,
                "messages_per_interval": 2,
                "rest_time_minutes": 30,
                "accounts_for_sending": 5,
                "accounts_for_history": 5,
                "history_msgs_per_turn": 2
            }

        acc_sending_count = profile.get("accounts_for_sending", 5)
        acc_history_count = profile.get("accounts_for_history", 5)

        if acc_sending_count > 0 and not contacts:
            db.update_automation_job_status(job_id, "error", notes="Sin contactos para Envío Real.")
            return

        # ── Dividir el pool en dos sub-pools exclusivos ──────────────────────────
        # Las primeras acc_sending_count cuentas van a envío real.
        # Las siguientes acc_history_count cuentas van a historial.
        # Si hay menos cuentas que las solicitadas, se usan todas las disponibles para ese rol.
        sending_pool = account_ids[:acc_sending_count] if acc_sending_count > 0 else []
        history_pool = account_ids[acc_sending_count:acc_sending_count + acc_history_count] if acc_history_count > 0 else []

        # Si no hay cuentas suficientes para historial, usar las que queden tras envío
        if not history_pool and acc_history_count > 0 and len(account_ids) > len(sending_pool):
            history_pool = account_ids[len(sending_pool):]

        print(f"[AutomationEngine] 📄 Pool Envío Real: {sending_pool}")
        print(f"[AutomationEngine] 📄 Pool Historial: {history_pool}")

        # Registrar TODAS las cuentas del job para terminate_job()
        with self._lock:
            self.job_account_ids[job_id] = list(account_ids)

        # Resetear estados previos en BD
        all_initial_states = db.get_all_account_states()
        for acc in account_ids:
            inst_st = runner.active_instances.get(acc, {}).get("status", "")
            db_st = all_initial_states.get(acc, {}).get("status_state", "")
            if inst_st != "BLOQUEADA" and db_st not in ("bloqueado", "restringido"):
                db.update_account_state(acc, "disponible", notes=f"Preparada para Job #{job_id}")

        # 1. Lanzar hilo secundario de Hacer Historial si hay cuentas en history_pool
        history_thread = None
        if history_pool:
            print(f"[AutomationEngine] 💬 Tanda de Hacer Historial ACTIVA para Job #{job_id} "
                  f"({acc_history_count} cuenta(s) por tanda) — pool: {history_pool}.")
            history_thread = threading.Thread(
                target=self._run_history_worker,
                args=(job_id, history_pool, profile),
                daemon=True
            )
            with self._lock:
                self.history_jobs[job_id] = history_thread
            history_thread.start()
        else:
            print(f"[AutomationEngine] ℹ️ Tanda de Historial DESACTIVADA para Job #{job_id} (0 cuentas configuradas o sin pool).")

        # 2. Ejecutar worker principal de Envío Real si hay cuentas en sending_pool
        if sending_pool:
            print(f"[AutomationEngine] 📤 Tanda de Envío Real ACTIVA para Job #{job_id} "
                  f"({acc_sending_count} cuenta(s) por tanda) — pool: {sending_pool}.")
            self._run_sending_worker(job_id, sending_pool, profile, campaign_id, contacts, sent_count, error_count)
        else:
            print(f"[AutomationEngine] 💬 Job #{job_id} configurado como SOLO HISTORIAL "
                  f"(0 cuentas de envío). Manteniendo servicio en segundo plano...")
            try:
                while not self.job_stop_flags.get(job_id, False):
                    curr_job = db.get_automation_job(job_id)
                    if not curr_job or curr_job.get("status") in ("paused", "completed", "error"):
                        break
                    time.sleep(5)
            except Exception:
                pass
            finally:
                db.update_automation_job_status(job_id, "completed", notes="Trabajo de Solo Historial finalizado.")

    def _check_and_skip_blocked(self, account_ids: list, blocked_ids: set, skip_sending: bool = False) -> list:
        """Retorna la lista de cuentas no bloqueadas consultando BD e instancias en memoria."""
        all_states = db.get_all_account_states()
        valid = []
        for acc in account_ids:
            if acc in blocked_ids:
                continue

            db_st = all_states.get(acc, {}).get("status_state", "")

            # Si se solicita omitir cuentas ocupadas en envío real (para no interferir en historial)
            if skip_sending and db_st == "enviando":
                continue

            # 1. Estado en Base de Datos
            if db_st in ("bloqueado", "restringido"):
                blocked_ids.add(acc)
                print(f"[AutomationEngine] 🚫 Cuenta '{acc}' ignorada en piscina (BD: '{db_st}').")
                continue

            # 2. Estado en Instancia activa de Playwright
            inst_st = runner.active_instances.get(acc, {}).get("status", "")
            if inst_st == "BLOQUEADA":
                blocked_ids.add(acc)
                print(f"[AutomationEngine] 🚫 Cuenta '{acc}' ignorada en piscina (Instancia viva: 'BLOQUEADA').")
                continue

            valid.append(acc)
        return valid

    # ──────────────────────────────────────────────────────────────────────────
    # WORKER DE ENVÍO REAL
    # ──────────────────────────────────────────────────────────────────────────

    def _run_sending_worker(self, job_id: int, account_ids: list, profile: dict,
                            campaign_id: int, contacts: list, sent_count: int, error_count: int):
        """Worker encargado del envío masivo de la campaña a clientes (Envío Real).
        Lanza acc_sending_count cuentas en PARALELO por tanda (igual que el worker de historial),
        de modo que si hay 2 cuentas de envío se abren 2 navegadores simultáneos.
        """
        delay_min = profile.get("delay_min_sec", 15)
        delay_max = profile.get("delay_max_sec", 45)
        msgs_session = profile.get("messages_per_session", 50)
        msgs_interval = profile.get("messages_per_interval", 2)
        rest_time_minutes = profile.get("rest_time_minutes", 30)
        rest_time_seconds = rest_time_minutes * 60
        acc_sending_count = profile.get("accounts_for_sending", 5)
        auto_reply_enabled = bool(profile.get("auto_reply_enabled", 0))
        auto_reply_message = profile.get("auto_reply_message", "")

        campaigns = db.get_campaigns()
        campaign = next((c for c in campaigns if c["id"] == campaign_id), None)
        template_msg = campaign["template_message"] if campaign else "Hola {nombre}, este es un mensaje automático."
        campaign_vars = campaign.get("variables", []) if campaign else []

        last_sent_timestamp: dict[str, float] = {}
        sent_in_session: dict[str, int] = {acc: 0 for acc in account_ids}
        consecutive_fails_per_acc: dict[str, int] = {acc: 0 for acc in account_ids}
        blocked_accounts: set = set()
        sent_lock = threading.Lock()   # Protege contact_idx, sent_count y error_count compartidos

        contact_idx_holder = [sent_count]    # Usar lista para permitir escritura desde hilos
        sent_count_holder = [sent_count]
        error_count_holder = [error_count]
        total_contacts = len(contacts)
        tanda_index = 0

        try:
            while True:
                # ── Verificar bandera de parada al inicio de cada ciclo ──────────
                if self.job_stop_flags.get(job_id, False):
                    break

                with sent_lock:
                    current_idx = contact_idx_holder[0]
                if current_idx >= total_contacts:
                    break

                curr_job = db.get_automation_job(job_id)
                if not curr_job or curr_job.get("status") in ("paused", "pausing", "completed", "error"):
                    break

                # Filtrar piscina disponible
                available_accounts = self._check_and_skip_blocked(account_ids, blocked_accounts, skip_sending=False)
                if not available_accounts:
                    print(f"[AutomationEngine] \ud83d\udeab Todas las cuentas del job #{job_id} están BLOQUEADAS/RESTRINGIDAS. Finalizando.")
                    db.update_automation_job_status(
                        job_id, "error",
                        sent=sent_count_holder[0],
                        errors=error_count_holder[0],
                        notes=f"Todas las cuentas bloqueadas. Enviados: {sent_count_holder[0]}, Errores: {error_count_holder[0]}."
                    )
                    return

                # ── Seleccionar tanda ────────────────────────────────────────────
                tanda_size = min(acc_sending_count, len(available_accounts))
                start_offset = (tanda_index * tanda_size) % len(available_accounts)
                tanda_accounts = [
                    available_accounts[(start_offset + i) % len(available_accounts)]
                    for i in range(tanda_size)
                ]
                tanda_index += 1

                print(f"[AutomationEngine] \ud83d\udce4 Tanda #{tanda_index} Envío Real — "
                      f"{len(tanda_accounts)} cuenta(s) en PARALELO: {tanda_accounts}")

                # ── Lanzar la tanda en hilos paralelos ──────────────────────────
                send_threads = []
                for acc_id in tanda_accounts:
                    t = threading.Thread(
                        target=self._process_single_sending_account,
                        args=(
                            job_id, acc_id, profile,
                            campaign_id, contacts, total_contacts,
                            template_msg, campaign_vars,
                            sent_in_session, consecutive_fails_per_acc,
                            last_sent_timestamp, blocked_accounts,
                            sent_count_holder, error_count_holder,
                            contact_idx_holder, sent_lock,
                            rest_time_seconds, delay_min, delay_max,
                            msgs_session, msgs_interval,
                            auto_reply_enabled, auto_reply_message
                        ),
                        daemon=True
                    )
                    send_threads.append(t)
                    t.start()

                # Esperar a que todos los hilos de la tanda terminen (sale si hay bandera de parada)
                for t in send_threads:
                    while t.is_alive():
                        t.join(timeout=0.2)
                        if self.job_stop_flags.get(job_id, False):
                            break

                if self.job_stop_flags.get(job_id, False):
                    break

            # ── Fin del bucle principal ──────────────────────────────────────────
            with sent_lock:
                final_sent = sent_count_holder[0]
                final_errors = error_count_holder[0]
                final_idx = contact_idx_holder[0]

            if final_idx >= total_contacts:
                final_status = "error" if final_sent == 0 and final_errors > 0 else "completed"
                final_notes = f"Concluido con {final_sent} enviado(s) y {final_errors} error(es)."
                db.update_automation_job_status(
                    job_id, final_status,
                    sent=final_sent,
                    errors=final_errors,
                    progress=100,
                    notes=final_notes
                )
            elif self.job_stop_flags.get(job_id, False):
                print(f"[AutomationEngine] \u23f8 Registrando estado 'paused' en BD para Job #{job_id}.")
                db.update_automation_job_status(
                    job_id, "paused",
                    sent=final_sent,
                    errors=final_errors,
                    notes="Trabajo pausado por el usuario."
                )

        except Exception as e:
            print(f"[AutomationEngine] Error en worker de envío Job #{job_id}: {e}")

        finally:
            all_final_states = db.get_all_account_states()
            for acc in account_ids:
                st = all_final_states.get(acc, {}).get("status_state", "")
                if st not in ("bloqueado", "restringido") and acc not in blocked_accounts:
                    db.update_account_state(acc, "disponible", notes="Disponible")

    def _process_single_sending_account(
            self, job_id: int, acc_id: str, profile: dict,
            campaign_id: int, contacts: list, total_contacts: int,
            template_msg: str, campaign_vars: list,
            sent_in_session: dict, consecutive_fails_per_acc: dict,
            last_sent_timestamp: dict, blocked_accounts: set,
            sent_count_holder: list, error_count_holder: list,
            contact_idx_holder: list, sent_lock: threading.Lock,
            rest_time_seconds: float, delay_min: int, delay_max: int,
            msgs_session: int, msgs_interval: int,
            auto_reply_enabled: bool, auto_reply_message: str):
        """
        Procesa el envío de una cuenta individual en su propio hilo (dentro de una tanda).
        Comparte contact_idx_holder con los otros hilos de la misma tanda para evitar duplicados.
        La bandera job_stop_flags se revisa al inicio de cada iteración.
        """
        # ── Verificar bandera al inicio ──────────────────────────────────────────
        if self.job_stop_flags.get(job_id, False):
            return

        auto_reply_enabled = bool(profile.get("auto_reply_enabled", 0))
        auto_reply_message = profile.get("auto_reply_message", "")

        # Verificar reposo de cuenta
        last_time = last_sent_timestamp.get(acc_id, 0)
        if last_time > 0:
            elapsed = time.time() - last_time
            if elapsed < rest_time_seconds:
                wait_remaining = rest_time_seconds - elapsed
                min_left = int(wait_remaining // 60)
                sec_left = int(wait_remaining % 60)
                print(f"[AutomationEngine] \u23f3 Reposo '{acc_id}': faltan {min_left}m {sec_left}s...")
                if not interruptible_sleep(wait_remaining, stop_checker=lambda: self.job_stop_flags.get(job_id, False)):
                    return

        if self.job_stop_flags.get(job_id, False):
            return

        # Verificar / Conectar cuenta
        current_status = runner.active_instances.get(acc_id, {}).get("status", "")
        db_st_check = db.get_all_account_states().get(acc_id, {}).get("status_state", "")

        if db_st_check in ("bloqueado", "restringido") or current_status == "BLOQUEADA":
            print(f"[AutomationEngine] \ud83d\udeab '{acc_id}' BLOQUEADA/RESTRINGIDA. Saltando...")
            runner.close_instance(acc_id)
            blocked_accounts.add(acc_id)
            return

        db.update_account_state(acc_id, "enviando", notes=f"Envío Real Job #{job_id}")

        if acc_id not in runner.active_instances or current_status != "CONECTADA":
            print(f"[AutomationEngine] \ud83d\udd04 Abriendo navegador para cuenta '{acc_id}'...")
            runner.open_session(acc_id)
            wait_conn = 0
            while wait_conn < 45:
                if self.job_stop_flags.get(job_id, False):   # ← bandera en cada tick
                    runner.close_instance(acc_id)
                    db.update_account_state(acc_id, "disponible", notes="Detenido")
                    return
                inst_status = runner.active_instances.get(acc_id, {}).get("status", "")
                db_st_wait = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
                if inst_status == "CONECTADA":
                    break
                if inst_status == "BLOQUEADA" or db_st_wait in ("bloqueado", "restringido"):
                    print(f"[AutomationEngine] \ud83d\udeab '{acc_id}' bloqueada al conectar. Buscando reemplazo...")
                    runner.close_instance(acc_id)
                    blocked_accounts.add(acc_id)
                    db.update_account_state(acc_id, "disponible", notes="Disponible")
                    return
                time.sleep(2)
                wait_conn += 2

        if self.job_stop_flags.get(job_id, False):
            runner.close_instance(acc_id)
            db.update_account_state(acc_id, "disponible", notes="Detenido")
            return

        final_status = runner.active_instances.get(acc_id, {}).get("status", "")
        db_st_final = db.get_all_account_states().get(acc_id, {}).get("status_state", "")

        if acc_id in blocked_accounts or final_status == "BLOQUEADA" or db_st_final in ("bloqueado", "restringido"):
            if acc_id not in blocked_accounts:
                blocked_accounts.add(acc_id)
                runner.close_instance(acc_id)
            print(f"[AutomationEngine] \u23ed\ufe0f Saltando cuenta bloqueada '{acc_id}'.")
            return

        if acc_id not in runner.active_instances or final_status != "CONECTADA":
            print(f"[AutomationEngine] \u26a0\ufe0f '{acc_id}' no logró conectarse. Saltando...")
            db.update_account_state(acc_id, "disponible", notes="No conectó a tiempo")
            return

        # Escanear chats no leídos
        try:
            all_states = db.get_all_account_states()
            peer_phones_set = {info["phone"] for info in all_states.values() if info.get("phone")}
            res_scan = runner.check_and_process_unread_chats(
                acc_id, peer_phones_set,
                auto_reply_enabled=auto_reply_enabled,
                auto_reply_message=auto_reply_message
            )
            if res_scan.get("notified_clients", 0) > 0:
                print(f"[AutomationEngine] \ud83d\udd14 {res_scan['notified_clients']} cliente(s) notificados en '{acc_id}'")
        except Exception as scan_err:
            print(f"[AutomationEngine] Nota en escaneo: {scan_err}")

        # Ráfaga de mensajes
        burst_limit = msgs_interval  # cada cuenta envía msgs_interval mensajes
        for b in range(burst_limit):
            # ── Bandera al inicio de cada mensaje ────────────────────────────────
            if self.job_stop_flags.get(job_id, False):
                break

            # Tomar el próximo contacto de forma atómica
            with sent_lock:
                if contact_idx_holder[0] >= total_contacts:
                    break
                contact_idx = contact_idx_holder[0]
                contact_idx_holder[0] += 1   # Reservar este índice

            contact = contacts[contact_idx]
            phone = contact.get("phone", "")
            text = self._format_message(template_msg, contact, campaign_vars)
            success, msg_response = runner.send_test_message(acc_id, phone, text)

            if success:
                with sent_lock:
                    sent_count_holder[0] += 1
                sent_in_session[acc_id] = sent_in_session.get(acc_id, 0) + 1
                consecutive_fails_per_acc[acc_id] = 0
            else:
                post_status = runner.active_instances.get(acc_id, {}).get("status", "")
                db_st_post = db.get_all_account_states().get(acc_id, {}).get("status_state", "")

                if post_status == "BLOQUEADA" or db_st_post in ("bloqueado", "restringido"):
                    print(f"[AutomationEngine] \ud83d\udeab BLOQUEO confirmado en '{acc_id}'. Reemplazando cuenta...")
                    runner.close_instance(acc_id)
                    blocked_accounts.add(acc_id)
                    if db_st_post not in ("bloqueado", "restringido"):
                        db.update_account_state(acc_id, "bloqueado", notes="Bloqueado durante envío real.", force=True)
                    with sent_lock:
                        error_count_holder[0] += 1
                    consecutive_fails_per_acc[acc_id] = 0
                    break
                else:
                    recovered = False
                    max_retries = 3
                    for attempt in range(1, max_retries + 1):
                        if self.job_stop_flags.get(job_id, False):   # ← bandera en reintento
                            break
                        print(f"[AutomationEngine] \u26a0\ufe0f Fallo temporal en '{acc_id}' ({msg_response}). Reintento ({attempt}/{max_retries})...")
                        runner.close_instance(acc_id)
                        time.sleep(2)
                        if self.job_stop_flags.get(job_id, False):
                            break
                        runner.open_session(acc_id)

                        wait_conn = 0
                        reconnected = False
                        while wait_conn < 45:
                            if self.job_stop_flags.get(job_id, False):   # ← bandera en wait
                                break
                            inst_st_rec = runner.active_instances.get(acc_id, {}).get("status", "")
                            db_st_rec = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
                            if inst_st_rec == "CONECTADA":
                                reconnected = True
                                break
                            if inst_st_rec == "BLOQUEADA" or db_st_rec in ("bloqueado", "restringido"):
                                print(f"[AutomationEngine] \ud83d\udeab BLOQUEO al recuperar '{acc_id}'.")
                                runner.close_instance(acc_id)
                                blocked_accounts.add(acc_id)
                                if db_st_rec not in ("bloqueado", "restringido"):
                                    db.update_account_state(acc_id, "bloqueado", notes="Bloqueado al intentar recuperar sesión en envío real.", force=True)
                                break
                            time.sleep(2)
                            wait_conn += 2

                        if acc_id in blocked_accounts or self.job_stop_flags.get(job_id, False):
                            break

                        if not reconnected:
                            print(f"[AutomationEngine] \u274c '{acc_id}' no logró reconectarse en reintento ({attempt}/{max_retries}).")
                            continue

                        print(f"[AutomationEngine] \ud83d\udd04 REINTENTO ({attempt}/{max_retries}) de envío en '{acc_id}' → {phone}...")
                        success_retry, msg_retry = runner.send_test_message(acc_id, phone, text)
                        if success_retry:
                            with sent_lock:
                                sent_count_holder[0] += 1
                            sent_in_session[acc_id] = sent_in_session.get(acc_id, 0) + 1
                            consecutive_fails_per_acc[acc_id] = 0
                            print(f"[AutomationEngine] \u2705 Recuperación exitosa para '{acc_id}'. Mensaje enviado en reintento {attempt}/{max_retries}.")
                            recovered = True
                            break

                        post_retry = runner.active_instances.get(acc_id, {}).get("status", "")
                        db_st_retry = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
                        if post_retry == "BLOQUEADA" or db_st_retry in ("bloqueado", "restringido"):
                            print(f"[AutomationEngine] \ud83d\udeab BLOQUEO detectado durante reintento en '{acc_id}'.")
                            runner.close_instance(acc_id)
                            blocked_accounts.add(acc_id)
                            if db_st_retry not in ("bloqueado", "restringido"):
                                db.update_account_state(acc_id, "bloqueado", notes="Bloqueado durante reintento en envío real.", force=True)
                            break

                    if acc_id in blocked_accounts:
                        with sent_lock:
                            error_count_holder[0] += 1
                        consecutive_fails_per_acc[acc_id] = 0
                        break

                    if not recovered:
                        with sent_lock:
                            error_count_holder[0] += 1
                        consecutive_fails_per_acc[acc_id] = consecutive_fails_per_acc.get(acc_id, 0) + 1

                        if consecutive_fails_per_acc[acc_id] < 2:
                            print(f"[AutomationEngine] \u26a0\ufe0f Fallo en número {phone} tras 3 reintentos en '{acc_id}'. "
                                  f"Probando con el número SIGUIENTE...")
                            continue
                        else:
                            print(f"[AutomationEngine] \ud83d\udeab Fallo consecutivo en 2 números distintos en '{acc_id}'. "
                                  f"Aplicando acción de bloqueo/reemplazo...")
                            runner.close_instance(acc_id)
                            blocked_accounts.add(acc_id)
                            db.update_account_state(acc_id, "bloqueado", notes=f"Bloqueado por fallo persistente.", force=True)
                            consecutive_fails_per_acc[acc_id] = 0
                            break

            with sent_lock:
                c_sent = sent_count_holder[0]
                c_err = error_count_holder[0]
                c_idx = contact_idx_holder[0]
            progress_pct = int((c_idx / total_contacts) * 100) if total_contacts > 0 else 0
            db.update_automation_job_status(
                job_id, "running",
                sent=c_sent,
                errors=c_err,
                progress=progress_pct
            )

            if b < burst_limit - 1:
                if not human_delay(delay_min, delay_max, stop_checker=lambda: self.job_stop_flags.get(job_id, False)):
                    break

        last_sent_timestamp[acc_id] = time.time()

        # Escanear chats no leídos POST-RÁFAGA
        if not self.job_stop_flags.get(job_id, False):
            try:
                all_states_post = db.get_all_account_states()
                peer_phones_post = {info["phone"] for info in all_states_post.values() if info.get("phone")}
                res_post = runner.check_and_process_unread_chats(
                    acc_id, peer_phones_post,
                    auto_reply_enabled=auto_reply_enabled,
                    auto_reply_message=auto_reply_message
                )
                if res_post.get("notified_clients", 0) > 0:
                    print(f"[AutomationEngine] \ud83d\udd14 [Post-ráfaga] {res_post['notified_clients']} cliente(s) notificados en '{acc_id}'")
            except Exception as scan_post_err:
                print(f"[AutomationEngine] Nota en escaneo post-ráfaga: {scan_post_err}")

        # \ud83e\uddf9 Cerrar navegador tras ráfaga de envío
        print(f"[AutomationEngine] \ud83e\uddf9 Libera recursos: Cerrando navegador de '{acc_id}' tras completar ráfaga de envío.")
        runner.close_instance(acc_id)
        db.update_account_state(acc_id, "disponible", notes="Disponible")

    # ──────────────────────────────────────────────────────────────────────────
    # WORKER DE HISTORIAL — cuenta individual (corre en hilo propio por tanda)
    # ──────────────────────────────────────────────────────────────────────────

    def _process_single_history_account(self, job_id: int, acc_id: str,
                                        all_states: dict, peer_phones: list,
                                        history_msgs_per_turn: int,
                                        warmup_phrases: list,
                                        blocked_history_accounts: set,
                                        blocked_lock: threading.Lock,
                                        auto_reply_enabled: bool = False,
                                        auto_reply_message: str = "") -> bool:
        """
        Procesa una sola cuenta de historial en paralelo dentro de su tanda.
        Retorna True si completó correctamente, False si fue bloqueada o falló.
        """
        if self.job_stop_flags.get(job_id, False):
            return False

        # Verificar bloqueo antes de operar
        inst_status_h = runner.active_instances.get(acc_id, {}).get("status", "")
        db_st_h = db.get_all_account_states().get(acc_id, {}).get("status_state", "")

        if db_st_h in ("bloqueado", "restringido") or inst_status_h == "BLOQUEADA":
            print(f"[AutomationEngine] 🚫 [Historial] '{acc_id}' BLOQUEADA/RESTRINGIDA. Buscando reemplazo...")
            runner.close_instance(acc_id)
            with blocked_lock:
                blocked_history_accounts.add(acc_id)
            return False

        # Abrir sesión si no está activa
        if acc_id not in runner.active_instances or inst_status_h != "CONECTADA":
            print(f"[AutomationEngine] 🔄 [Historial] Abriendo navegador para '{acc_id}'...")
            runner.open_session(acc_id)
            wait_conn = 0
            while wait_conn < 45:
                if self.job_stop_flags.get(job_id, False):
                    return False
                h_status = runner.active_instances.get(acc_id, {}).get("status", "")
                db_h_conn = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
                if h_status == "CONECTADA":
                    break
                if h_status == "BLOQUEADA" or db_h_conn in ("bloqueado", "restringido"):
                    print(f"[AutomationEngine] 🚫 [Historial] '{acc_id}' bloqueada al conectar. Buscando reemplazo...")
                    runner.close_instance(acc_id)
                    with blocked_lock:
                        blocked_history_accounts.add(acc_id)
                    return False
                time.sleep(2)
                wait_conn += 2

        # Verificación final de conexión
        final_h_status = runner.active_instances.get(acc_id, {}).get("status", "")
        db_h_final = db.get_all_account_states().get(acc_id, {}).get("status_state", "")

        if acc_id not in runner.active_instances or final_h_status != "CONECTADA" or db_h_final in ("bloqueado", "restringido"):
            if db_h_final in ("bloqueado", "restringido") or final_h_status == "BLOQUEADA":
                with blocked_lock:
                    blocked_history_accounts.add(acc_id)
            print(f"[AutomationEngine] ⚠️ [Historial] '{acc_id}' no conectó a tiempo. Saltando...")
            return False

        peer_phones_set = set(peer_phones)
        db.update_account_state(acc_id, "haciendo_historial", notes=f"Revisando y haciendo historial (Job #{job_id})")

        # 1. Monitorear chats no leídos
        try:
            res = runner.check_and_process_unread_chats(
                acc_id, peer_phones_set,
                auto_reply_enabled=auto_reply_enabled,
                auto_reply_message=auto_reply_message
            )
            if res["notified_clients"] > 0:
                print(f"[AutomationEngine] 🔔 {res['notified_clients']} cliente(s) notificados en '{acc_id}'")
        except Exception as scan_err:
            print(f"[AutomationEngine] Nota en escaneo historial '{acc_id}': {scan_err}")

        # 2. Enviar mensajes de calentamiento a cuentas amigas (buscando por NOMBRE y APELLIDO)
        #    SOLO se seleccionan como destino las cuentas con status_state == 'disponible'.
        #    Las cuentas bloqueadas, restringidas, enviando o haciendo historial se omiten.
        peer_accounts = []
        fresh_states = db.get_all_account_states()  # Leer estado actualizado antes de construir la lista
        for p_id, p_info in fresh_states.items():
            if p_id == acc_id:
                continue

            # No omitir cuentas activas en envió/historial; solo omitir bloqueadas/restringidas
            p_status = p_info.get("status_state", "")
            if p_status in ("bloqueado", "restringido"):
                continue

            fn = (p_info.get("first_name") or "").strip()
            ln = (p_info.get("last_name") or "").strip()
            phone = (p_info.get("phone") or "").strip()

            if not fn or not ln:
                refreshed = db.get_all_account_states().get(p_id, {})
                fn = (refreshed.get("first_name") or "").strip()
                ln = (refreshed.get("last_name") or "").strip()

            full_name = f"{fn} {ln}".strip()
            if not full_name and phone:
                full_name = phone

            if full_name:
                peer_accounts.append({
                    "account_id": p_id,
                    "full_name": full_name,
                    "phone": phone
                })

        if not peer_accounts:
            print(f"[AutomationEngine] ⚠️ [Historial] '{acc_id}' sin cuentas amigas en BD. Esperando...")
            interruptible_sleep(10, stop_checker=lambda: self.job_stop_flags.get(job_id, False))
        elif history_msgs_per_turn > 0:
            for _ in range(history_msgs_per_turn):
                if self.job_stop_flags.get(job_id, False):
                    break
                target_acc = random.choice(peer_accounts)
                target_name = target_acc["full_name"]
                target_phone = target_acc["phone"]
                text = random.choice(warmup_phrases)

                print(f"[AutomationEngine] 💬 [Historial] [{acc_id}] → cuenta amiga '{target_name}' (Tel: {target_phone})")
                ok = runner.send_warmup_peer_message(acc_id, target_name, text, target_phone=target_phone)

                if not ok:
                    h_post_status = runner.active_instances.get(acc_id, {}).get("status", "")
                    db_h_post = db.get_all_account_states().get(acc_id, {}).get("status_state", "")

                    if h_post_status == "BLOQUEADA" or db_h_post in ("bloqueado", "restringido"):
                        print(f"[AutomationEngine] 🚫 BLOQUEO confirmado en historial de '{acc_id}'. Cerrando...")
                        runner.close_instance(acc_id)
                        with blocked_lock:
                            blocked_history_accounts.add(acc_id)
                        if db_h_post not in ("bloqueado", "restringido"):
                            db.update_account_state(acc_id, "bloqueado", notes="Bloqueado durante historial.", force=True)
                        return False
                    else:
                        print(f"[AutomationEngine] ℹ️ Contacto '{target_name}' no encontrado en WhatsApp Web de '{acc_id}'. Omitiendo y pasando a otro contacto al azar...")
                        peer_accounts = [p for p in peer_accounts if p["full_name"] != target_name]
                        if not peer_accounts:
                            print(f"[AutomationEngine] ⚠️ '{acc_id}' sin mas contactos amigos disponibles en este turno.")
                            break
                        continue

                if not human_delay(10, 20, stop_checker=lambda: self.job_stop_flags.get(job_id, False)):
                    break

        db.update_account_state(acc_id, "disponible", notes="Disponible (Historial completado)")
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # WORKER DE HISTORIAL — orquestador de tandas
    # ──────────────────────────────────────────────────────────────────────────

    def _run_history_worker(self, job_id: int, account_ids: list, profile: dict):
        """Worker que orquesta tandas de historial usando acc_history_count cuentas
        simultáneas por tanda, rotando entre toda la piscina disponible.
        """
        acc_history_count = profile.get("accounts_for_history", 5)
        history_msgs_per_turn = profile.get("history_msgs_per_turn", 2)
        auto_reply_enabled = bool(profile.get("auto_reply_enabled", 0))
        auto_reply_message = profile.get("auto_reply_message", "")

        print(f"[AutomationEngine] 💬 Iniciando Tanda de Hacer Historial para Job #{job_id} — "
              f"piscina: {len(account_ids)} cuenta(s), tanda: {acc_history_count} cuenta(s) simultáneas.")

        warmup_phrases = [
            "Hola! Cómo va todo por allá?",
            "Excelente día, respondiendo pendiente 👍",
            "Un saludo! Todo listo y operativo por acá.",
            "Revisado, perfecto. Seguimos en contacto!",
            "Buenísimo, seguimos avanzando!",
            "Jaja bueno, cuéntame más",
            "Aquí andamos, todo bien!",
            "Claro, más tarde hablamos",
            "👍 Anotado, gracias!",
            "Ok perfecto, ya veo"
        ]

        blocked_history_accounts: set = set()
        blocked_lock = threading.Lock()
        tanda_index = 0

        try:
            while not self.job_stop_flags.get(job_id, False):
                curr_job = db.get_automation_job(job_id)
                if not curr_job or curr_job.get("status") in ("paused", "pausing", "completed", "error"):
                    break

                # Filtrar cuentas disponibles (no bloqueadas, no ocupadas en envío real)
                with blocked_lock:
                    blocked_snap = set(blocked_history_accounts)

                available_history = self._check_and_skip_blocked(account_ids, blocked_snap, skip_sending=True)

                with blocked_lock:
                    blocked_history_accounts.update(blocked_snap)

                if not available_history:
                    print(f"[AutomationEngine] 💬 [Historial] Sin cuentas libres para historial. Esperando...")
                    interruptible_sleep(5, stop_checker=lambda: self.job_stop_flags.get(job_id, False))
                    continue

                # ── Seleccionar tanda de acc_history_count cuentas ──────────────
                tanda_size = min(acc_history_count, len(available_history))
                start_offset = (tanda_index * tanda_size) % len(available_history)

                tanda_accounts = [
                    available_history[(start_offset + i) % len(available_history)]
                    for i in range(tanda_size)
                ]

                tanda_index += 1
                print(f"[AutomationEngine] 💬 [Historial] Tanda #{tanda_index} con "
                      f"{len(tanda_accounts)} cuenta(s): {tanda_accounts}")

                # Obtener estado global de cuentas amigas antes de lanzar la tanda
                all_states = db.get_all_account_states()
                peer_phones = [info["phone"] for info in all_states.values() if info.get("phone")]

                # ── Lanzar tanda en hilos paralelos ──────────────────────────────
                threads = []
                for acc_id in tanda_accounts:
                    t = threading.Thread(
                        target=self._process_single_history_account,
                        args=(
                            job_id, acc_id,
                            all_states, peer_phones,
                            history_msgs_per_turn,
                            warmup_phrases,
                            blocked_history_accounts,
                            blocked_lock,
                            auto_reply_enabled,
                            auto_reply_message
                        ),
                        daemon=True
                    )
                    threads.append(t)
                    t.start()

                # Esperar a que todos los hilos de la tanda terminen (sin bloquear si se solicita pausa)
                for t in threads:
                    while t.is_alive():
                        t.join(timeout=0.2)
                        if self.job_stop_flags.get(job_id, False):
                            break

                # Cerrar navegadores de la tanda completada
                print(f"[AutomationEngine] 🧹 [Historial] Tanda #{tanda_index} completada. Cerrando navegadores: {tanda_accounts}")
                for acc_id in tanda_accounts:
                    try:
                        runner.close_instance(acc_id)
                    except Exception as c_err:
                        print(f"[AutomationEngine] Nota al cerrar '{acc_id}': {c_err}")

                if self.job_stop_flags.get(job_id, False):
                    break

                interruptible_sleep(3, stop_checker=lambda: self.job_stop_flags.get(job_id, False))

        except Exception as e:
            print(f"[AutomationEngine] Error en worker de historial Job #{job_id}: {e}")

        finally:
            print(f"[AutomationEngine] 💬 Finalizando worker de historial Job #{job_id}. Asegurando cierre de instancias...")
            for acc in account_ids:
                try:
                    runner.close_instance(acc)
                except Exception:
                    pass


# Instancia global del motor de automatización
automation_engine = AutomationEngine()
