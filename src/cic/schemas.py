"""JSON Schemas for structured results.

Every object lists all of its properties as required and forbids extra keys,
so the same schema works with Claude Code's --json-schema and with Codex's
strict --output-schema. Optional values are nullable instead of omitted.
"""

from __future__ import annotations

_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": {"type": "string"}}


def _obj(properties: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


TASK_REPORT = _obj({
    "status": {
        "type": "string",
        "enum": ["done", "partial", "needs_input", "blocked", "failed"],
        "description": "done = all acceptance criteria met; partial = some remain; needs_input = a decision only the orchestrator can make; blocked = external obstacle; failed = no meaningful progress",
    },
    "summary": {"type": "string", "description": "2-5 sentences: what changed and the outcome"},
    "changes": {
        "type": "array",
        "items": _obj({"path": _STR, "change": {"type": "string", "description": "one line"}}),
    },
    "verification": {
        "type": "array",
        "items": _obj({
            "command": _STR,
            "outcome": {"type": "string", "enum": ["pass", "fail", "not_run"]},
            "details": {"type": "string", "description": "short evidence, e.g. '42 passed'"},
        }),
    },
    "assumptions": _STR_LIST,
    "risks": _STR_LIST,
    "open_questions": _STR_LIST,
    "next_steps": _STR_LIST,
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
})

REVIEW_REPORT = _obj({
    "verdict": {"type": "string", "enum": ["approve", "needs-attention"]},
    "summary": {"type": "string", "description": "terse ship/no-ship assessment"},
    "findings": {
        "type": "array",
        "items": _obj({
            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
            "title": _STR,
            "file": _STR,
            "line_start": {"type": ["integer", "null"]},
            "line_end": {"type": ["integer", "null"]},
            "body": {"type": "string", "description": "what fails, why this path is vulnerable, impact"},
            "recommendation": _STR,
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }),
    },
    "next_steps": _STR_LIST,
})

PLAN_REPORT = _obj({
    "summary": _STR,
    "approach": {"type": "string", "description": "chosen approach and why it beats the alternatives"},
    "alternatives": {"type": "array", "items": _obj({"option": _STR, "why_not": _STR})},
    "steps": {
        "type": "array",
        "items": _obj({"title": _STR, "details": _STR, "files": _STR_LIST, "verify": _STR}),
    },
    "risks": _STR_LIST,
    "verification": _STR_LIST,
    "open_questions": _STR_LIST,
})

BY_NAME = {"task": TASK_REPORT, "review": REVIEW_REPORT, "plan": PLAN_REPORT}
