"""Model routing: pick the cheapest Claude tier that will do the task well.

Tiers (Claude Code aliases, so they follow the latest model in each line):
  haiku  - fast and cheap: lookups, summaries, explanations of small code,
           mechanical edits (typos, renames, formatting), commit messages.
  sonnet - the default workhorse: features, bug fixes, tests, refactors,
           ordinary reviews and research.
  opus   - reserved for hard work: architecture/design, concurrency and
           security problems, ambiguous root-cause hunts, large multi-module
           changes, and anything that already failed on a lower tier.
Fable is never selected automatically; pass --model fable explicitly.

The router is deterministic and explainable. The orchestrator can always
override it with --model / --tier / --effort.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

LADDER = ["haiku", "sonnet", "opus"]
TIER_ALIASES = {"fast": "haiku", "balanced": "sonnet", "deep": "opus", "cheap": "haiku", "default": "sonnet"}
KINDS = ("ask", "explain", "chore", "docs", "test", "implement", "fix", "refactor", "review", "research", "debug", "plan")
WRITE_KINDS = {"chore", "docs", "test", "implement", "fix", "refactor", "debug"}
ACCESS_LEVELS = ("read", "edit", "auto", "full")

# Order matters for ties: earlier kinds win.
_KIND_RULES: list[tuple[str, list[str]]] = [
    ("review", [r"\breview\b", r"\baudit\b", r"\bcritique\b", r"\blook over\b", r"\bsecond opinion\b"]),
    ("debug", [r"\bdebug", r"\broot[- ]cause\b", r"\bflaky\b", r"\bintermittent", r"\bstack ?trace\b",
               r"\btraceback\b", r"\bsegfault\b", r"\bcrash(es|ing)?\b", r"\bhangs?\b", r"\bdeadlocks?\b",
               r"\bwhy (does|do|is|are|did)\b[^?]*\b(fail|break|crash|hang|slow|error|wrong)"]),
    ("fix", [r"\bfix(es|ed|ing)?\b", r"\bbugs?\b", r"\bbroken\b", r"\bregression\b", r"\bfailing\b", r"\bpatch\b",
             r"\bdoesn'?t work\b", r"\bnot working\b"]),
    ("test", [r"\b(unit|integration|e2e|end-to-end|regression|snapshot|property) tests?\b", r"\b(write|add) (some |more )?tests?\b",
              r"\btest coverage\b", r"\bcoverage\b", r"\btests? for\b"]),
    ("refactor", [r"\brefactor", r"\brestructur", r"\bclean ?up\b", r"\bextract\b", r"\bdeduplicat", r"\bsimplify\b",
                  r"\bmigrat(e|ion)\b", r"\bmoderni[sz]e\b", r"\bdecouple\b"]),
    ("plan", [r"\bplan\b", r"\bdesign\b", r"\barchitect", r"\bapproach\b", r"\bstrategy\b", r"\bpropos(e|al)\b",
              r"\brfc\b", r"\btrade-?offs?\b", r"\broadmap\b"]),
    ("research", [r"\bresearch\b", r"\bcompare\b", r"\bcomparison\b", r"\bevaluate\b", r"\bbest practices?\b",
                  r"\balternatives?\b", r"\bpros and cons\b", r"\bwhich (library|framework|tool|package|approach)\b"]),
    ("docs", [r"\b(write|update|add|improve|generate|fix)\b[^.]*\b(docs?|documentation|readme|docstrings?|changelog)\b",
              r"\bdocument (the|this|our|how|all)\b"]),
    ("chore", [r"\btypos?\b", r"\brename\b", r"\breformat\b", r"\bformatting\b", r"\blint(ing)? (errors|warnings|fix)",
               r"\bbump\b", r"\bcommit message\b", r"\bsort imports\b", r"\bupdate (the )?(dependency|dependencies|deps|pins?)\b"]),
    ("explain", [r"\bexplain\b", r"\bwhat (does|is|are)\b", r"\bhow (does|do|is|are)\b", r"\bwhere (is|are|does)\b",
                 r"\bsummari[sz]e\b", r"\bwalk me through\b", r"\boverview\b", r"\bdescribe\b"]),
    ("implement", [r"\bimplement", r"\badd\b", r"\bbuild\b", r"\bcreate\b", r"\bsupport\b", r"\bintegrate\b",
                   r"\bfeature\b", r"\bendpoint\b", r"\bwrite (a|an|the)\b", r"\bgenerate\b", r"\bscaffold"]),
]

# "build" and "make" are left out on purpose: in questions they are usually nouns
# ("why does the build fail?") rather than requests to change code.
_WRITE_VERBS = re.compile(
    r"\b(fix|add|implement|create|update|change|modify|refactor|write|remove|delete|rename|migrate|"
    r"replace|introduce|convert|upgrade|bump|patch|edit|generate)\b",
    re.I,
)
_QUESTION_START = re.compile(r"^\s*(what|how|where|why|which|who|when|is|are|does|do|can|could|should|explain|summari[sz]e|describe|list|show)\b", re.I)

# (pattern, weight) - signals that the task needs deeper reasoning.
_HARD: list[tuple[str, float]] = [
    (r"\barchitect", 2), (r"\bdesign\b", 1), (r"\bconcurren", 2), (r"\brace conditions?\b", 3),
    (r"\bdeadlocks?\b", 3), (r"\bthread[- ]?safe", 2), (r"\bdistributed\b", 2),
    (r"\bsecurity\b|\bvulnerab|\bcve\b|\bexploit|\binjection\b", 3),
    (r"\bauth(entication|orization)?\b|\boauth\b|\bcrypto", 1.5),
    (r"\bperformance\b|\boptimi[sz]|\blatency\b|\bthroughput\b", 1.5), (r"\bmemory leaks?\b|\bleaks?\b", 2),
    (r"\bmigrat", 1.5), (r"\bschema\b", 1), (r"\blegacy\b", 1),
    (r"\b(across|throughout) (the )?(code ?base|repo|project|app)\b|\bentire (code ?base|repo|project|app)\b|\bevery (module|file|service)\b", 2.5),
    (r"\bmulti[- ]?(file|module|service|step)\b|\bmonorepo\b", 1.5),
    (r"\bcomplex\b|\btricky\b|\bsubtle\b|\bhard\b|\bdifficult\b", 1.5),
    (r"\bintermittent|\bflaky\b|\bnon-?determinis", 2), (r"\broot[- ]cause\b", 1.5),
    (r"\bproduction\b|\boutage\b|\bincident\b|\bdata loss\b|\bcorrupt", 2),
    (r"\balgorithm|\bcompiler\b|\bparser\b|\bprotocol\b|\bstate machine\b", 1.5),
    (r"\btrade-?offs?\b", 1),
]
# (pattern, weight) - signals that a small/fast model is enough.
_EASY: list[tuple[str, float]] = [
    (r"\btypos?\b", 2.5), (r"\brename\b", 1.5), (r"\breformat\b|\bformatting\b", 1.5),
    (r"\bsmall\b|\bsimple\b|\bquick(ly)?\b|\btrivial\b|\bminor\b|\btiny\b", 1.5),
    (r"\bone[- ]liner?\b|\bsingle (line|file|function)\b", 1.5),
    (r"\blist\b|\bfind\b|\bwhere (is|are)\b|\blocate\b", 1),
    (r"\bsummari[sz]e\b|\bbrief(ly)?\b|\btl;?dr\b", 1.5), (r"\bdocstrings?\b|\bcomments?\b", 1),
    (r"\bcommit message\b|\bchangelog\b", 2), (r"\bboilerplate\b", 1),
    (r"\bconvert\b.*\b(json|yaml|csv|toml)\b|\btranslate\b", 1),
]

_BASE = {
    "ask": 0.5, "explain": 1.0, "chore": 0.5, "docs": 1.5, "test": 3.0, "implement": 3.0,
    "fix": 3.0, "refactor": 3.5, "review": 3.0, "research": 3.0, "debug": 4.0, "plan": 4.5,
}
# Effort per kind when the task lands on Sonnet. Mirrors Claude Code's guidance:
# medium for clear-scope work, high where edge cases and verification matter.
_SONNET_EFFORT = {
    "ask": "medium", "explain": "medium", "chore": "low", "docs": "medium", "test": "medium",
    "implement": "medium", "research": "medium", "review": "high", "fix": "high",
    "refactor": "high", "debug": "high", "plan": "high",
}
_FALLBACK = {"haiku": ["sonnet"], "sonnet": ["opus"], "opus": ["sonnet"]}
_FILE_HINT = re.compile(r"[\w./-]+\.(py|ts|tsx|js|jsx|go|rs|java|kt|swift|rb|php|c|cc|cpp|h|hpp|cs|m|mm|scala|sql|md|json|ya?ml|toml)\b")


@dataclass
class Route:
    kind: str
    tier: str
    model: str
    effort: str | None
    fallback: list[str]
    access: str
    score: float
    explicit_model: bool = False
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def label(self) -> str:
        effort = f"/{self.effort}" if self.effort else ""
        return f"{self.model}{effort}"


def _hits(patterns: list[tuple[str, float]], text: str) -> list[tuple[str, float]]:
    found = []
    for pattern, weight in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            found.append((match.group(0).lower(), weight))
    return found


def infer_kind(task: str) -> tuple[str, list[str]]:
    text = task.lower()
    scores: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    for kind, patterns in _KIND_RULES:
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                scores[kind] = scores.get(kind, 0) + 1
                matched.setdefault(kind, []).append(match.group(0))
    question = bool(_QUESTION_START.search(task)) or task.rstrip().endswith("?")
    writes = bool(_WRITE_VERBS.search(task))
    if not scores:
        if question and not writes:
            return "ask", ["question with no write verbs"]
        return ("implement" if writes else "ask"), ["no kind keywords; defaulted"]
    order = [kind for kind, _ in _KIND_RULES]
    best = max(scores, key=lambda k: (scores[k], -order.index(k)))
    # A pure question ("what does X do?", "why does Y fail?") stays read-only.
    if question and not writes and best in ("implement", "fix", "chore", "docs", "refactor", "test"):
        return "explain", [f"question form ({', '.join(matched.get(best, []))} read as a question)"]
    return best, [f"{best}: {', '.join(dict.fromkeys(matched[best]))}"]


def normalize_model(model: str | None) -> str | None:
    if not model:
        return None
    value = model.strip()
    lowered = value.lower()
    if lowered in ("auto", ""):
        return None
    return TIER_ALIASES.get(lowered, value)


def tier_of(model: str) -> str | None:
    lowered = model.lower()
    for tier in ("haiku", "sonnet", "opus", "fable"):
        if tier in lowered:
            return tier
    return None


def default_access(kind: str, task: str) -> str:
    if kind not in WRITE_KINDS:
        return "read"
    question = bool(_QUESTION_START.search(task)) or task.rstrip().endswith("?")
    if question and not _WRITE_VERBS.search(task):
        return "read"
    return "auto"


def route(
    task: str,
    *,
    kind: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    access: str | None = None,
    files: int = 0,
    default_model: str | None = None,
) -> Route:
    """Choose kind, tier, effort, fallback, and permission profile for a task."""
    reasons: list[str] = []
    warnings: list[str] = []

    if kind:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; choose from {', '.join(KINDS)}")
        reasons.append(f"kind {kind} (given)")
    else:
        kind, why = infer_kind(task)
        reasons.extend(why)

    score = _BASE[kind]
    hard = _hits(_HARD, task)
    easy = _hits(_EASY, task)
    if hard:
        score += min(sum(w for _, w in hard), 8)
        reasons.append("harder: " + ", ".join(sorted({h for h, _ in hard})))
    if easy:
        score -= min(sum(w for _, w in easy), 4)
        reasons.append("easier: " + ", ".join(sorted({e for e, _ in easy})))
    files = max(files, len(set(_FILE_HINT.findall(task))))
    if len(task) > 3000:
        score += 2
        reasons.append("long brief")
    elif len(task) > 1200:
        score += 1
        reasons.append("detailed brief")
    if files >= 15:
        score += 2
        reasons.append(f"{files} files in scope")
    elif files >= 5:
        score += 1
        reasons.append(f"{files} files in scope")

    explicit = normalize_model(model) or normalize_model(default_model)
    if explicit:
        chosen = explicit
        tier = tier_of(chosen) or "sonnet"
        reasons.insert(0, f"model {chosen} (explicit)")
    else:
        if score < 2:
            tier = "haiku"
        elif score < 6:
            tier = "sonnet"
        else:
            tier = "opus"
        chosen = tier
        reasons.insert(0, f"score {score:.1f} -> {tier}")

    if effort:
        chosen_effort: str | None = effort
    elif tier == "haiku":
        chosen_effort = None  # Haiku has no effort control
    elif tier == "sonnet":
        chosen_effort = _SONNET_EFFORT[kind]
    elif tier in ("opus", "fable"):
        # xhigh only where deep reasoning changes the outcome of hands-on work;
        # reviews and research stay at high even when the topic is hard.
        severe = sum(w for _, w in hard) >= 5 or any(
            re.search(r"security|vulnerab|race|deadlock|concurren|exploit|injection", h) for h, _ in hard
        )
        chosen_effort = "xhigh" if severe and kind in ("debug", "fix", "plan", "refactor", "implement") else "high"
    else:
        chosen_effort = None

    resolved_access = access or default_access(kind, task)
    if resolved_access not in ACCESS_LEVELS:
        raise ValueError(f"unknown access {resolved_access!r}; choose from {', '.join(ACCESS_LEVELS)}")
    if resolved_access == "auto" and tier == "haiku":
        # Claude Code silently drops auto mode to manual on Haiku, which would deny every
        # unlisted command in a headless run. Use the allowlist profile instead.
        resolved_access = "edit"
        warnings.append("auto permission mode is unavailable on Haiku; using the edit allowlist profile")

    return Route(
        kind=kind,
        tier=tier,
        model=chosen,
        effort=chosen_effort,
        fallback=list(_FALLBACK.get(tier, [])),
        access=resolved_access,
        score=round(score, 2),
        explicit_model=bool(explicit),
        reasons=reasons,
        warnings=warnings,
    )


def next_tier(current: str, allow_fable: bool = False) -> str | None:
    tier = tier_of(current) or current
    ladder = LADDER + (["fable"] if allow_fable else [])
    if tier not in ladder:
        return None
    index = ladder.index(tier)
    return ladder[index + 1] if index + 1 < len(ladder) else None
