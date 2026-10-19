"""Thin client for the public NHTSA APIs (no key required). Also used as the agent's
recall-lookup tool."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

BASE = "https://api.nhtsa.gov"
_client = httpx.Client(base_url=BASE, timeout=60.0, headers={"User-Agent": "vsia/0.1 (research project)"})


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=20), reraise=True,
       retry=retry_if_exception(_retryable))
def _get(path: str, params: dict[str, Any]) -> dict:
    r = _client.get(path, params=params)
    # NHTSA answers "no match" (unknown model string, or a model with no recalls) with HTTP 400 and an
    # empty result set. That is an empty answer, not an error, and must not be retried.
    if r.status_code == 400:
        return {"results": []}
    r.raise_for_status()
    return r.json()


def models_for(make: str, year: int, issue_type: str = "c") -> list[str]:
    data = _get("/products/vehicle/models", {"modelYear": year, "make": make, "issueType": issue_type})
    return sorted({r["model"] for r in data.get("results", [])})


def complaints_by_vehicle(make: str, model: str, year: int) -> list[dict]:
    return _get("/complaints/complaintsByVehicle", {"make": make, "model": model, "modelYear": year}).get(
        "results", []
    )


def recalls_by_vehicle(make: str, model: str, year: int) -> list[dict]:
    return _get("/recalls/recallsByVehicle", {"make": make, "model": model, "modelYear": year}).get(
        "results", []
    )


def recall_by_campaign(campaign_number: str) -> list[dict]:
    return _get("/recalls/campaignNumber", {"campaignNumber": campaign_number}).get("results", [])


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def normalize_complaint(raw: dict, make: str, model: str, year: int) -> dict:
    # The query string varies ('F-150 LIGHTNING' vs 'F-150 (SUPER CREW) LIGHTNING BEV'); the product
    # record attached to the complaint carries NHTSA's canonical model name, so prefer it.
    for p in raw.get("products") or []:
        if p.get("type") == "Vehicle" and (p.get("productMake") or "").upper() == make.upper():
            model = p.get("productModel") or model
            break
    return {
        "odi_number": int(raw["odiNumber"]),
        "make": make.upper(),
        "model": model.upper(),
        "model_year": int(year),
        "manufacturer": raw.get("manufacturer"),
        "date_filed": _parse_date(raw.get("dateComplaintFiled")),
        "date_incident": _parse_date(raw.get("dateOfIncident")),
        "crash": bool(raw.get("crash")),
        "fire": bool(raw.get("fire")),
        "injuries": int(raw.get("numberOfInjuries") or 0),
        "deaths": int(raw.get("numberOfDeaths") or 0),
        "vin_prefix": ((raw.get("vin") or "")[:11] or None),  # never store the serial part (ADR-0022)
        "components_raw": raw.get("components"),
        "summary": (raw.get("summary") or "").strip(),
    }


def normalize_recall(raw: dict) -> dict:
    # Recall API dates are DD/MM/YYYY.
    rd = raw.get("ReportReceivedDate")
    report_date = None
    if rd:
        try:
            report_date = datetime.strptime(rd, "%d/%m/%Y").date()
        except ValueError:
            report_date = _parse_date(rd)
    return {
        "campaign_number": raw["NHTSACampaignNumber"],
        "make": (raw.get("Make") or "").upper(),
        "model": (raw.get("Model") or "").upper(),
        "model_year": int(raw.get("ModelYear") or 0),
        "manufacturer": raw.get("Manufacturer"),
        "report_date": report_date,
        "component_raw": raw.get("Component"),
        "summary": raw.get("Summary"),
        "consequence": raw.get("Consequence"),
        "remedy": raw.get("Remedy"),
        "park_it": bool(raw.get("parkIt")),
        "park_outside": bool(raw.get("parkOutSide")),
        "ota": bool(raw.get("overTheAirUpdate")),
    }


CAMPAIGN_RE = re.compile(r"\b\d{2}[VEITC]\d{6}\b")
