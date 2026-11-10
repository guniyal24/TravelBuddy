"""Tool clients used by the planner agents.

  LocalTools  calls the Python tool functions directly (fast; used in most unit tests)
  MCPTools    calls the same tools through the Model Context Protocol: an MCP client talks
              to the MCP server. Transport is "memory" (server in this process, real MCP
              messages) or "stdio" (server launched as a separate subprocess, exactly how an
              external MCP host would run it).

Both expose `call(name, **arguments) -> dict`, so the planner does not care which it gets.
The planner's nodes are synchronous, so MCPTools keeps one long-lived client on a background
event loop thread and bridges calls into it.
"""
import asyncio
import json
import sys
import threading

from mcp.client import Client

from mcp_server import tools as impl


class ToolError(Exception):
    """A tool call failed (bad arguments, server error, timeout)."""


class LocalTools:
    _FUNCS = {
        "estimate_budget": impl.estimate_budget,
        "check_season": impl.season_check,
        "check_altitude_plan": impl.altitude_check,
        "get_weather": impl.weather_for,
        "get_transport": impl.transport_for,
        "check_conditions": impl.conditions_for,
    }

    def call(self, name: str, **arguments) -> dict:
        try:
            return self._FUNCS[name](**arguments)
        except KeyError:
            raise ToolError(f"unknown tool {name!r}") from None
        except (ValueError, TypeError) as exc:
            raise ToolError(str(exc)) from exc

    def close(self) -> None:
        pass


class MCPTools:
    def __init__(self, transport: str = "memory", timeout: float = 60.0):
        if transport not in ("memory", "stdio"):
            raise ValueError("transport must be 'memory' or 'stdio'")
        self.transport = transport
        self.timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._client = None
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="mcp-client")
        self._thread.start()
        if not self._ready.wait(timeout):
            raise ToolError("MCP client did not start in time")
        if self._error:
            raise ToolError(f"MCP client failed to start: {self._error}") from self._error

    # ---- background loop ----
    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    def _target(self):
        if self.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters

            return StdioServerParameters(command=sys.executable,
                                         args=["-m", "mcp_server.server"])
        from mcp_server.server import server

        return server

    async def _main(self) -> None:
        self._stop = asyncio.Event()
        try:
            # one task owns the client for its whole life (anyio scopes must exit where entered)
            async with Client(self._target()) as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # startup failure or crash: surface it to callers
            self._error = exc
            self._ready.set()

    # ---- public ----
    def call(self, name: str, **arguments) -> dict:
        if self._error:
            raise ToolError(f"MCP client unavailable: {self._error}")
        fut = asyncio.run_coroutine_threadsafe(self._client.call_tool(name, arguments),
                                               self._loop)
        try:
            result = fut.result(self.timeout)
        except Exception as exc:
            raise ToolError(f"MCP call {name} failed: {exc}") from exc
        text = result.content[0].text if result.content else ""
        if result.is_error:
            raise ToolError(text or f"tool {name} returned an error")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ToolError(f"tool {name} returned non-JSON output") from exc

    def close(self) -> None:
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=10)
