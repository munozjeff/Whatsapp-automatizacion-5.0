import random
import time
from playwright.sync_api import Page, BrowserContext

# Script de evasión anti-bot inyectado antes de cargar cualquier página
STEALTH_JS = """
// Ocultar webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Emular plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

// Emular idiomas
Object.defineProperty(navigator, 'languages', {
    get: () => ['es-ES', 'es', 'en-US', 'en']
});

// Emular objeto chrome
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

// Permisos falsificados
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);
"""

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

def apply_stealth_to_context(context: BrowserContext):
    """Aplica configuraciones stealth al contexto de Playwright."""
    context.add_init_script(STEALTH_JS)

def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)

def human_delay(min_sec: float = 0.5, max_sec: float = 2.0, stop_checker=None) -> bool:
    """Pausa aleatoria para simular comportamiento humano, interrumpible en tiempo real si stop_checker() es True."""
    target = random.uniform(min_sec, max_sec)
    step = 0.2
    elapsed = 0.0
    while elapsed < target:
        if stop_checker and stop_checker():
            return False
        sleep_time = min(step, target - elapsed)
        time.sleep(sleep_time)
        elapsed += sleep_time
    return True

def interruptible_sleep(seconds: float, stop_checker=None, step: float = 0.2) -> bool:
    """Espera interrumpible en intervalos cortos para permitir respuesta en tiempo real a señales de pausa/stop."""
    elapsed = 0.0
    while elapsed < seconds:
        if stop_checker and stop_checker():
            return False
        sleep_time = min(step, seconds - elapsed)
        time.sleep(sleep_time)
        elapsed += sleep_time
    return True

def human_type(page: Page, selector: str, text: str):
    """Tipea texto caracter por caracter con variaciones de velocidad humanas."""
    element = page.locator(selector)
    element.click()
    human_delay(0.2, 0.5)
    
    for char in text:
        element.type(char)
        # Retardo entre teclas (entre 40ms y 180ms)
        time.sleep(random.uniform(0.04, 0.18))
        # Ocasionalmente hace una pausa mas larga simulando pensar
        if random.random() < 0.05:
            time.sleep(random.uniform(0.3, 0.8))
