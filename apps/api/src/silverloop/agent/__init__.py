"""Outreach planning agent.

The deterministic policy decides whether to act and which action class is permitted. This
package decides, within that permission, which candidate to offer and how to word it -- and
submits every proposal to a deterministic guardrail before it can become an intervention.

See `agenticlayer.md` at the repository root for the design rationale and the evidence it emits.
"""

from silverloop.agent.constants import AGENT_VERSION, DEFAULT_MAX_ITERATIONS, DEFAULT_MODEL_ID
from silverloop.agent.guardrails import (
    ActivityOrderProposal,
    validate_activity_order,
    validate_proposal,
)
from silverloop.agent.intent_planner import plan_intent
from silverloop.agent.models import (
    AgentProposal,
    AgentRun,
    AgentToolCall,
    AgentUsage,
    GuardrailVerdict,
    PlannerMode,
)
from silverloop.agent.planner import (
    ActivityPlannerMode,
    ActivityPlanRun,
    PlannerState,
    describe_tool_surface,
    log_provider_failure,
    plan_activity_ranking,
    plan_outreach,
)
from silverloop.agent.tools import (
    ActivityOption,
    ActivityRankingContext,
    CandidateOption,
    HistoryEntry,
    ProgrammeOption,
    ToolContext,
    activity_tool_definitions,
    execute_activity_read_tool,
    execute_read_tool,
    tool_definitions,
)

__all__ = [
    "AGENT_VERSION",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MODEL_ID",
    "ActivityOption",
    "ActivityOrderProposal",
    "ActivityPlanRun",
    "ActivityPlannerMode",
    "ActivityRankingContext",
    "AgentProposal",
    "AgentRun",
    "AgentToolCall",
    "AgentUsage",
    "CandidateOption",
    "GuardrailVerdict",
    "HistoryEntry",
    "PlannerMode",
    "PlannerState",
    "ProgrammeOption",
    "ToolContext",
    "activity_tool_definitions",
    "describe_tool_surface",
    "execute_activity_read_tool",
    "execute_read_tool",
    "log_provider_failure",
    "plan_activity_ranking",
    "plan_intent",
    "plan_outreach",
    "tool_definitions",
    "validate_activity_order",
    "validate_proposal",
]
