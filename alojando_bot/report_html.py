"""
Generador de informe HTML interactivo con graficos Chart.js.
"""
import os
import html as html_mod
import logging
from datetime import datetime
from .models import ComparisonResult

logger = logging.getLogger(__name__)

PORTAL_COLORS = {
    "airbnb": "#FF5A5F",
    "booking": "#003580",
    "vrbo": "#3B5998",
    "google": "#4285F4",
    "manual": "#6B7280",
}


def generate_html_report(result: ComparisonResult, output_path: str = None) -> str:
    """Genera un informe HTML completo con graficos interactivos."""
    if output_path is None:
        from .config import OUTPUT_DIR
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(OUTPUT_DIR, "informe_{}.html".format(timestamp))

    original = result.original
    comparables = result.comparables
    currency = original.currency if original else "USD"

    # Preparar datos para graficos
    prices = [c.price_per_night for c in comparables if c.price_per_night > 0]
    price_labels = [_truncate(c.title, 30) for c in comparables if c.price_per_night > 0]
    price_sources = [c.source for c in comparables if c.price_per_night > 0]

    ratings = [c.rating for c in comparables if c.rating > 0]
    rating_labels = [_truncate(c.title, 25) for c in comparables if c.rating > 0]

    portal_counts = {}
    for c in comparables:
        portal_counts[c.source] = portal_counts.get(c.source, 0) + 1

    portal_avg_prices = {}
    for c in comparables:
        if c.price_per_night > 0:
            portal_avg_prices.setdefault(c.source, []).append(c.price_per_night)
    portal_avg_prices = {k: sum(v) / len(v) for k, v in portal_avg_prices.items()}

    # Construir secciones
    comp_rows = _build_comparable_rows(comparables[:20], currency)
    amenity_html = _build_amenity_section(result)
    pricing_sug = _build_suggestions(result.pricing_suggestions)
    amenity_sug = _build_suggestions(result.amenity_suggestions)
    title_sug = _build_suggestions(result.title_suggestions)
    desc_sug = _build_suggestions(result.description_suggestions)
    photo_sug = _build_suggestions(result.photo_suggestions)
    general_sug = _build_suggestions(result.general_suggestions)

    now = datetime.now()
    date_str = now.strftime("%d/%m/%Y a las %H:%M")
    footer_date = now.strftime("%d/%m/%Y %H:%M")

    orig_price = "{:.0f}".format(original.price_per_night)
    orig_rating = "{:.1f}".format(original.rating)
    median_str = "{:.0f}".format(result.median_price)
    avg_rating_str = "{:.1f}".format(result.avg_rating)

    # Datos JS
    js_price_labels = _js_array(price_labels[:15])
    js_prices = str(prices[:15])
    js_price_colors = _js_array([_portal_color(s) for s in price_sources[:15]])
    js_orig_price_line = str([original.price_per_night] * min(len(prices), 15))

    js_portal_labels = _js_array(list(portal_counts.keys()))
    js_portal_data = str(list(portal_counts.values()))
    js_portal_colors = _js_array([_portal_color(p) for p in portal_counts.keys()])

    js_pavg_labels = _js_array(list(portal_avg_prices.keys()))
    js_pavg_data = str([round(v) for v in portal_avg_prices.values()])
    js_pavg_colors = _js_array([_portal_color(p) for p in portal_avg_prices.keys()])

    js_rating_labels = _js_array(rating_labels[:15])
    js_ratings = str(ratings[:15])
    js_orig_rating_line = str([original.rating] * min(len(ratings), 15))

    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alojando BOT - Informe Comparativo</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root { --primary: #2563eb; --success: #16a34a; --warning: #d97706; --danger: #dc2626;
  --bg: #f8fafc; --card: #fff; --text: #1e293b; --text-light: #64748b; --border: #e2e8f0; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--text); line-height:1.6; }
.header { background:linear-gradient(135deg,var(--primary),#1d4ed8); color:#fff; padding:2rem; text-align:center; }
.header h1 { font-size:2rem; margin-bottom:.5rem; }
.header p { opacity:.9; font-size:1.1rem; }
.container { max-width:1200px; margin:0 auto; padding:2rem; }
.stats-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:1rem; margin-bottom:2rem; }
.stat-card { background:var(--card); border-radius:12px; padding:1.5rem; box-shadow:0 1px 3px rgba(0,0,0,.1); text-align:center; }
.stat-card .value { font-size:2rem; font-weight:700; color:var(--primary); }
.stat-card .label { color:var(--text-light); font-size:.875rem; margin-top:.25rem; }
.section { background:var(--card); border-radius:12px; padding:2rem; margin-bottom:1.5rem; box-shadow:0 1px 3px rgba(0,0,0,.1); }
.section h2 { font-size:1.4rem; margin-bottom:1rem; padding-bottom:.5rem; border-bottom:2px solid var(--primary); color:var(--primary); }
.section h3 { font-size:1.1rem; margin:1rem 0 .5rem; color:var(--text); }
.chart-container { position:relative; height:350px; margin:1rem 0; }
.suggestion { background:#f0f9ff; border-left:4px solid var(--primary); padding:1rem 1.25rem; margin:.75rem 0; border-radius:0 8px 8px 0; font-size:.95rem; }
.suggestion.positive { background:#f0fdf4; border-left-color:var(--success); }
.comparables-table { width:100%; border-collapse:collapse; margin:1rem 0; font-size:.9rem; }
.comparables-table th { background:var(--primary); color:#fff; padding:.75rem; text-align:left; font-weight:600; }
.comparables-table td { padding:.75rem; border-bottom:1px solid var(--border); }
.comparables-table tr:hover { background:#f1f5f9; }
.comparables-table tr.original { background:#dbeafe; font-weight:600; }
.portal-badge { display:inline-block; padding:.2rem .6rem; border-radius:9999px; font-size:.75rem; font-weight:600; color:#fff; }
.portal-airbnb { background:#FF5A5F; } .portal-booking { background:#003580; }
.portal-vrbo { background:#3B5998; } .portal-google { background:#4285F4; } .portal-manual { background:#6B7280; }
.amenity-tag { display:inline-block; padding:.25rem .75rem; margin:.25rem; border-radius:9999px; font-size:.85rem; background:#e0e7ff; color:#3730a3; }
.amenity-tag.missing { background:#fee2e2; color:#991b1b; }
.amenity-tag.unique { background:#dcfce7; color:#166534; }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; }
@media (max-width:768px) { .two-col { grid-template-columns:1fr; } .container { padding:1rem; } }
.footer { text-align:center; padding:2rem; color:var(--text-light); font-size:.85rem; }
</style>
</head>
<body>

<div class="header">
  <h1>Alojando BOT - Informe Comparativo</h1>
  <p>TITLE_PLACEHOLDER | CITY_PLACEHOLDER</p>
  <p style="font-size:.9rem;margin-top:.5rem;">Generado el DATE_PLACEHOLDER</p>
</div>

<div class="container">

<!-- Stats -->
<div class="stats-grid">
  <div class="stat-card"><div class="value">COMP_COUNT</div><div class="label">Comparables encontrados</div></div>
  <div class="stat-card"><div class="value">CURRENCY MEDIAN_PRICE</div><div class="label">Precio mediana/noche</div></div>
  <div class="stat-card"><div class="value">CURRENCY ORIG_PRICE</div><div class="label">Tu precio/noche</div></div>
  <div class="stat-card"><div class="value">AVG_RATING/5.0</div><div class="label">Rating promedio zona</div></div>
</div>

<!-- Precios -->
<div class="section">
  <h2>Analisis de Precios</h2>
  <div class="two-col">
    <div><div class="chart-container"><canvas id="priceChart"></canvas></div></div>
    <div><div class="chart-container"><canvas id="priceDistChart"></canvas></div></div>
  </div>
  <h3>Sugerencias de Precio</h3>
  PRICING_SUGGESTIONS
</div>

<!-- Portales -->
<div class="section">
  <h2>Comparables por Portal</h2>
  <div class="two-col">
    <div class="chart-container"><canvas id="portalChart"></canvas></div>
    <div class="chart-container"><canvas id="portalPriceChart"></canvas></div>
  </div>
</div>

<!-- Tabla -->
<div class="section">
  <h2>Detalle de Comparables</h2>
  <div style="overflow-x:auto;">
    <table class="comparables-table">
      <thead><tr><th>Portal</th><th>Titulo</th><th>Precio/noche</th><th>Rating</th><th>Resenas</th><th>Dormitorios</th></tr></thead>
      <tbody>
        <tr class="original">
          <td><span class="portal-badge portal-ORIG_SOURCE">TU ANUNCIO</span></td>
          <td>ORIG_TITLE</td><td>CURRENCY ORIG_PRICE</td>
          <td>ORIG_RATING</td><td>ORIG_REVIEWS</td><td>ORIG_BEDROOMS</td>
        </tr>
        COMPARABLE_ROWS
      </tbody>
    </table>
  </div>
</div>

<!-- Amenidades -->
<div class="section">
  <h2>Analisis de Amenidades</h2>
  AMENITY_SECTION
  <h3>Sugerencias</h3>
  AMENITY_SUGGESTIONS
</div>

<!-- Calificaciones -->
<div class="section">
  <h2>Calificaciones y Resenas</h2>
  <div class="chart-container" style="height:250px;"><canvas id="ratingChart"></canvas></div>
  <div class="suggestion positive">RATING_COMPARISON</div>
</div>

<!-- Titulo -->
<div class="section"><h2>Mejoras en Titulo</h2>TITLE_SUGGESTIONS</div>

<!-- Descripcion -->
<div class="section"><h2>Mejoras en Descripcion</h2>DESCRIPTION_SUGGESTIONS</div>

<!-- Fotos -->
<div class="section"><h2>Mejoras en Fotos</h2>PHOTO_SUGGESTIONS</div>

<!-- General -->
<div class="section"><h2>Recomendaciones Generales</h2>GENERAL_SUGGESTIONS</div>

</div>

<div class="footer">
  <p>Generado por Alojando BOT | FOOTER_DATE</p>
  <p>Este informe es orientativo. Los datos provienen de fuentes publicas y pueden variar.</p>
</div>

<script>
new Chart(document.getElementById('priceChart'), {
  type:'bar', data:{ labels:JS_PRICE_LABELS,
  datasets:[{ label:'Precio/noche (CURRENCY)', data:JS_PRICES,
  backgroundColor:JS_PRICE_COLORS, borderWidth:0, borderRadius:4 },
  { label:'Tu precio', data:JS_ORIG_PRICE_LINE, type:'line', borderColor:'#dc2626', borderWidth:2, borderDash:[5,5], pointRadius:0, fill:false }]
  }, options:{ responsive:true, maintainAspectRatio:false,
  plugins:{ title:{ display:true, text:'Precios por Comparable' } },
  scales:{ y:{ beginAtZero:true } } } });

var pd=JS_PRICES; var bins=_cb(pd,8);
new Chart(document.getElementById('priceDistChart'), {
  type:'bar', data:{ labels:bins.labels, datasets:[{ label:'Propiedades', data:bins.counts,
  backgroundColor:'#3b82f680', borderColor:'#3b82f6', borderWidth:1, borderRadius:4 }] },
  options:{ responsive:true, maintainAspectRatio:false,
  plugins:{ title:{ display:true, text:'Distribucion de Precios' } },
  scales:{ y:{ beginAtZero:true } } } });

new Chart(document.getElementById('portalChart'), {
  type:'doughnut', data:{ labels:JS_PORTAL_LABELS, datasets:[{ data:JS_PORTAL_DATA,
  backgroundColor:JS_PORTAL_COLORS }] },
  options:{ responsive:true, maintainAspectRatio:false,
  plugins:{ title:{ display:true, text:'Comparables por Portal' } } } });

new Chart(document.getElementById('portalPriceChart'), {
  type:'bar', data:{ labels:JS_PAVG_LABELS, datasets:[{ label:'Precio promedio (CURRENCY)',
  data:JS_PAVG_DATA, backgroundColor:JS_PAVG_COLORS, borderRadius:6 }] },
  options:{ responsive:true, maintainAspectRatio:false,
  plugins:{ title:{ display:true, text:'Precio Promedio por Portal' } },
  scales:{ y:{ beginAtZero:true } } } });

new Chart(document.getElementById('ratingChart'), {
  type:'bar', data:{ labels:JS_RATING_LABELS, datasets:[{ label:'Rating', data:JS_RATINGS,
  backgroundColor:JS_RATINGS.map(function(r){return r>=4.5?'#16a34a':r>=4.0?'#d97706':'#dc2626';}), borderRadius:4 },
  { label:'Tu rating', data:JS_ORIG_RATING_LINE, type:'line', borderColor:'#2563eb', borderWidth:2, borderDash:[5,5], pointRadius:0, fill:false }] },
  options:{ responsive:true, maintainAspectRatio:false,
  plugins:{ title:{ display:true, text:'Comparacion de Ratings' } },
  scales:{ y:{ min:0, max:5 } } } });

function _cb(d,n){ if(!d.length) return {labels:[],counts:[]};
  var mn=Math.min.apply(null,d),mx=Math.max.apply(null,d),w=(mx-mn)/n||1;
  var l=[],c=[]; for(var i=0;i<n;i++){l.push(Math.round(mn+i*w)+'-'+Math.round(mn+(i+1)*w)); c.push(0);}
  d.forEach(function(v){ var b=Math.floor((v-mn)/w); if(b>=n)b=n-1; c[b]++; });
  return {labels:l,counts:c}; }
</script>
</body></html>"""

    # Reemplazar placeholders
    replacements = {
        "TITLE_PLACEHOLDER": _esc(original.title or "Tu propiedad"),
        "CITY_PLACEHOLDER": _esc(original.city or "Ubicacion no especificada"),
        "DATE_PLACEHOLDER": date_str,
        "FOOTER_DATE": footer_date,
        "COMP_COUNT": str(len(comparables)),
        "CURRENCY": _esc(currency),
        "MEDIAN_PRICE": median_str,
        "ORIG_PRICE": orig_price,
        "AVG_RATING": avg_rating_str,
        "ORIG_SOURCE": original.source or "manual",
        "ORIG_TITLE": _esc(_truncate(original.title, 50)),
        "ORIG_RATING": orig_rating,
        "ORIG_REVIEWS": str(original.review_count),
        "ORIG_BEDROOMS": str(original.bedrooms),
        "COMPARABLE_ROWS": comp_rows,
        "AMENITY_SECTION": amenity_html,
        "PRICING_SUGGESTIONS": pricing_sug,
        "AMENITY_SUGGESTIONS": amenity_sug,
        "TITLE_SUGGESTIONS": title_sug,
        "DESCRIPTION_SUGGESTIONS": desc_sug,
        "PHOTO_SUGGESTIONS": photo_sug,
        "GENERAL_SUGGESTIONS": general_sug,
        "RATING_COMPARISON": _esc(result.rating_comparison),
        "JS_PRICE_LABELS": js_price_labels,
        "JS_PRICES": js_prices,
        "JS_PRICE_COLORS": js_price_colors,
        "JS_ORIG_PRICE_LINE": js_orig_price_line,
        "JS_PORTAL_LABELS": js_portal_labels,
        "JS_PORTAL_DATA": js_portal_data,
        "JS_PORTAL_COLORS": js_portal_colors,
        "JS_PAVG_LABELS": js_pavg_labels,
        "JS_PAVG_DATA": js_pavg_data,
        "JS_PAVG_COLORS": js_pavg_colors,
        "JS_RATING_LABELS": js_rating_labels,
        "JS_RATINGS": js_ratings,
        "JS_ORIG_RATING_LINE": js_orig_rating_line,
    }

    for key, value in replacements.items():
        html = html.replace(key, value)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Informe HTML generado: {}".format(output_path))
    return output_path


# --- Helpers ---

def _esc(text):
    """Escapa HTML."""
    return html_mod.escape(str(text)) if text else ""


def _truncate(text, length):
    """Trunca texto con elipsis."""
    if not text:
        return ""
    return (text[:length] + "...") if len(text) > length else text


def _portal_color(portal):
    """Devuelve el color del portal."""
    return PORTAL_COLORS.get(portal, "#94a3b8")


def _js_array(items):
    """Convierte lista Python a array JS de strings."""
    escaped = ['"{}"'.format(_esc(str(i))) for i in items]
    return "[" + ", ".join(escaped) + "]"


def _build_suggestions(items):
    """Genera HTML de sugerencias."""
    if not items:
        return ""
    parts = []
    for s in items:
        parts.append('<div class="suggestion">{}</div>'.format(_esc(s)))
    return "\n".join(parts)


def _build_comparable_rows(comparables, currency):
    """Genera filas HTML de la tabla de comparables."""
    rows = []
    for c in comparables:
        title_html = _esc(_truncate(c.title, 50))
        if c.url:
            title_html = '<a href="{}" target="_blank">{}</a>'.format(_esc(c.url), title_html)

        price_str = "{} {:.0f}".format(currency, c.price_per_night) if c.price_per_night > 0 else "-"
        rating_str = "{:.1f}".format(c.rating) if c.rating > 0 else "-"
        reviews_str = str(c.review_count) if c.review_count > 0 else "-"
        bedrooms_str = str(c.bedrooms) if c.bedrooms > 0 else "-"

        row = """<tr>
          <td><span class="portal-badge portal-{src}">{SRC}</span></td>
          <td>{title}</td><td>{price}</td><td>{rating}</td><td>{reviews}</td><td>{beds}</td>
        </tr>""".format(
            src=c.source, SRC=c.source.upper(),
            title=title_html, price=price_str,
            rating=rating_str, reviews=reviews_str, beds=bedrooms_str
        )
        rows.append(row)
    return "\n".join(rows)


def _build_amenity_section(result):
    """Genera la seccion de amenidades."""
    parts = []

    if result.common_amenities:
        parts.append('<h3>Amenidades mas comunes en la zona</h3><div>')
        for amenity, count in result.common_amenities:
            parts.append('<span class="amenity-tag">{} ({})</span>'.format(_esc(amenity), count))
        parts.append('</div>')

    if result.missing_amenities:
        parts.append('<h3>Amenidades que te faltan</h3><div>')
        for a in result.missing_amenities:
            parts.append('<span class="amenity-tag missing">{}</span>'.format(_esc(a)))
        parts.append('</div>')

    if result.unique_amenities:
        parts.append('<h3>Tus amenidades unicas (ventaja competitiva)</h3><div>')
        for a in result.unique_amenities:
            parts.append('<span class="amenity-tag unique">{}</span>'.format(_esc(a)))
        parts.append('</div>')

    return "\n".join(parts)
