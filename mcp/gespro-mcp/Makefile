# ──────────────────────────────────────────────────────────────────────────────
# Makefile — GESPRO MCP Server
# ──────────────────────────────────────────────────────────────────────────────
# Uso:
#   make install  → Instala dependencias (pip -r requirements.txt)
#   make run      → Modo stdio (local, para clientes MCP)
#   make run-sse  → Modo SSE en http://localhost:8000/sse
#   make build    → Construye la imagen Docker
#   make up       → Levanta el contenedor (stdio)
#   make down     → Detiene servicios
#   make logs     → Sigue los logs
#   make rebuild  → Rebuild y reinicio rápido
#   make test     → py_compile + import smoke
# ──────────────────────────────────────────────────────────────────────────────

.PHONY: help install run run-sse build up down logs rebuild test

.DEFAULT_GOAL := help

venv:
	uv venv .venv
	uv pip install --python .venv/bin/python -r requirements.txt

install:
	uv pip install -r requirements.txt

run:
	./run-mcp.sh

run-sse:
	./run-mcp.sh --transport sse --host 0.0.0.0 --port 8000

build:
	docker compose build

up: build
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

rebuild:
	docker compose build
	docker compose up -d

test:
	python3 -m py_compile server.py main.py
	python3 -c "import server; print('import ok, tools registradas')"

help:
	@echo "Targets: venv, install, run, run-sse, build, up, down, logs, rebuild, test"
