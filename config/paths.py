# config/paths.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA = ROOT / "data"
INPUT = DATA / "input"
OUTPUT = DATA / "output"
TAXONOMIES = DATA / "taxonomies"
DEBUG = DATA / "_debug"
LOGS = ROOT / "logs"
RUN_LOG = LOGS / "run_log.jsonl"

for _d in [INPUT, OUTPUT, TAXONOMIES, DEBUG, LOGS]:
    _d.mkdir(parents=True, exist_ok=True)
