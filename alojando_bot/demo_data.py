"""
Datos de demostración para Alojando BOT.
Simula resultados de búsqueda para generar informes completos de muestra.
"""
from .models import ListingData
from .extractor import create_manual_listing


def get_demo_listing() -> ListingData:
    """Devuelve un anuncio demo para analizar."""
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


def get_demo_comparables() -> dict:
    """
    Devuelve comparables simulados organizados por portal.
    Datos basados en rangos reales de Palermo Soho, Buenos Aires.
    """
    airbnb_results = [
        _make_listing("airbnb", "Luminoso estudio en Palermo Soho - Plaza Serrano",
                      price=55, rating=4.8, reviews=128, bedrooms=0, beds=1, bathrooms=1, guests=2,
                      amenities=["WiFi", "Cocina", "Aire acondicionado", "Smart TV", "Lavarropas", "Self check-in"],
                      url="https://www.airbnb.com/rooms/demo1"),
        _make_listing("airbnb", "Depto 2 amb con pileta y gym en Palermo",
                      price=82, rating=4.9, reviews=203, bedrooms=1, beds=2, bathrooms=1, guests=4,
                      amenities=["WiFi", "Cocina equipada", "Aire acondicionado", "Smart TV", "Lavarropas", "Pileta", "Gimnasio", "Self check-in", "Portero"],
                      url="https://www.airbnb.com/rooms/demo2"),
        _make_listing("airbnb", "Acogedor 1BR en el corazon de Palermo",
                      price=58, rating=4.6, reviews=87, bedrooms=1, beds=1, bathrooms=1, guests=3,
                      amenities=["WiFi", "Cocina", "Aire acondicionado", "TV", "Lavarropas"],
                      url="https://www.airbnb.com/rooms/demo3"),
        _make_listing("airbnb", "Penthouse con terraza panoramica Palermo",
                      price=120, rating=4.9, reviews=156, bedrooms=2, beds=3, bathrooms=2, guests=5,
                      amenities=["WiFi", "Cocina equipada", "Aire acondicionado", "Smart TV", "Lavarropas", "Terraza", "Parrilla/BBQ", "Self check-in", "Jacuzzi"],
                      url="https://www.airbnb.com/rooms/demo4"),
        _make_listing("airbnb", "Departamento vintage en Palermo Viejo",
                      price=48, rating=4.4, reviews=34, bedrooms=1, beds=1, bathrooms=1, guests=2,
                      amenities=["WiFi", "Cocina", "Calefaccion", "TV"],
                      url="https://www.airbnb.com/rooms/demo5"),
    ]

    booking_results = [
        _make_listing("booking", "Palermo Soho Apartments - Superior",
                      price=75, rating=4.3, reviews=312, bedrooms=1, beds=2, bathrooms=1, guests=4,
                      amenities=["WiFi", "Cocina equipada", "Aire acondicionado", "Smart TV", "Lavarropas", "Ascensor", "Seguridad 24h"],
                      url="https://www.booking.com/hotel/ar/demo1"),
        _make_listing("booking", "BA Soho Studio - Boutique Apartment",
                      price=62, rating=4.5, reviews=89, bedrooms=0, beds=1, bathrooms=1, guests=2,
                      amenities=["WiFi", "Cocina basica", "Aire acondicionado", "Smart TV", "Ascensor"],
                      url="https://www.booking.com/hotel/ar/demo2"),
        _make_listing("booking", "Casa Palermo - 2 Bedroom Luxury",
                      price=95, rating=4.7, reviews=167, bedrooms=2, beds=2, bathrooms=2, guests=5,
                      amenities=["WiFi", "Cocina equipada", "Aire acondicionado", "Smart TV", "Lavarropas", "Balcon", "Pileta", "Gimnasio", "Estacionamiento"],
                      url="https://www.booking.com/hotel/ar/demo3"),
        _make_listing("booking", "Cozy Flat Palermo Hollywood",
                      price=52, rating=4.1, reviews=45, bedrooms=1, beds=1, bathrooms=1, guests=2,
                      amenities=["WiFi", "Cocina", "Aire acondicionado", "TV"],
                      url="https://www.booking.com/hotel/ar/demo4"),
    ]

    vrbo_results = [
        _make_listing("vrbo", "Stunning Palermo Apartment with Pool Access",
                      price=88, rating=4.6, reviews=52, bedrooms=1, beds=2, bathrooms=1, guests=4,
                      amenities=["WiFi", "Cocina equipada", "Aire acondicionado", "Smart TV", "Lavarropas", "Pileta", "Balcon"],
                      url="https://www.vrbo.com/demo1"),
        _make_listing("vrbo", "Modern Loft in Palermo Soho",
                      price=70, rating=4.8, reviews=73, bedrooms=1, beds=1, bathrooms=1, guests=3,
                      amenities=["WiFi", "Cocina equipada", "Aire acondicionado", "Smart TV", "Lavarropas", "Self check-in", "Terraza"],
                      url="https://www.vrbo.com/demo2"),
        _make_listing("vrbo", "Family-Friendly 3BR in Palermo",
                      price=110, rating=4.5, reviews=28, bedrooms=3, beds=4, bathrooms=2, guests=7,
                      amenities=["WiFi", "Cocina equipada", "Aire acondicionado", "Smart TV", "Lavarropas", "Balcon", "Ascensor", "Estacionamiento"],
                      url="https://www.vrbo.com/demo3"),
    ]

    google_results = [
        _make_listing("google", "Departamento Premium Palermo - Google VR",
                      price=78, rating=4.4, reviews=0, bedrooms=1, beds=2, bathrooms=1, guests=4,
                      amenities=["WiFi", "Cocina", "Aire acondicionado"],
                      url=""),
        _make_listing("google", "Estudio ejecutivo Palermo Soho",
                      price=60, rating=4.2, reviews=0, bedrooms=0, beds=1, bathrooms=1, guests=2,
                      amenities=["WiFi", "Cocina basica", "Aire acondicionado"],
                      url=""),
    ]

    return {
        "airbnb": airbnb_results,
        "booking": booking_results,
        "vrbo": vrbo_results,
        "google": google_results,
    }


def _make_listing(source, title, price, rating, reviews, bedrooms, beds, bathrooms, guests, amenities, url=""):
    """Helper para crear un ListingData rápidamente."""
    listing = ListingData()
    listing.source = source
    listing.title = title
    listing.price_per_night = float(price)
    listing.currency = "USD"
    listing.rating = float(rating)
    listing.review_count = int(reviews)
    listing.bedrooms = int(bedrooms)
    listing.beds = int(beds)
    listing.bathrooms = float(bathrooms)
    listing.max_guests = int(guests)
    listing.amenities = amenities
    listing.url = url
    listing.city = "Buenos Aires"
    listing.country = "Argentina"
    listing.neighborhood = "Palermo"
    listing.photo_count = 15 + hash(title) % 20
    return listing
