"""
Motor de análisis y comparación de anuncios.
Genera sugerencias de precios, mejoras en título, descripción, fotos y amenidades.
"""
import statistics
import logging
from typing import List, Dict
from collections import Counter

from .models import ListingData, ComparisonResult
from .config import AMENITY_MAPPING

logger = logging.getLogger(__name__)


def analyze(original: ListingData, portal_results: Dict[str, List[ListingData]]) -> ComparisonResult:
    """
    Analiza el anuncio original contra los comparables encontrados.

    Args:
        original: Datos del anuncio original
        portal_results: Diccionario {portal: [ListingData, ...]}

    Returns:
        ComparisonResult con todo el análisis
    """
    result = ComparisonResult()
    result.original = original

    # Combinar todos los comparables
    all_comparables = []
    for portal, listings in portal_results.items():
        all_comparables.extend(listings)

    result.comparables = all_comparables

    if not all_comparables:
        logger.warning("No se encontraron comparables. El análisis será limitado.")
        result.general_suggestions = [
            "No se encontraron anuncios comparables en los portales buscados.",
            "Intentá con una ubicación más amplia (ciudad en vez de barrio).",
            "Verificá que la ciudad y el país estén correctamente escritos.",
        ]
        return result

    logger.info(f"Analizando {len(all_comparables)} comparables...")

    # 1. Análisis de precios
    _analyze_pricing(original, all_comparables, result)

    # 2. Análisis de amenidades
    _analyze_amenities(original, all_comparables, result)

    # 3. Análisis de ratings
    _analyze_ratings(original, all_comparables, result)

    # 4. Sugerencias de título
    _generate_title_suggestions(original, all_comparables, result)

    # 5. Sugerencias de descripción
    _generate_description_suggestions(original, all_comparables, result)

    # 6. Sugerencias de fotos
    _generate_photo_suggestions(original, all_comparables, result)

    # 7. Sugerencias generales
    _generate_general_suggestions(original, all_comparables, result)

    return result


def _analyze_pricing(original: ListingData, comparables: List[ListingData], result: ComparisonResult):
    """Análisis detallado de precios."""
    prices = [c.price_per_night for c in comparables if c.price_per_night > 0]

    if not prices:
        result.pricing_suggestions = [
            "No se pudieron obtener precios de los comparables.",
            "Considerá verificar manualmente los precios en los portales.",
        ]
        return

    result.avg_price = round(statistics.mean(prices), 2)
    result.median_price = round(statistics.median(prices), 2)
    result.min_price = min(prices)
    result.max_price = max(prices)

    # Calcular percentil del precio original
    if original.price_per_night > 0:
        below = sum(1 for p in prices if p < original.price_per_night)
        result.price_percentile = round((below / len(prices)) * 100, 1)

        # Rango sugerido (percentil 25-75 de los comparables)
        sorted_prices = sorted(prices)
        q1_idx = max(0, len(sorted_prices) // 4)
        q3_idx = min(len(sorted_prices) - 1, (3 * len(sorted_prices)) // 4)
        result.suggested_price_low = sorted_prices[q1_idx]
        result.suggested_price_high = sorted_prices[q3_idx]

        # Generar sugerencias de precio
        suggestions = []
        diff_pct = ((original.price_per_night - result.median_price) / result.median_price * 100) if result.median_price > 0 else 0

        if diff_pct > 20:
            suggestions.append(
                f"Tu precio ({original.currency} {original.price_per_night:.0f}/noche) está un "
                f"{diff_pct:.0f}% por encima de la mediana del mercado ({original.currency} {result.median_price:.0f}). "
                f"Considerá bajarlo para ser más competitivo, a menos que tu propiedad tenga diferenciadores claros."
            )
        elif diff_pct < -20:
            suggestions.append(
                f"Tu precio ({original.currency} {original.price_per_night:.0f}/noche) está un "
                f"{abs(diff_pct):.0f}% por debajo de la mediana ({original.currency} {result.median_price:.0f}). "
                f"Podrías estar subvaluando tu propiedad. Considerá aumentar el precio gradualmente."
            )
        else:
            suggestions.append(
                f"Tu precio ({original.currency} {original.price_per_night:.0f}/noche) está alineado con "
                f"el mercado (mediana: {original.currency} {result.median_price:.0f}). ¡Buen posicionamiento!"
            )

        suggestions.append(
            f"Rango de precios del mercado: {original.currency} {result.min_price:.0f} - "
            f"{original.currency} {result.max_price:.0f}/noche."
        )
        suggestions.append(
            f"Rango sugerido (percentil 25-75): {original.currency} {result.suggested_price_low:.0f} - "
            f"{original.currency} {result.suggested_price_high:.0f}/noche."
        )

        # Sugerencia de pricing dinámico
        suggestions.append(
            "Considerá implementar precios dinámicos: subir en temporada alta/fines de semana "
            "y ofrecer descuentos para estadías largas (7+ noches)."
        )

        result.pricing_suggestions = suggestions
    else:
        result.pricing_suggestions = [
            f"Promedio del mercado: {original.currency} {result.avg_price:.0f}/noche.",
            f"Mediana del mercado: {original.currency} {result.median_price:.0f}/noche.",
            f"Rango: {original.currency} {result.min_price:.0f} - {original.currency} {result.max_price:.0f}/noche.",
            "No tenemos tu precio actual para comparar. Ingresalo para un análisis más detallado.",
        ]


def _analyze_amenities(original: ListingData, comparables: List[ListingData], result: ComparisonResult):
    """Análisis de amenidades comparativo."""
    # Contar amenidades en comparables
    amenity_counter = Counter()
    comparables_with_amenities = 0

    for comp in comparables:
        if comp.amenities:
            comparables_with_amenities += 1
            for amenity in comp.amenities:
                amenity_counter[amenity] += 1

    if not amenity_counter:
        result.amenity_suggestions = [
            "No se pudieron obtener amenidades de los comparables.",
            "Las amenidades más valoradas suelen ser: WiFi, cocina equipada, "
            "aire acondicionado, lavarropas, estacionamiento y Smart TV.",
        ]
        return

    # Amenidades más comunes (>30% de los comparables)
    threshold = max(1, comparables_with_amenities * 0.3)
    result.common_amenities = [
        (amenity, count)
        for amenity, count in amenity_counter.most_common(20)
        if count >= threshold
    ]

    # Amenidades que faltan en el original
    original_amenities_lower = {a.lower() for a in original.amenities}

    result.missing_amenities = [
        amenity for amenity, count in amenity_counter.most_common(20)
        if amenity.lower() not in original_amenities_lower
        and count >= threshold
    ]

    # Amenidades únicas del original
    all_comp_amenities_lower = {a.lower() for a in amenity_counter.keys()}
    result.unique_amenities = [
        a for a in original.amenities
        if a.lower() not in all_comp_amenities_lower
    ]

    # Generar sugerencias
    suggestions = []

    if result.missing_amenities:
        suggestions.append(
            "Amenidades populares que no figuran en tu anuncio: "
            + ", ".join(result.missing_amenities[:8]) + ". "
            "Si las tenés, asegurate de agregarlas al anuncio."
        )

    if result.unique_amenities:
        suggestions.append(
            "Amenidades que te diferencian de la competencia: "
            + ", ".join(result.unique_amenities[:5]) + ". "
            "¡Destacalas en tu título y descripción!"
        )

    # Sugerencias de amenidades de alto impacto
    high_impact = ["WiFi", "Cocina", "Aire acondicionado", "Lavarropas",
                   "Estacionamiento", "Pileta", "Smart TV", "Self check-in"]
    missing_high_impact = [a for a in high_impact if a.lower() not in original_amenities_lower]
    if missing_high_impact:
        suggestions.append(
            "Amenidades de alto impacto que podrías considerar agregar: "
            + ", ".join(missing_high_impact[:5]) + "."
        )

    result.amenity_suggestions = suggestions


def _analyze_ratings(original: ListingData, comparables: List[ListingData], result: ComparisonResult):
    """Análisis de ratings y reseñas."""
    ratings = [c.rating for c in comparables if c.rating > 0]

    if ratings:
        result.avg_rating = round(statistics.mean(ratings), 2)

        if original.rating > 0:
            if original.rating > result.avg_rating:
                result.rating_comparison = (
                    f"Tu calificación ({original.rating:.1f}) está por encima del "
                    f"promedio de competidores ({result.avg_rating:.1f}). ¡Excelente! "
                    f"Destacá esto en tu descripción."
                )
            elif original.rating < result.avg_rating:
                result.rating_comparison = (
                    f"Tu calificación ({original.rating:.1f}) está por debajo del "
                    f"promedio ({result.avg_rating:.1f}). Enfocate en mejorar la "
                    f"experiencia del huésped para subir tu rating."
                )
            else:
                result.rating_comparison = (
                    f"Tu calificación ({original.rating:.1f}) está en línea con "
                    f"el promedio del mercado ({result.avg_rating:.1f})."
                )
        else:
            result.rating_comparison = (
                f"Promedio de calificación en la zona: {result.avg_rating:.1f}/5.0. "
                f"Apuntá a superar este número."
            )


def _generate_title_suggestions(original: ListingData, comparables: List[ListingData], result: ComparisonResult):
    """Genera sugerencias para mejorar el título."""
    suggestions = []

    titles = [c.title for c in comparables if c.title]

    # Analizar longitud de títulos exitosos
    if titles:
        avg_len = statistics.mean(len(t) for t in titles)
        suggestions.append(
            f"Los títulos de competidores tienen en promedio {avg_len:.0f} caracteres. "
            f"{'Tu título es más corto de lo recomendado.' if len(original.title) < avg_len * 0.7 else ''}"
            f"{'Tu título es más largo que el promedio.' if len(original.title) > avg_len * 1.3 else ''}"
        )

    # Palabras clave comunes en títulos exitosos
    if titles:
        word_counter = Counter()
        stop_words = {"de", "en", "la", "el", "los", "las", "un", "una", "y", "con", "a",
                      "the", "in", "at", "with", "and", "for", "to", "of", "is", "-", "&",
                      "near", "from", "by", "|", "/", "·", "★"}
        for title in titles:
            words = title.lower().split()
            for word in words:
                clean = word.strip(",.!?()[]{}\"'")
                if clean and len(clean) > 2 and clean not in stop_words:
                    word_counter[clean] += 1

        top_words = [w for w, c in word_counter.most_common(15) if c >= 2]
        if top_words:
            suggestions.append(
                "Palabras más usadas en títulos de la competencia: "
                + ", ".join(top_words[:10]) + ". "
                "Considerá incluir las más relevantes."
            )

    # Buenas prácticas
    suggestions.append(
        "Buenas prácticas para títulos: incluí el tipo de propiedad, "
        "la ubicación/barrio, y 1-2 amenidades destacadas. "
        "Ej: 'Moderno 2BR con pileta en Palermo - WiFi & Smart TV'"
    )

    if original.title and not any(char.isdigit() for char in original.title):
        suggestions.append(
            "Considerá incluir números en el título (cantidad de habitaciones, "
            "distancia a puntos de interés). Los números captan la atención."
        )

    result.title_suggestions = suggestions


def _generate_description_suggestions(original: ListingData, comparables: List[ListingData], result: ComparisonResult):
    """Genera sugerencias para mejorar la descripción."""
    suggestions = []

    if original.description:
        desc_len = len(original.description)
        if desc_len < 200:
            suggestions.append(
                f"Tu descripción es corta ({desc_len} caracteres). "
                "Las descripciones más efectivas tienen entre 500-1000 caracteres. "
                "Agregá más detalles sobre el espacio, la zona y la experiencia."
            )
        elif desc_len > 2000:
            suggestions.append(
                "Tu descripción es muy larga. Considerá hacerla más concisa. "
                "Los huéspedes suelen escanear, no leer todo."
            )
    else:
        suggestions.append(
            "No se detectó una descripción. Una buena descripción es crucial para convertir visitas en reservas."
        )

    # Elementos recomendados en la descripción
    suggestions.append(
        "Elementos clave para la descripción: "
        "1) Apertura atractiva que capte la atención. "
        "2) Descripción del espacio y habitaciones. "
        "3) Amenidades destacadas. "
        "4) Información del barrio/zona (restaurantes, transporte, atracciones). "
        "5) Para quién es ideal (parejas, familias, viajeros de negocios). "
        "6) Instrucciones de llegada o cercanía a aeropuerto/transporte."
    )

    # Sugerencias de idioma
    suggestions.append(
        "Si tu propiedad atrae turistas internacionales, tené la descripción "
        "en español e inglés como mínimo."
    )

    result.description_suggestions = suggestions


def _generate_photo_suggestions(original: ListingData, comparables: List[ListingData], result: ComparisonResult):
    """Genera sugerencias para mejorar las fotos."""
    suggestions = []

    comp_photo_counts = [c.photo_count for c in comparables if c.photo_count > 0]

    if comp_photo_counts:
        avg_photos = statistics.mean(comp_photo_counts)
        suggestions.append(
            f"Los competidores tienen en promedio {avg_photos:.0f} fotos. "
            f"{'Subí más fotos para ser competitivo.' if original.photo_count < avg_photos else 'Tu cantidad de fotos está bien.'}"
            if original.photo_count > 0 else
            f"Los competidores tienen en promedio {avg_photos:.0f} fotos. Asegurate de tener al menos esa cantidad."
        )

    suggestions.extend([
        "Fotos esenciales: sala/living, cada dormitorio, baño(s), cocina, "
        "vista exterior, balcón/terraza (si aplica), entrada del edificio.",

        "Consejos de fotografía: usá luz natural, sacá fotos en ángulo amplio, "
        "mantené los espacios ordenados, y mostrá los detalles que destacás en la descripción.",

        "La primera foto es la más importante - debe mostrar el espacio más "
        "atractivo de tu propiedad. Los anuncios con buenas fotos reciben "
        "hasta 40% más de clics.",

        "Considerá incluir fotos del barrio, vistas desde la propiedad, "
        "y amenidades especiales (pileta, terraza, etc.).",
    ])

    result.photo_suggestions = suggestions


def _generate_general_suggestions(original: ListingData, comparables: List[ListingData], result: ComparisonResult):
    """Genera sugerencias generales."""
    suggestions = []

    # Análisis por portal
    portal_counts = Counter(c.source for c in comparables)
    if portal_counts:
        suggestions.append(
            "Distribución de comparables encontrados: "
            + ", ".join(f"{portal}: {count}" for portal, count in portal_counts.most_common())
            + ". Considerá listar tu propiedad en todos estos portales para maximizar visibilidad."
        )

    # Superhost status
    if not original.superhost:
        suggestions.append(
            "No sos Superhost/Preferred Partner. Trabajá en obtener esta distinción: "
            "mantené un rating alto (4.8+), respondé rápido a consultas, "
            "minimizá cancelaciones, y mantené tu calendario actualizado."
        )

    # Reseñas
    if original.review_count < 10:
        suggestions.append(
            "Tenés pocas reseñas. Estrategias para conseguir más: "
            "pedí reviews después de cada estadía, ofrecé una experiencia excepcional, "
            "y respondé amablemente a todas las reseñas existentes."
        )

    # Self check-in
    amenities_lower = [a.lower() for a in original.amenities]
    if "self check-in" not in amenities_lower and "self check in" not in amenities_lower:
        suggestions.append(
            "Considerá ofrecer self check-in (caja de llaves o cerradura inteligente). "
            "Es una de las amenidades más buscadas y mejora la experiencia del huésped."
        )

    # Política de cancelación
    if original.cancellation_policy and "strict" in original.cancellation_policy.lower():
        suggestions.append(
            "Tu política de cancelación es estricta. Una política más flexible "
            "puede atraer más reservas, especialmente de viajeros internacionales."
        )

    # Noches mínimas
    if original.min_nights > 3:
        suggestions.append(
            f"Tu estadía mínima es {original.min_nights} noches. "
            "Considerá reducirla a 1-2 noches para captar más reservas, "
            "especialmente en temporada baja."
        )

    # Publicación en múltiples plataformas
    suggestions.append(
        "Para maximizar ingresos, publicá tu propiedad en Airbnb, Booking.com, "
        "Vrbo y Google Vacation Rentals. Usá un channel manager para sincronizar "
        "calendarios y evitar doble reserva."
    )

    result.general_suggestions = suggestions


def generate_summary(result: ComparisonResult) -> str:
    """Genera un resumen textual del análisis."""
    lines = []
    lines.append(f"RESUMEN DE ANÁLISIS - {result.original.title or 'Tu propiedad'}")
    lines.append("=" * 60)

    lines.append(f"\nComparables encontrados: {len(result.comparables)}")

    if result.avg_price > 0:
        lines.append(f"\nPRECIOS DEL MERCADO:")
        lines.append(f"  Promedio: {result.original.currency} {result.avg_price:.0f}/noche")
        lines.append(f"  Mediana: {result.original.currency} {result.median_price:.0f}/noche")
        lines.append(f"  Rango: {result.original.currency} {result.min_price:.0f} - {result.original.currency} {result.max_price:.0f}")
        if result.original.price_per_night > 0:
            lines.append(f"  Tu precio: {result.original.currency} {result.original.price_per_night:.0f} (percentil {result.price_percentile:.0f})")

    if result.avg_rating > 0:
        lines.append(f"\nCALIFICACIONES:")
        lines.append(f"  {result.rating_comparison}")

    return "\n".join(lines)
