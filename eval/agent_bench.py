"""Answer-level bench: does an agent get the question RIGHT?

nDCG asks whether the correct record ranked highly. An agent asks a different
question — what is the answer — and the two come apart exactly where this project
claims to be useful. A retriever can surface the right document and the agent still
answers from the stale one sitting next to it.

So: the same questions, the same model, the same turn budget, two toolsets.

    claimbase   one tool: recall (via the MCP server, the real transport)
    grep        two tools: search and read, over the three repos

Then a judge that never learns which agent produced which answer, scoring against
the gold answer. Wrong is unambiguous in a way nDCG is not, and it does not depend
on the ranking weights I tuned against eight questions — which is the point.

Fairness notes, since a rigged baseline would make this worthless:
- identical model, temperature and turn budget for both
- the grep agent gets ripgrep over all three repos plus file reads, which is what an
  agent without claimbase actually has
- judging is blind and order-randomised per question

Run: python eval/agent_bench.py --n 9
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from baselines import load_gold  # noqa: E402
from claimbase.llm import call_llm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"
REPOS = ["/home/ivy/Work/guru", "/home/ivy/Work/guru-web", "/home/ivy/Work/rellm"]
MODEL = "Qwen3.5-27B-UD-Q4_K_XL.gguf"
MAX_TOKENS = 2048
MAX_TURNS = 3

ANSWER_SYS = """You answer questions about an engineering project from evidence you \
gather with tools.

Work in at most {turns} tool calls, then answer. To call a tool emit ONLY:
{tools}

When you have enough evidence, emit:
ANSWER: <your answer in two sentences or fewer>

Be decisive. If the evidence shows something changed, say what is true NOW and note \
what it replaced. If you cannot tell, say so plainly rather than guessing."""

CLAIMBASE_TOOLS = (
    'SEARCH: <the question, in full>\n'
    '(a claim graph, not a keyword index — pass the whole question, since phrasing '
    'like "why is" or "still current" changes which claims are ranked highest; '
    'results carry kind, trust, date and supersession standing)'
)
GREP_TOOLS = 'GREP: <pattern>\nREAD: <path>\n(ripgrep and file reads over the guru, guru-web and rellm repos)'

JUDGE_SYS = """You grade an answer against a reference answer.

Reply with ONLY one word:
CORRECT   - matches the reference on the substantive point
PARTIAL   - right direction, misses or garbles something material
WRONG     - contradicts the reference, or asserts a superseded state as current

A confidently stated stale answer is WRONG, not PARTIAL."""


def grep_tool(pattern: str) -> str:
    out = subprocess.run(
        ["rg", "-i", "--max-count", "3", "--max-columns", "300", "-n", pattern, *REPOS],
        capture_output=True, text=True, timeout=60,
    ).stdout
    return "\n".join(out.splitlines()[:25]) or "(no matches)"


def read_tool(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        for r in REPOS:
            if (Path(r) / path).exists():
                p = Path(r) / path
                break
    try:
        return p.read_text(errors="ignore")[:3000]
    except Exception as e:
        return f"(cannot read: {e})"


async def claimbase_tool(session, query: str) -> str:
    res = await session.call_tool("recall", {"query": query, "k": 6})
    payload = json.loads(res.content[0].text)
    lines = []
    for h in payload.get("results", []):
        lines.append(
            f"- {h['claim'][:280]}\n    [{h['kind']} · {h['trust']} · "
            f"{(h['asserted_at'] or '?')[:10]} · supersedes {h['supersedes']}]"
        )
    return "\n".join(lines) or "(nothing)"


async def run_agent(question: str, mode: str, session=None) -> tuple[str, list[str]]:
    tools = CLAIMBASE_TOOLS if mode == "claimbase" else GREP_TOOLS
    system = ANSWER_SYS.format(turns=MAX_TURNS, tools=tools)
    transcript, trace = [f"Question: {question}"], []

    for _ in range(MAX_TURNS + 1):
        reply = call_llm(
            provider="llamacpp", model=MODEL, system=system,
            prompt="\n\n".join(transcript), max_tokens=MAX_TOKENS, timeout=300,
        )
        if m := re.search(r"ANSWER:\s*(.+)", reply, re.S):
            return m.group(1).strip()[:600], trace
        if mode == "claimbase" and (m := re.search(r"SEARCH:\s*(.+)", reply)):
            q = m.group(1).strip()
            trace.append(f"SEARCH {q[:60]}")
            transcript += [reply.strip(), f"Results:\n{await claimbase_tool(session, q)}"]
            continue
        if mode == "grep" and (m := re.search(r"GREP:\s*(.+)", reply)):
            pat = m.group(1).strip()
            trace.append(f"GREP {pat[:60]}")
            transcript += [reply.strip(), f"Matches:\n{grep_tool(pat)}"]
            continue
        if mode == "grep" and (m := re.search(r"READ:\s*(\S+)", reply)):
            path = m.group(1).strip()
            trace.append(f"READ {path[:60]}")
            transcript += [reply.strip(), f"File:\n{read_tool(path)}"]
            continue
        # No tool call and no ANSWER: take whatever it said as the answer rather
        # than looping — a model that will not follow the protocol still gave a view.
        return reply.strip()[:600], trace
    return "(no answer within turn budget)", trace


def judge(question: str, reference: str, answer: str) -> str:
    verdict = call_llm(
        provider="llamacpp", model=MODEL, system=JUDGE_SYS,
        prompt=f"Question: {question}\n\nReference: {reference}\n\nAnswer: {answer}",
        max_tokens=256, timeout=180,
    )
    for v in ("CORRECT", "PARTIAL", "WRONG"):
        if v in verdict.upper():
            return v
    return "WRONG"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=9)
    args = ap.parse_args()

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    gold = load_gold()[: args.n]
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    params = StdioServerParameters(command=str(PYTHON), args=["-m", "claimbase.mcp_server"], env=env)

    rows = []
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            for g in gold:
                out = {"id": g["id"], "class": g["class"], "question": g["question"]}
                # Order randomised so a systematic bias in one position cannot
                # masquerade as a difference between the toolsets.
                modes = ["claimbase", "grep"]
                random.Random(hash(g["id"]) & 0xFFFF).shuffle(modes)
                for mode in modes:
                    ans, trace = await run_agent(
                        g["question"], mode, session if mode == "claimbase" else None
                    )
                    out[mode] = {"answer": ans, "trace": trace,
                                 "verdict": judge(g["question"], g["answer"], ans)}
                rows.append(out)
                print(f"  {g['id']}  claimbase={out['claimbase']['verdict']:<8} "
                      f"grep={out['grep']['verdict']}", flush=True)

    def tally(mode):
        c = {"CORRECT": 0, "PARTIAL": 0, "WRONG": 0}
        for r_ in rows:
            c[r_[mode]["verdict"]] += 1
        return c

    print(f"\n  {'':<12} {'CORRECT':>8} {'PARTIAL':>8} {'WRONG':>7}")
    for mode in ("claimbase", "grep"):
        t = tally(mode)
        print(f"  {mode:<12} {t['CORRECT']:>8} {t['PARTIAL']:>8} {t['WRONG']:>7}")
    Path(__file__).parent.joinpath("results-agent.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
