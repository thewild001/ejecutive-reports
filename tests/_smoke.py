"""Verificación Fase 3 sin pytest (pytest no instalable en este entorno)."""
import importlib
import inspect
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, ".")

for m in ["common.cache", "common.exporters", "common.snapshots",
          "common.http_client", "common.config_models", "common.settings",
          "gitlab.gitlab_report", "gespro.gespro_report",
          "trends.trends_report", "trends.rss_fetcher"]:
    importlib.import_module(m)

from common.settings import load_config
load_config("config.yaml")
print("imports + config OK")

total = failed = 0
for mod_name in ["tests.test_cache_exporters", "tests.test_metrics_analytics"]:
    t = importlib.import_module(mod_name)
    for name in [f for f in dir(t) if f.startswith("test_")]:
        fn = getattr(t, name)
        total += 1
        try:
            if "tmp_path" in inspect.signature(fn).parameters:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
        except Exception:
            failed += 1
            print("FAIL", name)
            traceback.print_exc()

print(f"{total - failed}/{total} tests OK")
sys.exit(1 if failed else 0)
