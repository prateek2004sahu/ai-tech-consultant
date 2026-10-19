from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Feasibility = Literal["not_checked", "existing_configuration", "existing_with_limitation",
                      "custom_development", "needs_clarification"]


class Requirement(BaseModel):
    id: str = ""
    description: str
    quote: str = ""
    line: int | None = None
    meeting_id: str = ""
    status: Literal["confirmed", "unclear", "disputed"] = "confirmed"
    priority: Literal["must", "should", "optional"] = "should"
    origin: Literal["explicit", "inferred"] = "explicit"
    quote_verified: bool = False
    feasibility: Feasibility = "not_checked"
    feasibility_evidence: str = ""
    kb_sources: list[str] = []
    acceptance_criteria: list[str] = []
    removed: bool = False


class ExtractedReq(BaseModel):
    description: str = Field(min_length=3)
    quote: str = ""
    line: int | None = None
    status: Literal["confirmed", "unclear", "disputed"] = "confirmed"
    priority: Literal["must", "should", "optional"] = "should"
    origin: Literal["explicit", "inferred"] = "explicit"
    matches_id: str | None = None
    change: Literal["new", "modified", "unchanged"] = "new"


class Removal(BaseModel):
    matches_id: str
    quote: str = ""
    line: int | None = None


class Constraint(BaseModel):
    kind: Literal["deadline", "budget", "other"]
    text: str
    quote: str = ""


class Extract(BaseModel):
    requirements: list[ExtractedReq] = []
    removals: list[Removal] = []
    constraints: list[Constraint] = []
    open_questions: list[str] = []


class ScopeText(BaseModel):
    objective: str
    current_problem: str
    proposed_solution: str
    acceptance_criteria: dict[str, list[str]] = {}
    exclusions: list[str] = []
    assumptions: list[str] = []
    client_responsibilities: list[str] = []
    risks: list[str] = []


class EstTask(BaseModel):
    requirement_id: str
    name: str
    low: float = Field(ge=0)
    likely: float = Field(ge=0)
    high: float = Field(ge=0)
    assumptions: str = ""


class EstimateOut(BaseModel):
    tasks: list[EstTask]


class ProposalText(BaseModel):
    executive_summary: str
    next_steps: list[str] = []


class FeasOut(BaseModel):
    feasibility: Literal["existing_configuration", "existing_with_limitation", "custom_development", "needs_clarification"]
    reason: str = ""


class MeetingIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    meeting_date: str = Field(min_length=8, max_length=30, description="ISO date, e.g. 2026-10-16")
    transcript: str = Field(min_length=20, max_length=400_000)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    client: str = Field(min_length=1, max_length=200)


class ApproveIn(BaseModel):
    reviewer: str = Field(min_length=2, max_length=100)
