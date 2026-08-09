"""Claim extraction — the teacher pass.

Precision over recall (DESIGN §4.2): a missed claim costs one bad retrieval, a
hallucinated claim poisons the graph and is worse than the semantic soup it
replaced. Sub-threshold output goes to `claims_review`, never to `claims`.

Every claim records `extractor_version`, so a model change can reprocess
selectively instead of rebuilding the world.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .llm import call_llm

EXTRACTOR_VERSION = "teacher-27b-v2"

# The kind definitions the graph actually acts on. Written as consequences rather
# than dictionary glosses, because the model's job is to pick the label that makes
# supersession behave correctly (§4.5), not to classify prose in the abstract.
SYSTEM = """You extract atomic claims from an engineering corpus.

A claim is one self-contained assertion that could later be checked, contradicted, or superseded. Resolve pronouns so each claim stands alone.

**Extract at most 5 claims per passage. Prefer few substantial claims over many small ones.** Most passages carry one or two real assertions surrounded by detail; detail is not a claim.

Choose the kind by asking what should happen when a LATER statement disagrees with this one:

- observation: a report of what was done, seen, or measured on one occasion. Accumulates, supersedes nothing. **This is the most common kind in work notes and the right default when unsure.**
- decision: a choice that was made and that overrides earlier choices on the same subject. Work write-ups that conclude "we did X because Y" are decisions.
- fact: a durable, checkable property of the world or the code. **Narrow. Use it only when the statement would still need to be true tomorrow.** A report of an action taken is an observation, not a fact.
- practice: how work is currently done. Can stop being true without anyone being wrong.
- capability: what a tool can do, whether or not anyone uses it.
- hypothesis: hedged, proposed, or uncertain — "seems", "probably", "may", "suggests", "worth checking", "I think". **If a statement carries any hedge, it is a hypothesis even if it sounds authoritative. This is the single most important distinction here; a hypothesis promoted to fact corrupts the graph.**
- plan / task: intended or outstanding future work.
- preference: what someone wants or favours.

Rules:
- Extract nothing from code, tables, logs, file listings or command lines.
- Never invent detail absent from the passage.
- confidence is your certainty the claim is correctly extracted, 0.0-1.0.

Return ONLY a JSON array, no prose:
[{"content": "...", "kind": "observation", "confidence": 0.9}]
Return [] if the passage asserts nothing."""


@dataclass
class Extracted:
    content: str
    kind: str
    confidence: float


VALID_KINDS = {
    "fact", "decision", "practice", "capability",
    "observation", "hypothesis", "plan", "task", "preference",
}

_ARRAY = re.compile(r"\[.*\]", re.S)


def parse(raw: str) -> list[Extracted]:
    """Tolerant parse. A malformed response yields nothing rather than garbage —
    an unparseable answer and a wrong answer must not be confusable."""
    m = _ARRAY.search(raw or "")
    if not m:
        return []
    try:
        rows = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        content = str(r.get("content", "")).strip()
        kind = str(r.get("kind", "")).strip().lower()
        if not content or kind not in VALID_KINDS:
            continue
        try:
            conf = float(r.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        out.append(Extracted(content, kind, max(0.0, min(1.0, conf))))
    return out


def extract(
    passage: str,
    *,
    model: str = "Qwen3.5-27B-UD-Q4_K_XL.gguf",
    provider: str = "llamacpp",
    max_tokens: int = 8192,
    timeout: float = 600.0,
) -> tuple[list[Extracted], str]:
    """Returns (claims, raw). The raw response is kept so a parse failure can be
    diagnosed rather than silently counted as an empty extraction."""
    raw = call_llm(
        provider=provider,
        model=model,
        system=SYSTEM,
        prompt=f"Passage:\n\n{passage.strip()[:6000]}",
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return parse(raw), raw
