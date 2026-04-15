"""
Alojando BOT - Backend API (Flask)
"""
import os
import sys
import json
import logging
import uuid
import ipaddress
import socket
from datetime import datetime
from threading import Thread, Lock
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alojando_bot.models import ListingData, ComparisonResult
from alojando_bot.extractor import extract_from_url, extract_from_html, create_manual_listing
from alojando_bot.scraper import (
    search_all_portals, build_search_urls, parse_search_html,
    search_with_browser_html
)
from alojando_bot.analyzer import analyze, generate_summary
from alojando_bot.report_html import generate_html_report
from alojando_bot.demo_data import get_demo_listing, get_demo_comparables
from alojando_bot.config import OUTPUT_DIR, PORTALS

try:
    from alojando_bot.report_word import generate_word_report
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    from alojando_bot.browser_fetch import is_available as pw_available, fetch_page as pw_fetch
    PLAYWRIGHT_AVAILABLE = pw_available()
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="frontend/build", static_url_path="")

# CORS: restringir a orígenes conocidos (localhost para dev, Railway para prod)
allowed_origins = os.environ.get("CORS_ORIGINS", "").split(",") if os.environ.get("CORS_ORIGINS") else None
if allowed_origins:
    CORS(app, origins=allowed_origins)
else:
    # En desarrollo, permitir localhost en cualquier puerto
    CORS(app, origins=[
        r"http://localhost:\d+",
        r"http://127\.0\.0\.1:\d+",
    ])

# Rate limiting
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(get_remote_address, app=app, default_limits=["200 per hour"])
except ImportError:
    limiter = None
    logger.warning("flask-limiter no instalado - sin rate limiting")

# Thread-safe analyses storage
analyses = {}
_analyses_lock = Lock()
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _set_analysis(analysis_id, data):
    """Thread-safe update de análisis."""
    with _analyses_lock:
        analyses[analysis_id] = data


def _update_analysis(analysis_id, **kwargs):
    """Thread-safe partial update de análisis."""
    with _analyses_lock:
        if analysis_id in analyses:
            analyses[analysis_id].update(kwargs)


def _get_analysis(analysis_id):
    """Thread-safe get de análisis."""
    with _analyses_lock:
        return analyses.get(analysis_id, {}).copy()


def _validate_url(url: str) -> tuple:
    """
    Valida una URL para prevenir SSRF.
    Returns: (is_valid: bool, error_message: str)
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL inválida"

    if parsed.scheme not in ("http", "https"):
        return False, "Solo se permiten URLs HTTP/HTTPS"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL sin hostname"

    # Bloquear hosts internos
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
    if hostname.lower() in blocked_hosts:
        return False, "No se permiten URLs internas"

    # Bloquear IPs privadas
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return False, "No se permiten IPs privadas o reservadas"
    except ValueError:
        # Es un hostname, no una IP - resolver y verificar
        try:
            resolved = socket.gethostbyname(hostname)
            ip = ipaddress.ip_address(resolved)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                return False, "El hostname resuelve a una IP privada"
        except socket.gaierror:
            pass  # No se pudo resolver, dejar pasar (fallará al conectarse)

    # Bloquear protocolos peligrosos en el path
    if "file:" in url.lower() or "javascript:" in url.lower():
        return False, "Protocolo no permitido"

    return True, ""


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "2.5.0", "docx_available": DOCX_AVAILABLE, "playwright_available": PLAYWRIGHT_AVAILABLE})


@app.route("/api/analyze", methods=["POST"])
def start_analysis():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Se requiere un body JSON"}), 400

    mode = data.get("mode", "")
    portals = data.get("portals", PORTALS)

    analysis_id = str(uuid.uuid4())[:8]
    _set_analysis(analysis_id, {
        "id": analysis_id, "status": "processing", "progress": 0,
        "message": "Iniciando analisis...", "result": None,
        "created_at": datetime.now().isoformat(),
    })

    try:
        if mode == "url":
            url = data.get("url", "").strip()
            if not url:
                return jsonify({"error": "Se requiere una URL"}), 400
            pre_html = data.get("html", None)
            listing = extract_from_url(url, html=pre_html)
        elif mode == "manual":
            manual_data = data.get("data", {})
            if not manual_data:
                return jsonify({"error": "Se requieren datos del anuncio"}), 400
            listing = create_manual_listing(manual_data)
        elif mode == "demo":
            listing = get_demo_listing()
        else:
            return jsonify({"error": "Modo invalido. Usar: url, manual o demo"}), 400
    except Exception as e:
        return jsonify({"error": "Error al procesar input: " + str(e)}), 400

    thread = Thread(target=_run_analysis, args=(analysis_id, listing, portals, mode == "demo"))
    thread.daemon = True
    thread.start()

    return jsonify({
        "analysis_id": analysis_id, "status": "processing",
        "message": "Analisis iniciado", "listing": listing.to_dict(),
    })


@app.route("/api/analyze/browser-assisted", methods=["POST"])
def start_browser_assisted_analysis():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Se requiere un body JSON"}), 400

    listing_url = data.get("listing_url", "")
    listing_html = data.get("listing_html", "")
    search_html = data.get("search_html", {})
    manual_price = float(data.get("manual_price", 0) or 0)
    currency = data.get("currency", "USD")
    max_comparables = int(data.get("max_comparables", 20) or 20)
    manual_bedrooms = int(data.get("bedrooms", 0) or 0)
    manual_max_guests = int(data.get("max_guests", 0) or 0)
    manual_property_type = data.get("property_type", "")
    manual_amenities = data.get("amenities", [])
    compare_with_hotels = bool(data.get("compare_with_hotels", False))

    if not listing_html and not listing_url:
        return jsonify({"error": "Se requiere listing_url o listing_html"}), 400

    analysis_id = str(uuid.uuid4())[:8]
    _set_analysis(analysis_id, {
        "id": analysis_id, "status": "processing", "progress": 0,
        "message": "Procesando datos del browser...", "result": None,
        "created_at": datetime.now().isoformat(),
    })

    try:
        if listing_html:
            listing = extract_from_url(listing_url, html=listing_html)
        else:
            listing = extract_from_url(listing_url)
        # Apply manual price if extractor could not get it
        if manual_price > 0 and listing.price_per_night == 0:
            listing.price_per_night = manual_price
        if currency:
            listing.currency = currency
        # Apply manual property type, bedrooms and amenities
        if manual_property_type and not listing.property_type:
            listing.property_type = manual_property_type
        if manual_bedrooms > 0 and listing.bedrooms == 0:
            listing.bedrooms = manual_bedrooms
        if manual_max_guests > 0 and listing.max_guests == 0:
            listing.max_guests = manual_max_guests
        if manual_amenities:
            existing = set(listing.amenities) if listing.amenities else set()
            for a in manual_amenities:
                existing.add(a)
            listing.amenities = list(existing)
    except Exception as e:
        return jsonify({"error": "Error al extraer datos: " + str(e)}), 400

    thread = Thread(target=_run_browser_assisted_analysis,
                    args=(analysis_id, listing, search_html, max_comparables,
                          compare_with_hotels, manual_property_type))
    thread.daemon = True
    thread.start()

    return jsonify({
        "analysis_id": analysis_id, "status": "processing",
        "message": "Analisis iniciado (browser-assisted)", "listing": listing.to_dict(),
    })


@app.route("/api/search-urls", methods=["POST"])
def get_search_urls():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Se requiere un body JSON"}), 400
    portals = data.get("portals", PORTALS)
    radius_meters = int(data.get("radius_meters", 0) or 0)
    manual_address = data.get("address", "").strip()
    manual_lat = float(data.get("latitude", 0) or 0)
    manual_lng = float(data.get("longitude", 0) or 0)
    manual_bedrooms = int(data.get("bedrooms", 0) or 0)
    manual_max_guests = int(data.get("max_guests", 0) or 0)
    manual_property_type = data.get("property_type", "")
    manual_checkin = data.get("checkin", "").strip()
    manual_checkout = data.get("checkout", "").strip()
    try:
        if "listing" in data:
            listing = create_manual_listing(data["listing"])
        elif "url" in data:
            listing = extract_from_url(data["url"], html=data.get("html"))
        else:
            return jsonify({"error": "Se requiere 'listing' o 'url'"}), 400
        # Override con dirección manual si se proporcionó
        if manual_address:
            listing.address = manual_address
            parts = [p.strip() for p in manual_address.split(",")]
            if len(parts) >= 2:
                listing.neighborhood = parts[0]
                listing.city = parts[1]
            if len(parts) >= 3:
                listing.country = parts[-1]
        if manual_lat and manual_lng:
            listing.latitude = manual_lat
            listing.longitude = manual_lng
        if manual_bedrooms > 0 and listing.bedrooms == 0:
            listing.bedrooms = manual_bedrooms
        if manual_max_guests > 0 and listing.max_guests == 0:
            listing.max_guests = manual_max_guests
        if manual_property_type and not listing.property_type:
            listing.property_type = manual_property_type
        # Geocodificar dirección si tenemos dirección pero no coordenadas
        if (manual_address or listing.address) and not (listing.latitude and listing.longitude):
            addr = manual_address or listing.address
            coords = _geocode_address(addr)
            if coords:
                listing.latitude, listing.longitude = coords
                logger.info("Geocoded '%s' -> %s, %s", addr, listing.latitude, listing.longitude)
        urls = build_search_urls(listing, portals, radius_meters=radius_meters, checkin=manual_checkin, checkout=manual_checkout)
        return jsonify({"search_urls": urls, "listing": listing.to_dict()})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/parse-search", methods=["POST"])
def parse_search():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Se requiere un body JSON"}), 400
    portal = data.get("portal", "")
    html = data.get("html", "")
    max_results = int(data.get("max_results", 0) or 0)
    if not portal or not html:
        return jsonify({"error": "Se requieren 'portal' y 'html'"}), 400
    results = parse_search_html(portal, html, max_results=max_results)
    return jsonify({"portal": portal, "count": len(results), "results": [r.to_dict() for r in results]})


@app.route("/api/analyze/<analysis_id>", methods=["GET"])
def get_analysis(analysis_id):
    entry = _get_analysis(analysis_id)
    if not entry:
        return jsonify({"error": "Analisis no encontrado"}), 404
    return jsonify(entry)


@app.route("/api/report/<filename>", methods=["GET"])
def download_report(filename):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Archivo no encontrado"}), 404
    return send_file(filepath, as_attachment=True)


@app.route("/api/portals", methods=["GET"])
def get_portals():
    return jsonify({"portals": PORTALS})


@app.route("/api/demo-listing", methods=["GET"])
def get_demo():
    listing = get_demo_listing()
    return jsonify(listing.to_dict())


@app.route("/api/proxy-fetch", methods=["POST"])
def proxy_fetch():
    if limiter:
        # Rate limit: 30 requests per minute for proxy-fetch
        try:
            limiter.limit("30 per minute")(lambda: None)()
        except Exception:
            pass
    import requests as req
    data = request.get_json()
    url = data.get("url", "") if data else ""
    force_browser = data.get("force_browser", False)
    if not url:
        return jsonify({"error": "Se requiere URL", "success": False}), 400

    # Validar URL para prevenir SSRF
    is_valid, error_msg = _validate_url(url)
    if not is_valid:
        return jsonify({"error": error_msg, "success": False}), 400

    # Portales que necesitan browser real (bloquean requests HTTP simples)
    needs_browser = any(domain in url for domain in ["booking.com", "vrbo.com", "google.com/travel"])

    # Usar Playwright si disponible para portales que lo necesitan
    if PLAYWRIGHT_AVAILABLE and (needs_browser or force_browser):
        logger.info("Usando Playwright para: %s", url[:80])
        result = pw_fetch(url, wait_seconds=3, timeout=35)
        result["method"] = "playwright"

        # Si Vrbo devuelve 429 (rate limit), reintentar con más espera
        if result.get("status") == 429 and "vrbo.com" in url:
            logger.info("Vrbo 429 - reintentando con mas espera...")
            import time
            time.sleep(3)
            result = pw_fetch(url, wait_seconds=6, timeout=40)
            result["method"] = "playwright-retry"

        return jsonify(result)

    # requests HTTP con headers de browser (para Airbnb y fallback)
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        session = req.Session()
        resp = session.get(url, headers=browser_headers, timeout=30, allow_redirects=True)
        return jsonify({
            "html": resp.text, "status": resp.status_code,
            "success": resp.status_code == 200,
            "url": resp.url, "content_length": len(resp.text),
            "method": "requests",
        })
    except req.RequestException as e:
        logger.warning("Proxy fetch failed for %s: %s", url, e)
        return jsonify({"error": str(e), "success": False, "status": 0, "method": "requests"})


def _run_analysis_common(analysis_id, listing, portal_results_fn, search_progress_msg="Buscando comparables...", search_progress_pct=20):
    """Función común para ejecutar análisis (directa o browser-assisted)."""
    try:
        _update_analysis(analysis_id, progress=search_progress_pct, message=search_progress_msg)
        portal_results = portal_results_fn()
        total = sum(len(v) for v in portal_results.values())
        portal_detail = ", ".join(f"{p}: {len(v)}" for p, v in portal_results.items() if v)
        _update_analysis(analysis_id, progress=70,
                        message="Encontrados %d comparables (%s). Analizando..." % (total, portal_detail) if portal_detail else "Encontrados %d comparables. Analizando..." % total)
        result = analyze(listing, portal_results)
        _update_analysis(analysis_id, progress=80, message="Generando informes...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = os.path.join(OUTPUT_DIR, "informe_%s_%s.html" % (analysis_id, timestamp))
        generate_html_report(result, html_path)
        docx_path = None
        if DOCX_AVAILABLE:
            docx_path = os.path.join(OUTPUT_DIR, "informe_%s_%s.docx" % (analysis_id, timestamp))
            try:
                generate_word_report(result, docx_path)
            except Exception:
                docx_path = None
        _update_analysis(analysis_id,
                        progress=100, status="completed",
                        message="Analisis completado",
                        result=_serialize_result(result),
                        html_report=os.path.basename(html_path),
                        docx_report=os.path.basename(docx_path) if docx_path else None)
    except Exception as e:
        logger.error("Error en analisis %s: %s", analysis_id, e, exc_info=True)
        _update_analysis(analysis_id, status="error", message="Error: " + str(e), progress=0)


def _run_analysis(analysis_id, listing, portals, is_demo):
    def get_results():
        if is_demo:
            return get_demo_comparables()
        return search_all_portals(listing, portals)
    _run_analysis_common(analysis_id, listing, get_results, "Buscando comparables en portales...", 20)


def _run_browser_assisted_analysis(analysis_id, listing, search_html, max_comparables=20,
                                    compare_with_hotels=False, user_property_type=""):
    def get_results():
        return search_with_browser_html(listing, search_html, max_results=max_comparables,
                                       compare_with_hotels=compare_with_hotels,
                                       user_property_type=user_property_type)
    _run_analysis_common(analysis_id, listing, get_results, "Parseando resultados de portales...", 30)


# Serve frontend
@app.route("/")
def serve_frontend():
    index_path = os.path.join(app.static_folder or "", "index.html")
    if os.path.exists(index_path):
        return send_from_directory(app.static_folder, "index.html")
    fallback = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    if os.path.exists(fallback):
        return send_file(fallback)
    return "<h1>Alojando BOT API</h1><p>Frontend no encontrado.</p>"


@app.route("/<path:path>")
def serve_static(path):
    if app.static_folder and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    index_path = os.path.join(app.static_folder or "", "index.html")
    if os.path.exists(index_path):
        return send_from_directory(app.static_folder, "index.html")
    fallback = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    if os.path.exists(fallback):
        return send_file(fallback)
    return jsonify({"error": "Not found"}), 404


def _serialize_result(result):
    import statistics as stats_mod
    comparables = result.comparables or []
    prices = [c.price_per_night for c in comparables if c.price_per_night > 0]
    ratings = [c.rating for c in comparables if c.rating > 0]

    # Estadísticas por portal
    portal_stats = {}
    for c in comparables:
        portal = c.source or "unknown"
        if portal not in portal_stats:
            portal_stats[portal] = {"count": 0, "prices": [], "ratings": [], "with_amenities": 0}
        portal_stats[portal]["count"] += 1
        if c.price_per_night > 0:
            portal_stats[portal]["prices"].append(c.price_per_night)
        if c.rating > 0:
            portal_stats[portal]["ratings"].append(c.rating)
        if c.amenities:
            portal_stats[portal]["with_amenities"] += 1

    portal_summary = {}
    for portal, data in portal_stats.items():
        portal_summary[portal] = {
            "count": data["count"],
            "avg_price": round(stats_mod.mean(data["prices"]), 2) if data["prices"] else 0,
            "min_price": round(min(data["prices"]), 2) if data["prices"] else 0,
            "max_price": round(max(data["prices"]), 2) if data["prices"] else 0,
            "avg_rating": round(stats_mod.mean(data["ratings"]), 2) if data["ratings"] else 0,
            "with_amenities": data["with_amenities"],
        }

    # Distribución de precios vs usuario
    original = result.original
    price_distribution = {"cheaper": 0, "similar": 0, "more_expensive": 0}
    if original and original.price_per_night > 0 and prices:
        low = original.price_per_night * 0.85
        high = original.price_per_night * 1.15
        for p in prices:
            if p < low:
                price_distribution["cheaper"] += 1
            elif p > high:
                price_distribution["more_expensive"] += 1
            else:
                price_distribution["similar"] += 1

    # Desviación estándar del precio
    price_stdev = round(stats_mod.stdev(prices), 2) if len(prices) >= 2 else 0

    # Top comparables por precio más cercano al usuario
    top_matches = []
    if original and original.price_per_night > 0:
        sorted_by_proximity = sorted(
            [c for c in comparables if c.price_per_night > 0],
            key=lambda c: abs(c.price_per_night - original.price_per_night)
        )
        for c in sorted_by_proximity[:5]:
            top_matches.append({
                "title": c.title,
                "source": c.source,
                "price": c.price_per_night,
                "rating": c.rating,
                "url": c.url,
                "diff_pct": round(((c.price_per_night - original.price_per_night) / original.price_per_night) * 100, 1) if original.price_per_night > 0 else 0,
            })

    return {
        "original": result.original.to_dict() if result.original else {},
        "comparables": [c.to_dict() for c in comparables],
        "stats": {
            "total_comparables": len(comparables),
            "avg_price": round(result.avg_price, 2),
            "median_price": round(result.median_price, 2),
            "min_price": round(result.min_price, 2),
            "max_price": round(result.max_price, 2),
            "price_stdev": price_stdev,
            "price_percentile": round(result.price_percentile, 1),
            "suggested_price_low": round(result.suggested_price_low, 2),
            "suggested_price_high": round(result.suggested_price_high, 2),
            "avg_rating": round(result.avg_rating, 2),
            "total_with_prices": len(prices),
            "total_with_ratings": len(ratings),
        },
        "portal_stats": portal_summary,
        "price_distribution": price_distribution,
        "top_matches": top_matches,
        "analysis": {
            "rating_comparison": result.rating_comparison,
            "common_amenities": result.common_amenities,
            "missing_amenities": result.missing_amenities,
            "unique_amenities": result.unique_amenities,
        },
        "suggestions": {
            "pricing": result.pricing_suggestions,
            "title": result.title_suggestions,
            "description": result.description_suggestions,
            "photos": result.photo_suggestions,
            "amenities": result.amenity_suggestions,
            "general": result.general_suggestions,
        },
    }


def _geocode_address(address: str):
    """Geocodifica una dirección usando Nominatim (OpenStreetMap)."""
    import requests as req
    try:
        resp = req.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "AlojandoBot/2.1"},
            timeout=10,
        )
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        logger.warning("Geocoding failed for '%s': %s", address, e)
    return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    print("\n" + "=" * 50)
    print("  ALOJANDO BOT - Servidor Web v2.5")
    print("  http://localhost:%d" % port)
    if PLAYWRIGHT_AVAILABLE:
        print("  Playwright: DISPONIBLE (multi-portal)")
    else:
        print("  Playwright: NO DISPONIBLE (solo Airbnb)")
    print("=" * 50 + "\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
