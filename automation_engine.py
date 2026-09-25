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
        """Termina INMEDIATAMENTE un job de forma no bloqueante:
        1. Activa la bandera de parada para todos los hilos en tiempo real.
        2. Actualiza inmediatamente el estado en Base de Datos.
        3. Despacha la limpieza de navegadores y procesos en segundo plano para no bloquear la respuesta HTTP.
        """
        from session_manager import SessionManager
        print(f"[AutomationEngine] 🛑 TERMINATE no bloqueante solicitado para Job #{job_id}...")

        # 1. Activar bandera de parada de inmediato en memoria
        with self._lock:
            self.job_stop_flags[job_id] = True
            acc_ids = set(self.job_account_ids.get(job_id, []))

        # Respaldar lista de cuentas desde la BD por si la memoria no la tenía registrada completa
        try:
            db_job = db.get_automation_job(job_id)
            if db_job and db_job.get("account_ids"):
                acc_ids.update(db_job.get("account_ids", []))
        except Exception as db_e:
            print(f"[AutomationEngine] Nota al leer job de BD en terminate: {db_e}")

        # 2. Actualizar estado en BD INMEDIATAMENTE
        try:
            db.update_automation_job_status(
                job_id, "paused",
                notes="Detenido totalmente por el usuario (Envío + Historial)."
            )
            all_states = db.get_all_account_states()
            for acc_id in acc_ids:
                db_st = all_states.get(acc_id, {}).get("status_state", "")
                if db_st not in ("bloqueado", "restringido"):
                    db.update_account_state(acc_id, "disponible", notes="Detenido por usuario")
        except Exception as e:
            print(f"[AutomationEngine] Error actualizando BD en terminate_job #{job_id}: {e}")

        # 3. Lanzar limpieza física de navegadores y procesos en segundo plano
        def _cleanup_bg():
            for acc_id in acc_ids:
                try:
                    runner.close_instance(acc_id)
                except Exception as e:
                    print(f"[AutomationEngine] Nota al cerrar '{acc_id}' en terminate bg: {e}")

            time.sleep(0.3)
            for acc_id in acc_ids:
                try:
                    SessionManager.kill_profile_processes(acc_id)
                except Exception as e:
                    print(f"[AutomationEngine] Nota en kill_profile_processes para '{acc_id}': {e}")
            print(f"[AutomationEngine] 🛑 Limpieza en segundo plano de Job #{job_id} completada.")

        t_clean = threading.Thread(target=_cleanup_bg, daemon=True)
        t_clean.start()

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

    # ──────────────────────────────────────────────────────────────────────────────
    # WORKER DE ENVÍO REAL
    # ──────────────────────────────────────────────────────────────────────────────

    def _run_sending_worker(self, job_id: int, account_ids: list, profile: dict,
                            campaign_id: int, contacts: list, sent_count: int, error_count: int):
        """Dispatcher de ráfagas de envío real.

        Arquitectura de turno-por-ráfaga:
        - Mantiene exactamente acc_sending_count slots de ráfaga concurrentes.
        - Cada slot ejecuta UNA ráfaga para una cuenta elegida ALEATORIAMENTE
          entre las elegibles (no bloqueadas, no agotadas, no en otro slot).
        - Al terminar la ráfaga el navegador se cierra de inmediato.
        - Cuentas que llegan a msgs_session se agregan a exhausted_accounts
          y no son seleccionables para el resto del job.
        """
        delay_min       = profile.get("delay_min_sec", 15)
        delay_max       = profile.get("delay_max_sec", 45)
        msgs_session    = profile.get("messages_per_session", 50)
        msgs_interval   = profile.get("messages_per_interval", 2)
        acc_sending_count = profile.get("accounts_for_sending", 5)
        auto_reply_enabled  = bool(profile.get("auto_reply_enabled", 0))
        auto_reply_message  = profile.get("auto_reply_message", "")

        campaigns   = db.get_campaigns()
        campaign    = next((c for c in campaigns if c["id"] == campaign_id), None)
        template_msg  = campaign["template_message"] if campaign else "Hola {nombre}, este es un mensaje automático."
        campaign_vars = campaign.get("variables", []) if campaign else []

        # Estado compartido (acceso protegido por sent_lock)
        sent_in_session: dict[str, int]   = {acc: 0 for acc in account_ids}
        consecutive_fails:  dict[str, int] = {acc: 0 for acc in account_ids}
        blocked_accounts: set = set()
        exhausted_accounts: set = set()   # cuentas que agotaron msgs_session en este job
        active_slots: set = set()          # cuentas con un slot de ráfaga activo ahora mismo
        sent_lock = threading.Lock()

        contact_idx_holder  = [sent_count]
        sent_count_holder   = [sent_count]
        error_count_holder  = [error_count]
        total_contacts      = len(contacts)

        active_burst_threads: dict[str, threading.Thread] = {}

        try:
            while True:
                # ── Bandera de parada ────────────────────────────────────────────────
                if self.job_stop_flags.get(job_id, False):
                    break

                with sent_lock:
                    current_idx = contact_idx_holder[0]
                if current_idx >= total_contacts:
                    break

                curr_job = db.get_automation_job(job_id)
                if not curr_job or curr_job.get("status") in ("paused", "pausing", "completed", "error"):
                    break

                # ── Limpiar slots terminados ───────────────────────────────────────────
                done = [a for a, t in active_burst_threads.items() if not t.is_alive()]
                for a in done:
                    del active_burst_threads[a]
                with sent_lock:
                    active_slots.difference_update(done)

                # ── Cuentas elegibles ───────────────────────────────────────────────
                # Elegibles = no bloqueadas, no agotadas, no con slot activo
                eligible = self._check_and_skip_blocked(account_ids, blocked_accounts, skip_sending=False)
                with sent_lock:
                    eligible = [a for a in eligible
                                if a not in exhausted_accounts
                                and a not in active_slots]

                if not eligible and not active_burst_threads:
                    # Todas bloqueadas o agotadas y ningún slot activo: terminar
                    reason = "agotadas" if not blocked_accounts else "bloqueadas/agotadas"
                    print(f"[AutomationEngine] 🚫 Todas las cuentas están {reason} en Job #{job_id}. Finalizando.")
                    db.update_automation_job_status(
                        job_id, "error",
                        sent=sent_count_holder[0],
                        errors=error_count_holder[0],
                        notes=f"Cuentas {reason}. Enviados: {sent_count_holder[0]}."
                    )
                    return

                # ── Abrir nuevos slots hasta target_count ────────────────────────────
                target_count = min(acc_sending_count, len(eligible) + len(active_burst_threads))
                slots_to_open = target_count - len(active_burst_threads)

                if slots_to_open > 0 and eligible:
                    # Mezcla aleatoria para selección equitativa
                    pool_shuffled = eligible[:]
                    random.shuffle(pool_shuffled)
                    for acc_id in pool_shuffled:
                        if slots_to_open <= 0:
                            break
                        with sent_lock:
                            active_slots.add(acc_id)
                        t = threading.Thread(
                            target=self._execute_one_burst,
                            args=(
                                job_id, acc_id,
                                contacts, total_contacts,
                                template_msg, campaign_vars,
                                sent_in_session, consecutive_fails,
                                blocked_accounts, exhausted_accounts, active_slots,
                                sent_count_holder, error_count_holder,
                                contact_idx_holder, sent_lock,
                                delay_min, delay_max,
                                msgs_session, msgs_interval,
                                auto_reply_enabled, auto_reply_message,
                            ),
                            daemon=True
                        )
                        active_burst_threads[acc_id] = t
                        t.start()
                        slots_to_open -= 1
                        print(f"[AutomationEngine] 🚀 Slot de ráfaga abierto para '{acc_id}' "
                              f"({len(active_burst_threads)}/{target_count} activos).")

                interruptible_sleep(1.0, stop_checker=lambda: self.job_stop_flags.get(job_id, False))

            # Esperar slots activos antes de finalizar
            for t in list(active_burst_threads.values()):
                while t.is_alive():
                    t.join(timeout=0.2)
                    if self.job_stop_flags.get(job_id, False):
                        break

            with sent_lock:
                final_sent   = sent_count_holder[0]
                final_errors = error_count_holder[0]
                final_idx    = contact_idx_holder[0]

            if final_idx >= total_contacts:
                final_status = "error" if final_sent == 0 and final_errors > 0 else "completed"
                db.update_automation_job_status(
                    job_id, final_status,
                    sent=final_sent, errors=final_errors, progress=100,
                    notes=f"Concluido con {final_sent} enviado(s) y {final_errors} error(es)."
                )
            elif self.job_stop_flags.get(job_id, False):
                db.update_automation_job_status(
                    job_id, "paused",
                    sent=final_sent, errors=final_errors,
                    notes="Trabajo pausado por el usuario."
                )

        except Exception as e:
            print(f"[AutomationEngine] Error en dispatcher de envío Job #{job_id}: {e}")

        finally:
            all_final_states = db.get_all_account_states()
            for acc in account_ids:
                st = all_final_states.get(acc, {}).get("status_state", "")
                if st not in ("bloqueado", "restringido") and acc not in blocked_accounts:
                    db.update_account_state(acc, "disponible", notes="Disponible")

    def _execute_one_burst(
            self, job_id: int, acc_id: str,
            contacts: list, total_contacts: int,
            template_msg: str, campaign_vars: list,
            sent_in_session: dict, consecutive_fails: dict,
            blocked_accounts: set, exhausted_accounts: set, active_slots: set,
            sent_count_holder: list, error_count_holder: list,
            contact_idx_holder: list, sent_lock: threading.Lock,
            delay_min: int, delay_max: int,
            msgs_session: int, msgs_interval: int,
            auto_reply_enabled: bool, auto_reply_message: str):
        """
        Ejecuta UNA sola ráfaga de msgs_interval mensajes para acc_id:
          1. Abre el navegador.
          2. Envía hasta msgs_interval mensajes.
          3. Escanea chats no leídos.
          4. Cierra el navegador.
          5. Marca la cuenta como:
             - agotada (exhausted) si llegó al límite de sesión
             - bloqueada si hubo bloqueo
             - disponible (libre para otro slot) en cualquier otro caso
        No ejecuta más de una ráfaga; el dispatcher lanza un nuevo slot
        en cuanto este hilo termina.
        """
        if self.job_stop_flags.get(job_id, False):
            with sent_lock:
                active_slots.discard(acc_id)
            return

        try:
            # ── 1. Verificar estado previo ──────────────────────────────────────────
            db_st = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
            inst_st = runner.active_instances.get(acc_id, {}).get("status", "")

            if db_st in ("bloqueado", "restringido") or inst_st == "BLOQUEADA":
                print(f"[AutomationEngine] 🚫 '{acc_id}' bloqueada antes de iniciar ráfaga. Saltando.")
                blocked_accounts.add(acc_id)
                return

            # ── 2. Abrir navegador ────────────────────────────────────────────────
            db.update_account_state(acc_id, "enviando", notes=f"Ráfaga Job #{job_id}")

            if acc_id not in runner.active_instances or inst_st != "CONECTADA":
                print(f"[AutomationEngine] 🔄 Abriendo navegador para ráfaga de '{acc_id}'...")
                runner.open_session(acc_id)
                wait_conn = 0
                while wait_conn < 45:
                    if self.job_stop_flags.get(job_id, False):
                        return
                    s = runner.active_instances.get(acc_id, {}).get("status", "")
                    ds = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
                    if s == "CONECTADA":
                        break
                    if s == "BLOQUEADA" or ds in ("bloqueado", "restringido"):
                        print(f"[AutomationEngine] 🚫 '{acc_id}' bloqueada al conectar.")
                        blocked_accounts.add(acc_id)
                        return
                    time.sleep(2)
                    wait_conn += 2

            if self.job_stop_flags.get(job_id, False):
                return

            final_s  = runner.active_instances.get(acc_id, {}).get("status", "")
            final_ds = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
            if final_s != "CONECTADA" or final_ds in ("bloqueado", "restringido"):
                if final_ds in ("bloqueado", "restringido") or final_s == "BLOQUEADA":
                    blocked_accounts.add(acc_id)
                print(f"[AutomationEngine] ⚠️ '{acc_id}' no conectó a tiempo. Liberando slot.")
                return

            # ── 2.5. Escaneo de mensajes no leídos AL INICIO del procesamiento ──────
            try:
                all_st = db.get_all_account_states()
                peer_phones = {info["phone"] for info in all_st.values() if info.get("phone")}
                print(f"[AutomationEngine] 🔍 [Envío Real] Escaneo AL INICIO del procesamiento para '{acc_id}'...")
                res_init = runner.check_and_process_unread_chats(
                    acc_id, peer_phones,
                    auto_reply_enabled=auto_reply_enabled,
                    auto_reply_message=auto_reply_message
                )
                if res_init.get("notified_clients", 0) > 0:
                    print(f"[AutomationEngine] 🔔 AL INICIO [Envío Real]: {res_init['notified_clients']} cliente(s) notificados en '{acc_id}'")
            except Exception as scan_err:
                print(f"[AutomationEngine] Nota escaneo pre-ráfaga '{acc_id}': {scan_err}")

            # ── 3. Ejecutar ráfaga (msgs_interval mensajes) ────────────────────────
            sent_in_burst = 0
            burst_blocked = False

            for _ in range(msgs_interval):
                if self.job_stop_flags.get(job_id, False):
                    break

                # Verificar límite de sesión dentro de la ráfaga
                with sent_lock:
                    if sent_in_session.get(acc_id, 0) >= msgs_session:
                        break

                # Reservar contacto de forma atómica
                with sent_lock:
                    if contact_idx_holder[0] >= total_contacts:
                        break
                    idx = contact_idx_holder[0]
                    contact_idx_holder[0] += 1

                contact = contacts[idx]
                phone = contact.get("phone", "")
                text  = self._format_message(template_msg, contact, campaign_vars)
                success, _ = runner.send_test_message(acc_id, phone, text)

                if success:
                    with sent_lock:
                        sent_count_holder[0] += 1
                        sent_in_session[acc_id] = sent_in_session.get(acc_id, 0) + 1
                    sent_in_burst += 1
                    consecutive_fails[acc_id] = 0
                else:
                    post_s  = runner.active_instances.get(acc_id, {}).get("status", "")
                    post_ds = db.get_all_account_states().get(acc_id, {}).get("status_state", "")

                    if post_s == "BLOQUEADA" or post_ds in ("bloqueado", "restringido"):
                        print(f"[AutomationEngine] 🚫 BLOQUEO en '{acc_id}' durante ráfaga.")
                        blocked_accounts.add(acc_id)
                        if post_ds not in ("bloqueado", "restringido"):
                            db.update_account_state(acc_id, "bloqueado",
                                                    notes="Bloqueado durante ráfaga.", force=True)
                        with sent_lock:
                            error_count_holder[0] += 1
                        consecutive_fails[acc_id] = 0
                        burst_blocked = True
                        break
                    else:
                        with sent_lock:
                            error_count_holder[0] += 1
                        consecutive_fails[acc_id] = consecutive_fails.get(acc_id, 0) + 1

                        if consecutive_fails[acc_id] < 5:
                            print(f"[AutomationEngine] ⚠️ Fallo con {phone} "
                                  f"[{consecutive_fails[acc_id]}/5]. Siguiente número...")
                            continue   # siguiente mensaje de la ráfaga
                        else:
                            print(f"[AutomationEngine] 🚫 5 fallos consecutivos en '{acc_id}'. Bloqueando.")
                            blocked_accounts.add(acc_id)
                            db.update_account_state(acc_id, "bloqueado",
                                                    notes="5 fallos consecutivos.", force=True)
                            consecutive_fails[acc_id] = 0
                            burst_blocked = True
                            break

            # ── 4. Post-ráfaga: log + escaneo de chats AL FINAL del procesamiento ──
            if not burst_blocked:
                with sent_lock:
                    c_sent  = sent_count_holder[0]
                    c_err   = error_count_holder[0]
                    c_idx   = contact_idx_holder[0]
                    ses_cnt = sent_in_session.get(acc_id, 0)
                progress_pct = int((c_idx / total_contacts) * 100) if total_contacts > 0 else 0
                db.update_automation_job_status(
                    job_id, "running", sent=c_sent, errors=c_err, progress=progress_pct
                )
                print(f"[AutomationEngine] 📨 Ráfaga '{acc_id}': "
                      f"{sent_in_burst}/{msgs_interval} enviados "
                      f"(sesión acumulada: {ses_cnt}/{msgs_session}).")

                # Escanear chats no leídos AL FINAL
                try:
                    all_st = db.get_all_account_states()
                    peer_phones = {info["phone"] for info in all_st.values() if info.get("phone")}
                    print(f"[AutomationEngine] 🔍 [Envío Real] Escaneo AL FINAL del procesamiento para '{acc_id}'...")
                    res = runner.check_and_process_unread_chats(
                        acc_id, peer_phones,
                        auto_reply_enabled=auto_reply_enabled,
                        auto_reply_message=auto_reply_message
                    )
                    if res.get("notified_clients", 0) > 0:
                        print(f"[AutomationEngine] 🔔 AL FINAL [Envío Real]: {res['notified_clients']} cliente(s) notificados en '{acc_id}'")
                except Exception as scan_err:
                    print(f"[AutomationEngine] Nota escaneo post-ráfaga '{acc_id}': {scan_err}")

                # Verificar si la cuenta agotó su límite de sesión
                with sent_lock:
                    if sent_in_session.get(acc_id, 0) >= msgs_session:
                        exhausted_accounts.add(acc_id)
                        print(f"[AutomationEngine] ✅ '{acc_id}' alcanzó límite de sesión "
                              f"({msgs_session} msgs). No será seleccionada nuevamente en este job.")

        finally:
            # ── 5. Cerrar navegador SIEMPRE al terminar la ráfaga ─────────────────
            print(f"[AutomationEngine] 🧹 Cerrando navegador de '{acc_id}' tras ráfaga.")
            try:
                runner.close_instance(acc_id)
            except Exception:
                pass
            db_fin = db.get_all_account_states().get(acc_id, {}).get("status_state", "")
            if db_fin not in ("bloqueado", "restringido") and acc_id not in blocked_accounts:
                db.update_account_state(acc_id, "disponible", notes="Disponible (post-ráfaga)")
            # Liberar el slot para que el dispatcher pueda asignar otro
            with sent_lock:
                active_slots.discard(acc_id)

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

        # 1. Monitorear chats no leídos AL INICIO del procesamiento de historial
        try:
            print(f"[AutomationEngine] 🔍 [Historial] Escaneo AL INICIO del procesamiento para '{acc_id}'...")
            res = runner.check_and_process_unread_chats(
                acc_id, peer_phones_set,
                auto_reply_enabled=auto_reply_enabled,
                auto_reply_message=auto_reply_message
            )
            if res.get("notified_clients", 0) > 0:
                print(f"[AutomationEngine] 🔔 AL INICIO [Historial]: {res['notified_clients']} cliente(s) notificados en '{acc_id}'")
        except Exception as scan_err:
            print(f"[AutomationEngine] Nota en escaneo historial inicio '{acc_id}': {scan_err}")

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

        # 3. Escanear chats no leídos AL FINAL del procesamiento de historial
        try:
            print(f"[AutomationEngine] 🔍 [Historial] Escaneo AL FINAL del procesamiento para '{acc_id}'...")
            res_fin = runner.check_and_process_unread_chats(
                acc_id, peer_phones_set,
                auto_reply_enabled=auto_reply_enabled,
                auto_reply_message=auto_reply_message
            )
            if res_fin.get("notified_clients", 0) > 0:
                print(f"[AutomationEngine] 🔔 AL FINAL [Historial]: {res_fin['notified_clients']} cliente(s) notificados en '{acc_id}'")
        except Exception as scan_err:
            print(f"[AutomationEngine] Nota en escaneo historial final '{acc_id}': {scan_err}")

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
