"""Data contracts shared by every stage. Changing a field here is a contract change: update
docs/architecture/data-contracts.md and bump TRIAGE_SCHEMA_VERSION."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

TRIAGE_SCHEMA_VERSION = "1.0"

Severity = Literal["S1", "S2", "S3", "S4"]
Route = Literal["auto", "review"]


class Complaint(BaseModel):
    odi_number: int
    make: str
    model: str
    model_year: int
    manufacturer: str | None = None
    date_filed: date | None = None
    date_incident: date | None = None
    crash: bool = False
    fire: bool = False
    injuries: int = 0
    deaths: int = 0
    vin_prefix: str | None = None
    components_raw: str | None = None  # NHTSA-coded label. Never shown to the LLM (label leakage).
    summary: str


class Recall(BaseModel):
    campaign_number: str
    make: str
    model: str
    model_year: int
    manufacturer: str | None = None
    report_date: date | None = None
    component_raw: str | None = None
    summary: str | None = None
    consequence: str | None = None
    remedy: str | None = None
    park_it: bool = False
    park_outside: bool = False
    ota: bool = False


class RecallDocExtraction(BaseModel):
    """Fixed schema for fields extracted from a parsed recall communication document (FR-2)."""

    campaign_number: str = Field(pattern=r"^\d{2}[VEITC]\d{6}$")
    component: str
    defect_summary: str
    remedy: str
    affected_models: list[str] = Field(default_factory=list)
    model_years: list[int] = Field(default_factory=list)
    source_url: str | None = None


class RetrievalHit(BaseModel):
    id: str
    namespace: str
    score: float
    text: str
    metadata: dict = Field(default_factory=dict)


class ExtractedFields(BaseModel):
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    symptom: str = Field(description="One-sentence plain description of the failure")
    mileage: int | None = None
    speed_context: Literal["moving", "stationary", "unknown"] = "unknown"


class RecallMatch(BaseModel):
    campaign_number: str = Field(pattern=r"^\d{2}[VEITC]\d{6}$")
    rationale: str


class TriageOutput(BaseModel):
    """What the LLM must return. Validated before anything is written."""

    extracted: ExtractedFields
    component: str
    secondary_components: list[str] = Field(default_factory=list)
    severity: Severity
    severity_reason: str
    recall_matches: list[RecallMatch] = Field(default_factory=list, max_length=3)
    model_confidence: float = Field(ge=0.0, le=1.0)
    injection_suspected: bool = False


class TriageRecord(BaseModel):
    """What is persisted: model output plus provenance, calibrated confidence and route."""

    odi_number: int
    schema_version: str = TRIAGE_SCHEMA_VERSION
    output: TriageOutput
    confidence: float
    confidence_signals: dict = Field(default_factory=dict)
    route: Route
    cited_sources: list[str] = Field(default_factory=list)
    provider: str
    model: str
    prompt_version: str
    latency_ms: int
    cost_usd: float
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LLMCall(BaseModel):
    provider: str
    model: str
    purpose: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    ok: bool = True
    error: str | None = None
    prompt_version: str | None = None
    ref_id: str | None = None


class ReviewDecision(BaseModel):
    odi_number: int
    queue_id: int | None = None  # resolves this exact queue item; else the oldest pending one for odi_number
    reviewer: str = "analyst"
    accepted: bool
    component: str | None = None
    severity: Severity | None = None
    recall_campaigns: list[str] = Field(default_factory=list)
    note: str | None = None
