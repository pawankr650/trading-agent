"""Config + environment loading shared by both systems."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(ROOT / ".env")
    except ImportError:  # minimal fallback parser
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


OVERRIDES = DATA_DIR / "overrides.json"  # settings changed from the web app (keeps config.yaml comments intact)


def load_config(path: str | Path | None = None, overrides: bool = True) -> dict:
    _load_dotenv()
    path = Path(path or os.getenv("STOCKPILOT_CONFIG", ROOT / "config.yaml"))
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if overrides and OVERRIDES.exists():
        try:
            cfg.update(json.loads(OVERRIDES.read_text()))
        except ValueError:
            logging.getLogger(__name__).warning("ignoring corrupt %s", OVERRIDES)
    return cfg


def save_override(key: str, value) -> None:
    data = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    data[key] = value
    OVERRIDES.write_text(json.dumps(data, indent=1))


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / f"{name}.log")],
    )
    return logging.getLogger(name)
