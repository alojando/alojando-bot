# Alojando BOT

BOT de analisis y comparacion de alquileres temporarios. Toma un anuncio de alquiler (URL o datos manuales) y busca, analiza y compara contra listings similares en Airbnb, Booking, Vrbo y Google Vacation Rentals. Genera un informe detallado con sugerencias de precios, mejoras en titulo, descripcion, fotos y amenidades.

## Arquitectura

**Stack:** Flask backend (Python 3.11) + React frontend (inline Babel-transpiled JSX en un solo HTML).

**Flujo principal (browser-assisted):**
1. Frontend envia URL del anuncio al backend `/api/proxy-fetch`
2. Backend usa Playwright headless Chromium para obtener HTML renderizado (con stealth anti-detection)
3. Frontend solicita URLs de busqueda via `/api/search-urls` (incluye filtros de dormitorios, fechas, huespedes, tipo propiedad, radio, portales seleccionados)
4. Frontend itera por cada portal, llama a `/api/proxy-fetch` para obtener resultados de busqueda (con paginacion para Airbnb)
5. HTML de todos los portales se envia a `/api/analyze/browser-assisted`
6. Backend parsea HTML, filtra por similitud (dormitorios exactos, capacidad, rango de precio), convierte monedas (ARS/USD via API), genera analisis y reportes
7. Frontend hace polling de `/api/analyze/{id}` hasta completar

## Estructura de archivos

```
alojando_bot/           # Core del bot
  config.py             # Configuracion (headers, portales, amenidades mapping)
  models.py             # ListingData dataclass, ComparisonResult
  extractor.py          # Extrae datos de HTML de listings (Airbnb, Booking, etc.)
  scraper.py            # Construye URLs de busqueda, parsea resultados de cada portal
  browser_fetch.py      # Playwright headless con stealth (anti-detection, cookie dismiss)
  currency.py           # Conversion de monedas con cache (open.er-api, frankfurter.app)
  analyzer.py           # Analisis comparativo, estadisticas, sugerencias
  report_html.py        # Genera reporte HTML standalone
  report_word.py        # Genera reporte .docx
  demo_data.py          # Datos de demo (Palermo Soho)

web/
  app.py                # Flask API (endpoints, polling, proxy-fetch, geocoding)
  frontend/
    index.html          # React SPA completa (formulario, charts, resultados, tabs)

Dockerfile              # Python 3.11-slim + Playwright Chromium
railway.toml            # Config de deploy en Railway
requirements.txt        # Dependencias Python
```

## Comandos

```bash
# Desarrollo local
pip install -r requirements.txt
playwright install chromium
python -m web.app
# Abre en http://localhost:5000

# Docker
docker build -t alojando-bot .
docker run -p 5000:5000 alojando-bot
```

## API Endpoints

- `GET /api/health` - Health check (incluye estado de Playwright)
- `POST /api/proxy-fetch` - Proxy que usa Playwright para obtener HTML de cualquier URL
- `POST /api/search-urls` - Genera URLs de busqueda para cada portal con filtros
- `POST /api/analyze/browser-assisted` - Inicia analisis con HTML pre-obtenido
- `GET /api/analyze/{id}` - Polling de progreso/resultado
- `POST /api/analyze` - Analisis directo (manual/demo)
- `GET /api/report/{filename}` - Descarga reportes generados

## Detalles tecnicos importantes

### Scraping multi-portal
- **Airbnb**: Busqueda con bounding box, filtros `min_bedrooms/max_bedrooms`, `l2_property_type_ids`, paginacion con `items_offset` (18 resultados por pagina)
- **Booking**: Filtro `entire_place_bedroom_count`, `nflt=ht_id%3D220` (solo apartamentos completos), acepta status 202
- **Google Travel**: Parser de DOM especifico (`<h2 class="BgYkof">` vacation rentals, `<div class="AdWm1c">` hotels), precios en ARS con formato "$ 60.245"
- **Vrbo**: Tiene rate limiting agresivo (429), hay retry logic con delay

### Stealth anti-detection (browser_fetch.py)
- Override de `navigator.webdriver`, fake plugins, fake languages, chrome.runtime
- Auto-dismiss de cookie popups (9 selectores comunes)
- Scroll para lazy-loading
- Process tree killing robusto (Windows/Linux)

### Conversion de monedas (currency.py)
- Airbnb devuelve USD, Booking/Google devuelven ARS
- 3 APIs en cascada: open.er-api.com, frankfurter.app, USD pivot
- Cache de 1 hora

### Frontend (index.html)
- React 18 + Babel standalone (transpilacion en browser)
- Chart.js para graficos (barras, doughnut)
- Estado: `selectedPortals`, `maxComparables`, formulario con dormitorios/huespedes/amenidades/fechas/tipo propiedad
- La funcion `runBrowserAssistedAnalysis` tiene 13 parametros - tener cuidado al modificarla
- Responsive con media queries a 768px y 480px

### Filtrado de comparables (scraper.py `_filter_similar`)
- Dormitorios: match exacto (si es estudio, solo estudios)
- Capacidad: no mas de 2x la capacidad del listing original
- Precio: entre 0.1x y 5x del precio original (elimina outliers)

## Deploy

Configurado para **Railway** con Dockerfile. Railway inyecta `$PORT` automaticamente. No requiere variables de entorno obligatorias. El health check esta en `/api/health`.

## Convenciones

- Idioma de la UI: espanol (argentino)
- Moneda principal: USD con soporte ARS
- Codigo y comentarios: mix espanol/ingles
- No usar test files en produccion (estan en .dockerignore/.gitignore)
