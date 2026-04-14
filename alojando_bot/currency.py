"""
Módulo de conversión de monedas para Alojando BOT.

Usa APIs gratuitas para obtener tipos de cambio actualizados.
Incluye cache para no hacer demasiadas requests.
"""
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Cache de tipos de cambio: {(from, to): (rate, timestamp)}
_cache = {}
_CACHE_TTL = 3600  # 1 hora


def get_exchange_rate(from_currency: str, to_currency: str) -> Optional[float]:
    """
    Obtiene el tipo de cambio entre dos monedas.

    Args:
        from_currency: Moneda origen (ej: "ARS", "EUR", "BRL")
        to_currency: Moneda destino (ej: "USD")

    Returns:
        Float con el tipo de cambio, o None si falla
    """
    from_currency = from_currency.upper().strip()
    to_currency = to_currency.upper().strip()

    if from_currency == to_currency:
        return 1.0

    # Revisar cache
    cache_key = (from_currency, to_currency)
    if cache_key in _cache:
        rate, ts = _cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            return rate

    # Intentar múltiples APIs
    rate = (
        _try_exchangerate_api(from_currency, to_currency)
        or _try_frankfurter_api(from_currency, to_currency)
        or _try_fixer_fallback(from_currency, to_currency)
    )

    if rate:
        _cache[cache_key] = (rate, time.time())
        # También cachear el inverso
        _cache[(to_currency, from_currency)] = (1.0 / rate, time.time())
        logger.info("Exchange rate: 1 %s = %.4f %s", from_currency, rate, to_currency)

    return rate


def convert_price(amount: float, from_currency: str, to_currency: str) -> float:
    """
    Convierte un precio de una moneda a otra.

    Args:
        amount: Monto a convertir
        from_currency: Moneda origen
        to_currency: Moneda destino

    Returns:
        Monto convertido, o el monto original si falla la conversión
    """
    if not amount or amount <= 0:
        return amount

    from_currency = from_currency.upper().strip()
    to_currency = to_currency.upper().strip()

    if from_currency == to_currency:
        return amount

    rate = get_exchange_rate(from_currency, to_currency)
    if rate:
        converted = round(amount * rate, 2)
        return converted

    logger.warning("No se pudo convertir %s %s -> %s", amount, from_currency, to_currency)
    return amount


def _try_exchangerate_api(from_curr: str, to_curr: str) -> Optional[float]:
    """API gratuita: exchangerate-api.com (sin API key, 1500 req/mes)."""
    import requests
    try:
        url = f"https://open.er-api.com/v6/latest/{from_curr}"
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("result") == "success":
                rates = data.get("rates", {})
                if to_curr in rates:
                    return float(rates[to_curr])
    except Exception as e:
        logger.debug("exchangerate-api failed: %s", e)
    return None


def _try_frankfurter_api(from_curr: str, to_curr: str) -> Optional[float]:
    """API gratuita: frankfurter.app (sin límite, pero no tiene ARS)."""
    import requests
    try:
        url = f"https://api.frankfurter.app/latest?from={from_curr}&to={to_curr}"
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            rates = data.get("rates", {})
            if to_curr in rates:
                return float(rates[to_curr])
    except Exception as e:
        logger.debug("frankfurter failed: %s", e)
    return None


def _try_fixer_fallback(from_curr: str, to_curr: str) -> Optional[float]:
    """Fallback: usar USD como pivote con exchangerate-api."""
    import requests
    if from_curr == "USD" or to_curr == "USD":
        return None  # Ya intentado directamente

    try:
        # from_curr -> USD -> to_curr
        url = f"https://open.er-api.com/v6/latest/USD"
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("result") == "success":
                rates = data.get("rates", {})
                if from_curr in rates and to_curr in rates:
                    # 1 USD = X from_curr, 1 USD = Y to_curr
                    # 1 from_curr = Y/X to_curr
                    return float(rates[to_curr]) / float(rates[from_curr])
    except Exception as e:
        logger.debug("fixer_fallback failed: %s", e)
    return None


def detect_currency_from_portal(portal: str, html_snippet: str = "") -> str:
    """
    Detecta la moneda que usa un portal basándose en el portal y el HTML.

    Args:
        portal: Nombre del portal
        html_snippet: Fragmento de HTML para detectar moneda

    Returns:
        Código de moneda (ej: "USD", "ARS", "EUR")
    """
    # Airbnb generalmente muestra en la moneda del usuario (default USD)
    if portal == "airbnb":
        return "USD"

    # Booking y Google: detectar del HTML
    if html_snippet:
        snippet = html_snippet[:5000].lower()
        if "ars" in snippet or "$ " in snippet:
            # Verificar si los precios son de rango ARS (> 10000)
            import re
            prices = re.findall(r'[\$]\s*([\d.]+)', snippet)
            for p in prices:
                clean = p.replace(".", "")
                try:
                    val = float(clean)
                    if val > 10000:  # Precio > 10000 seguro es ARS
                        return "ARS"
                except ValueError:
                    continue
        if "eur" in snippet or "€" in snippet:
            return "EUR"
        if "brl" in snippet or "r$" in snippet:
            return "BRL"

    # Defaults por portal para búsquedas en Argentina
    if portal in ("booking", "google"):
        return "ARS"

    return "USD"
