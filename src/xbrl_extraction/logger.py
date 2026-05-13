# src/xbrl_extraction/logger.py
import json
from datetime import datetime, timezone
from config.paths import RUN_LOG


def log_run(entry: dict) -> None:
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    with RUN_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
