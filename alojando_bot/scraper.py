"""
Módulo de búsqueda de anuncios comparables.

ARQUITECTURA: Los portales de alquiler (Airbnb, Booking, Vrbo) usan protección
anti-bot agresiva que bloquea requests HTTP simples. Este módulo ofrece dos modos:

1. BROWSER-ASSISTED (recomendado para web):
   El frontend del usuario abre las páginas de búsqueda en iframes/tabs ocultos,
   obtiene el HTML renderizado, y lo envía al backend vía API.
   Funciones: parse_search_html(), build_search_urls()

2. DIRECT (fallback):
   Intenta hacer requests directos. Funciona para algunos portales menores.
   Funciones: search_all_portals()

El modo browser-assisted es el que funciona de forma fiable con Airbnb y Booking.
"""
import re
import json
import time
import logging
from typing import List, Dict
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from .models import ListingData
from .config import HEADERS, REQUEST_TIMEOUT, MAX_COMPARABLES_PER_PORTAL
from .extractor import normalize_amenity, parse_airbnb_search_results
from .currency import convert_price, detect_currency_from_portal

logger = logging.getLogger(__name__)


# ============================================
# BROWSER-ASSISTED MODE (principal)
# ============================================

def build_search_urls(listing: ListingData, portals: list = None, radius_meters: int = 0, checkin: str = "", checkout: str = "") -> Dict[str, str]:
    """
    Construye las URLs de búsqueda para cada portal.

    Args:
        listing: El anuncio original
        portals: Lista de portales
        radius_meters: Radio de búsqueda en metros (0 = usar ubicación por texto)
        checkin: Fecha de check-in (YYYY-MM-DD) o vacío para usar default
        checkout: Fecha de check-out (YYYY-MM-DD) o vacío para usar default

    Returns:
        Dict {portal: search_url}
    """
    if portals is None:
        portals = ["airbnb", "booking", "vrbo", "google"]

    urls = {}
    location = _build_location_query(listing)

    if not location and not (listing.latitude and listing.longitude):
        logger.warning("Sin información de ubicación suficiente para buscar")
        return urls

    # Calcular bounding box si tenemos coordenadas y radio
    bbox = None
    if listing.latitude and listing.longitude and radius_meters > 0:
        bbox = _calc_bounding_box(listing.latitude, listing.longitude, radius_meters)
        logger.info("Bounding box (radio %dm): %s", radius_meters, bbox)

    for portal in portals:
        url = _get_search_url(portal, listing, location, bbox=bbox, checkin=checkin, checkout=checkout)
        if url:
            urls[portal] = url

    return urls


def _calc_bounding_box(lat: float, lng: float, radius_meters: int) -> dict:
    """
    Calcula el bounding box (NE/SW) dado un centro y radio en metros.
    Usa una aproximación simple basada en grados por metro.
    """
    import math
    # 1 grado de latitud ~ 111,320 metros
    lat_delta = radius_meters / 111320.0
    # 1 grado de longitud varía según la latitud
    lng_delta = radius_meters / (111320.0 * math.cos(math.radians(lat)))

    return {
        "ne_lat": round(lat + lat_delta, 6),
        "ne_lng": round(lng + lng_delta, 6),
        "sw_lat": round(lat - lat_delta, 6),
        "sw_lng": round(lng - lng_delta, 6),
    }


def _build_location_query(listing: ListingData) -> str:
    """Construye string de ubicación para búsqueda."""
    parts = []
    if listing.neighborhood:
        parts.append(listing.neighborhood)
    if listing.city:
        parts.append(listing.city)
    if listing.country and listing.country not in (listing.city or ""):
        parts.append(listing.country)
    if not parts and listing.address:
        parts.append(listing.address)
    return ", ".join(parts)


def _get_default_dates() -> tuple:
    """Genera fechas de check-in (7 días adelante) y check-out (9 días adelante)."""
    from datetime import datetime, timedelta
    check_in = datetime.now() + timedelta(days=7)
    check_out = check_in + timedelta(days=2)
    return check_in.strftime("%Y-%m-%d"), check_out.strftime("%Y-%m-%d")


def _get_search_url(portal: str, listing: ListingData, location: str, bbox: dict = None, checkin: str = "", checkout: str = "") -> str:
    """
    Genera la URL de búsqueda para un portal específico.
    Incluye filtros por dormitorios y tipo de propiedad cuando el portal lo soporta.
    Si checkin/checkout están vacíos, usa fechas por defecto (7 días adelante).
    """
    if not checkin or not checkout:
        checkin, checkout = _get_default_dates()
    bedrooms = listing.bedrooms or 0

    if portal == "airbnb":
        base = "https://www.airbnb.com/s/{location}/homes"
        params = ["refinement_paths%5B%5D=%2Fhomes"]
        params.append(f"checkin={checkin}")
        params.append(f"checkout={checkout}")
        if listing.max_guests > 0:
            params.append(f"adults={min(listing.max_guests, 16)}")
        # Filtrar por dormitorios exactos en la URL.
        # Airbnb no siempre respeta este filtro, pero ayuda a mejorar los resultados.
        # El filtro post-parseo (_filter_similar con ±1) es el que realmente filtra.
        if bedrooms > 0:
            params.append(f"min_bedrooms={bedrooms}")
            params.append(f"max_bedrooms={bedrooms}")
        elif bedrooms == 0:
            params.append("min_bedrooms=0")
            params.append("max_bedrooms=0")
            params.append("room_types%5B%5D=Entire+home%2Fapt")
        # Tipo de propiedad en Airbnb
        # l2_property_type_ids: 1=apartment, 3=house, 4=room
        if listing.property_type:
            pt = listing.property_type.lower()
            if any(w in pt for w in ["estudio", "studio", "monoambiente", "loft", "apartamento", "apartment", "depto", "departamento"]):
                params.append("l2_property_type_ids%5B%5D=1")  # Apartment
            elif any(w in pt for w in ["casa", "house", "villa", "chalet"]):
                params.append("l2_property_type_ids%5B%5D=3")  # House
        # Bounding box para búsqueda por radio
        if bbox:
            params.append(f"ne_lat={bbox['ne_lat']}")
            params.append(f"ne_lng={bbox['ne_lng']}")
            params.append(f"sw_lat={bbox['sw_lat']}")
            params.append(f"sw_lng={bbox['sw_lng']}")
            params.append("search_by_map=true")
            params.append("zoom_level=15")
        url = base.format(location=quote_plus(location))
        if params:
            url += "?" + "&".join(params)
        return url

    elif portal == "booking":
        params = [f"ss={quote_plus(location)}", "nflt=ht_id%3D220"]
        params.append(f"checkin={checkin}")
        params.append(f"checkout={checkout}")
        if listing.max_guests > 0:
            params.append(f"group_adults={listing.max_guests}")
        # Booking: no filtrar por dormitorios exactos en la URL porque
        # Booking tampoco los respeta bien. Nuestro filtro post-parseo se encarga.
        # Booking soporta lat/lng con radio
        if bbox:
            center_lat = (bbox['ne_lat'] + bbox['sw_lat']) / 2
            center_lng = (bbox['ne_lng'] + bbox['sw_lng']) / 2
            params.append(f"latitude={center_lat}")
            params.append(f"longitude={center_lng}")
        return "https://www.booking.com/searchresults.html?" + "&".join(params)

    elif portal == "vrbo":
        params = [f"destination={quote_plus(location)}"]
        params.append(f"startDate={checkin}")
        params.append(f"endDate={checkout}")
        if listing.max_guests > 0:
            params.append(f"adults={listing.max_guests}")
        # Vrbo: filtro por dormitorios exactos
        if bedrooms >= 0:
            params.append(f"minBedrooms={bedrooms}")
            params.append(f"maxBedrooms={bedrooms}")
        # Vrbo soporta bounding box
        if bbox:
            params.append(f"latNorth={bbox['ne_lat']}")
            params.append(f"latSouth={bbox['sw_lat']}")
            params.append(f"longEast={bbox['ne_lng']}")
            params.append(f"longWest={bbox['sw_lng']}")
        return "https://www.vrbo.com/search?" + "&".join(params)

    elif portal == "google":
        # Google: incluir dormitorios en la query de búsqueda
        if bedrooms == 0:
            search_query = f"studio vacation rental {location}"
        elif bedrooms == 1:
            search_query = f"1 bedroom apartment rental {location}"
        else:
            search_query = f"{bedrooms} bedroom vacation rental {location}"
        if listing.property_type:
            pt = listing.property_type.lower()
            if any(w in pt for w in ["estudio", "studio", "monoambiente"]):
                search_query = f"studio rental {location}"
            elif any(w in pt for w in ["casa", "house", "villa"]):
                search_query = f"{bedrooms} bedroom house rental {location}"
        return (f"https://www.google.com/travel/hotels?q={quote_plus(search_query)}"
                f"&hl=es&checkin={checkin}&checkout={checkout}")

    return ""


def parse_search_html(portal: str, html: str, max_results: int = 0) -> List[ListingData]:
    """
    Parsea el HTML de resultados de búsqueda obtenido por el browser.

    Args:
        portal: Nombre del portal (airbnb, booking, vrbo, google)
        html: HTML de la página de resultados
        max_results: Máximo de resultados (0 = usar config default)

    Returns:
        Lista de ListingData
    """
    limit = max_results if max_results > 0 else MAX_COMPARABLES_PER_PORTAL

    parsers = {
        "airbnb": _parse_airbnb_search,
        "booking": _parse_booking_search,
        "vrbo": _parse_vrbo_search,
        "google": _parse_google_search,
    }

    parser = parsers.get(portal)
    if not parser:
        logger.warning(f"No hay parser para portal: {portal}")
        return []

    try:
        # For multi-page HTML (separated by PAGE_BREAK), parse each page
        all_results = []
        pages = html.split("\n<!-- PAGE_BREAK -->\n")
        for page_html in pages:
            page_results = parser(page_html)
            all_results.extend(page_results)
        # Deduplicate by listing_id or title
        seen = set()
        unique = []
        for r in all_results:
            key = r.listing_id or r.title
            if key and key not in seen:
                seen.add(key)
                unique.append(r)
            elif not key:
                unique.append(r)
        logger.info(f"Parseados {len(unique)} resultados unicos de {portal} ({len(pages)} pagina(s))")
        return unique[:limit]
    except Exception as e:
        logger.error(f"Error al parsear resultados de {portal}: {e}")
        return []


def _parse_airbnb_search(html: str) -> List[ListingData]:
    """Parsea resultados de búsqueda de Airbnb usando la función del extractor."""
    return parse_airbnb_search_results(html)


def _parse_booking_search(html: str) -> List[ListingData]:
    """Parsea resultados de búsqueda de Booking.com."""
    results = []
    soup = BeautifulSoup(html, "html.parser")

    # Booking usa property-card divs
    cards = soup.find_all("div", {"data-testid": "property-card"})
    if not cards:
        cards = soup.find_all("div", class_=re.compile(r"sr_property_block|property-card"))

    for card in cards:
        listing = ListingData(source="booking")

        # Título
        title_el = card.find("div", {"data-testid": "title"})
        if not title_el:
            title_el = card.find(["h2", "h3", "a"], class_=re.compile(r"hotel_name"))
        if title_el:
            listing.title = title_el.get_text(strip=True)

        # URL
        link = card.find("a", {"data-testid": "title-link"})
        if not link:
            link = card.find("a", href=re.compile(r"booking\.com"))
        if link:
            listing.url = urljoin("https://www.booking.com", link.get("href", ""))

        # Precio total y calcular por noche
        price_el = card.find(["span", "div"], {"data-testid": "price-and-discounted-price"})
        if not price_el:
            price_el = card.find(class_=re.compile(r"price|bui-price"))
        if price_el:
            # Formato ARS: "$ 256.090" (punto = miles) o EUR/USD: "$256.09"
            price_text = price_el.get_text()
            # Remove currency symbols and whitespace, handle thousands separator
            clean = re.sub(r'[^\d.,]', '', price_text)
            # If format uses . as thousands (e.g. "256.090" or "1.693.587")
            if clean.count('.') > 1 or (clean.count('.') == 1 and len(clean.split('.')[-1]) == 3):
                clean = clean.replace('.', '')  # remove thousands dots
                clean = clean.replace(',', '.')  # comma becomes decimal
            elif clean.count(',') == 1 and len(clean.split(',')[-1]) == 2 and clean.count('.') == 0:
                # European decimal: "150,50" -> "150.50"
                clean = clean.replace(',', '.')
            else:
                clean = clean.replace(',', '')  # remove thousands commas
            price_match = re.search(r'(\d+\.?\d*)', clean)
            if price_match:
                total_price = float(price_match.group(1))
                # Extraer número de noches para calcular precio por noche
                nights = 2  # default (our search uses 2 nights)
                nights_el = card.find(["div", "span"], {"data-testid": "price-for-x-nights"})
                if nights_el:
                    nights_match = re.search(r'(\d+)\s*noch', nights_el.get_text())
                    if nights_match:
                        nights = int(nights_match.group(1))
                listing.price_per_night = round(total_price / nights, 2)

        # Rating (Booking usa escala de 10) y review count
        # Formato: "Puntuación: 8,3 8,3Muy bien 356 comentarios"
        rating_el = card.find(["div", "span"], {"data-testid": "review-score"})
        if not rating_el:
            rating_el = card.find(class_=re.compile(r"review-score"))
        if rating_el:
            rating_text = rating_el.get_text()
            rating_match = re.search(r'(\d+[\.,]\d+)', rating_text)
            if rating_match:
                val = float(rating_match.group(1).replace(",", "."))
                listing.rating = val / 2 if val > 5 else val
            # Extract review count
            review_match = re.search(r'(\d+)\s*comentario', rating_text)
            if review_match:
                listing.review_count = int(review_match.group(1))

        # Extraer dormitorios, huéspedes, baños y tipo de propiedad del texto del card
        card_text = card.get_text(separator=" ", strip=True)

        # Tipo de propiedad: detectar si es hotel
        _detect_property_type(listing, card_text)

        # Dormitorios: "1 dormitorio", "2 bedrooms", "Studio"
        if listing.bedrooms == 0:
            bed_match = re.search(r'(\d+)\s*(?:dormitorio|bedroom|habitaci)', card_text, re.I)
            if bed_match:
                listing.bedrooms = int(bed_match.group(1))
            elif re.search(r'\b(?:estudio|studio|monoambiente)\b', card_text, re.I):
                # Es un estudio, marcar como 0 dormitorios pero sabemos que es chico
                listing.property_type = "estudio"

        # Huéspedes/personas: "4 huéspedes", "sleeps 6", "4 adultos"
        if listing.max_guests == 0:
            guests_match = re.search(r'(\d+)\s*(?:hu[eé]sped|guest|persona|adult)', card_text, re.I)
            if guests_match:
                listing.max_guests = int(guests_match.group(1))

        # Baños
        if listing.bathrooms == 0:
            bath_match = re.search(r'(\d+)\s*(?:ba[ñn]o|bathroom)', card_text, re.I)
            if bath_match:
                listing.bathrooms = int(bath_match.group(1))

        if listing.title:
            results.append(listing)

    # Intentar también con JSON-LD
    if not results:
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") in ["Hotel", "LodgingBusiness", "VacationRental"]:
                            listing = ListingData(source="booking")
                            listing.title = item.get("name", "")
                            if item.get("aggregateRating"):
                                val = float(item["aggregateRating"].get("ratingValue", 0))
                                listing.rating = val / 2 if val > 5 else val
                            if listing.title:
                                results.append(listing)
            except (json.JSONDecodeError, TypeError):
                continue

    return results


def _parse_vrbo_search(html: str) -> List[ListingData]:
    """Parsea resultados de búsqueda de Vrbo."""
    results = []
    soup = BeautifulSoup(html, "html.parser")

    # Vrbo embebe JSON en scripts
    for script in soup.find_all("script"):
        text = script.string or ""
        if "listingId" in text or "propertyId" in text:
            try:
                data = json.loads(text)
                listings = _find_vrbo_listings(data)
                for item in listings:
                    listing = ListingData(source="vrbo")
                    listing.title = item.get("headline", item.get("name", ""))
                    listing.listing_id = str(item.get("listingId", item.get("propertyId", "")))
                    listing.url = f"https://www.vrbo.com/{listing.listing_id}" if listing.listing_id else ""

                    price_data = item.get("price", item.get("priceInfo", {}))
                    if isinstance(price_data, dict):
                        listing.price_per_night = float(price_data.get("lead", {}).get("amount", 0))

                    listing.rating = float(item.get("averageRating", 0))
                    listing.review_count = int(item.get("reviewCount", 0))
                    listing.bedrooms = int(item.get("bedrooms", 0))
                    listing.bathrooms = float(item.get("bathrooms", 0))
                    listing.max_guests = int(item.get("sleeps", item.get("maxOccupants", 0)))

                    if listing.title:
                        results.append(listing)
            except (json.JSONDecodeError, TypeError):
                continue

    # Fallback: HTML cards
    if not results:
        cards = soup.find_all("div", {"data-stid": re.compile(r"property-listing")})
        for card in cards:
            listing = ListingData(source="vrbo")
            title_el = card.find(["h3", "h2"])
            if title_el:
                listing.title = title_el.get_text(strip=True)
            link = card.find("a", href=True)
            if link:
                listing.url = urljoin("https://www.vrbo.com", link["href"])
            price_el = card.find(string=re.compile(r'[\$€£]\s*\d+'))
            if price_el:
                match = re.search(r'[\$€£]\s*(\d+)', price_el)
                if match:
                    listing.price_per_night = float(match.group(1))
            if listing.title:
                results.append(listing)

    return results


def _find_vrbo_listings(data, depth=0) -> list:
    """Recursivamente busca listings en JSON de Vrbo."""
    if depth > 8:
        return []
    results = []
    if isinstance(data, dict):
        if "headline" in data and ("listingId" in data or "propertyId" in data):
            results.append(data)
        for val in data.values():
            results.extend(_find_vrbo_listings(val, depth + 1))
    elif isinstance(data, list):
        for item in data:
            results.extend(_find_vrbo_listings(item, depth + 1))
    return results


def _parse_google_search(html: str) -> List[ListingData]:
    """
    Parsea resultados de búsqueda de Google Travel.

    Google Travel tiene dos tipos de cards:
    1. Vacation rentals: <h2 class="BgYkof"> con precio "$ 60.245 de media por noche"
    2. Hotels/aparthotels: <div class="AdWm1c"> con "186.437 ARS" y rating "4,2/5 (416)"

    Los precios en ARS usan punto como separador de miles: "$ 60.245" = 60245 ARS
    """
    results = []
    soup = BeautifulSoup(html, "html.parser")

    # ---- Tipo 1: Vacation rental cards (h2 con clase BgYkof) ----
    rental_titles = soup.find_all("h2", class_=re.compile(r"BgYkof"))
    for title_el in rental_titles:
        listing = ListingData(source="google")
        listing.property_type = "vacation_rental"
        listing.title = title_el.get_text(strip=True)

        # Buscar el <a> padre que envuelve toda la card (link a detalle)
        container = title_el.find_parent("a")
        if not container:
            # Fallback: subir hasta encontrar un contenedor razonable
            container = title_el.parent
            for _ in range(6):
                if container and container.parent and container.parent.name not in ['body', 'html', '[document]']:
                    parent_text_len = len(container.parent.get_text(strip=True))
                    # Parar si el padre es demasiado grande (otro card se mezcla)
                    if parent_text_len > 2000:
                        break
                    container = container.parent

        if not container:
            container = title_el.parent

        card_text = container.get_text(separator=" ", strip=True) if container else ""

        # Precio: "$ 60.245" (ARS, punto = miles)
        price_match = re.search(r'\$\s*([\d.]+)', card_text)
        if price_match:
            price_str = price_match.group(1).replace(".", "")  # quitar puntos de miles
            try:
                listing.price_per_night = float(price_str)
            except ValueError:
                pass

        # Rating y reviews: pueden estar separados por " | " en el texto
        # Formatos: "4,6 | (107)" o "4,6(107)" o "4.6 (107)"
        rating_match = re.search(r'(\d)[,.](\d)\s*[|\s]*\((\d+)\)', card_text)
        if rating_match:
            listing.rating = float(f"{rating_match.group(1)}.{rating_match.group(2)}")
            listing.review_count = int(rating_match.group(3))

        # URL del link padre
        link = container.find("a", href=True) if container else None
        if not link and title_el.parent:
            link = title_el.find_parent("a")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                listing.url = "https://www.google.com" + href
            elif href.startswith("http"):
                listing.url = href

        # Detalles: dormitorios, capacidad, baños
        details_match = re.search(r'(\d+)\s*dormitorio', card_text, re.I)
        if details_match:
            listing.bedrooms = int(details_match.group(1))
        guests_match = re.search(r'[Cc]apacidad\s*(?:para\s*)?(\d+)', card_text)
        if guests_match:
            listing.max_guests = int(guests_match.group(1))
        bath_match = re.search(r'(\d+)\s*ba[ñn]o', card_text, re.I)
        if bath_match:
            listing.bathrooms = int(bath_match.group(1))

        if listing.title:
            results.append(listing)

    # ---- Tipo 2: Hotel/apart-hotel cards (div con clase AdWm1c) ----
    hotel_cards = soup.find_all("div", class_=re.compile(r"AdWm1c"))
    for card in hotel_cards:
        card_text = card.get_text(separator=" | ", strip=True)
        if not card_text or len(card_text) < 10:
            continue

        listing = ListingData(source="google")
        listing.property_type = "hotel"

        # El primer texto largo suele ser el nombre
        name_el = card.find("div", class_=re.compile(r"ogfYpf"))
        if name_el:
            listing.title = name_el.get_text(strip=True)

        # Precio en ARS: "186.437 ARS" o "$ 186.437"
        ars_match = re.search(r'([\d.]+)\s*ARS', card_text)
        if ars_match:
            price_str = ars_match.group(1).replace(".", "")
            try:
                listing.price_per_night = float(price_str)
            except ValueError:
                pass
        if not listing.price_per_night:
            price_match = re.search(r'\$\s*([\d.]+)', card_text)
            if price_match:
                price_str = price_match.group(1).replace(".", "")
                try:
                    listing.price_per_night = float(price_str)
                except ValueError:
                    pass

        # Rating: "4,2/5 (416)" o "4,2 | (416)" o "4,2(416)"
        rating_match = re.search(r'(\d)[,.](\d)(?:/5)?\s*[|\s]*\((\d+)\)', card_text)
        if rating_match:
            listing.rating = float(f"{rating_match.group(1)}.{rating_match.group(2)}")
            listing.review_count = int(rating_match.group(3))

        # Dormitorios y huéspedes del texto
        details_match = re.search(r'(\d+)\s*dormitorio', card_text, re.I)
        if details_match:
            listing.bedrooms = int(details_match.group(1))
        guests_match = re.search(r'[Cc]apacidad\s*(?:para\s*)?(\d+)', card_text)
        if not guests_match:
            guests_match = re.search(r'(\d+)\s*(?:hu[eé]sped|guest|persona)', card_text, re.I)
        if guests_match:
            listing.max_guests = int(guests_match.group(1))

        # URL
        link = card.find("a", href=True)
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                listing.url = "https://www.google.com" + href
            elif href.startswith("http"):
                listing.url = href

        if listing.title and listing.title not in [r.title for r in results]:
            results.append(listing)

    logger.info(f"Google Travel: {len(results)} resultados ({len(rental_titles)} rentals + {len(hotel_cards)} hotels)")
    return results


# ============================================
# DIRECT MODE (fallback, puede fallar)
# ============================================

def search_all_portals(listing: ListingData, portals: list = None,
                       compare_with_hotels: bool = False, user_property_type: str = "") -> dict:
    """
    Busca comparables directamente (puede fallar con portales que bloquean bots).

    Para un método más fiable, usar build_search_urls() + parse_search_html()
    desde el frontend.

    Args:
        listing: El anuncio original
        portals: Lista de portales
        compare_with_hotels: Si True, incluir hoteles en comparables
        user_property_type: Tipo de propiedad del usuario

    Returns:
        Dict con portal como key y lista de ListingData como value
    """
    if portals is None:
        portals = ["airbnb", "booking", "vrbo", "google"]

    all_results = {}
    search_urls = build_search_urls(listing, portals)

    for portal in portals:
        url = search_urls.get(portal)
        if not url:
            all_results[portal] = []
            continue

        try:
            logger.info(f"Buscando en {portal.upper()}: {url}")
            time.sleep(1.5)  # Rate limiting

            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            results = parse_search_html(portal, response.text)
            all_results[portal] = results
            logger.info(f"Encontrados {len(results)} resultados en {portal}")

        except requests.RequestException as e:
            logger.warning(f"Error al buscar en {portal} (esperado - anti-bot): {e}")
            all_results[portal] = []

    return all_results


# ============================================
# BROWSER-ASSISTED SEARCH (para el web app)
# ============================================

def search_with_browser_html(listing: ListingData, portal_html: Dict[str, str], max_results: int = 0,
                             compare_with_hotels: bool = False, user_property_type: str = "") -> dict:
    """
    Parsea HTML de búsqueda proporcionado por el browser del usuario.
    Normaliza todos los precios a la moneda del listing original.

    Args:
        listing: El anuncio original
        portal_html: Dict {portal: html_string} con el HTML de cada portal
        max_results: Máximo de resultados por portal (0 = usar config default)

    Returns:
        Dict con portal como key y lista de ListingData como value
    """
    all_results = {}
    target_currency = (listing.currency or "USD").upper()

    for portal, html in portal_html.items():
        if html:
            html_len = len(html) if html else 0
            logger.info(f"Parseando {portal}: {html_len} chars de HTML recibidos")
            # Detectar páginas de error/captcha
            if html_len < 2000:
                logger.warning(f"{portal}: HTML muy corto ({html_len} chars), posible bloqueo")
                all_results[portal] = []
                continue
            # Solo detectar captcha real: HTML corto + palabra clave captcha
            if html_len < 15000:
                lower_html = html[:5000].lower()
                if "captcha" in lower_html and "verify" in lower_html:
                    logger.warning(f"{portal}: Detectado captcha en respuesta corta")
                    all_results[portal] = []
                    continue
            results = parse_search_html(portal, html, max_results=max_results)
            pre_filter_count = len(results)
            logger.info(f"{portal}: Parseados {pre_filter_count} resultados")

            # Detectar moneda del portal y convertir precios a moneda del usuario
            portal_currency = detect_currency_from_portal(portal, html[:5000])
            if portal_currency != target_currency:
                converted = 0
                for r in results:
                    if r.price_per_night and r.price_per_night > 0:
                        r.price_per_night = convert_price(r.price_per_night, portal_currency, target_currency)
                        r.currency = target_currency
                        converted += 1
                if converted:
                    logger.info(f"{portal}: Convertidos {converted} precios de {portal_currency} a {target_currency}")
            else:
                for r in results:
                    r.currency = target_currency

            # Filtrar el propio listing del usuario
            if listing.listing_id:
                results = [r for r in results if r.listing_id != listing.listing_id]

            # Filtrar por similitud: descartar propiedades muy diferentes
            results = _filter_similar(results, listing,
                                     compare_with_hotels=compare_with_hotels,
                                     user_property_type=user_property_type)

            post_filter_count = len(results)
            if pre_filter_count != post_filter_count:
                logger.info(f"{portal}: {pre_filter_count} parseados -> {post_filter_count} similares "
                           f"(filtrados {pre_filter_count - post_filter_count} por dormitorios/huespedes/precio)")

            all_results[portal] = results
        else:
            logger.warning(f"{portal}: No se recibió HTML")
            all_results[portal] = []

    return all_results


def _infer_bedrooms_from_text(text: str) -> int:
    """
    Intenta inferir la cantidad de dormitorios desde el título o texto del card.
    Patrones: "2 dormitorios", "3 bedroom", "2BR", "estudio", "studio", "monoambiente"
    """
    if not text:
        return 0
    text_lower = text.lower()

    # Estudio/monoambiente = 0 dormitorios (pero lo marcamos como -1 para no confundir con "desconocido")
    studio_patterns = ["estudio", "studio", "monoambiente", "loft", "efficiency"]
    if any(p in text_lower for p in studio_patterns):
        # Solo si no menciona dormitorios explícitamente
        if not re.search(r'\d+\s*(dormitorio|bedroom|habitaci|br\b)', text_lower):
            return 0

    # "2 dormitorios", "3 bedrooms", "1 habitación", "2BR"
    patterns = [
        r'(\d+)\s*dormitorio',
        r'(\d+)\s*bedroom',
        r'(\d+)\s*habitaci[oó]n',
        r'(\d+)\s*br\b',
        r'(\d+)\s*bed\s*room',
        r'(\d+)\s*dorm\b',
        r'(\d+)\s*rec[aá]mara',
        r'(\d+)\s*cuarto',
    ]
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return int(match.group(1))

    return 0


def _infer_guests_from_text(text: str) -> int:
    """Intenta inferir la cantidad de huéspedes desde texto."""
    if not text:
        return 0
    patterns = [
        r'(\d+)\s*hu[eé]sped',
        r'(\d+)\s*guest',
        r'(\d+)\s*persona',
        r'(\d+)\s*people',
        r'capacidad\s*(?:para\s*)?(\d+)',
        r'sleeps?\s*(\d+)',
        r'(\d+)\s*adult',
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return int(match.group(1))
    return 0


_HOTEL_KEYWORDS = [
    "hotel", "hostel", "hostal", "resort", "inn", "posada",
    "hostería", "hosteria", "motel", "b&b", "bed and breakfast",
    "bed & breakfast", "pension", "pensión", "albergue",
]

_APARTHOTEL_KEYWORDS = [
    "apart-hotel", "aparthotel", "apart hotel", "apartotel",
]


def _detect_property_type(listing: ListingData, text: str = ""):
    """Detecta si un listing es hotel, apartamento, casa, etc. desde el texto."""
    if listing.property_type and listing.property_type not in ("", "vacation_rental"):
        return  # Ya tiene tipo asignado

    check_text = " ".join(filter(None, [listing.title, text])).lower()
    if not check_text:
        return

    # Apart-hotel es un caso especial: tiene "hotel" pero es un apartamento
    for kw in _APARTHOTEL_KEYWORDS:
        if kw in check_text:
            listing.property_type = "aparthotel"
            return

    # Hoteles
    for kw in _HOTEL_KEYWORDS:
        # Match word boundary: "hotel" pero no "hoteles" falso positivo en "Photoloft"
        if re.search(r'\b' + re.escape(kw) + r'\b', check_text):
            listing.property_type = "hotel"
            return

    # Casas
    if re.search(r'\b(casa|house|villa|chalet|cabaña|cabana|cabin)\b', check_text):
        listing.property_type = "casa"
        return

    # Departamentos/apartamentos
    if re.search(r'\b(apartamento|apartment|depto|departamento|flat|piso)\b', check_text):
        listing.property_type = "apartamento"
        return

    # Estudios
    if re.search(r'\b(estudio|studio|monoambiente|loft)\b', check_text):
        listing.property_type = "estudio"
        return


def _enrich_listing_from_text(listing: ListingData) -> ListingData:
    """
    Enriquece un listing intentando extraer dormitorios, huéspedes
    y tipo de propiedad del título y otros textos disponibles.
    """
    text = " ".join(filter(None, [listing.title, listing.description]))

    if listing.bedrooms == 0:
        inferred = _infer_bedrooms_from_text(text)
        if inferred > 0:
            listing.bedrooms = inferred
            logger.debug(f"Inferido {inferred} dormitorios de texto: {listing.title}")

    if listing.max_guests == 0:
        inferred = _infer_guests_from_text(text)
        if inferred > 0:
            listing.max_guests = inferred
            logger.debug(f"Inferido {inferred} huespedes de texto: {listing.title}")

    # Inferir property_type si no se tiene
    _detect_property_type(listing, text)

    return listing


def _is_hotel_type(property_type: str, title: str = "") -> bool:
    """Determina si un listing es de tipo hotel/hostel."""
    check = (property_type or "").lower()
    if check in ("hotel", "hostel", "hostal", "resort", "motel", "inn", "posada",
                  "hostería", "hosteria", "albergue", "b&b", "pension", "pensión"):
        return True
    # Verificar también en el título
    title_lower = (title or "").lower()
    for kw in _HOTEL_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', title_lower):
            # Excepto apart-hotel que es un apartamento
            if any(ak in title_lower for ak in _APARTHOTEL_KEYWORDS):
                return False
            return True
    return False


def _property_type_compatible(user_type: str, comp_type: str) -> bool:
    """
    Verifica si el tipo de propiedad del comparable es compatible con el del usuario.

    NOTA: No filtramos apartamento vs casa porque los portales clasifican
    inconsistentemente (Booking llama "casa" a muchos departamentos).
    Solo filtramos el caso hotel vs no-hotel, que se maneja aparte.
    """
    # No filtrar por tipo entre alquileres temporarios - los portales son inconsistentes
    # El filtro de hoteles ya se encarga de excluir hoteles/hosteles
    return True


def _filter_similar(results: List[ListingData], listing: ListingData,
                    compare_with_hotels: bool = False, user_property_type: str = "") -> List[ListingData]:
    """
    Filtra resultados para quedarse solo con propiedades similares al listing original.

    Criterios:
    - Hoteles: excluir si compare_with_hotels=False
    - Tipo de propiedad: apartamentos solo con apartamentos, casas solo con casas
    - Dormitorios: match exacto cuando ambos tienen datos; inferir de título si falta
    - Huéspedes: máximo +2 personas de diferencia
    - Precio: rango ajustado (0.3x a 3x)
    - Si no hay datos de dormitorios ni huéspedes, usar el precio como proxy
    """
    if not results:
        return results

    user_bedrooms = listing.bedrooms if listing.bedrooms is not None else -1
    user_guests = listing.max_guests or 0
    user_price = listing.price_per_night or 0
    effective_property_type = user_property_type or listing.property_type or ""
    filtered = []
    reject_reasons = {"hotel": 0, "tipo": 0, "dormitorios": 0, "huespedes": 0, "precio": 0, "proxy": 0}

    for r in results:
        # Enriquecer el comparable con datos inferidos del título
        _enrich_listing_from_text(r)

        # --- Filtro de hoteles ---
        if not compare_with_hotels:
            if _is_hotel_type(r.property_type, r.title):
                logger.debug(f"Filtrado por hotel: {r.title} (tipo={r.property_type})")
                reject_reasons["hotel"] += 1
                continue

        # --- Filtro por tipo de propiedad ---
        if effective_property_type and r.property_type:
            if not _property_type_compatible(effective_property_type, r.property_type):
                logger.debug(f"Filtrado por tipo: {r.title} (tipo={r.property_type} vs user={effective_property_type})")
                reject_reasons["tipo"] += 1
                continue

        # --- Filtro por dormitorios (tolerancia ±2) ---
        # Los portales no respetan los filtros de dormitorios en la URL y devuelven
        # resultados mixtos. Permitimos ±2 para tener suficientes comparables.
        # Un 3-dorm es razonablemente comparable a un 1-dorm en la misma zona.
        if user_bedrooms >= 0 and r.bedrooms > 0:
            diff = abs(r.bedrooms - user_bedrooms)
            if diff > 2:
                logger.debug(f"Filtrado por dormitorios: {r.title} ({r.bedrooms} dorm vs {user_bedrooms})")
                reject_reasons["dormitorios"] += 1
                continue

        # --- Filtro por huéspedes ---
        # Tolerancia coherente con ±2 dormitorios: +6 arriba, mitad abajo
        if user_guests > 0 and r.max_guests > 0:
            if r.max_guests > user_guests + 6:
                logger.debug(f"Filtrado por huespedes (muy grande): {r.title} ({r.max_guests} vs {user_guests})")
                reject_reasons["huespedes"] += 1
                continue
            if r.max_guests < max(1, user_guests // 2):
                logger.debug(f"Filtrado por huespedes (muy chico): {r.title} ({r.max_guests} vs {user_guests})")
                reject_reasons["huespedes"] += 1
                continue

        # --- Filtro por precio (ajustado) ---
        if user_price > 0 and r.price_per_night > 0:
            ratio = r.price_per_night / user_price
            if ratio > 3.0 or ratio < 0.3:
                logger.debug(f"Filtrado por precio extremo: {r.title} ({r.price_per_night} vs {user_price})")
                reject_reasons["precio"] += 1
                continue

        # --- Filtro de seguridad: precio como proxy de tamaño ---
        if user_bedrooms >= 0 and r.bedrooms == 0 and r.max_guests == 0:
            if user_price > 0 and r.price_per_night > 0:
                if r.price_per_night > user_price * 2.5:
                    logger.debug(f"Filtrado por precio/tamaño proxy: {r.title} ({r.price_per_night} vs {user_price})")
                    reject_reasons["proxy"] += 1
                    continue

        filtered.append(r)

    removed = len(results) - len(filtered)
    if removed > 0:
        reasons_str = ", ".join(f"{k}={v}" for k, v in reject_reasons.items() if v > 0)
        logger.info(f"Filtro: {len(filtered)}/{len(results)} conservados (rechazados: {reasons_str})")

    return filtered
