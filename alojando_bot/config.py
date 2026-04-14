"""
Configuración de Alojando BOT
"""
import os

# Headers para requests HTTP
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Timeout para requests
REQUEST_TIMEOUT = 30

# Número máximo de comparables por defecto (configurable por request)
MAX_COMPARABLES_PER_PORTAL = 20

# Portales soportados
PORTALS = ["airbnb", "booking", "vrbo", "google"]

# Mapeo de amenidades estándar (para normalizar entre portales)
AMENITY_MAPPING = {
    # WiFi
    "wifi": "WiFi",
    "wi-fi": "WiFi",
    "internet": "WiFi",
    "wireless internet": "WiFi",
    "free wifi": "WiFi",

    # Cocina
    "kitchen": "Cocina",
    "cocina": "Cocina",
    "kitchenette": "Cocina básica",
    "fully equipped kitchen": "Cocina equipada",

    # Aire acondicionado
    "air conditioning": "Aire acondicionado",
    "aire acondicionado": "Aire acondicionado",
    "ac": "Aire acondicionado",
    "a/c": "Aire acondicionado",

    # Calefacción
    "heating": "Calefacción",
    "calefacción": "Calefacción",

    # Lavarropas
    "washer": "Lavarropas",
    "washing machine": "Lavarropas",
    "lavadora": "Lavarropas",
    "lavarropas": "Lavarropas",

    # Secadora
    "dryer": "Secadora",
    "secadora": "Secadora",

    # TV
    "tv": "TV",
    "television": "TV",
    "smart tv": "Smart TV",
    "netflix": "Netflix/Streaming",
    "streaming": "Netflix/Streaming",

    # Estacionamiento
    "parking": "Estacionamiento",
    "free parking": "Estacionamiento gratuito",
    "garage": "Garage",
    "estacionamiento": "Estacionamiento",

    # Pileta
    "pool": "Pileta",
    "swimming pool": "Pileta",
    "piscina": "Pileta",
    "pileta": "Pileta",

    # Otros
    "gym": "Gimnasio",
    "gymnasium": "Gimnasio",
    "gimnasio": "Gimnasio",
    "elevator": "Ascensor",
    "ascensor": "Ascensor",
    "balcony": "Balcón",
    "balcón": "Balcón",
    "terrace": "Terraza",
    "terraza": "Terraza",
    "garden": "Jardín",
    "jardín": "Jardín",
    "hot tub": "Jacuzzi",
    "jacuzzi": "Jacuzzi",
    "bbq": "Parrilla/BBQ",
    "grill": "Parrilla/BBQ",
    "parrilla": "Parrilla/BBQ",
    "self check-in": "Self check-in",
    "doorman": "Portero",
    "portero": "Portero",
    "security": "Seguridad",
    "seguridad": "Seguridad",
    "pet friendly": "Acepta mascotas",
    "pets allowed": "Acepta mascotas",
}

# Directorio de salida para reportes
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reportes")
