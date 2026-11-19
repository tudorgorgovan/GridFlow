"""
Client for the ENTSO-E Transparency Platform REST API.

Downloads one UTC day of one dataset for one bidding zone and returns the XML
exactly as received. Parsing happens later, in PySpark (silver layer).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

API_URL = "https://web-api.tp.entsoe.eu/api"

# Request parameters per dataset. Every name in "zone_params" gets the country's EIC code.
DATASETS = {
    "load": {  # Actual Total Load
        "params": {"documentType": "A65", "processType": "A16"},
        "zone_params": ["outBiddingZone_Domain"],
    },
    "generation": {  # Actual Generation per Production Type
        "params": {"documentType": "A75", "processType": "A16"},
        "zone_params": ["in_Domain"],
    },
    "prices": {  # Day-ahead prices
        "params": {"documentType": "A44", "contract_MarketAgreement.type": "A01"},
        "zone_params": ["in_Domain", "out_Domain"],
    },
}


class EntsoeError(Exception):
    """General ENTSO-E error. Messages never contain the security token."""


class EntsoeAuthError(EntsoeError):
    """401: the token is missing, wrong or not activated."""


class EntsoeNoDataError(EntsoeError):
    """The request was valid, but ENTSO-E has no data for it (yet)."""


def day_window(day: date) -> tuple[str, str]:
    """[day 00:00 UTC, next day 00:00 UTC) in the API's yyyyMMddHHmm format."""
    start = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.strftime("%Y%m%d%H%M"), end.strftime("%Y%m%d%H%M")


def build_params(dataset: str, zone: str, day: date) -> dict:
    """Query parameters for one dataset, zone and day (without the token)."""
    if dataset not in DATASETS:
        raise ValueError(f"Unknown dataset {dataset!r}. Known: {sorted(DATASETS)}")

    params = DATASETS[dataset]["params"].copy()
    zone_params = DATASETS[dataset]["zone_params"]
    for param in zone_params:
        params[param] = zone

    period_start, period_end = day_window(day)
    params["periodStart"] = period_start
    params["periodEnd"] = period_end
    return params


def make_session() -> requests.Session:
    """HTTP session with automatic retries for network errors, 429 and 5xx (F4)."""
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_day(session: requests.Session, token: str, dataset: str, zone: str, day: date) -> bytes:
    """Download one UTC day of `dataset` for bidding zone `zone`. Returns the raw XML."""
    params = build_params(dataset, zone, day)
    where = f"{dataset}/{zone}/{day.isoformat()}"
    log.info("ENTSO-E request %s with params %s", where, params)

    try:
        # The token is added only here, so `params` is always safe to log.
        resp = session.get(API_URL, params={**params, "securityToken": token}, timeout=60)
    except requests.RequestException as e:
        # str(e) contains the full URL, token included -> report only the error type,
        # and `from None` keeps the original exception out of the traceback.
        raise EntsoeError(f"Request failed after retries for {where}: {type(e).__name__}") from None

    # 1. Wrong or inactive token. No point retrying.
    if resp.status_code == 401:
        raise EntsoeAuthError(f"401 Unauthorized for {where}: check ENTSOE_TOKEN in .env")

    # 2. ENTSO-E answers with an Acknowledgement_MarketDocument instead of data
    #    when there is no data (HTTP 200) or when the request is invalid (HTTP 400).
    if b"Acknowledgement_MarketDocument" in resp.content:
        if resp.status_code == 200:
            raise EntsoeNoDataError(f"No data for {where}: {resp.text[:500]}")
        raise EntsoeError(f"HTTP {resp.status_code} for {where}: {resp.text[:500]}")

    # 3. Anything else that is not a success (e.g. 503 after all retries).
    if resp.status_code != 200:
        raise EntsoeError(f"HTTP {resp.status_code} for {where}: {resp.text[:300]}")

    log.info("ENTSO-E OK %s: %d bytes, %d <Point> elements",
             where, len(resp.content), resp.content.count(b"<Point>"))
    return resp.content


if __name__ == "__main__":
    # Quick manual check: python src/gridflow/ingestion/entsoe.py  (with PYTHONPATH=src)
    from gridflow.settings import get_entsoe_token

    logging.basicConfig(level=logging.INFO)
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    s = make_session()
    for ds in DATASETS:
        xml = fetch_day(s, get_entsoe_token(), ds, "10YRO-TEL------P", yesterday)
        print(f"{ds}: {xml.count(b'<Point>')} points")
