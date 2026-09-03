# Imagen para ejecutar los reportes de forma programada (cron del host o scheduler externo)
# Build:  docker build -t reports-suite .
# Run:    docker compose run --rm gespro
FROM python:3.12-slim

# fuentes DejaVu para acentos en PDF
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# uv como gestor de dependencias
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system --no-cache fpdf2>=2.7 httpx>=0.27 PyYAML>=6.0

COPY . .

# Sin entrada por defecto: cada servicio del compose define su comando
CMD ["python", "gespro/gespro_report.py"]
