"""
Alojando BOT - CLI Principal
Analizador comparativo de alquileres temporarios.
"""
import os
import sys
import json
import argparse
import logging
from datetime import datetime

from .models import ListingData
from .extractor import extract_from_url, create_manual_listing, interactive_input, detect_portal
from .scraper import search_all_portals
from .analyzer import analyze, generate_summary
from .report_html import generate_html_report
from .config import OUTPUT_DIR, PORTALS

# python-docx depende de lxml que puede no estar disponible en algunos sistemas
try:
    from .report_word import generate_word_report
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


BANNER = r"""
    _    _        _                 _        ____   ___ _____
   / \  | | ___  (_) __ _ _ __   __| | ___  | __ ) / _ \_   _|
  / _ \ | |/ _ \ | |/ _` | '_ \ / _` |/ _ \ |  _ \| | | || |
 / ___ \| | (_) || | (_| | | | | (_| | (_) || |_) | |_| || |
/_/   \_\_|\___/_/ |\__,_|_| |_|\__,_|\___/ |____/ \___/ |_|
              |__/
    Analizador Comparativo de Alquileres Temporarios v1.0
"""


def main():
    parser = argparse.ArgumentParser(
        description="Alojando BOT - Analizador comparativo de alquileres temporarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  # Analizar desde URL
  python -m alojando_bot --url https://www.airbnb.com/rooms/12345

  # Entrada manual interactiva
  python -m alojando_bot --manual

  # Desde archivo JSON
  python -m alojando_bot --json datos_anuncio.json

  # Especificar portales y formato
  python -m alojando_bot --url URL --portals airbnb booking --format html

  # Con datos manuales inline
  python -m alojando_bot --data '{"title":"Mi depto","city":"Buenos Aires","price":80,"bedrooms":2}'
        """
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", "-u", help="URL del anuncio a analizar")
    input_group.add_argument("--manual", "-m", action="store_true", help="Modo interactivo (ingreso manual)")
    input_group.add_argument("--json", "-j", help="Archivo JSON con datos del anuncio")
    input_group.add_argument("--data", "-d", help="JSON inline con datos del anuncio")
    input_group.add_argument("--demo", action="store_true",
                             help="Ejecutar con datos de demostración")

    parser.add_argument("--portals", "-p", nargs="+", choices=PORTALS, default=PORTALS,
                        help="Portales donde buscar (default: todos)")
    parser.add_argument("--format", "-f", choices=["html", "docx", "both"], default="both",
                        help="Formato del informe (default: both)")
    parser.add_argument("--output", "-o", help="Directorio de salida para los informes")
    parser.add_argument("--max-results", type=int, default=10,
                        help="Máximo de comparables por portal (default: 10)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Modo verbose")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print(BANNER)

    # Configurar directorio de salida
    output_dir = args.output or OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    # 1. Obtener datos del anuncio
    print("\n" + "=" * 60)
    print("  PASO 1: Carga del anuncio")
    print("=" * 60)

    if args.demo:
        from .demo_data import get_demo_listing, get_demo_comparables
        listing = get_demo_listing()
        print(f"Usando datos de demostración: {listing.title}")
    elif args.url:
        print(f"Extrayendo datos de: {args.url}")
        listing = extract_from_url(args.url)
        print(f"Anuncio extraído: {listing.title}")
    elif args.manual:
        listing = interactive_input()
    elif args.json:
        with open(args.json, "r", encoding="utf-8") as f:
            data = json.load(f)
        listing = create_manual_listing(data)
        print(f"Datos cargados desde: {args.json}")
    elif args.data:
        data = json.loads(args.data)
        listing = create_manual_listing(data)
        print(f"Datos cargados: {listing.title}")

    # Mostrar resumen del anuncio
    _print_listing_summary(listing)

    # 2. Buscar comparables
    print("\n" + "=" * 60)
    print("  PASO 2: Buscando comparables en portales")
    print("=" * 60)

    if args.demo:
        # En modo demo, usar datos simulados
        from .demo_data import get_demo_comparables
        portal_results = get_demo_comparables()
        print("(Usando comparables simulados para demostración)")
    else:
        portal_results = search_all_portals(listing, args.portals)

    total = sum(len(v) for v in portal_results.values())
    print(f"\nTotal de comparables encontrados: {total}")
    for portal, results in portal_results.items():
        print(f"  {portal.upper()}: {len(results)} resultados")

    # 3. Analizar
    print("\n" + "=" * 60)
    print("  PASO 3: Analizando datos")
    print("=" * 60)

    result = analyze(listing, portal_results)

    # Mostrar resumen en consola
    summary = generate_summary(result)
    print(f"\n{summary}")

    # 4. Generar informes
    print("\n" + "=" * 60)
    print("  PASO 4: Generando informes")
    print("=" * 60)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    generated_files = []

    if args.format in ("html", "both"):
        html_path = os.path.join(output_dir, f"informe_{timestamp}.html")
        try:
            html_file = generate_html_report(result, html_path)
            generated_files.append(html_file)
            print(f"Informe HTML: {html_file}")
        except Exception as e:
            logger.error(f"Error al generar HTML: {e}")

    if args.format in ("docx", "both"):
        if not DOCX_AVAILABLE:
            print("\n  [!] Generacion Word no disponible (falta python-docx/lxml).")
            print("      El informe HTML contiene toda la informacion con graficos interactivos.")
            print("      Para habilitar Word: pip install python-docx")
        else:
            docx_path = os.path.join(output_dir, f"informe_{timestamp}.docx")
            try:
                docx_file = generate_word_report(result, docx_path)
                generated_files.append(docx_file)
                print(f"Informe Word: {docx_file}")
            except Exception as e:
                logger.error(f"Error al generar DOCX: {e}")
                print(f"  El informe HTML fue generado correctamente.")

    # Resumen final
    print("\n" + "=" * 60)
    print("  LISTO!")
    print("=" * 60)
    print(f"\nArchivos generados:")
    for f in generated_files:
        print(f"  -> {f}")

    if not generated_files:
        print("  No se generaron archivos. Revisá los errores arriba.")

    return result


def _print_listing_summary(listing: ListingData):
    """Imprime un resumen del anuncio en consola."""
    print(f"\n--- Tu anuncio ---")
    if listing.title:
        print(f"  Titulo: {listing.title}")
    if listing.property_type:
        print(f"  Tipo: {listing.property_type}")
    location = ", ".join(filter(None, [listing.address, listing.neighborhood, listing.city, listing.country]))
    if location:
        print(f"  Ubicacion: {location}")
    if listing.price_per_night > 0:
        print(f"  Precio: {listing.currency} {listing.price_per_night:.0f}/noche")
    if listing.bedrooms > 0:
        print(f"  Dormitorios: {listing.bedrooms} | Camas: {listing.beds} | Banos: {listing.bathrooms}")
    if listing.max_guests > 0:
        print(f"  Huespedes max: {listing.max_guests}")
    if listing.amenities:
        print(f"  Amenidades: {', '.join(listing.amenities[:10])}")
    if listing.rating > 0:
        print(f"  Rating: {listing.rating:.1f}/5.0 ({listing.review_count} resenas)")


def _get_demo_listing() -> ListingData:
    """Devuelve datos de demostración para testing."""
    return create_manual_listing({
        "title": "Moderno 2BR en Palermo Soho con balcon y vista",
        "property_type": "Apartamento",
        "description": "Hermoso departamento de 2 ambientes completamente equipado en el corazon de Palermo Soho. "
                       "A pasos de restaurantes, bares y tiendas. Ideal para parejas o viajeros de negocios.",
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


if __name__ == "__main__":
    main()
