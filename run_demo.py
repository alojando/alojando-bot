#\!/usr/bin/env python3
"""Direct runner that bypasses cached .pyc"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Patch to avoid stale .pyc
import importlib

# Import fresh
from alojando_bot.models import ListingData, ComparisonResult
from alojando_bot.extractor import create_manual_listing
from alojando_bot.scraper import search_all_portals
from alojando_bot.analyzer import analyze, generate_summary
from alojando_bot.report_html import generate_html_report
from alojando_bot.report_word import generate_word_report
from alojando_bot.config import OUTPUT_DIR

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

print("""
    _    _        _                 _        ____   ___ _____ 
   / \\  | | ___  (_) __ _ _ __   __| | ___  | __ ) / _ \\_   _|
  / _ \\ | |/ _ \\ | |/ _` | '_ \\ / _` |/ _ \\ |  _ \\| | | || |  
 / ___ \\| | (_) || | (_| | | | | (_| | (_) || |_) | |_| || |  
/_/   \\_\\_|\\___/_/ |\\__,_|_| |_|\\__,_|\\___/ |____/ \\___/ |_|  
              |__/                                             
    Analizador Comparativo de Alquileres Temporarios v1.0
""")

# Demo data
listing = create_manual_listing({
    "title": "Moderno 2BR en Palermo Soho con balcon y vista",
    "property_type": "Apartamento",
    "description": "Hermoso departamento de 2 ambientes completamente equipado en el corazon de Palermo Soho.",
    "address": "Honduras 4800",
    "city": "Buenos Aires",
    "country": "Argentina",
    "neighborhood": "Palermo Soho",
    "price_per_night": "65",
    "currency": "USD",
    "bedrooms": "1",
    "beds": "2",
    "bathrooms": "1",
    "max_guests": "4",
    "amenities": "WiFi, Cocina equipada, Aire acondicionado, Smart TV, Lavarropas, Balcon, Ascensor",
    "rating": "4.7",
    "review_count": "45",
    "check_in": "15:00",
    "check_out": "11:00",
    "min_nights": "2",
    "host_name": "Jon",
    "superhost": "false",
    "cancellation_policy": "moderate",
})

print("=" * 60)
print("  PASO 1: Carga del anuncio (DEMO)")
print("=" * 60)
print(f"  Titulo: {listing.title}")
print(f"  Ubicacion: {listing.city}, {listing.country}")
print(f"  Precio: {listing.currency} {listing.price_per_night}/noche")
print(f"  Amenidades: {', '.join(listing.amenities[:8])}")

print("\n" + "=" * 60)
print("  PASO 2: Buscando comparables en portales")
print("=" * 60)

portal_results = search_all_portals(listing)
total = sum(len(v) for v in portal_results.values())
print(f"\nTotal comparables: {total}")
for portal, results in portal_results.items():
    print(f"  {portal.upper()}: {len(results)}")

print("\n" + "=" * 60)
print("  PASO 3: Analizando datos")
print("=" * 60)

result = analyze(listing, portal_results)
summary = generate_summary(result)
print(f"\n{summary}")

print("\n" + "=" * 60)
print("  PASO 4: Generando informes")
print("=" * 60)

os.makedirs(OUTPUT_DIR, exist_ok=True)
from datetime import datetime
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# HTML
html_path = os.path.join(OUTPUT_DIR, f"informe_{ts}.html")
try:
    html_file = generate_html_report(result, html_path)
    print(f"  HTML: {html_file}")
except Exception as e:
    print(f"  Error HTML: {e}")

# DOCX
docx_path = os.path.join(OUTPUT_DIR, f"informe_{ts}.docx")
try:
    docx_file = generate_word_report(result, docx_path)
    print(f"  DOCX: {docx_file}")
except Exception as e:
    print(f"  Error DOCX: {e}")
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("  LISTO\!")
print("=" * 60)
