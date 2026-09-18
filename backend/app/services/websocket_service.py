"""In-process WebSocket hub (spec section 28).

Channels:
  team:{team_id}         private pushes for one team (attacks, freezes, jams, traps)
  event:{event_id}       everyone in the event (lifecycle changes, leaderboard ticks)
  coord:{event_id}       coordinators only (dashboard refresh hints, live log)

Messages are small hints ("state changed") plus the data needed for urgent
UI such as the attack countdown. Clients always resync through
``GET /me/state`` after (re)connecting, so a dropped socket never leaves a
phone out of date.

Single process only. Running several API processes would need a Redis
pub/sub fan-out behind ``publish``.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger("round2.ws")


def team_channel(team_id: str) -> str:
    return f"team:{team_id}"


def event_channel(event_id: str) -> str:
    return f"event:{event_id}"


def coord_channel(event_id: str) -> str:
    return f"coord:{event_id}"


class Hub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._channels_of: dict[WebSocket, list[str]] = {}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def register(self, ws: WebSocket, channels: list[str]) -> None:
        self._channels_of[ws] = channels
        for channel in channels:
            self._subs[channel].add(ws)

    def unregister(self, ws: WebSocket) -> None:
        for channel in self._channels_of.pop(ws, []):
            subs = self._subs.get(channel)
            if subs is not None:
                subs.discard(ws)
                if not subs:
                    self._subs.pop(channel, None)

    def connection_count(self) -> int:
        return len(self._channels_of)

    async def _broadcast(self, channel: str, message: dict) -> None:
        for ws in list(self._subs.get(channel, ())):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - a dead socket must not break the others
                self.unregister(ws)

    def publish(self, channel: str, message: dict) -> None:
        """Fire-and-forget; safe to call from request threads or the loop."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        coro = self._broadcast(channel, message)
        if running is loop:
            loop.create_task(coro)
        else:
            try:
                asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:  # loop shutting down
                coro.close()


hub = Hub()
