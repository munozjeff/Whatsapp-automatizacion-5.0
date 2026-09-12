import sys
import time
import random
import re
import threading
import queue
import urllib.parse
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright, Playwright, BrowserContext, Page
from session_manager import SessionManager
from anti_detection import apply_stealth_to_context, get_random_user_agent, human_delay, human_type
import database as db

class WhatsAppRunner:
    def __init__(self):
        self._lock = threading.Lock()
        self.active_instances: dict[str, dict] = {} # account_id -> { "pw", "context", "page", "status", "account_id", "task_queue" }
        self.pending_qrs: dict[str, dict] = {} # account_id -> { "status": "waiting_qr" | "success" | "error", "message": str }

    def _dispatch_to_instance(self, account_id: str, fn, *args, timeout=60, **kwargs):
        """Despacha de forma segura una función al hilo propietario de la instancia de Playwright."""
        with self._lock:
            instance = self.active_instances.get(account_id)
            if not instance or instance.get("status") != "CONECTADA":
                return False, f"La cuenta '{account_id}' no está conectada o disponible."
            task_queue = instance.get("task_queue")

        if not task_queue:
            return False, f"La cuenta '{account_id}' no tiene hilo ejecutor activo."

        res_q = queue.Queue()
        task_queue.put((fn, args, kwargs, res_q))
        try:
            return res_q.get(timeout=timeout)
        except queue.Empty:
            return False, f"Tiempo de espera ({timeout}s) agotado al ejecutar acción en '{account_id}'."

    def _handle_manual_close(self, account_id: str):
        """Manejador llamado automáticamente cuando la ventana se cierra manualmente por el usuario."""
        with self._lock:
            self.active_instances.pop(account_id, None)
        print(f"[{account_id}] La ventana fue cerrada.")
        SessionManager.prune_profile_cache(account_id)

    def start_qr_login(self, account_id: str, on_complete_callback=None):
        """Inicia proceso de login QR con perfil persistente."""
        with self._lock:
            if account_id in self.active_instances:
                return False, "La cuenta ya está abierta."
            self.pending_qrs[account_id] = {"status": "waiting_qr", "message": "Esperando escaneo de código QR..."}

        thread = threading.Thread(
            target=self._run_qr_login_worker,
            args=(account_id, on_complete_callback),
            daemon=True
        )
        thread.start()
        return True, "Navegador iniciado. Escanea el código QR que aparece en pantalla."

    def _run_qr_login_worker(self, account_id: str, callback):
        try:
            SessionManager.kill_profile_processes(account_id)
            SessionManager.unlock_profile(account_id)
            user_data_dir = SessionManager.get_profile_dir(account_id)
            pw = sync_playwright().start()
            
            context: BrowserContext = pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                viewport={"width": 1280, "height": 800},
                user_agent=get_random_user_agent(),
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-session-crashed-bubble",
                    "--no-first-run",
                    "--no-default-browser-check"
                ]
            )
            context.on("close", lambda ctx: self._handle_manual_close(account_id))
            apply_stealth_to_context(context)
            page: Page = context.pages[0] if context.pages else context.new_page()
            page._account_id = account_id

            task_queue = queue.Queue()
            with self._lock:
                self.active_instances[account_id] = {
                    "pw": pw,
                    "context": context,
                    "page": page,
                    "status": "ESPERANDO_QR",
                    "account_id": account_id,
                    "task_queue": task_queue
                }

            page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=60000)

            print(f"[{account_id}] Esperando inicio de sesión en WhatsApp Web...")
            logged_in = False
            start_time = time.time()
            timeout_seconds = 180 # 3 minutos para escanear QR

            while time.time() - start_time < timeout_seconds:
                if page.is_closed():
                    break

                if (page.locator("#side").first.is_visible() or 
                    page.locator('header').first.is_visible() or 
                    page.locator('div[contenteditable="true"]').count() > 0):
                    
                    time.sleep(5)
                    logged_in = True
                    break

                time.sleep(2)

            if logged_in:
                print(f"[{account_id}] ¡Inicio de sesión exitoso! Cerrando popups de confirmación...")

                if not page.is_closed():
                    self.dismiss_whatsapp_modals(page)

                print(f"[{account_id}] Perfil persistente sincronizado.")
                with self._lock:
                    self.pending_qrs[account_id] = {
                        "status": "success",
                        "message": "¡Sesión guardada con éxito! La cuenta permanecerá conectada permanentemente."
                    }
                    if account_id in self.active_instances:
                        self.active_instances[account_id]["status"] = "CONECTADA"

                self.extract_whatsapp_phone_number(account_id)

                # Bucle de despacho de tareas en el hilo ejecutor del QR worker
                while not page.is_closed():
                    try:
                        item = task_queue.get(timeout=1.0)
                        if item is None:
                            break
                        func, args, kwargs, res_q = item
                        try:
                            res = func(page, *args, **kwargs)
                            if res_q:
                                res_q.put(res)
                        except Exception as exc:
                            err_clean = str(exc).encode('ascii', 'ignore').decode('ascii')
                            print(f"[{account_id}] Error ejecutando tarea: {err_clean}")
                            if res_q:
                                res_q.put((False, err_clean))
                    except queue.Empty:
                        pass
            else:
                with self._lock:
                    self.pending_qrs[account_id] = {
                        "status": "error",
                        "message": "Tiempo de espera agotado o ventana cerrada sin escanear QR."
                    }
                self.close_instance(account_id)

        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{account_id}] Error en QR Worker: {err_msg}")
            with self._lock:
                self.pending_qrs[account_id] = {
                    "status": "error",
                    "message": f"Error al abrir navegador: {err_msg}"
                }
            self.close_instance(account_id)

    def open_session(self, account_id: str):
        """Abre la sesion persistente cargando la carpeta de usuario de Chromium."""
        with self._lock:
            if account_id in self.active_instances:
                return True, "La sesión ya está activa."

        if not SessionManager.has_session(account_id):
            return False, "No se encontró sesión previa para esta cuenta. Por favor escanear QR primero."

        thread = threading.Thread(
            target=self._run_open_session_worker,
            args=(account_id,),
            daemon=True
        )
        thread.start()
        return True, "Abriendo navegador con perfil persistente..."

    def _run_open_session_worker(self, account_id: str):
        try:
            SessionManager.kill_profile_processes(account_id)
            SessionManager.unlock_profile(account_id)
            user_data_dir = SessionManager.get_profile_dir(account_id)
            pw = sync_playwright().start()

            context: BrowserContext = pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                viewport={"width": 1280, "height": 800},
                user_agent=get_random_user_agent(),
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-session-crashed-bubble",
                    "--no-first-run",
                    "--no-default-browser-check"
                ]
            )
            context.on("close", lambda ctx: self._handle_manual_close(account_id))
            apply_stealth_to_context(context)
            page: Page = context.pages[0] if context.pages else context.new_page()
            page._account_id = account_id

            task_queue = queue.Queue()
            with self._lock:
                self.active_instances[account_id] = {
                    "pw": pw,
                    "context": context,
                    "page": page,
                    "status": "CARGANDO",
                    "account_id": account_id,
                    "task_queue": task_queue
                }

            page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
            
            # Monitorear conexión y verificar si hay QR / bloqueo
            start_t = time.time()
            connected = False
            is_blocked = False

            while time.time() - start_t < 30:
                if page.is_closed():
                    break

                # 1. Chequeo inmediato de QR o bloqueo por WhatsApp
                if self.check_if_blocked_or_logged_out(page, account_id):
                    print(f"[{account_id}] 🚫 Sesión cerrada / QR detectado. Marcando como BLOQUEADA.")
                    is_blocked = True
                    break

                # 2. Chequeo de sesión activa conectada
                if (
                    page.locator("#pane-side").first.is_visible() or
                    page.locator("#side").first.is_visible() or 
                    page.locator("header").first.is_visible() or
                    page.locator('div[role="row"]').count() > 0 or
                    page.locator('div[contenteditable="true"]').count() > 0
                ):
                    connected = True
                    break
                time.sleep(1.0)

            if is_blocked:
                # Cerrar el navegador y liberar recursos inmediatamente
                print(f"[{account_id}] 🚫 Cerrando navegador bloqueado y liberando recursos...")
                # Vaciar la task_queue para desbloquear cualquier hilo esperando respuesta
                while not task_queue.empty():
                    try:
                        item = task_queue.get_nowait()
                        if item is not None:
                            _, _, _, res_q = item
                            if res_q:
                                res_q.put((False, f"Cuenta '{account_id}' bloqueada por WhatsApp (QR detectado)."))
                    except Exception:
                        break
                self._cleanup_instance_resources(account_id)
            elif connected or not page.is_closed():
                # Intentar descartar modales una única vez
                try:
                    self.dismiss_whatsapp_modals(page)
                except Exception:
                    pass

                with self._lock:
                    if account_id in self.active_instances:
                        self.active_instances[account_id]["status"] = "CONECTADA"
                print(f"[{account_id}] ✅ Sesión activa y lista (CONECTADA).")
                try:
                    self.extract_whatsapp_phone_number(account_id)
                except Exception as ex_err:
                    print(f"[{account_id}] Nota extrayendo teléfono: {ex_err}")

                # Loop ejecutor de tareas en el hilo de Playwright de la cuenta
                last_blocked_check = time.time()
                while not page.is_closed():
                    try:
                        item = task_queue.get(timeout=1.0)
                        if item is None:
                            break
                        func, args, kwargs, res_q = item
                        try:
                            res = func(page, *args, **kwargs)
                            if res_q:
                                res_q.put(res)
                        except Exception as exc:
                            err_clean = str(exc).encode('ascii', 'ignore').decode('ascii')
                            print(f"[{account_id}] Error ejecutando tarea: {err_clean}")
                            if res_q:
                                res_q.put((False, err_clean))
                    except queue.Empty:
                        if time.time() - last_blocked_check > 10:
                            last_blocked_check = time.time()
                            if self.check_if_blocked_or_logged_out(page, account_id):
                                print(f"[{account_id}] 🚫 Cuenta suspendida/desconectada detectada en monitoreo de reposo. Cerrando...")
                                # Vaciar task_queue: responder con error a todos los que esperan
                                while not task_queue.empty():
                                    try:
                                        pending = task_queue.get_nowait()
                                        if pending is not None:
                                            _, _, _, p_res_q = pending
                                            if p_res_q:
                                                p_res_q.put((False, f"Cuenta '{account_id}' bloqueada/desconectada."))
                                    except Exception:
                                        break
                                break  # salir del loop de tareas

                # Al salir del loop de tareas por bloqueo, cerrar el navegador
                with self._lock:
                    post_status = self.active_instances.get(account_id, {}).get("status", "")
                if post_status == "BLOQUEADA":
                    print(f"[{account_id}] 🚫 Cerrando navegador y liberando instancia bloqueada...")
                    self._cleanup_instance_resources(account_id)

        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{account_id}] Error al abrir perfil persistente: {err_msg}")
            self.close_instance(account_id)

    def close_instance(self, account_id: str):
        """Cierra la ventana activa enviando señal de parada al worker thread."""
        with self._lock:
            instance = self.active_instances.get(account_id)

        if instance:
            tq = instance.get("task_queue")
            if tq:
                tq.put(None)  # Enviar señal de terminación al bucle del hilo

        return self._cleanup_instance_resources(account_id)

    def _cleanup_instance_resources(self, account_id: str):
        with self._lock:
            instance = self.active_instances.pop(account_id, None)

        if instance:
            try:
                context: BrowserContext = instance.get("context")
                if context:
                    for page in context.pages:
                        try:
                            page.on("dialog", lambda dialog: dialog.accept())
                            page.evaluate("window.onbeforeunload = null;")
                        except Exception:
                            pass
                    try:
                        context.close()
                    except Exception:
                        pass

                pw = instance.get("pw")
                if pw:
                    try:
                        pw.stop()
                    except Exception:
                        pass
            except Exception as e:
                print(f"Error procesando cierre de {account_id}: {e}")
            
            time.sleep(0.5)
            SessionManager.kill_profile_processes(account_id)
            SessionManager.prune_profile_cache(account_id)

            return True, f"Sesión de '{account_id}' cerrada y guardada."
        return False, "La cuenta no está activa."

    def dismiss_whatsapp_modals(self, page: Page):
        """
        Espera que aparezcan popups o modales sobrepuestos en WhatsApp Web 
        (como 'Usar aquí', 'Continuar', 'Novedades', 'Notificaciones', etc.) 
        y los cierra/descarta de forma automática y agresiva.
        """
        print("--> Monitoreando y cerrando popups/modales de WhatsApp Web...")
        
        deadline = time.time() + 8
        modals_dismissed = 0

        while time.time() < deadline:
            if page.is_closed():
                return

            try:
                # 1. Enviar Escape para cerrar diálogos emergentes estándar
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

                # 2. Ejecutar script JS para detectar y hacer clic en botones de modales o remover la capa overlay
                res = page.evaluate("""() => {
                    const modalSelectors = [
                        'div[role="dialog"]',
                        'div[aria-modal="true"]',
                        '[data-animate-modal-popup="true"]',
                        '[data-testid="confirm-popup"]',
                        '[data-testid="popup-contents"]',
                        '[data-testid*="popup"]',
                        '[data-testid*="modal"]'
                    ];
                    
                    const candidates = Array.from(document.querySelectorAll(modalSelectors.join(',')));
                    
                    // Buscar elementos overlay fijos/absolutos con alto z-index
                    const overlays = Array.from(document.querySelectorAll('div')).filter(el => {
                        const style = window.getComputedStyle(el);
                        const isFixedOrAbs = style.position === 'fixed' || style.position === 'absolute';
                        const zIdx = parseInt(style.zIndex || '0', 10);
                        return isFixedOrAbs && zIdx >= 50 && el.offsetHeight > 80 && el.offsetWidth > 80;
                    });

                    const allModals = [...new Set([...candidates, ...overlays])].filter(el => {
                        if (!el || !el.isConnected) return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    });

                    if (allModals.length === 0) return 'none';

                    let resultStatus = 'none';
                    for (const modal of allModals) {
                        const buttons = Array.from(modal.querySelectorAll('button, div[role="button"], [tabindex="0"]'));

                        // 1. Prioridad: Botones de confirmación/acción ("Usar aquí", "Continuar", "Entendido", "Aceptar", "OK")
                        let btn = buttons.find(b => {
                            const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                            return txt.includes('usar aquí') || txt.includes('use here') ||
                                   txt.includes('continuar') || txt.includes('continue') ||
                                   txt.includes('entendido') || txt.includes('got it') ||
                                   txt.includes('aceptar') || txt.includes('accept') ||
                                   txt.includes('de acuerdo') || txt.includes('ok');
                        });

                        // 2. Segunda prioridad: Botones de descarte ("Ahora no", "Cerrar", "Close", "Cancelar")
                        if (!btn) {
                            btn = buttons.find(b => {
                                const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                                return txt.includes('ahora no') || txt.includes('not now') ||
                                       txt.includes('cerrar') || txt.includes('close') ||
                                       txt.includes('cancelar') || txt.includes('cancel') ||
                                       aria.includes('cerrar') || aria.includes('close');
                            });
                        }

                        // 3. Tercera prioridad: Icono X de cierre
                        if (!btn) {
                            btn = modal.querySelector('[data-icon="x"], [data-icon="close"], [data-icon="x-viewer"], [data-testid="x"]');
                        }

                        // Clic o remover del DOM
                        if (btn) {
                            btn.click();
                            resultStatus = 'clicked_button';
                        } else {
                            modal.remove();
                            resultStatus = 'removed_modal';
                        }
                    }

                    // Limpiar fondos oscuros / backdrops remanentes
                    const backdrops = Array.from(document.querySelectorAll('div[data-animate-modal-backdrop="true"], div[class*="backdrop"]'));
                    backdrops.forEach(b => { try { b.remove(); } catch(e) {} });

                    return resultStatus;
                }""")

                if res != 'none':
                    modals_dismissed += 1
                    print(f"--> [Modal WA] Descartado con éxito ({res}).")
                    time.sleep(0.5)
                else:
                    if modals_dismissed > 0 or (time.time() - (deadline - 8)) >= 2.5:
                        break

            except Exception as e:
                print(f"Nota en descarte modal: {e}")

            time.sleep(0.5)

        if modals_dismissed > 0:
            print(f"--> [{modals_dismissed}] modal(es) de WhatsApp Web cerrado(s) correctamente.")
        else:
            print("--> No se detectaron modales de confirmación pendientes.")

    def extract_whatsapp_phone_number(self, account_id: str) -> str | None:
        """
        Extrae el número de teléfono propio vinculado a la sesión de WhatsApp Web.
        1. Intenta extracción instantánea por LocalStorage / window.Store.
        2. Si falla, realiza inspección DOM rápida vía JavaScript procesando marcas Unicode LTR y espacios NBSP.
        Guarda automáticamente el resultado en BD (account_states.phone).
        """
        with self._lock:
            instance = self.active_instances.get(account_id)

        if not instance or instance.get("status") != "CONECTADA":
            return None

        page: Page = instance["page"]
        phone_number = None

        try:
            print(f"[{account_id}] Intentando extraer número de teléfono propio...")

            # Método 1: Extracción por LocalStorage / window.Store
            try:
                ls_phone = page.evaluate("""() => {
                    try {
                        if (window.Store && window.Store.User && window.Store.User.getMeUser) {
                            const me = window.Store.User.getMeUser();
                            if (me && me.user) return '+' + me.user;
                        }
                    } catch(e) {}

                    try {
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            const val = localStorage.getItem(key);
                            if (val) {
                                const m1 = val.match(/(\d{8,15})(:[0-9]+)?@(c\.us|s\.whatsapp\.net)/);
                                if (m1 && m1[1].length >= 8) return '+' + m1[1];
                                const m2 = val.match(/"user"\s*:\s*"?(\d{8,15})"?/);
                                if (m2 && m2[1].length >= 8) return '+' + m2[1];
                                const m3 = val.match(/"wid"\s*:\s*"?(\d{8,15})"?/);
                                if (m3 && m3[1].length >= 8) return '+' + m3[1];
                            }
                        }
                    } catch(e) {}
                    return null;
                }""")
                if ls_phone:
                    phone_number = ls_phone
                    print(f"[{account_id}] [OK] Numero extraido por LocalStorage: {phone_number}")
            except Exception as ls_err:
                err_clean = str(ls_err).encode('ascii', 'ignore').decode('ascii')
                print(f"[{account_id}] Nota en extraccion LocalStorage: {err_clean}")

            # Método 2: Apertura de perfil e inspección DOM rápida vía JS
            if not phone_number:
                self.dismiss_whatsapp_modals(page)

                profile_selectors = [
                    "button[aria-label*='Perfil']", 
                    "button[aria-label*='Tú']", 
                    "header img", 
                    "header button",
                    "div[title*='Perfil']",
                    "div[aria-label*='Perfil']"
                ]
                for sel in profile_selectors:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            time.sleep(1.5)
                            break
                    except Exception:
                        continue

                try:
                    sub_btn = page.locator("button:has-text('Nombre, foto'), button:has-text('Perfil')").first
                    if sub_btn.is_visible(timeout=1000):
                        sub_btn.click()
                        time.sleep(1)
                except Exception:
                    pass

                # Extraer texto del DOM escaneando todo el texto visible (soporta WhatsApp Personal y WhatsApp Business)
                dom_phone = page.evaluate("""() => {
                    const findPhoneInText = (text) => {
                        if (!text) return null;
                        const clean = text.replace(/[\u200e\u200f\u202a-\u202e]/g, '');
                        const matches = clean.match(/\+?\d[\d\s\-\(\)\u00a0\u202f]{7,20}/g) || [];
                        for (const m of matches) {
                            const trimmed = m.trim();
                            const digits = trimmed.replace(/[^\d]/g, '');
                            if (digits.length >= 8 && digits.length <= 15) {
                                if (!/^\d{4}[\-\/]\d{2}[\-\/]\d{2}/.test(trimmed)) {
                                    return trimmed;
                                }
                            }
                        }
                        return null;
                    };

                    // 1. Buscar en todo el texto visible del documento
                    let found = findPhoneInText(document.body ? document.body.innerText : '');
                    if (found) return found;

                    // 2. Buscar en inputs, textareas y atributos de título/aria
                    const elements = Array.from(document.querySelectorAll('input, textarea, [title], [aria-label]'));
                    for (const el of elements) {
                        const val = el.value || el.getAttribute('title') || el.getAttribute('aria-label') || '';
                        found = findPhoneInText(val);
                        if (found) return found;
                    }

                    return null;
                }""")

                if not dom_phone:
                    # Scroll hacia abajo en el drawer por si es perfil Business y el número está más abajo
                    try:
                        page.mouse.wheel(0, 500)
                        time.sleep(0.5)
                        dom_phone = page.evaluate("""() => {
                            const findPhoneInText = (text) => {
                                if (!text) return null;
                                const clean = text.replace(/[\u200e\u200f\u202a-\u202e]/g, '');
                                const matches = clean.match(/\+?\d[\d\s\-\(\)\u00a0\u202f]{7,20}/g) || [];
                                for (const m of matches) {
                                    const trimmed = m.trim();
                                    const digits = trimmed.replace(/[^\d]/g, '');
                                    if (digits.length >= 8 && digits.length <= 15) {
                                        if (!/^\d{4}[\-\/]\d{2}[\-\/]\d{2}/.test(trimmed)) {
                                            return trimmed;
                                        }
                                    }
                                }
                                return null;
                            };
                            return findPhoneInText(document.body ? document.body.innerText : '');
                        }""")
                    except Exception:
                        pass

                if dom_phone:
                    phone_number = dom_phone
                    print(f"[{account_id}] [OK] Numero extraido por inspeccion DOM: {phone_number}")

                try:
                    page.keyboard.press("Escape")
                    time.sleep(0.5)
                except Exception:
                    pass

            if phone_number:
                db.update_account_state(account_id, "disponible", phone=phone_number)
                print(f"[{account_id}] [OK] Numero de telefono extraido final y guardado en BD: {phone_number}")
            else:
                print(f"[{account_id}] [WARN] No se pudo extraer el numero de telefono.")

        except Exception as e:
            err_clean = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{account_id}] Error extrayendo telefono: {err_clean}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

        return phone_number

    def check_and_process_unread_chats(self, account_id: str, peer_phones_set: set, auto_reply_enabled: bool = False, auto_reply_message: str = "") -> dict:
        """
        Escanea chats no leídos en WhatsApp Web despachando la orden al hilo ejecutor.
        """
        res = self._dispatch_to_instance(account_id, self._internal_check_unread, account_id, peer_phones_set, auto_reply_enabled, auto_reply_message, timeout=60)
        if isinstance(res, dict):
            return res
        return {"replied_friends": 0, "notified_clients": 0}

    def _internal_check_unread(self, page: Page, account_id: str, peer_phones_set: set, auto_reply_enabled: bool = False, auto_reply_message: str = "") -> dict:
        page._account_id = account_id
        replied_friends = 0
        notified_clients = 0

        # Obtener dinámicamente los teléfonos Y nombres de todas las cuentas del sistema
        system_phones = db.get_all_account_phone_digits()
        system_names = db.get_all_account_contact_names()  # set de nombres lowercased
        combined_peers = set(peer_phones_set or []) | system_phones

        try:
            # Volver al panel principal si estábamos en un chat individual
            try:
                current_url = page.url
                if "send?phone=" in current_url or "/send" in current_url:
                    page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
                    time.sleep(2)
                    if not page.is_closed():
                        self.dismiss_whatsapp_modals(page)
            except Exception:
                pass

            print(f"[{account_id}] 🔍 Buscando TODOS los chats no leídos sin excepción...")
            time.sleep(1.0)

            # Bucle continuo hasta procesar TODOS los chats no leídos disponibles (sin límite)
            max_scan_passes = 5
            pass_num = 0
            processed_titles_in_run = set()

            # Selectores exhaustivos de badges de mensajes no leídos
            UNREAD_ROW_SELECTORS = [
                'div[role="row"]:has(span[aria-label*="no leído"])',
                'div[role="row"]:has(span[aria-label*="no leido"])',
                'div[role="row"]:has(span[aria-label*="unread"])',
                'div[role="row"]:has(span[data-testid="icon-unread-count"])',
                'div[role="row"]:has(span[aria-label*="mensaje"])',
                'div[role="row"]:has(div[aria-label*="unread"])',
                'div[role="row"]:has(div[aria-label*="no leído"])',
            ]

            while pass_num < max_scan_passes:
                pass_num += 1

                # Buscar filas no leídas con todos los selectores
                unread_rows = []
                for sel in UNREAD_ROW_SELECTORS:
                    try:
                        found = page.locator(sel).all()
                        if found:
                            for f in found:
                                if f not in unread_rows:
                                    unread_rows.append(f)
                    except Exception:
                        pass

                if not unread_rows:
                    # Scroll en el panel lateral #pane-side por si hay chats no leídos más abajo
                    try:
                        pane = page.locator('#pane-side').first
                        if pane.is_visible(timeout=500):
                            pane.evaluate("el => el.scrollTop += 450")
                            time.sleep(0.8)
                            for sel in UNREAD_ROW_SELECTORS:
                                try:
                                    found = page.locator(sel).all()
                                    if found:
                                        for f in found:
                                            if f not in unread_rows:
                                                unread_rows.append(f)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                if not unread_rows:
                    break

                print(f"[{account_id}] 📬 Pasada #{pass_num}: {len(unread_rows)} chat(s) no leído(s) detectado(s). Procesando todos...")

                processed_in_this_pass = 0

                for row in unread_rows:
                    if page.is_closed():
                        break

                    chat_name = "?"
                    try:
                        nombre_elem = row.locator('span[dir="auto"][title]').first
                        if not nombre_elem.is_visible(timeout=1000):
                            nombre_elem = row.locator('span[dir="auto"]').first
                            if not nombre_elem.is_visible(timeout=800):
                                continue

                        chat_name = (nombre_elem.get_attribute("title") or nombre_elem.inner_text() or "").strip()
                        if not chat_name or chat_name in processed_titles_in_run:
                            continue

                        processed_titles_in_run.add(chat_name)
                        clean_digits = re.sub(r'[^\d]', '', chat_name)
                        chat_name_lower = chat_name.lower()

                        # Verificar si es cuenta amiga o cuenta del sistema
                        is_friend = False

                        if clean_digits and len(clean_digits) >= 7:
                            for peer_digits in combined_peers:
                                if peer_digits and (peer_digits in clean_digits or clean_digits in peer_digits):
                                    is_friend = True
                                    break

                        if not is_friend:
                            for sys_name in system_names:
                                if sys_name and (sys_name in chat_name_lower or chat_name_lower in sys_name):
                                    is_friend = True
                                    print(f"[{account_id}] 🛡️ '{chat_name}' identificado como cuenta propia por nombre en BD ('{sys_name}'). Omitiendo notificación cliente.")
                                    break

                        if not is_friend and db.is_system_generated_name(chat_name):
                            is_friend = True
                            print(f"[{account_id}] 🛡️ '{chat_name}' identificado como cuenta propia por patrón autogenerado. Omitiendo notificación cliente.")

                        # Abrir el chat haciendo clic en el row
                        click_ok = False
                        try:
                            row.click(force=True, timeout=2000)
                            click_ok = True
                            time.sleep(1)
                        except Exception:
                            try:
                                safe_name = chat_name.replace("'", "\\'")
                                alt = page.locator(f"//span[@title='{safe_name}']/ancestor::div[@role='row']").first
                                alt.click(force=True, timeout=2000)
                                click_ok = True
                                time.sleep(1)
                            except Exception:
                                pass

                        if not click_ok:
                            continue

                        processed_in_this_pass += 1

                        if is_friend:
                            # Amigo: responder saludo de calentamiento
                            print(f"[{account_id}] 🤖 Amigo ('{chat_name}'). Respondiendo calentamiento...")
                            compose = self._find_compose_input(page)
                            if compose:
                                warmup_replies = [
                                    "Hola! Todo bien por acá 👍",
                                    "Perfecto, seguimos en contacto!",
                                    "Excelente, un saludo!",
                                    "Revisado, gracias!",
                                    "👍 Todo listo!"
                                ]
                                reply_text = random.choice(warmup_replies)
                                compose.click()
                                page.keyboard.type(reply_text, delay=20)
                                time.sleep(0.3)
                                sent = False
                                try:
                                    send_btn = page.locator(
                                        'button[aria-label*="Enviar"], button[aria-label*="Send"], span[data-icon="send"]'
                                    ).first
                                    if send_btn.is_visible(timeout=1500):
                                        send_btn.click()
                                        sent = True
                                except Exception:
                                    pass
                                if not sent:
                                    compose.press("Enter")
                                replied_friends += 1

                        else:
                            # Cliente real: leer último mensaje y notificar
                            print(f"[{account_id}] 🔔 ¡Cliente real ('{chat_name}')! Guardando notificación...")
                            last_msg_text = ""
                            try:
                                for sel in [
                                    'span[data-testid="selectable-text"]',
                                    'div.message-in span.copyable-text',
                                    'div.message-in span.selectable-text',
                                    'div.message-in div.copyable-text',
                                ]:
                                    elems = page.locator(sel).all()
                                    if elems:
                                        last_msg_text = elems[-1].inner_text().strip()
                                        if last_msg_text:
                                            break
                            except Exception:
                                pass

                            db.add_client_notification(
                                account_id, chat_name, chat_name,
                                last_msg_text or "Nuevo mensaje no leído de cliente."
                            )
                            notified_clients += 1

                            if auto_reply_enabled and auto_reply_message and auto_reply_message.strip():
                                print(f"[{account_id}] 🤖 Autorespuesta activa para cliente ('{chat_name}'). Enviando...")
                                compose = self._find_compose_input(page)
                                if compose:
                                    compose.click()
                                    page.keyboard.type(auto_reply_message.strip(), delay=20)
                                    time.sleep(0.3)
                                    sent = False
                                    try:
                                        send_btn = page.locator(
                                            'button[aria-label*="Enviar"], button[aria-label*="Send"], span[data-icon="send"]'
                                        ).first
                                        if send_btn.is_visible(timeout=1500):
                                            send_btn.click()
                                            sent = True
                                    except Exception:
                                        pass
                                    if not sent:
                                        compose.press("Enter")
                                    time.sleep(1)

                        # Cerrar chat con Escape inmediatamente tras procesar
                        try:
                            page.keyboard.press("Escape")
                            time.sleep(0.3)
                            page.keyboard.press("Escape")
                            time.sleep(0.3)
                        except Exception:
                            pass

                    except Exception as err_item:
                        print(f"[{account_id}] Error procesando chat '{chat_name}': {err_item}")
                        try:
                            page.keyboard.press("Escape")
                        except Exception:
                            pass

                if processed_in_this_pass == 0:
                    break

            # Volver scroll al inicio al terminar la exploración completa
            try:
                page.locator('#pane-side').first.evaluate("el => el.scrollTop = 0")
            except Exception:
                pass

            if notified_clients > 0 or replied_friends > 0:
                print(f"[{account_id}] ✅ Escaneo exhaustivo completado: {notified_clients} cliente(s) notificados, {replied_friends} amigo(s) respondidos.")
            else:
                print(f"[{account_id}] ✓ Escaneo exhaustivo completado: 0 chats no leídos pendientes.")

        except Exception as e:
            print(f"[{account_id}] Error en escaneo de chats: {e}")

        return {"replied_friends": replied_friends, "notified_clients": notified_clients}


    def _find_compose_input(self, page: Page):
        """
        Localiza el campo de composición de mensajes del chat abierto.
        Compatible con versiones nuevas y antiguas de WhatsApp Web:
          1. div[data-testid="conversation-compose-box-input"] — WA nuevo
          2. footer div[contenteditable="true"]               — WA intermedio
          3. div[contenteditable="true"][data-tab="10"]       — WA antiguo
          4. p.copyable-text.x15bjb6t                         — Legacy
        Returns: Locator visible o None.
        """
        selectors = [
            'div[data-testid="conversation-compose-box-input"]',
            'footer div[contenteditable="true"]',
            'div[contenteditable="true"][data-tab="10"]',
            'p.copyable-text.x15bjb6t',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=2000):
                    return loc
            except Exception:
                pass
        return None

    def check_if_blocked_or_logged_out(self, page: Page, account_id: str) -> bool:
        """
        Verifica si la cuenta de WhatsApp fue suspendida/bloqueada o si la sesión se cerró.
        Detecta:
          - Código QR (canvas, data-ref, qrcode)
          - Pantallas de login / vinculación de teléfono
          - Mensajes explícitos de suspensión de cuenta
        Si detecta bloqueo:
          1. Actualiza BD (account_states): status_state = 'bloqueado'
          2. Actualiza active_instances: status = 'BLOQUEADA'
        Returns: True si la cuenta está bloqueada/desconectada, False en caso contrario.
        """
        if not page or page.is_closed():
            return True

        try:
            # 1. Detección de Canvas / QR
            qr_selectors = [
                'canvas[aria-label*="Scan"]',
                'canvas[aria-label*="Escanear"]',
                'div[data-testid="qrcode"]',
                'canvas',
                'div[data-ref]'
            ]
            has_qr = False
            for sel in qr_selectors:
                try:
                    if page.locator(sel).first.is_visible(timeout=400):
                        has_qr = True
                        print(f"[{account_id}] ⚠️ Detectado código QR ({sel}). Sesión cerrada por WhatsApp.")
                        break
                except Exception:
                    pass

            # 2. Detección por textos de login o suspensión
            has_login_text = False
            login_texts = [
                "Pasos para iniciar sesión",
                "Vincular con el número de teléfono",
                "Use WhatsApp on your computer",
                "To use WhatsApp on your computer",
                "Tu cuenta ha sido suspendida",
                "Cuenta suspendida",
                "Esta cuenta no tiene permiso para usar WhatsApp",
                "Tu número fue suspendido"
            ]
            for txt in login_texts:
                try:
                    if page.locator(f"text='{txt}'").first.is_visible(timeout=300):
                        has_login_text = True
                        print(f"[{account_id}] ⚠️ Detectado indicador de desconexión/bloqueo: '{txt}'.")
                        break
                except Exception:
                    pass

            # 3. Detección de cuenta RESTRINGIDA TEMPORALMENTE (timelock popup)
            # Selector exclusivo del popup de restriccion con temporizador
            has_restriction = False
            restriction_selectors = [
                '[data-testid="reachout-timelock-restricted-modal-bullet-1"]',
                '[data-testid="reachout-timelock-restricted-modal-bullet-2"]',
            ]
            for sel in restriction_selectors:
                try:
                    if page.locator(sel).first.is_visible(timeout=400):
                        has_restriction = True
                        print(f"[{account_id}] ⚠️ Detectado popup de RESTRICCION TEMPORAL ({sel}).")
                        break
                except Exception:
                    pass

            # Textos del popup de restriccion como respaldo
            if not has_restriction:
                restriction_texts = [
                    "tu cuenta está restringida en los dispositivos vinculados",
                    "cuenta está restringida",
                    "no podrás iniciar nuevos chats",
                    "mensajes automáticos o mensajería masiva",
                    "Tu cuenta ha sido restringida",
                    "your account is restricted",
                ]
                for txt in restriction_texts:
                    try:
                        if page.locator(f"text='{txt}'").first.is_visible(timeout=300):
                            has_restriction = True
                            print(f"[{account_id}] ⚠️ Detectado texto de restriccion: '{txt[:50]}...'")
                            break
                    except Exception:
                        pass

            if has_qr or has_login_text:
                reason = "Desconectada / QR detectado (Posible suspensión por WhatsApp)"
                print(f"[{account_id}] 🚫 ALERTA: Cuenta bloqueada/desconectada. Marcando en BD...")
                db.update_account_state(account_id, "bloqueado", notes=reason, force=True)
                with self._lock:
                    if account_id in self.active_instances:
                        self.active_instances[account_id]["status"] = "BLOQUEADA"
                return True

            if has_restriction:
                reason = "Cuenta RESTRINGIDA TEMPORALMENTE por WhatsApp (spam/mensajeria masiva detectada)"
                print(f"[{account_id}] 🚫 ALERTA: Cuenta RESTRINGIDA. Marcando en BD y cerrando...")
                db.update_account_state(account_id, "bloqueado", notes=reason, force=True)
                with self._lock:
                    if account_id in self.active_instances:
                        self.active_instances[account_id]["status"] = "BLOQUEADA"
                return True

            return False
        except Exception as e:
            print(f"[{account_id}] Nota al verificar estado de bloqueo: {e}")
            return False

    def _open_chat_for_phone(self, page: Page, account_id: str, clean_phone: str) -> bool:
        """
        Abre un chat de WhatsApp usando el flujo nativo de 'Nuevo chat' (example_mkt).
          Paso 1: ESC + Clic en boton 'Nuevo chat'
          Paso 2: Esperar input de busqueda y escribir numero
          Paso 3: Esperar resultados de contacto
          Paso 4: Clic en la fila del contacto o ENTER
          Paso 5: Confirmar que el compose box quedo activo
        NOTA: CSS y XPath NO se pueden mezclar en un solo locator().
              Se intentan por separado.
        """
        print(f"[{account_id}] 🔍 [Nuevo chat] Abriendo para +{clean_phone}...")

        # Selectores CSS del boton Nuevo chat (sin XPath mezclado)
        NEW_CHAT_CSS = [
            '[title="Nuevo chat"]',
            '[aria-label="Nuevo chat"]',
            '[data-testid="new-chat-btn"]',
        ]
        # Selectores XPath del boton Nuevo chat (separados)
        NEW_CHAT_XPATH = [
            '//span[@data-icon="new-chat-outline"]/ancestor::button[1]',
            '//button[@aria-label="Nuevo chat"]',
            '//div[@title="Nuevo chat"]',
        ]

        # Selectores del input de busqueda (modal nuevo chat)
        SEARCH_CSS = [
            'input[data-tab="3"]',
            'div[data-tab="3"][contenteditable="true"]',
            'input.copyable-text',
        ]
        SEARCH_XPATH = [
            '//p[contains(@class,"copyable-text") and contains(@class,"x15bjb6t")]',
            '//input[@data-tab="3" and contains(@class,"html-input")]',
            '//input[contains(@class,"copyable-text")]',
        ]

        try:
            # ── Paso 1: Clic en boton 'Nuevo chat' ────────────────────────────────
            try:
                page.keyboard.press("Escape")
                time.sleep(0.4)
            except Exception:
                pass

            new_chat_btn = None

            for css_sel in NEW_CHAT_CSS:
                try:
                    loc = page.locator(css_sel).first
                    if loc.is_visible(timeout=2000):
                        new_chat_btn = loc
                        print(f"[{account_id}] ✓ Boton 'Nuevo chat' (CSS: {css_sel})")
                        break
                except Exception:
                    pass

            if not new_chat_btn:
                for xpath_sel in NEW_CHAT_XPATH:
                    try:
                        loc = page.locator(f"xpath={xpath_sel}").first
                        if loc.is_visible(timeout=2000):
                            new_chat_btn = loc
                            print(f"[{account_id}] ✓ Boton 'Nuevo chat' (XPath)")
                            break
                    except Exception:
                        pass

            if not new_chat_btn:
                print(f"[{account_id}] ❌ No se encontro el boton 'Nuevo chat'.")
                return False

            try:
                new_chat_btn.click(force=True, timeout=3000)
            except Exception:
                try:
                    new_chat_btn.evaluate("el => el.click()")
                except Exception:
                    pass

            # ── Paso 2: Esperar y localizar el input de busqueda ─────────────────
            search_loc = None

            for css_sel in SEARCH_CSS:
                try:
                    loc = page.locator(css_sel).first
                    loc.wait_for(state="visible", timeout=5000)
                    search_loc = loc
                    print(f"[{account_id}] ✓ Campo busqueda (CSS: {css_sel})")
                    break
                except Exception:
                    pass

            if not search_loc:
                for xpath_sel in SEARCH_XPATH:
                    try:
                        loc = page.locator(f"xpath={xpath_sel}").first
                        loc.wait_for(state="visible", timeout=5000)
                        search_loc = loc
                        print(f"[{account_id}] ✓ Campo busqueda (XPath)")
                        break
                    except Exception:
                        pass

            if not search_loc:
                print(f"[{account_id}] ❌ No se encontro el campo de busqueda del modal.")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return False

            # Clic, limpiar y tipear el numero (usando force=True y fallback de foco JS para evitar pointer interception)
            try:
                search_loc.click(force=True, timeout=3000)
            except Exception:
                try:
                    search_loc.evaluate("el => el.focus()")
                except Exception:
                    pass
            time.sleep(0.3)
            page.keyboard.press("Control+a")
            time.sleep(0.1)
            page.keyboard.press("Delete")
            time.sleep(0.1)
            page.keyboard.type(clean_phone, delay=35)

            # ── Paso 3: Esperar que aparezcan resultados de contacto ───────────
            try:
                contact_section = page.locator(
                    'xpath=//span[contains(text(),"Contactos en WhatsApp")'
                    ' or contains(text(),"Usuarios que no están en tus contactos")'
                    ' or contains(text(),"Usuarios que no estan en tus contactos")'
                    ' or contains(text(),"Contacts on WhatsApp")'
                    ' or contains(text(),"Resultados")]'
                ).first
                contact_section.wait_for(state="visible", timeout=4000)
                print(f"[{account_id}] ✓ Resultado de contacto detectado (+{clean_phone}).")
            except Exception:
                print(f"[{account_id}] ⚠️ Esperando renderizado de resultados...")
                time.sleep(1.0)

            # ── Paso 4: Clic en la fila del contacto / ENTER ─────────────────
            ROW_SELECTORS = [
                '[data-testid="cell-frame-container"]',
                'div[data-tab="4"][role="button"]',
                'div[role="button"]:has(span[title])',
                'div[role="listitem"]',
                'div[role="row"]',
                'li[role="option"]'
            ]

            opened = False
            for row_sel in ROW_SELECTORS:
                try:
                    contact_row = page.locator(row_sel).first
                    if contact_row.is_visible(timeout=1500):
                        try:
                            contact_row.click(force=True, timeout=2000)
                        except Exception:
                            contact_row.evaluate("el => el.click()")
                        opened = True
                        print(f"[{account_id}] ✓ Clic en fila de contacto ({row_sel}).")
                        break
                except Exception:
                    pass

            if not opened:
                # Intentar por coincidencia del número de teléfono en el title del span
                clean_digits = re.sub(r'[^\d]', '', clean_phone)
                if len(clean_digits) >= 7:
                    last_digits = clean_digits[-7:]
                    try:
                        target_span = page.locator(f'span[title*="{last_digits}"]').first
                        if target_span.is_visible(timeout=1500):
                            try:
                                target_span.click(force=True, timeout=2000)
                            except Exception:
                                target_span.evaluate("el => el.click()")
                            opened = True
                            print(f"[{account_id}] ✓ Clic en span por número de teléfono (*{last_digits}).")
                    except Exception:
                        pass

            if not opened:
                try:
                    search_loc.press("Enter")
                    print(f"[{account_id}] ✓ ENTER en campo de busqueda.")
                except Exception:
                    page.keyboard.press("Enter")
                    print(f"[{account_id}] ✓ ENTER global.")

            # ── Paso 5: Confirmar que el chat quedo abierto (espera activa) ────
            compose = None
            deadline = time.time() + 8
            while time.time() < deadline:
                compose = self._find_compose_input(page)
                if compose:
                    break
                time.sleep(0.5)

            if compose:
                print(f"[{account_id}] ✅ Chat para +{clean_phone} abierto y compose box listo.")
                return True

            # Ultimo intento: ENTER global + espera corta
            try:
                page.keyboard.press("Enter")
                time.sleep(1.2)
                compose = self._find_compose_input(page)
                if compose:
                    print(f"[{account_id}] ✅ Chat +{clean_phone} abierto (respaldo Enter final).")
                    return True
            except Exception:
                pass

            print(f"[{account_id}] ❌ No se pudo confirmar apertura del chat de +{clean_phone}.")
            return False

        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{account_id}] ❌ Error en flujo 'Nuevo chat' para +{clean_phone}: {err_msg}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def send_test_message(self, account_id: str, phone_number: str, message_text: str):
        """
        Envía un mensaje al número dado despachando la tarea al hilo ejecutor de Playwright.
        """
        return self._dispatch_to_instance(account_id, self._internal_send_test_message, phone_number, message_text, timeout=60)

    def _internal_send_test_message(self, page: Page, phone_number: str, message_text: str):
        account_id = getattr(page, "_account_id", "instance")
        try:
            # Verificar si la cuenta se encuentra bloqueada/desconectada por QR antes de enviar
            if self.check_if_blocked_or_logged_out(page, account_id):
                return False, f"La cuenta '{account_id}' se encuentra BLOQUEADA/Desconectada en WhatsApp (QR detectado)."

            clean_phone = "".join(filter(str.isdigit, phone_number))
            if not clean_phone:
                return False, "Número de teléfono inválido."

            # Formatear números de 10 dígitos (añadir prefijo de país si falta)
            if len(clean_phone) == 10:
                if clean_phone.startswith("3"):
                    clean_phone = "57" + clean_phone  # Colombia
                elif clean_phone.startswith("5"):
                    clean_phone = "52" + clean_phone  # México

            print(f"[{account_id}] 📤 Enviando mensaje a +{clean_phone}...")

            # Intentar abrir chat mediante flujo nativo de búsqueda primero
            chat_opened = self._open_chat_for_phone(page, account_id, clean_phone)

            if not chat_opened:
                print(f"[{account_id}] Flujo nativo no abrio el chat → intentando via URL direct...")
                target_url = f"https://web.whatsapp.com/send?phone={clean_phone}"
                page.goto(target_url, wait_until="domcontentloaded")
                human_delay(2, 3)
                if not page.is_closed():
                    self.dismiss_whatsapp_modals(page)
                    # ── Verificar bloqueo inmediatamente tras la navegacion URL ──
                    if self.check_if_blocked_or_logged_out(page, account_id):
                        return False, f"Cuenta '{account_id}' BLOQUEADA/Desconectada (QR detectado tras navegacion URL)."

            # Verificar si el número no existe en WhatsApp
            try:
                invalid_elem = page.locator(
                    "div:has-text('no está en WhatsApp'), "
                    "div:has-text('invalid'), "
                    "div:has-text('no es válido')"
                ).first
                if invalid_elem.is_visible(timeout=1500):
                    print(f"[{account_id}] ❌ +{clean_phone} no está en WhatsApp.")
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
                    return False, f"El número +{clean_phone} no está en WhatsApp."
            except Exception:
                pass

            # Localizar el campo de texto con _find_compose_input
            chat_input = self._find_compose_input(page)
            if not chat_input:
                # Intentar fallback con selector directo
                chat_input = page.locator(
                    'footer div[contenteditable="true"], '
                    'div[contenteditable="true"][data-tab="10"]'
                ).first
                try:
                    chat_input.wait_for(state="visible", timeout=8000)
                except Exception:
                    if not page.is_closed() and self.check_if_blocked_or_logged_out(page, account_id):
                        return False, f"Cuenta '{account_id}' BLOQUEADA/Desconectada en WhatsApp."
                    return False, f"No se pudo abrir el chat de +{clean_phone} (timeout de compose box)."

            human_delay(1, 2)

            # Hacer clic para asegurar el foco en el campo
            try:
                chat_input.click()
                time.sleep(0.4)
            except Exception:
                pass

            # Limpiar texto previo
            try:
                page.keyboard.press("Control+a")
                time.sleep(0.15)
                page.keyboard.press("Delete")
                time.sleep(0.15)
            except Exception:
                pass

            # ── Insertar texto multilínea (preservando newlines \n, emojis y estructura) ──
            normalized_text = message_text.replace("\r\n", "\n")
            inserted_ok = False

            try:
                inserted_ok = page.evaluate("""(text) => {
                    const input = document.querySelector('div[data-testid="conversation-compose-box-input"]') || 
                                  document.querySelector('footer div[contenteditable="true"]') ||
                                  document.querySelector('div[contenteditable="true"][data-tab="10"]') ||
                                  document.activeElement;
                    if (!input) return false;
                    
                    input.focus();
                    
                    // Limpiar contenido previo del input
                    try {
                        const sel = window.getSelection();
                        const range = document.createRange();
                        range.selectNodeContents(input);
                        sel.removeAllRanges();
                        sel.addRange(range);
                    } catch(e) {}

                    // Método 1: Evento DataTransfer 'paste' (Manejador nativo de Lexical/DraftJS en WhatsApp Web)
                    try {
                        const dt = new DataTransfer();
                        dt.setData('text/plain', text);
                        const pasteEvt = new ClipboardEvent('paste', {
                            clipboardData: dt,
                            bubbles: true,
                            cancelable: true
                        });
                        input.dispatchEvent(pasteEvt);
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        
                        const currentText = input.innerText || input.textContent || '';
                        if (currentText.trim().length > 0) {
                            if (text.includes('\\n')) {
                                const hasNewlines = currentText.includes('\\n') || input.querySelectorAll('p, br').length > 1;
                                if (hasNewlines) return true;
                            } else {
                                return true;
                            }
                        }
                    } catch(e) {}

                    return false;
                }""", normalized_text)
            except Exception as ev_err:
                print(f"[{account_id}] Nota en inserción JS de texto: {ev_err}")
                inserted_ok = False

            if not inserted_ok:
                print(f"[{account_id}] 📝 Inserción nativa de texto multilínea con insert_text + Shift+Enter...")
                try:
                    page.keyboard.press("Control+a")
                    time.sleep(0.1)
                    page.keyboard.press("Delete")
                    time.sleep(0.1)
                except Exception:
                    pass

                lines = normalized_text.split("\n")
                for idx, line in enumerate(lines):
                    if line:
                        try:
                            page.keyboard.insert_text(line)
                        except Exception:
                            page.keyboard.type(line, delay=5)
                    if idx < len(lines) - 1:
                        page.keyboard.press("Shift+Enter")
                        time.sleep(0.05)

            time.sleep(0.5)

            # ── Estrategia de envío ──────────────────────────────────────────
            sent = False
            try:
                send_btn = page.locator(
                    'button[aria-label*="Enviar"], '
                    'button[aria-label*="Send"], '
                    'span[data-icon="send"], '
                    'button span[data-icon="send"]'
                ).first
                send_btn.wait_for(state="visible", timeout=3000)
                send_btn.click()
                sent = True
                print(f"[{account_id}] ✅ Enviado con clic en botón Enviar.")
            except Exception:
                pass

            if not sent:
                try:
                    chat_input.press("Enter")
                    sent = True
                    print(f"[{account_id}] ✅ Enviado con tecla Enter.")
                except Exception:
                    pass

            if not sent:
                page.keyboard.press("Enter")
                print(f"[{account_id}] ✅ Enviado con keyboard.press(Enter) global.")

            human_delay(1, 2)

            # Presionar Escape para cerrar/deseleccionar el chat activo y volver a la lista principal
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
                page.keyboard.press("Escape")
                time.sleep(0.3)
            except Exception:
                pass

            print(f"[{account_id}] [OK] Mensaje enviado con éxito a +{clean_phone} y chat cerrado con Escape.")
            return True, f"Mensaje enviado con éxito a +{clean_phone}"

        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{account_id}] Error al enviar mensaje: {err_msg}")
            # Verificar si el error fue causado por un bloqueo de cuenta
            try:
                if not page.is_closed():
                    self.check_if_blocked_or_logged_out(page, account_id)
            except Exception:
                pass
            return False, f"Error al enviar mensaje: {err_msg}"

    def _open_chat_for_name(self, page: Page, account_id: str, contact_name: str) -> bool:
        """
        Abre un chat de WhatsApp usando el flujo nativo de 'Nuevo chat' buscando por NOMBRE del contacto (first_name + last_name).
          Paso 1: ESC + Clic en boton 'Nuevo chat'
          Paso 2: Esperar input de busqueda y escribir Nombre + Apellidos
          Paso 3: Esperar resultados de contacto
          Paso 4: Clic en la fila del contacto coincidente / ENTER
          Paso 5: Confirmar que el compose box quedo activo
        """
        clean_name = (contact_name or "").strip()
        if not clean_name:
            print(f"[{account_id}] ❌ Nombre de contacto vacio para busqueda de historial.")
            return False

        print(f"[{account_id}] 🔍 [Nuevo chat Historial] Buscando contacto amigo por NOMBRE: '{clean_name}'...")

        NEW_CHAT_CSS = [
            '[title="Nuevo chat"]',
            '[aria-label="Nuevo chat"]',
            '[data-testid="new-chat-btn"]',
            'button[aria-label*="Nuevo chat"]',
            'div[title*="Nuevo chat"]',
        ]
        NEW_CHAT_XPATH = [
            '//span[@data-icon="new-chat-outline"]/ancestor::button[1]',
            '//button[@aria-label="Nuevo chat"]',
            '//div[@title="Nuevo chat"]',
            '//span[@data-icon="chat"]/ancestor::button[1]',
        ]

        SEARCH_CSS = [
            'input[data-tab="3"]',
            'div[data-tab="3"][contenteditable="true"]',
            'input.copyable-text',
            'div[contenteditable="true"][data-tab="3"]',
            'p.copyable-text.x15bjb6t',
        ]
        SEARCH_XPATH = [
            '//p[contains(@class,"copyable-text") and contains(@class,"x15bjb6t")]',
            '//input[@data-tab="3" and contains(@class,"html-input")]',
            '//input[contains(@class,"copyable-text")]',
            '//div[@contenteditable="true" and @data-tab="3"]',
        ]

        try:
            # ── Paso 1: Clic en boton 'Nuevo chat' ────────────────────────────────
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
                page.keyboard.press("Escape")
                time.sleep(0.3)
            except Exception:
                pass

            new_chat_btn = None
            for css_sel in NEW_CHAT_CSS:
                try:
                    loc = page.locator(css_sel).first
                    if loc.is_visible(timeout=1500):
                        new_chat_btn = loc
                        print(f"[{account_id}] ✓ Boton 'Nuevo chat' (CSS: {css_sel})")
                        break
                except Exception:
                    pass

            if not new_chat_btn:
                for xpath_sel in NEW_CHAT_XPATH:
                    try:
                        loc = page.locator(f"xpath={xpath_sel}").first
                        if loc.is_visible(timeout=1500):
                            new_chat_btn = loc
                            print(f"[{account_id}] ✓ Boton 'Nuevo chat' (XPath)")
                            break
                    except Exception:
                        pass

            if not new_chat_btn:
                print(f"[{account_id}] ❌ No se encontro el boton 'Nuevo chat'.")
                return False

            try:
                new_chat_btn.click(force=True, timeout=3000)
            except Exception:
                try:
                    new_chat_btn.evaluate("el => el.click()")
                except Exception:
                    pass

            # ── Paso 2: Esperar y localizar el input de busqueda ─────────────────
            search_loc = None
            for css_sel in SEARCH_CSS:
                try:
                    loc = page.locator(css_sel).first
                    loc.wait_for(state="visible", timeout=4000)
                    search_loc = loc
                    print(f"[{account_id}] ✓ Campo busqueda (CSS: {css_sel})")
                    break
                except Exception:
                    pass

            if not search_loc:
                for xpath_sel in SEARCH_XPATH:
                    try:
                        loc = page.locator(f"xpath={xpath_sel}").first
                        loc.wait_for(state="visible", timeout=4000)
                        search_loc = loc
                        print(f"[{account_id}] ✓ Campo busqueda (XPath)")
                        break
                    except Exception:
                        pass

            if not search_loc:
                print(f"[{account_id}] ❌ No se encontro el campo de busqueda del modal.")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return False

            # Limpiar e ingresar Nombre + Apellidos
            try:
                search_loc.click(force=True, timeout=2000)
            except Exception:
                try:
                    search_loc.evaluate("el => el.focus()")
                except Exception:
                    pass
            time.sleep(0.3)
            page.keyboard.press("Control+a")
            time.sleep(0.1)
            page.keyboard.press("Delete")
            time.sleep(0.1)
            page.keyboard.type(clean_name, delay=40)

            # ── Paso 3: Esperar que aparezcan resultados de contacto ───────────
            time.sleep(1.8)

            # ── Paso 4: Clic en la fila del contacto coincidente ─────────────
            opened = False

            selectors_to_try = [
                f'span[title="{clean_name}"]',
                f'span[title*="{clean_name}"]',
                f'span:has-text("{clean_name}")',
                '[data-testid="cell-frame-container"]',
                'div[data-tab="4"][role="button"]',
                'div[role="row"]',
                'li[role="option"]'
            ]

            for sel in selectors_to_try:
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=1000):
                        try:
                            loc.click(force=True, timeout=2000)
                        except Exception:
                            loc.evaluate("el => el.click()")
                        opened = True
                        print(f"[{account_id}] ✓ Clic en resultado con selector '{sel}'.")
                        break
                except Exception:
                    pass

            if not opened:
                try:
                    search_loc.press("Enter")
                    print(f"[{account_id}] ✓ ENTER en campo de busqueda.")
                except Exception:
                    page.keyboard.press("Enter")
                    print(f"[{account_id}] ✓ ENTER global.")

            # ── Paso 5: Confirmar apertura del chat ────
            compose = None
            deadline = time.time() + 8
            while time.time() < deadline:
                compose = self._find_compose_input(page)
                if compose:
                    break
                time.sleep(0.5)

            if compose:
                print(f"[{account_id}] ✅ Chat para '{clean_name}' abierto y compose box listo.")
                return True

            print(f"[{account_id}] ❌ No se pudo abrir chat para '{clean_name}'.")
            return False

        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{account_id}] ❌ Error abriendo chat por nombre para '{clean_name}': {err_msg}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def send_warmup_peer_message(self, account_id: str, target_name: str, message_text: str, target_phone: str = "") -> bool:
        """Envía un mensaje de simulación/historial a otra cuenta amiga del sistema BUSCANDO POR NOMBRE (first_name + last_name)."""
        res = self._dispatch_to_instance(account_id, self._internal_send_warmup_peer_message, target_name, message_text, target_phone, timeout=60)
        if isinstance(res, tuple):
            return res[0]
        return bool(res)

    def _internal_send_warmup_peer_message(self, page: Page, target_name: str, message_text: str, target_phone: str = ""):
        account_id = getattr(page, "_account_id", "instance")
        try:
            if self.check_if_blocked_or_logged_out(page, account_id):
                return False, f"La cuenta '{account_id}' se encuentra BLOQUEADA/Desconectada en WhatsApp."

            print(f"[{account_id}] 💬 [Historial] Buscando contacto amigo por NOMBRE COMPLETO: '{target_name}'...")

            # Intentar abrir chat buscando únicamente por NOMBRE COMPLETO (first_name + last_name)
            chat_opened = self._open_chat_for_name(page, account_id, target_name)

            if not chat_opened:
                print(f"[{account_id}] 💬 Contacto '{target_name}' no fue encontrado en WhatsApp Web. Pasando al siguiente contacto...")
                try:
                    page.keyboard.press("Escape")
                    time.sleep(0.3)
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return False, f"Contacto amigo '{target_name}' no fue encontrado."

            # Localizar el campo de texto de composicion
            chat_input = self._find_compose_input(page)
            if not chat_input:
                return False, f"No se pudo localizar el compose box para '{target_name}'."

            human_delay(1, 2)
            try:
                chat_input.click()
                time.sleep(0.3)
            except Exception:
                pass

            try:
                page.keyboard.type(message_text, delay=25)
                time.sleep(0.3)
            except Exception:
                pass

            sent = False
            try:
                send_btn = page.locator(
                    'button[aria-label*="Enviar"], button[aria-label*="Send"], span[data-icon="send"]'
                ).first
                if send_btn.is_visible(timeout=2000):
                    send_btn.click()
                    sent = True
            except Exception:
                pass

            if not sent:
                try:
                    chat_input.press("Enter")
                    sent = True
                except Exception:
                    page.keyboard.press("Enter")
                    sent = True

            human_delay(1, 2)

            # Presionar Escape para cerrar/deseleccionar el chat activo y volver a la lista principal
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
                page.keyboard.press("Escape")
                time.sleep(0.3)
            except Exception:
                pass

            print(f"[{account_id}] 💬 [Historial] ✅ Mensaje enviado con éxito por nombre a '{target_name}' y chat cerrado con Escape.")
            return True, f"Mensaje de historial enviado por nombre a '{target_name}'."

        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[{account_id}] Error enviando mensaje de historial a '{target_name}': {err_msg}")
            return False, f"Error en historial: {err_msg}"

    def get_status_all(self, accounts_list: list[dict]) -> list[dict]:
        """Combina las cuentas almacenadas en disco con su estado en vivo."""
        with self._lock:
            active_ids = {acc_id: data["status"] for acc_id, data in self.active_instances.items()}

        result = []
        for acc in accounts_list:
            acc_id = acc["account_id"]
            live_status = active_ids.get(acc_id, "DESCONECTADA (En disco)")
            pending = self.pending_qrs.get(acc_id)

            result.append({
                **acc,
                "is_active": acc_id in active_ids,
                "status": live_status,
                "pending_qr": pending
            })
        return result

# Instancia global
runner = WhatsAppRunner()
