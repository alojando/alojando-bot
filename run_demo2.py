#\!/usr/bin/env python3
"""Demo runner with simulated data"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

from alojando_bot.demo_data import get_demo_listing, get_demo_comparables
from alojando_bot.analyzer import analyze, generate_summary
from alojando_bot.report_html import generate_html_report
from alojando_bot.report_word import generate_word_report
from alojando_bot.config import OUTPUT_DIR
from datetime import datetime

print("ALOJANDO BOT - Demo con datos simulados")
print("=" * 60)

listing = get_demo_listing()
print(f"Anuncio: {listing.title}")
print(f"Ubicacion: {listing.city}, {listing.country}")
print(f"Precio: {listing.currency} {listing.price_per_night}/noche")

portal_results = get_demo_comparables()
total = sum(len(v) for v in portal_results.values())
print(f"\nComparables simulados: {total}")
for portal, results in portal_results.items():
    print(f"  {portal.upper()}: {len(results)}")

print("\nAnalizando...")
result = analyze(listing, portal_results)

summary = generate_summary(result)
print(f"\n{summary}")

print("\nGenerando informes...")
os.makedirs(OUTPUT_DIR, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

html_path = os.path.join(OUTPUT_DIR, f"informe_{ts}.html")
html_file = generate_html_report(result, html_path)
print(f"  HTML: {html_file}")

docx_path = os.path.join(OUTPUT_DIR, f"informe_{ts}.docx")
try:
    docx_file = generate_word_report(result, docx_path)
    print(f"  DOCX: {docx_file}")
except Exception as e:
    print(f"  Error DOCX: {e}")
    import traceback; traceback.print_exc()

print("\nLISTO\!")
