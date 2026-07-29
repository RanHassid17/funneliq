"""`POST /api/ask` — the AI analyst.

This is the only endpoint in FunnelIQ that spends money per request, so it is
also the only one with a rate limit. The budget is per authenticated user, keyed
on the subject claim of their verified session rather than on an IP, because an
IP is shared by everyone in the office and trivially changed by anyone else.

**The endpoint degrades rather than fails.** If `ANTHROPIC_API_KEY` is unset, or
CrewAI cannot load on the deployment image, this returns 503 with the reason and
every other route keeps working. FunnelIQ without the analyst is a smaller
product; FunnelIQ that will not start is not a product.

`GET /api/ask/status` exists so the dashboard can hide the ask panel instead of
offering a box that only ever returns an error.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...crew import CrewUnavailable, unavailable_reason
from ...crew.analyst import MAX_QUESTION_CHARS, QUESTIONS_PER_HOUR, RateLimited, answer
from ..auth import User, current_user

router = APIRouter(prefix="/api", tags=["analyst"])


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)


@router.get("/ask/status")
def ask_status(_: User = Depends(current_user)) -> dict[str, Any]:
    """Whether the analyst is available, and its limits."""
    reason = unavailable_reason()
    return {
        "available": reason is None,
        "reason": reason,
        "questions_per_hour": QUESTIONS_PER_HOUR,
        "max_question_chars": MAX_QUESTION_CHARS,
    }


@router.post("/ask")
def ask(request: Question, user: User = Depends(current_user)) -> dict[str, Any]:
    """Ask the campaign analyst a question.

    Answers are drafted by an analyst agent with tool access and then checked by
    a reviewer agent that has none, so the check is of the draft rather than a
    second attempt at the answer.
    """
    try:
        return answer(request.question, user.id)
    except RateLimited as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except CrewUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
