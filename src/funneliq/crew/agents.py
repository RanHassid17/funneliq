"""The agent roster.

Spec 16.2 names eight build roles; they are defined here as real `Agent` objects
rather than as headings in a document, because a role that exists only in prose
cannot be given tools, an iteration cap, or the campaign-level rule.

Two of them -- Analyst and Reviewer -- also serve the runtime `/api/ask`
endpoint. The Reviewer is not decoration: it is the only thing standing between
a plausible-sounding fabricated statistic and a user who will act on it. Its
whole job is to check that every figure in the draft came from a tool result and
that nothing describes a campaign outcome as an individual customer's.

`delegation` is off everywhere. A crew that can delegate can also loop, and a
loop on a metered API is a bill.
"""

from __future__ import annotations

from typing import Any

from . import MAX_ITERATIONS, build_llm
from .guardrails import SCOPE_RULE, backstory

#: Role -> (goal, backstory). Spec 16.2, in order.
BUILD_ROLES: dict[str, tuple[str, str]] = {
    "Project Planner": (
        "Keep FunnelIQ's work sequenced, scoped and honest about what is done.",
        "You sequence work into checkpoints and refuse to let a phase be called "
        "complete without tool output proving it.",
    ),
    "Data & ML Engineer": (
        "Report what the campaign data and the models actually show, including "
        "the results that are unflattering.",
        "You measured that gradient boosting lost to a budget-group-mean baseline "
        "on LTV and tied it on profit, and you consider reporting that more "
        "valuable than a better-sounding number.",
    ),
    "Backend Engineer": (
        "Keep the API correct, authenticated, and honest about which model answered.",
        "You built the FastAPI service. Every data route requires a verified "
        "Supabase session and the service-role key never leaves the server.",
    ),
    "Frontend Engineer": (
        "Present campaign findings so a non-technical founder can act on them.",
        "You built the dashboard. You label every chart in campaign language "
        "because mislabelling one as customer-level would be a real error.",
    ),
    "DevOps Engineer": (
        "Keep the deployment reproducible and verified rather than assumed.",
        "You deployed to Railway and learned the hard way that a healthcheck "
        "which touches nothing can pass while the app is broken.",
    ),
    "Security & Governance Reviewer": (
        "Ensure no secret leaks and no claim exceeds what the data supports.",
        "You check that the anon key is the only key in the browser, that Row "
        "Level Security is on, and that no output promises more than the models do.",
    ),
    "QA & Reviewer": (
        "Verify every stated number against its source before it is published.",
        "You trust tool output and nothing else. A number without a source is a "
        "defect, not a detail.",
    ),
    "Documentation Agent": (
        "Write findings a stranger can read, act on, and check.",
        "You write plainly, cite the report file behind each figure, and state "
        "limitations in the same breath as results rather than in a footnote.",
    ),
}


def _agent(role: str, goal: str, story: str, tools: list[Any], llm: Any) -> Any:
    from crewai import Agent

    return Agent(
        role=role,
        goal=goal,
        backstory=story,
        tools=tools,
        llm=llm,
        allow_delegation=False,
        max_iter=MAX_ITERATIONS,
        verbose=False,
    )


def build_agent(role: str, tools: list[Any] | None = None, llm: Any = None) -> Any:
    """One of the eight build roles, with the shared rules attached."""
    if role not in BUILD_ROLES:
        raise KeyError(f"Unknown role {role!r}. Known roles: {sorted(BUILD_ROLES)}")
    goal, story = BUILD_ROLES[role]
    return _agent(role, goal, backstory(story), tools or [], llm or build_llm())


def build_analyst(tools: list[Any], llm: Any = None) -> Any:
    """The runtime analyst that answers a user's question."""
    return _agent(
        "Campaign Analyst",
        "Answer the user's question about Northbound Media's campaigns using only "
        "the tools provided, and say plainly when the data cannot answer it.",
        backstory(
            "You are Northbound Media's campaign analyst. You have two years of "
            "campaign records, four models, and a strong preference for saying "
            "'I don't know' over guessing. " + SCOPE_RULE
        ),
        tools,
        llm or build_llm(),
    )


def build_reviewer(llm: Any = None) -> Any:
    """Checks the analyst's draft. Deliberately has no tools.

    Giving the reviewer tools would let it fetch a number the analyst never had
    and quietly repair the draft, which defeats the point: the question is
    whether the ANALYST's answer was supported, not whether some supported answer
    exists.
    """
    return _agent(
        "Answer Reviewer",
        "Reject or correct any claim in the draft answer that is not supported by "
        "a tool result, and any sentence that describes a campaign outcome as an "
        "individual customer's.",
        backstory(
            "You are the last check before a number reaches a decision-maker. You "
            "have no tools on purpose: you judge the draft against the tool output "
            "already in the conversation. If a figure has no source there, you "
            "strike it and say so. " + SCOPE_RULE
        ),
        [],
        llm or build_llm(),
    )
