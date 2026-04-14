"""
Alojando BOT - Backend API (Flask)
"""
import os
import sys
import json
import logging
import uuid
from datetime import datetime
from threading import Thread

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
CORS(app)

analyses = {}
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "2.1.0", "docx_available": DOCX_AVAILABLE, "playwright_available": PLAYWRIGHT_AVAILABLE})


@app.route("/api/analyze", methods=["POST"])
def start_analysis():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Se requiere un body JSON"}), 400

    mode = data.get("mode", "")
    portals = data.get("portals", PORTALS)

    analysis_id = str(uuid.uuid4())[:8]
    analyses[analysis_id] = {
        "id": analysis_id, "status": "processing", "progress": 0,
        "message": "Iniciando analisis...", "result": None,
        "created_at": datetime.now().isoformat(),
    }

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

    if not listing_html and not listing_url:
        return jsonify({"error": "Se requiere listing_url o listing_html"}), 400

    analysis_id = str(uuid.uuid4())[:8]
    analyses[analysis_id] = {
        "id": analysis_id, "status": "processing", "progress": 0,
        "message": "Procesando datos del browser...", "result": None,
        "created_at": datetime.now().isoformat(),
    }

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

    thread = Thread(target=_run_browser_assisted_analysis, args=(analysis_id, listing, search_html, max_comparables))
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
    entry = analyses.get(analysis_id)
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
    import requests as req
    data = request.get_json()
    url = data.get("url", "") if data else ""
    force_browser = data.get("force_browser", False)
    if not url:
        return jsonify({"error": "Se requiere URL", "success": False}), 400

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


def _run_analysis(analysis_id, listing, portals, is_demo):
    try:
        entry = analyses[analysis_id]
        entry["progress"] = 20
        entry["message"] = "Buscando comparables en portales..."
        if is_demo:
            portal_results = get_demo_comparables()
        else:
            portal_results = search_all_portals(listing, portals)
        total = sum(len(v) for v in portal_results.values())
        entry["progress"] = 60
        entry["message"] = "Encontrados %d comparables. Analizando..." % total
        result = analyze(listing, portal_results)
        entry["progress"] = 80
        entry["message"] = "Generando informes..."
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
        entry["progress"] = 100
        entry["status"] = "completed"
        entry["message"] = "Analisis completado"
        entry["result"] = _serialize_result(result)
        entry["html_report"] = os.path.basename(html_path)
        entry["docx_report"] = os.path.basename(docx_path) if docx_path else None
    except Exception as e:
        logger.error("Error en analisis %s: %s", analysis_id, e, exc_info=True)
        analyses[analysis_id]["status"] = "error"
        analyses[analysis_id]["message"] = "Error: " + str(e)
        analyses[analysis_id]["progress"] = 0


def _run_browser_assisted_analysis(analysis_id, listing, search_html, max_comparables=20):
    try:
        entry = analyses[analysis_id]
        entry["progress"] = 30
        entry["message"] = "Parseando resultados de portales..."
        portal_results = search_with_browser_html(listing, search_html, max_results=max_comparables)
        total = sum(len(v) for v in portal_results.values())
        entry["progress"] = 60
        entry["message"] = "Encontrados %d comparables. Analizando..." % total
        result = analyze(listing, portal_results)
        entry["progress"] = 80
        entry["message"] = "Generando informes..."
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
        entry["progress"] = 100
        entry["status"] = "completed"
        entry["message"] = "Analisis completado"
        entry["result"] = _serialize_result(result)
        entry["html_report"] = os.path.basename(html_path)
        entry["docx_report"] = os.path.basename(docx_path) if docx_path else None
    except Exception as e:
        logger.error("Error en analisis browser-assisted %s: %s", analysis_id, e, exc_info=True)
        analyses[analysis_id]["status"] = "error"
        analyses[analysis_id]["message"] = "Error: " + str(e)
        analyses[analysis_id]["progress"] = 0


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
    return {
        "original": result.original.to_dict() if result.original else {},
        "comparables": [c.to_dict() for c in result.comparables],
        "stats": {
            "total_comparables": len(result.comparables),
            "avg_price": round(result.avg_price, 2),
            "median_price": round(result.median_price, 2),
            "min_price": round(result.min_price, 2),
            "max_price": round(result.max_price, 2),
            "price_percentile": round(result.price_percentile, 1),
            "suggested_price_low": round(result.suggested_price_low, 2),
            "suggested_price_high": round(result.suggested_price_high, 2),
            "avg_rating": round(result.avg_rating, 2),
        },
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
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    print("\n" + "=" * 50)
    print("  ALOJANDO BOT - Servidor Web v2.1")
    print("  http://localhost:%d" % port)
    if PLAYWRIGHT_AVAILABLE:
        print("  Playwright: DISPONIBLE (multi-portal)")
    else:
        print("  Playwright: NO DISPONIBLE (solo Airbnb)")
    print("=" * 50 + "\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
