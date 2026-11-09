#!/usr/bin/env python3
"""
Entry point for GESPRO MCP Server.
Can be run directly or via docker.

Uso:
    export GESPRO_API_KEY="..."
    export GESPRO_URL="https://tu-redmine.example.com/"

    # Modo stdio (default) — tubería local, para clientes MCP / docker exec:
    python main.py
    python main.py --transport stdio

    # Modo SSE — servidor HTTP, ideal para conexiones remotas:
    python main.py --transport sse --host 0.0.0.0 --port 8000
    # → http://localhost:8000/sse

    # Modo streamable-http:
    python main.py --transport streamable-http --port 8000

La variable de entorno MCP_TRANSPORT se usa como fallback si no se
pasa --transport (los flags CLI tienen precedencia).
"""

import argparse
import os
import sys

# Add the project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="GESPRO MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transporte MCP (default: env MCP_TRANSPORT o 'stdio')",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host para transportes HTTP (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Puerto para transportes HTTP (default: 8000)",
    )
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
