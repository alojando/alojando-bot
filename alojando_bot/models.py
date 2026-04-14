"""
Modelos de datos para Alojando BOT
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ListingData:
    """Datos de un anuncio de alquiler temporario."""
    # Identificación
    source: str = ""           # airbnb, booking, vrbo, google, manual
    url: str = ""
    listing_id: str = ""

    # Información básica
    title: str = ""
    description: str = ""
    property_type: str = ""    # apartamento, casa, estudio, etc.

    # Ubicación
    address: str = ""
    city: str = ""
    country: str = ""
    neighborhood: str = ""
    latitude: float = 0.0
    longitude: float = 0.0

    # Precio
    price_per_night: float = 0.0
    currency: str = "USD"
    cleaning_fee: float = 0.0
    service_fee: float = 0.0

    # Capacidad
    max_guests: int = 0
    bedrooms: int = 0
    beds: int = 0
    bathrooms: float = 0.0

    # Amenidades
    amenities: list = field(default_factory=list)

    # Fotos
    photos: list = field(default_factory=list)       # URLs de fotos
    photo_count: int = 0

    # Reseñas
    rating: float = 0.0
    review_count: int = 0
    reviews: list = field(default_factory=list)      # Lista de textos de reseñas

    # Host
    host_name: str = ""
    superhost: bool = False
    host_response_rate: str = ""

    # Políticas
    cancellation_policy: str = ""
    check_in: str = ""
    check_out: str = ""
    min_nights: int = 0

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class ComparisonResult:
    """Resultado del análisis comparativo."""
    # Anuncio original
    original: Optional[ListingData] = None

    # Comparables encontrados
    comparables: list = field(default_factory=list)  # Lista de ListingData

    # Análisis de precios
    avg_price: float = 0.0
    median_price: float = 0.0
    min_price: float = 0.0
    max_price: float = 0.0
    price_percentile: float = 0.0     # Percentil del precio original
    suggested_price_low: float = 0.0
    suggested_price_high: float = 0.0

    # Análisis de amenidades
    common_amenities: list = field(default_factory=list)      # Amenidades más comunes
    missing_amenities: list = field(default_factory=list)      # Que el original no tiene
    unique_amenities: list = field(default_factory=list)       # Que el original tiene y otros no

    # Análisis de reseñas
    avg_rating: float = 0.0
    rating_comparison: str = ""

    # Sugerencias
    title_suggestions: list = field(default_factory=list)
    description_suggestions: list = field(default_factory=list)
    photo_suggestions: list = field(default_factory=list)
    pricing_suggestions: list = field(default_factory=list)
    amenity_suggestions: list = field(default_factory=list)
    general_suggestions: list = field(default_factory=list)
