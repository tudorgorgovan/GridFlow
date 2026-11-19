"""
GridFlow settings: project paths, country configuration and secrets.

Works the same way in two places:
- in Docker, where docker-compose.yaml sets GRIDFLOW_HOME=/opt/airflow/gridflow
  and passes the variables from .env to the containers;
- locally (tests, quick scripts), where GRIDFLOW_HOME is not set, so the repo root
  is used, and .env is read with python-dotenv.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# settings.py is at <repo>/src/gridflow/settings.py -> parents[2] is <repo>
_REPO_ROOT = Path(__file__).resolve().parents[2]

GRIDFLOW_HOME = Path(os.getenv("GRIDFLOW_HOME", _REPO_ROOT))
CONFIG_FILE = GRIDFLOW_HOME / "config" / "countries.yaml"
DATA_DIR = GRIDFLOW_HOME / "data"
RAW_DIR = DATA_DIR / "raw"

# Locally, load .env so ENTSOE_TOKEN is available. In Docker the variables are
# already in the environment, and python-dotenv does not override them.
try:
    from dotenv import load_dotenv

    load_dotenv(GRIDFLOW_HOME / ".env")
except ImportError:
    pass


def _read_config(path: Path = CONFIG_FILE) -> dict:
    with open(path, encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    return config


def load_countries(path: Path = CONFIG_FILE) -> list[dict]:
    """Countries from countries.yaml that are enabled.

    A country without an `enabled` key is treated as enabled.
    """
    config = _read_config(path)
    all_countries = config["countries"]

    enabled_countries = []
    for country in all_countries:
        is_enabled = country.get("enabled", True)
        if is_enabled:
            enabled_countries.append(country)

    return enabled_countries


def load_entsoe_datasets(path: Path = CONFIG_FILE) -> list[str]:
    """ENTSO-E datasets to download every day (load, generation, prices)."""
    config = _read_config(path)
    datasets = config["entsoe_datasets"]
    return list(datasets)


def get_entsoe_token() -> str:
    """The ENTSO-E security token from the environment, or a clear error."""
    token = os.getenv("ENTSOE_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "ENTSOE_TOKEN is not set. Add it to the .env file in the project root."
        )
    return token
