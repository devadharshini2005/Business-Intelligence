"""Blocking gateway to mcp_server.py.

The API process (api_server.py, chat_agent.py) never touches MongoDB itself: it starts
mcp_server.py as a subprocess (stdio) and calls its tools through this class.

The API code is synchronous while the MCP client is async, so one MCP session lives on a
background event loop and `call()` blocks until the tool result is back.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CALL_TIMEOUT_S = 120


class McpToolError(Exception):
    """An MCP tool reported an error (its message is the tool's own)."""


class McpGateway:
    def __init__(self, server_script: str | None = None) -> None:
        self._script = server_script or str(Path(__file__).resolve().parent / "mcp_server.py")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="mcp-gateway", daemon=True)
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    # --- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        if self._session is not None:
            return
        if not self._thread.is_alive():
            self._thread.start()
        asyncio.run_coroutine_threadsafe(self._connect(), self._loop).result(timeout=60)

    async def _connect(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=[self._script],
            env=dict(os.environ),
            cwd=str(Path(self._script).resolve().parent),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

    def close(self) -> None:
        if self._session is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._stack.aclose(), self._loop).result(timeout=15)
        except Exception:
            pass
        finally:
            self._session = None
            self._loop.call_soon_threadsafe(self._loop.stop)

    # --- calls -----------------------------------------------------------------
    async def _call(self, name: str, args: dict[str, Any]) -> Any:
        if self._session is None:
            raise McpToolError("MCP gateway is not started")
        res = await self._session.call_tool(name, args)
        text = "".join(getattr(c, "text", "") or "" for c in res.content)
        if res.isError:
            raise McpToolError(text or f"tool {name} failed")
        data = getattr(res, "structuredContent", None)
        if data is None:
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                raise McpToolError(f"tool {name} returned non-JSON output: {text[:200]}") from None
        elif isinstance(data, dict) and set(data) == {"result"}:
            data = data["result"]  # some SDK versions wrap return values
        if isinstance(data, dict) and set(data) == {"error"}:
            raise McpToolError(str(data["error"]))
        return data

    def call(self, name: str, **args: Any) -> Any:
        """Call an MCP tool and return its parsed result. Raises McpToolError on a tool error."""
        return asyncio.run_coroutine_threadsafe(self._call(name, args), self._loop).result(timeout=CALL_TIMEOUT_S)

    def rows(self, name: str, **args: Any) -> list[Any]:
        """For tools that return {"rows": [...]}: just the rows."""
        return self.call(name, **args)["rows"]