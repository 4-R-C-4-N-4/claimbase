"""The MCP server's blast radius.

These test the security posture rather than the features, because the failure mode
is silent: a server that quietly accepts writes looks identical to one that does not
until something has already been written.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"
pytestmark = pytest.mark.skipif(not PYTHON.exists(), reason="venv not built")


async def _session(write: bool):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    if write:
        env["CLAIMBASE_MCP_WRITE"] = "1"
    else:
        env.pop("CLAIMBASE_MCP_WRITE", None)
    params = StdioServerParameters(command=str(PYTHON), args=["-m", "claimbase.mcp_server"], env=env)
    return stdio_client(params), ClientSession


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def _tools_and_probe(write: bool):
    client, Session = await _session(write)
    async with client as (r, w):
        async with Session(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            res = await s.call_tool(
                "assert_claim", {"text": "SANDBOX TEST must not persist", "kind": "observation"}
            )
            body = res.content[0].text if res.content else ""
            return names, body


@pytest.mark.timeout(120)
def test_write_tool_absent_and_unreachable_by_default() -> None:
    """Not merely unlisted: a tool that is only hidden can still be named by an
    injected instruction, so the call itself must fail."""
    names, body = _run(_tools_and_probe(write=False))
    assert "assert_claim" not in names
    assert "Unknown tool" in body


@pytest.mark.timeout(120)
def test_write_tool_appears_only_when_enabled() -> None:
    names, _ = _run(_tools_and_probe(write=True))
    assert "assert_claim" in names


@pytest.mark.timeout(120)
def test_read_role_cannot_write() -> None:
    """The default connection must be incapable of writing, not merely disinclined."""
    import psycopg

    from claimbase.mcp_server import RO_DSN

    with psycopg.connect(RO_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM claims")
        assert cur.fetchone()[0] > 0
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            cur.execute("DELETE FROM claims WHERE false")


@pytest.mark.timeout(120)
def test_results_are_framed_as_untrusted() -> None:
    """Retrieved text reaches a model's context. It must arrive labelled as data, or
    instruction-shaped content in the corpus reads as instruction."""
    from claimbase.mcp_server import UNTRUSTED

    async def go():
        client, Session = await _session(False)
        async with client as (r, w):
            async with Session(r, w) as s:
                await s.initialize()
                res = await s.call_tool("recall", {"query": "auto-promote", "k": 2})
                return json.loads(res.content[0].text)

    payload = _run(go())
    assert payload["_note"] == UNTRUSTED
