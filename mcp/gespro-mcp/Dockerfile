# ──────────────────────────────────────────────────────────────────────────────
# Dockerfile — GESPRO MCP Server
# ──────────────────────────────────────────────────────────────────────────────
# Construir:
#   docker build -t gespro-mcp:latest .
#
# Ejecutar (stdio, para docker exec desde un cliente MCP):
#   docker compose up -d && docker exec -i gespro-mcp python3 main.py
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY server.py .
COPY main.py .

# Variables de entorno por defecto (se sobrescriben con .env o env_file)
# ⚠ NO poner la API key real aquí — queda grabada en la imagen.
ENV GESPRO_URL=https://redmine.example.com/
ENV GESPRO_VERIFY_SSL=true
ENV GESPRO_TIMEOUT=30.0
ENV GESPRO_DEFAULT_LIMIT=50

# Usuario no privilegiado para mayor seguridad
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import server; print('ok')" || exit 1

# Punto de entrada: el argumento --transport decide modo stdio, sse o http
ENTRYPOINT ["python3", "main.py"]
CMD ["--transport", "stdio"]
