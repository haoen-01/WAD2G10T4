"""Typed records the planner produces.

Every field here ends up in append-only intervention evidence, so the shapes are chosen to be
auditable after the fact: what the agent saw, what it called, what the guardrail said, and what
it cost. Nothing in this module talks to a model or a database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from silverloop.models import Decision

# How the selected candidate was ultimately chosen. Every value except `agent` means the
# deterministic ranker supplied the answer, and the reason is preserved for the audit trail.
PlannerMode = Literal[
    "agent",  # the model proposed and the guardrail approved
    "fallback_disabled",  # LLM_ENABLED=false, or the SDK/API key is absent
    "fallback_error",  # the provider call failed or was refused
    "fallback_exhausted",  # the iteration cap was reached with no approved proposal
    "fallback_no_proposal",  # the model ended its turn without calling propose_outreach
]


class AgentToolCall(BaseModel):
    """One tool invocation, recorded whether it succeeded or failed.

    `summary` is a short human-readable line rather than the raw payload: tool results are kept
    small on purpose, and the audit record should stay readable in the operations view.
    """

    iteration: int = Field(ge=1)
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    summary: str
    error: str | None = None


class GuardrailVerdict(BaseModel):
    """Result of the deterministic check applied to a proposed outreach message."""

    approved: bool
    violations: list[str] = Field(default_factory=list)

    def as_feedback(self) -> str:
        """Render violations as instruction text the planner can act on next iteration."""
        if self.approved:
            return "Approved."
        numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(self.violations, 1))
        return (
            "REJECTED by the deterministic safety gate. Fix every point and call "
            f"propose_outreach again:\n{numbered}"
        )


class AgentProposal(BaseModel):
    """What the planner wants to send, before the guardrail has ruled on it."""

    candidate_key: str
    message: str
    reasoning: str = ""


class AgentUsage(BaseModel):
    """Token accounting summed across every iteration of one planner run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


class AgentRun(BaseModel):
    """The complete, auditable record of one planning run.

    This is what gets written into intervention evidence. `selected_candidate_key` is always
    populated -- when `mode` is any of the fallback values it holds the deterministic ranker's
    choice, so a reader never has to guess whether the agent was involved.
    """

    evidence_id: str
    agent_version: str
    mode: PlannerMode
    decision: Decision
    model: str | None = None
    started_at: datetime
    latency_ms: int = 0
    iterations: int = 0
    max_iterations: int
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    guardrail_rejections: list[str] = Field(default_factory=list)
    proposal: AgentProposal | None = None
    selected_candidate_key: str
    selected_message: str
    fallback_reason: str | None = None
    usage: AgentUsage = Field(default_factory=AgentUsage)

    @property
    def used_agent(self) -> bool:
        return self.mode == "agent"

    @property
    def rejected_proposal_count(self) -> int:
        """How many proposals the gate turned down.

        Distinct from `len(guardrail_rejections)`, which counts individual violations -- one
        rejected proposal routinely breaks several rules at once.
        """
        return sum(
            1 for call in self.tool_calls if call.tool_name == "propose_outreach" and not call.ok
        )

    @property
    def tool_call_success_rate(self) -> float | None:
        """Share of tool calls that returned a usable result. `None` when none were made."""
        if not self.tool_calls:
            return None
        successes = sum(1 for call in self.tool_calls if call.ok)
        return round(successes / len(self.tool_calls), 3)

    def trace_detail(self) -> str:
        """One line for the nine-stage decision trace shown in the simulator."""
        if not self.used_agent:
            return (
                f"Deterministic ranker selected the candidate ({self.mode}); "
                f"{self.fallback_reason or 'planner not consulted'}."
            )
        rejected = self.rejected_proposal_count
        revision = (
            f" after {rejected} guardrail revision(s) covering "
            f"{len(self.guardrail_rejections)} violation(s)"
            if rejected
            else " on first proposal"
        )
        return (
            f"Planner ({self.model}) proposed the candidate in {self.iterations} iteration(s) "
            f"using {len(self.tool_calls)} tool call(s), approved by the safety gate{revision}."
        )

    def as_evidence(self) -> dict[str, Any]:
        """Compact dictionary embedded in append-only intervention evidence."""
        return {
            "agent_evidence_id": self.evidence_id,
            "agent_version": self.agent_version,
            "mode": self.mode,
            # Precomputed so the decision trace can render the planner's contribution without
            # rehydrating this record.
            "trace_detail": self.trace_detail(),
            "model": self.model,
            "started_at": self.started_at.isoformat(),
            "latency_ms": self.latency_ms,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "tool_calls": [call.model_dump() for call in self.tool_calls],
            "tool_call_success_rate": self.tool_call_success_rate,
            "guardrail_rejections": self.guardrail_rejections,
            # Violations counts individual broken rules; rejected_proposals counts how many
            # times the planner had to go back and revise.
            "guardrail_violation_count": len(self.guardrail_rejections),
            "rejected_proposal_count": self.rejected_proposal_count,
            "fallback_reason": self.fallback_reason,
            "usage": self.usage.model_dump(),
            "total_tokens": self.usage.total_tokens,
            "agent_reasoning": self.proposal.reasoning if self.proposal else None,
            "boundary": (
                "The planner chose only the wording and candidate within an action class the "
                "deterministic policy had already permitted. It cannot change consent, "
                "data-quality, confidence, contact-cap or human-review gates."
            ),
        }
