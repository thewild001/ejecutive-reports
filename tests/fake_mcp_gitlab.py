"""Servidor MCP falso (stdio) con salidas en el formato que parsea portfolio_report.

Uso: python tests/fake_mcp_gitlab.py --transport stdio
Variables: FAKE_MCP_FAIL=1 → toda tool devuelve isError; FAKE_MCP_ARGS_LOG=<ruta> →
registra "tool\t<json args>" por llamada (para verificar parámetros enviados).
"""
import json
import os
import sys

OUT = {
    "reporte_salud_proyecto": (
        "Salud: 🟡 REGULAR  (68/100)\n*Ramas* — 14 total · 2 protegidas · 7 stale\n"
        "*Issues* — 10 abiertos · 6 sin asignar\n*MRs* — 3 abiertos · 12 mergeados\n"
        "*Últimos commits*\n• 2026-11-06 fix: algo\n"),
    "analizar_rendimiento_pipelines": (
        "20 pipelines analizados\n✅ Éxito: 80 %\n❌ Fallos: 20 %\nDuración promedio: 7 min\n"),
    "analizar_merge_requests": (
        "20 analizados\n· Mergeados: 12\n· Abiertos: 3\nTiempo promedio a merge: 6.5 días\n"
        "*Top autores*\n· Ana Pérez: 7 MRs\n· Luis Gómez: 5 MRs\n*Ramas destino*\n· main: 12\n"),
    "analizar_colaboradores_activos": (
        "`▬▬▬▬` *Ana Pérez* — 30 (60%)\n`▬▬` *Luis Gómez* — 20 (40%)\n"),
    "analizar_distribucion_codigo_y_silos": (
        "*Factor Bus*: ~2 desarrolladores\nHHI: 0.620\nTop contribuidor*: 60%\nRiesgo Alto\n"
        "`▬▬▬▬` Ana Pérez: 30 (60.0%)\n`▬▬` Luis Gómez: 20 (40.0%)\n"),
    "analizar_tendencia_contribuciones": (
        "`▬▬▬` 2026-05: 40\n`▬▬▬` 2026-06: 38\n`▬▬▬` 2026-07: 36\n"
        "`▬▬` 2026-08: 20\n`▬▬` 2026-09: 15\n`▬` 2026-10: 10\n"
        "📊 Promedio: 26/mes\nPico: 2026-05 (40 commits)\n"
        "*Top contribuyentes*\n· Ana Pérez: 80 (55.0%)\n"),
    "detectar_ramas_stale": "7 ramas stale\n",
    "obtener_patrones_horarios_commits": (
        "☀️ Mañana: 10\n🌤️ Tarde: 12\n🌆 Noche: 3\n🌙 Madrugada: 1\n⏰ Hora pico: ~10:00\n"
        "Lunes: 8\nMartes: 7\nMiércoles: 6\nJueves: 5\nViernes: 4\nSábado: 1\nDomingo: 0\n"),
    "analizar_grupo_salud": (
        "3 proyectos activos\n▸ *alfa* — pipelines: 18/20 · ramas: 14 (7 stale) · issues: 10\n"
        "▸ *beta* — pipelines: 20/20 · ramas: 5 (1 stale) · issues: 2\n"),
}


def main() -> None:
    log = os.environ.get("FAKE_MCP_ARGS_LOG")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("method") == "initialize":
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "fake", "version": "0"}}}), flush=True)
        elif msg.get("method") == "tools/call":
            name = msg["params"]["name"]
            if log:
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(f"{name}\t{json.dumps(msg['params']['arguments'], sort_keys=True)}\n")
            if os.environ.get("FAKE_MCP_FAIL") or name not in OUT:
                res = {"isError": True, "content": [{"type": "text", "text": "error"}]}
            else:
                res = {"content": [{"type": "text", "text": OUT[name]}]}
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)


if __name__ == "__main__":
    main()
