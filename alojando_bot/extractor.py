"""
Modulo de extraccion de datos de anuncios.
Soporta extraccion desde URLs de Airbnb, Booking, Vrbo y entrada manual.
"""
import re
import json
import logging
import base64
from urllib.parse import urlparse
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .models import ListingData
from .config import HEADERS, REQUEST_TIMEOUT, AMENITY_MAPPING

logger = logging.getLogger(__name__)


def normalize_amenity(amenity: str) -> str:
    key = amenity.lower().strip()
    return AMENITY_MAPPING.get(key, amenity.strip().title())


def detect_portal(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if "airbnb" in domain:
        return "airbnb"
    elif "booking" in domain:
        return "booking"
    elif "vrbo" in domain or "homeaway" in domain:
        return "vrbo"
    elif "google" in domain:
        return "google"
    return "unknown"


def extract_from_url(url: str, html: str = None) -> ListingData:
    portal = detect_portal(url)
    logger.info("Portal detectado: %s para URL: %s", portal, url)

    if html:
        soup = BeautifulSoup(html, "html.parser")
    else:
        try:
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            logger.error("Error al acceder a la URL: %s", e)
            listing = ListingData(source=portal, url=url)
            listing.title = "[No se pudo acceder - " + portal + "]"
            return listing

    extractors = {
        "airbnb": _extract_airbnb,
        "booking": _extract_booking,
        "vrbo": _extract_vrbo,
        "google": _extract_google,
    }
    extractor = extractors.get(portal, _extract_generic)
    listing = extractor(soup, url)
    listing.source = portal
    listing.url = url
    return listing


def extract_from_html(html: str, url: str = "") -> ListingData:
    portal = detect_portal(url) if url else "unknown"
    if portal == "unknown":
        html_lower = html[:5000].lower()
        if "airbnb" in html_lower or "muscache.com" in html_lower:
            portal = "airbnb"
        elif "booking.com" in html_lower:
            portal = "booking"
        elif "vrbo.com" in html_lower:
            portal = "vrbo"
    return extract_from_url(url, html=html)


def _extract_json_ld(soup: BeautifulSoup) -> list:
    results = []
    scripts = soup.find_all("script", {"type": "application/ld+json"})
    for script in scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return results


def _extract_meta_tags(soup: BeautifulSoup) -> dict:
    meta = {}
    og_tags = soup.find_all("meta", attrs={"property": re.compile(r"^og:")})
    for tag in og_tags:
        key = tag.get("property", "").replace("og:", "")
        meta[key] = tag.get("content", "")
    desc_tag = soup.find("meta", {"name": "description"})
    if desc_tag:
        meta["description"] = desc_tag.get("content", "")
    return meta


def _extract_airbnb(soup: BeautifulSoup, url: str) -> ListingData:
    listing = ListingData()

    # 1. JSON-LD
    json_ld_items = _extract_json_ld(soup)
    vacation_rental = None
    for item in json_ld_items:
        item_type = item.get("@type", "")
        if item_type == "VacationRental":
            vacation_rental = item

    if vacation_rental:
        listing.title = vacation_rental.get("name", "")
        listing.description = vacation_rental.get("description", "")
        listing.latitude = float(vacation_rental.get("latitude", 0) or 0)
        listing.longitude = float(vacation_rental.get("longitude", 0) or 0)

        addr = vacation_rental.get("address", {})
        if isinstance(addr, dict):
            listing.city = addr.get("addressLocality", "")
            listing.address = addr.get("streetAddress", "")
            listing.country = addr.get("addressCountry", "")

        agg_rating = vacation_rental.get("aggregateRating", {})
        if agg_rating:
            listing.rating = float(agg_rating.get("ratingValue", 0) or 0)
            listing.review_count = int(agg_rating.get("ratingCount", 0) or 0)

        images = vacation_rental.get("image", [])
        if isinstance(images, list):
            listing.photos = images[:20]
        elif isinstance(images, str):
            listing.photos = [images]
        listing.photo_count = len(listing.photos)

        contains = vacation_rental.get("containsPlace", {})
        if isinstance(contains, dict):
            occupancy = contains.get("occupancy", {})
            if isinstance(occupancy, dict):
                listing.max_guests = int(occupancy.get("value", 0) or 0)

    # 2. Meta tags fallback
    meta = _extract_meta_tags(soup)
    if not listing.title:
        listing.title = meta.get("title", "") or (soup.title.string if soup.title else "")
    if not listing.description:
        listing.description = meta.get("description", "")

    # 3. data-deferred-state-0
    deferred = _extract_airbnb_deferred_state(soup)
    if deferred:
        _enrich_from_deferred(listing, deferred)

    # 4. Listing ID from URL
    id_match = re.search(r'/rooms/(\d+)', url)
    if id_match:
        listing.listing_id = id_match.group(1)

    return listing


def _extract_airbnb_deferred_state(soup: BeautifulSoup) -> Optional[dict]:
    script = soup.find("script", {"id": "data-deferred-state-0"})
    if not script or not script.string:
        return None
    try:
        raw = json.loads(script.string)
        niobe = raw.get("niobeClientData", [])
        if not niobe:
            return None
        for entry in niobe:
            if len(entry) >= 2:
                query_name = entry[0] or ""
                if "StaysPdpSections" in query_name or "Pdp" in query_name:
                    data = entry[1].get("data", {})
                    pdp = data.get("presentation", {}).get("stayProductDetailPage", {})
                    if pdp:
                        return pdp
        for entry in niobe:
            if len(entry) >= 2:
                data = entry[1].get("data", {})
                pdp = data.get("presentation", {}).get("stayProductDetailPage", {})
                if pdp:
                    return pdp
    except (json.JSONDecodeError, TypeError, KeyError, IndexError) as e:
        logger.warning("Error al parsear data-deferred-state: %s", e)
    return None


def _enrich_from_deferred(listing: ListingData, pdp: dict):
    sections_container = pdp.get("sections", {})
    sections = sections_container.get("sections", [])

    def find_section(section_id):
        for s in sections:
            if s.get("sectionId") == section_id:
                return s.get("section", {})
        return {}

    # Reviews
    reviews_sec = find_section("REVIEWS_DEFAULT")
    if reviews_sec:
        if not listing.rating and reviews_sec.get("overallRating"):
            listing.rating = float(reviews_sec["overallRating"])
        if not listing.review_count and reviews_sec.get("overallCount"):
            listing.review_count = int(reviews_sec["overallCount"])

    # Amenities
    amenities_sec = find_section("AMENITIES_DEFAULT")
    if amenities_sec and not listing.amenities:
        all_groups = amenities_sec.get("seeAllAmenitiesGroups", [])
        for group in all_groups:
            for amenity in group.get("amenities", []):
                if amenity.get("available", True):
                    name = amenity.get("title", "")
                    if name:
                        listing.amenities.append(normalize_amenity(name))

    # Booking / pricing
    book_sec = find_section("BOOK_IT_SIDEBAR")
    if book_sec:
        if not listing.max_guests and book_sec.get("maxGuestCapacity"):
            listing.max_guests = int(book_sec["maxGuestCapacity"])

    # Sleeping arrangement (bedrooms)
    sleeping_sec = find_section("SLEEPING_ARRANGEMENT_WITH_IMAGES")
    if sleeping_sec:
        arrangements = sleeping_sec.get("arrangementDetails", [])
        if arrangements and not listing.bedrooms:
            listing.bedrooms = len(arrangements)

    # Description
    desc_modal = find_section("DESCRIPTION_MODAL")
    if desc_modal and not listing.description:
        items = desc_modal.get("items", [])
        for item in items:
            html_data = item.get("html", {})
            if html_data:
                html_text = html_data.get("htmlText", "")
                if html_text:
                    clean_text = re.sub(r'<[^>]+>', '\n', html_text)
                    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
                    listing.description = clean_text
                    break

    # Location
    loc_sec = find_section("LOCATION_DEFAULT")
    if loc_sec:
        if not listing.latitude and loc_sec.get("lat"):
            listing.latitude = float(loc_sec["lat"])
        if not listing.longitude and loc_sec.get("lng"):
            listing.longitude = float(loc_sec["lng"])

    # Hero photos
    hero_sec = find_section("HERO_DEFAULT")
    if hero_sec:
        preview_images = hero_sec.get("previewImages", [])
        if preview_images and len(preview_images) > listing.photo_count:
            listing.photo_count = len(preview_images)
            for img in preview_images:
                base_url = img.get("baseUrl", "")
                if base_url and base_url not in listing.photos:
                    listing.photos.append(base_url)

    # Highlights
    highlights_sec = find_section("HIGHLIGHTS_DEFAULT")
    if highlights_sec:
        for h in highlights_sec.get("highlights", []):
            title = h.get("title", "").lower()
            if "wifi" in title or "wi-fi" in title:
                if "WiFi" not in listing.amenities:
                    listing.amenities.append("WiFi")
            if "mascota" in title or "pet" in title:
                if "Acepta Mascotas" not in listing.amenities:
                    listing.amenities.append("Acepta Mascotas")


def parse_airbnb_search_results(html: str) -> list:
    """Parsea resultados de busqueda de Airbnb desde HTML."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    script = soup.find("script", {"id": "data-deferred-state-0"})
    if not script or not script.string:
        logger.warning("No se encontro data-deferred-state-0 en resultados de busqueda")
        return results

    try:
        raw = json.loads(script.string)
        niobe = raw.get("niobeClientData", [])

        search_results = None
        for entry in niobe:
            if len(entry) >= 2:
                query_name = entry[0] or ""
                if "StaysSearch" in query_name or "Search" in query_name:
                    data = entry[1].get("data", {})
                    pres = data.get("presentation", {})
                    search = pres.get("staysSearch", {})
                    sr = search.get("results", {})
                    search_results = sr.get("searchResults", [])
                    if search_results:
                        break

        if not search_results:
            logger.warning("No se encontraron searchResults en el JSON")
            return results

        for item in search_results:
            listing = _parse_search_result_item(item)
            if listing and listing.title:
                results.append(listing)

    except (json.JSONDecodeError, TypeError, KeyError, IndexError) as e:
        logger.error("Error al parsear resultados de busqueda: %s", e)

    return results


def _parse_search_result_item(item: dict) -> Optional[ListingData]:
    try:
        listing = ListingData(source="airbnb")
        listing.title = item.get("title", "")

        # Rating: "4,88 (76)"
        rating_str = item.get("avgRatingLocalized", "")
        if rating_str:
            rp = r'([\d,\.]+)\s*\((\d+)\)'
            rating_match = re.match(rp, rating_str)
            if rating_match:
                listing.rating = float(rating_match.group(1).replace(",", "."))
                listing.review_count = int(rating_match.group(2))

        # Precio por noche
        price_data = item.get("structuredDisplayPrice", {})
        if price_data:
            explanation = price_data.get("explanationData", {})
            if explanation:
                price_details = explanation.get("priceDetails", [])
                for group in price_details:
                    for detail in group.get("items", []):
                        desc = detail.get("description", "")
                        nightly_match = re.search(r'por \$([\d.,]+)', desc)
                        if nightly_match:
                            ps = nightly_match.group(1).replace(".", "").replace(",", ".")
                            try:
                                listing.price_per_night = float(ps)
                            except ValueError:
                                pass
                            break
                    if listing.price_per_night > 0:
                        break

            if listing.price_per_night == 0:
                primary = price_data.get("primaryLine", {})
                if primary:
                    price_str = primary.get("price", "")
                    qualifier = primary.get("qualifier", "")
                    match = re.search(r'\$([\d.,]+)', price_str)
                    if match:
                        total = float(match.group(1).replace(".", "").replace(",", "."))
                        nights_match = re.search(r'(\d+)\s*noche', qualifier)
                        if nights_match:
                            nights = int(nights_match.group(1))
                            if nights > 0:
                                listing.price_per_night = round(total / nights, 2)
                        else:
                            listing.price_per_night = total

            # Moneda
            primary = price_data.get("primaryLine", {})
            if primary:
                price_str = primary.get("price", "")
                if "USD" in price_str:
                    listing.currency = "USD"
                elif "EUR" in price_str:
                    listing.currency = "EUR"

        # Habitaciones
        content = item.get("structuredContent", {})
        if content:
            for pline in content.get("primaryLine", []):
                body = pline.get("body", "")
                bed_match = re.search(r'(\d+)\s*dormitorio', body, re.I)
                if bed_match:
                    listing.bedrooms = int(bed_match.group(1))
                beds_match = re.search(r'(\d+)\s*cama', body, re.I)
                if beds_match:
                    listing.beds = int(beds_match.group(1))

        # Fotos
        pictures = item.get("contextualPictures", [])
        if pictures:
            listing.photo_count = len(pictures)
            for pic in pictures[:5]:
                pic_url = pic.get("picture", "")
                if pic_url:
                    listing.photos.append(pic_url)

        # demandStayListing (ID, coords)
        demand = item.get("demandStayListing", {})
        if demand:
            encoded_id = demand.get("id", "")
            if encoded_id:
                try:
                    decoded = base64.b64decode(encoded_id).decode("utf-8")
                    if ":" in decoded:
                        listing.listing_id = decoded.split(":")[-1]
                except Exception:
                    listing.listing_id = encoded_id

            if listing.listing_id:
                listing.url = "https://www.airbnb.com/rooms/" + listing.listing_id

            location = demand.get("location", {})
            if location:
                coord = location.get("coordinate", {})
                if coord:
                    listing.latitude = float(coord.get("latitude", 0) or 0)
                    listing.longitude = float(coord.get("longitude", 0) or 0)

        subtitle = item.get("subtitle", "")
        if subtitle:
            listing.neighborhood = subtitle

        return listing

    except Exception as e:
        logger.warning("Error al parsear resultado de busqueda: %s", e)
        return None


def _extract_booking(soup: BeautifulSoup, url: str) -> ListingData:
    listing = ListingData()
    json_ld_items = _extract_json_ld(soup)
    meta = _extract_meta_tags(soup)

    for item in json_ld_items:
        if item.get("@type") in ["LodgingBusiness", "Hotel", "VacationRental", "Accommodation"]:
            listing.title = item.get("name", "")
            listing.description = item.get("description", "")
            if item.get("aggregateRating"):
                listing.rating = float(item["aggregateRating"].get("ratingValue", 0))
                listing.review_count = int(item["aggregateRating"].get("reviewCount", 0))
            addr = item.get("address", {})
            if isinstance(addr, dict):
                listing.address = addr.get("streetAddress", "")
                listing.city = addr.get("addressLocality", "")
                listing.country = addr.get("addressCountry", "")
            images = item.get("image", [])
            if isinstance(images, list):
                listing.photos = images[:20]
            elif isinstance(images, str):
                listing.photos = [images]
            listing.photo_count = len(listing.photos)
            break

    if not listing.title:
        listing.title = meta.get("title", "") or (soup.title.string if soup.title else "")
    if not listing.description:
        listing.description = meta.get("description", "")
    return listing


def _extract_vrbo(soup: BeautifulSoup, url: str) -> ListingData:
    listing = ListingData()
    json_ld_items = _extract_json_ld(soup)
    meta = _extract_meta_tags(soup)
    for item in json_ld_items:
        listing.title = item.get("name", "") or listing.title
        listing.description = item.get("description", "") or listing.description
        if item.get("aggregateRating"):
            listing.rating = float(item["aggregateRating"].get("ratingValue", 0))
            listing.review_count = int(item["aggregateRating"].get("reviewCount", 0))
    if not listing.title:
        listing.title = meta.get("title", "")
    id_match = re.search(r'/(\d+)', url)
    if id_match:
        listing.listing_id = id_match.group(1)
    return listing


def _extract_google(soup: BeautifulSoup, url: str) -> ListingData:
    listing = ListingData()
    json_ld_items = _extract_json_ld(soup)
    meta = _extract_meta_tags(soup)
    for item in json_ld_items:
        listing.title = item.get("name", "") or listing.title
        listing.description = item.get("description", "") or listing.description
    if not listing.title:
        listing.title = meta.get("title", "")
    return listing


def _extract_generic(soup: BeautifulSoup, url: str) -> ListingData:
    listing = ListingData()
    json_ld_items = _extract_json_ld(soup)
    meta = _extract_meta_tags(soup)
    for item in json_ld_items:
        listing.title = item.get("name", "") or listing.title
        listing.description = item.get("description", "") or listing.description
        if item.get("aggregateRating"):
            listing.rating = float(item["aggregateRating"].get("ratingValue", 0))
            listing.review_count = int(item["aggregateRating"].get("reviewCount", 0))
    if not listing.title:
        listing.title = meta.get("title", "") or (soup.title.string if soup.title else "")
    return listing


def create_manual_listing(data: dict) -> ListingData:
    listing = ListingData(source="manual")
    field_mapping = {
        "title": "title", "titulo": "title",
        "description": "description", "descripcion": "description",
        "address": "address", "direccion": "address",
        "city": "city", "ciudad": "city",
        "country": "country", "pais": "country",
        "neighborhood": "neighborhood", "barrio": "neighborhood",
        "price": "price_per_night", "precio": "price_per_night",
        "price_per_night": "price_per_night",
        "currency": "currency", "moneda": "currency",
        "bedrooms": "bedrooms", "habitaciones": "bedrooms", "dormitorios": "bedrooms",
        "beds": "beds", "camas": "beds",
        "bathrooms": "bathrooms", "banos": "bathrooms",
        "max_guests": "max_guests", "huespedes": "max_guests", "guests": "max_guests",
        "property_type": "property_type", "tipo": "property_type",
        "rating": "rating", "calificacion": "rating",
        "review_count": "review_count", "reviews": "review_count",
        "amenities": "amenities", "amenidades": "amenities", "comodidades": "amenities",
        "cancellation_policy": "cancellation_policy",
        "check_in": "check_in", "check_out": "check_out",
        "min_nights": "min_nights",
        "host_name": "host_name", "superhost": "superhost",
    }

    for input_key, value in data.items():
        mapped_key = field_mapping.get(input_key.lower(), input_key)
        if hasattr(listing, mapped_key):
            if mapped_key == "amenities":
                if isinstance(value, str):
                    value = [normalize_amenity(a) for a in value.split(",")]
                elif isinstance(value, list):
                    value = [normalize_amenity(a) for a in value]
            elif mapped_key in ("price_per_night", "cleaning_fee", "service_fee", "rating", "bathrooms"):
                value = float(value) if value else 0.0
            elif mapped_key in ("bedrooms", "beds", "max_guests", "review_count", "min_nights", "photo_count"):
                value = int(value) if value else 0
            elif mapped_key == "superhost":
                value = bool(value)
            setattr(listing, mapped_key, value)

    return listing


def interactive_input() -> ListingData:
    print("\n" + "=" * 60)
    print("   ALOJANDO BOT - Ingreso manual de anuncio")
    print("=" * 60)
    data = {}
    data["title"] = input("Titulo del anuncio: ").strip()
    data["city"] = input("Ciudad: ").strip()
    data["country"] = input("Pais: ").strip()
    data["neighborhood"] = input("Barrio/Zona: ").strip()
    price_str = input("Precio por noche: ").strip()
    data["price_per_night"] = price_str if price_str else "0"
    data["currency"] = input("Moneda (USD/EUR/ARS) [USD]: ").strip() or "USD"
    data["max_guests"] = input("Huespedes maximos: ").strip() or "0"
    data["bedrooms"] = input("Dormitorios: ").strip() or "0"
    amenities_str = input("Amenidades (separadas por coma): ").strip()
    data["amenities"] = amenities_str if amenities_str else ""
    data["rating"] = input("Calificacion (1-5): ").strip() or "0"
    data["review_count"] = input("Cantidad de resenas: ").strip() or "0"
    return create_manual_listing(data)
