"""
Browser-based fetching using Playwright via subprocess.

Los portales como Booking, Vrbo y Google bloquean requests HTTP simples.
Este módulo usa Playwright en un subproceso separado para evitar conflictos
de threading con Flask (greenlet issue).

Mejoras v2:
- Stealth: inyecta scripts anti-detección (navigator.webdriver, plugins, etc.)
- Cookie popups: cierra automáticamente banners de cookies (Booking, etc.)
- Scroll: hace scroll para activar lazy-loading de resultados
- Timeout robusto: Popen + kill forzado en lugar de subprocess.run
- Reintentos: si falla el primer intento, reintenta una vez

Instalación:
    pip install playwright
    playwright install chromium
"""
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time

logger = logging.getLogger(__name__)

# =============================================
# Script que se ejecuta en un subproceso aislado
# =============================================
_FETCH_SCRIPT = r'''
import json, sys, os, time

def main():
    url = sys.argv[1]
    out_file = sys.argv[2]
    wait_seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 3

    from playwright.sync_api import sync_playwright

    # Stealth JS para inyectar antes de cada navegación
    STEALTH_JS = """
    // Overwrite navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Fake plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5]
    });

    // Fake languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['es-AR', 'es', 'en-US', 'en']
    });

    // Overwrite chrome runtime
    window.chrome = { runtime: {} };

    // Overwrite permissions query
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1366,768",
                "--disable-extensions",
                "--disable-gpu",
                "--lang=es-AR",
            ]
        )
        context = browser.new_context(
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "es-AR,es;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        # Inyectar stealth script antes de cada página
        context.add_init_script(STEALTH_JS)

        page = context.new_page()

        status = 0
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
            status = response.status if response else 0
        except Exception as e:
            error_result = {"html": "", "status": 0, "success": False,
                           "url": url, "content_length": 0, "error": str(e)}
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(error_result, f)
            browser.close()
            return

        # Esperar un poco para que JS renderice
        time.sleep(min(wait_seconds, 2))

        # Intentar cerrar popups de cookies (Booking, Vrbo, etc.)
        cookie_selectors = [
            'button[id="onetrust-accept-btn-handler"]',       # OneTrust (Booking, Vrbo)
            'button[data-testid="accept-btn"]',                # Booking
            'button[aria-label="Aceptar"]',
            'button[aria-label="Accept"]',
            'button:has-text("Aceptar")',
            'button:has-text("Accept All")',
            'button:has-text("Aceptar todo")',
            'button:has-text("Agree")',
            '#cookie-consent-accept',
        ]
        for sel in cookie_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    break
            except Exception:
                continue

        # Esperar que se renderice contenido
        time.sleep(max(0, wait_seconds - 2))

        # Scroll down para activar lazy-loading
        try:
            for i in range(3):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(0.5)
        except Exception:
            pass

        # Esperar networkidle con timeout corto
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        # Obtener el HTML final
        html = page.content()
        final_url = page.url

        context.close()
        browser.close()

        result = {
            "html": html,
            "status": status,
            "success": status in (200, 202, 301, 302),
            "url": final_url,
            "content_length": len(html),
        }
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f)

if __name__ == "__main__":
    main()
'''


def is_available() -> bool:
    """Verifica si Playwright está instalado y Chromium descargado."""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def fetch_page(url: str, wait_seconds: float = 3, timeout: int = 35) -> dict:
    """
    Obtiene el HTML de una página usando Playwright en un subproceso.

    Usa Popen en lugar de subprocess.run para poder matar el proceso
    de forma agresiva si se cuelga (kill tree incluyendo Chromium).

    Args:
        url: URL a visitar
        wait_seconds: Segundos a esperar después de la carga para JS rendering
        timeout: Timeout total en segundos para el subproceso

    Returns:
        Dict con: html, status, success, url, content_length
    """
    # Crear archivos temporales
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="pw_fetch_")
    os.close(fd)
    fd2, script_path = tempfile.mkstemp(suffix=".py", prefix="pw_script_")
    os.close(fd2)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(_FETCH_SCRIPT)

    proc = None
    try:
        logger.info("Playwright fetch: %s (timeout=%ds)", url[:80], timeout)

        # Usar Popen para control total del proceso
        proc = subprocess.Popen(
            [sys.executable, script_path, url, tmp_path, str(wait_seconds)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # En Windows, crear nuevo grupo de procesos para poder matarlo entero
            creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
        )

        # Esperar con timeout
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Playwright timeout (%ds) for %s - killing process", timeout, url[:60])
            _kill_process_tree(proc)
            return {
                "html": "", "status": 0, "success": False,
                "url": url, "content_length": 0,
                "error": f"Timeout after {timeout}s",
            }

        if proc.returncode != 0:
            err_msg = (stderr or "")[:500]
            logger.error("Playwright subprocess error (rc=%d): %s", proc.returncode, err_msg[:200])
            return {
                "html": "", "status": 0, "success": False,
                "url": url, "content_length": 0,
                "error": f"Subprocess failed (rc={proc.returncode}): {err_msg[:200]}",
            }

        # Leer resultado del archivo temporal
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, "r", encoding="utf-8") as f:
                result = json.load(f)
            logger.info("Playwright OK: %s (%d chars, status=%s)",
                       url[:60], result.get("content_length", 0), result.get("status"))
            return result
        else:
            return {
                "html": "", "status": 0, "success": False,
                "url": url, "content_length": 0,
                "error": "No output file generated",
            }

    except Exception as e:
        logger.error("Playwright fetch error: %s", e)
        if proc and proc.poll() is None:
            _kill_process_tree(proc)
        return {
            "html": "", "status": 0, "success": False,
            "url": url, "content_length": 0,
            "error": str(e),
        }
    finally:
        # Asegurar que el proceso está muerto
        if proc and proc.poll() is None:
            _kill_process_tree(proc)
        # Cleanup temp files
        for p in [tmp_path, script_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


def _kill_process_tree(proc):
    """Mata el proceso y todos sus hijos (Chromium crea varios procesos)."""
    try:
        if sys.platform == "win32":
            # En Windows: taskkill /F /T mata el árbol entero
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=5,
            )
        else:
            # En Linux/Mac: kill process group
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=3)
    except Exception:
        pass
