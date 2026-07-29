"""Offline crew: draft a findings section from the committed evidence.

    python -m funneliq.crew.run --stage analysis
    python -m funneliq.crew.run --stage analysis --dry-run   # no API calls

Planner scopes, the ML Engineer reads the evidence, QA checks every figure
against it, and the Documentation Agent writes the prose. It reads only
`reports/*.json` -- the same files `REPORT.md` cites -- so the crew and the
report cannot disagree about a number.

Output goes to `reports/crew_analysis.md`, never to `REPORT.md` directly. A
generated draft is a draft: a human decides what enters the report. That is also
why this runs on demand rather than in CI, where it would spend money on every
push and tempt someone to trust an unread file.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import REPORTS_DIR
from . import CrewUnavailable, build_llm, unavailable_reason
from .agents import build_agent
from .guardrails import customer_level_drift
from .tools import build_tools, funnel_stats, model_scoreboard

OUTPUT_PATH = REPORTS_DIR / "crew_analysis.md"

STAGES = ("analysis",)

#: The roles this stage runs, in order. Backend, Frontend, DevOps and Security
#: are build-time roles with nothing to contribute to a findings write-up.
ANALYSIS_ROLES = (
    "Project Planner",
    "Data & ML Engineer",
    "QA & Reviewer",
    "Documentation Agent",
)

_TASKS: dict[str, tuple[str, str]] = {
    "Project Planner": (
        "State, in at most five bullets, what a findings section about Northbound "
        "Media's campaign data must cover to be useful to a founder deciding how "
        "to spend a 50,000 shekel monthly budget. Do not answer the questions.",
        "Five bullets naming the questions the section must answer.",
    ),
    "Data & ML Engineer": (
        "Using funnel_stats and model_scoreboard, report the figures that answer "
        "the planner's bullets. Quote exact numbers from the tool results. Include "
        "the results that are unflattering -- specifically which models did not "
        "beat their naive baseline.",
        "A list of findings, each with its figure and the tool it came from.",
    ),
    "QA & Reviewer": (
        "Check every figure in the engineer's findings against the tool results in "
        "this conversation. Flag any number that does not appear in a tool result, "
        "and any sentence that describes a campaign outcome as an individual "
        "customer's outcome.",
        "The verified findings, with any unsupported figure removed and noted.",
    ),
    "Documentation Agent": (
        "Write the verified findings as a Markdown section titled '## Campaign "
        "findings'. Plain prose, campaign language throughout, each figure followed "
        "by its source, and limitations stated alongside results rather than in a "
        "footnote. At most 400 words.",
        "A Markdown section ready for a human to review before it enters REPORT.md.",
    ),
}


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        return "unknown"


def evidence_summary() -> dict[str, Any]:
    """What the crew will read, resolved before spending anything on it.

    A dry run prints this. If a report file is missing, that is worth finding out
    for free rather than three agent turns in.
    """
    stats = json.loads(funnel_stats())
    scoreboard = json.loads(model_scoreboard())
    return {
        "reports_dir": str(REPORTS_DIR),
        "rows": stats.get("rows"),
        "funnel_stages": len(stats.get("followup_dropout", [])),
        "models": [m.get("target") for m in scoreboard.get("models", [])],
        "errors": [d["error"] for d in (stats, scoreboard) if "error" in d],
    }


def run_analysis(output_path: Path = OUTPUT_PATH) -> Path:
    """Run the analysis crew and write its draft. Costs money."""
    reason = unavailable_reason()
    if reason:
        raise CrewUnavailable(reason)

    from crewai import Crew, Process, Task

    llm = build_llm()
    tools = build_tools()

    agents: list[Any] = []
    tasks: list[Any] = []
    for role in ANALYSIS_ROLES:
        description, expected = _TASKS[role]
        # Only the engineer needs tools; the others reason over what it produced,
        # which is what makes QA a review rather than a second lookup.
        agent = build_agent(role, tools if role == "Data & ML Engineer" else [], llm)
        agents.append(agent)
        tasks.append(
            Task(
                description=description,
                expected_output=expected,
                agent=agent,
                context=list(tasks),
            )
        )

    crew = Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=True)
    draft = str(crew.kickoff()).strip()

    drift = customer_level_drift(draft)
    header = "\n".join(
        [
            "<!-- Generated by `python -m funneliq.crew.run --stage analysis`.",
            "     A DRAFT. Review before any of it enters REPORT.md.",
            f"     Generated: {datetime.now(UTC).isoformat(timespec='seconds')}",
            f"     Commit: {_git_sha()}",
            "     Source: reports/profile.json, reports/models.json",
            f"     Campaign-language warnings: {drift or 'none'} -->",
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(header + draft + "\n")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, default="analysis")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the evidence and roles that would run, without calling the model.",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        print(json.dumps(evidence_summary(), indent=2))
        print(f"\nRoles for stage {args.stage!r}: {', '.join(ANALYSIS_ROLES)}")
        blocked = unavailable_reason()
        print(f"Analyst status: {blocked or 'ready'}")
        return 0

    try:
        path = run_analysis()
    except CrewUnavailable as exc:
        print(f"Cannot run: {exc}")
        return 1
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
