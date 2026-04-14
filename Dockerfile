FROM python:3.11-slim

# Dependencias de sistema para Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 \
    libxss1 libxtst6 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Playwright + Chromium
RUN playwright install chromium

# Copiar proyecto
COPY . .

# Crear directorio de reportes
RUN mkdir -p reportes

ENV FLASK_DEBUG=false

# Railway inyecta $PORT automaticamente
EXPOSE ${PORT:-5000}

CMD ["python", "-m", "web.app"]
