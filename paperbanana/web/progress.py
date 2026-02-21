"""進捗通知フック — パイプラインの各エージェントの実行状況をWebSocketで送信する。

CLIの monkey-patch パターン (cli.py 238-316行目) を踏襲し、
console.print() の代わりに ws.send_json() でブラウザに通知する。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

    from paperbanana.core.pipeline import PaperBananaPipeline


async def _send(ws: WebSocket, **data) -> None:
    """WebSocketにJSONメッセージを送信する（切断済みなら無視）。"""
    try:
        await ws.send_json(data)
    except Exception:
        pass


def attach_progress_hooks(pipeline: PaperBananaPipeline, ws: WebSocket) -> None:
    """パイプラインの各エージェントに進捗通知フックを付ける。

    各エージェントの run() をラップし、実行前後にWebSocketへメッセージを送信する。
    パイプライン本体のコードは一切変更しない。
    """
    orig_optimizer = pipeline.optimizer.run
    orig_retriever = pipeline.retriever.run
    orig_planner = pipeline.planner.run
    orig_stylist = pipeline.stylist.run
    orig_visualizer = pipeline.visualizer.run
    orig_critic = pipeline.critic.run

    async def _optimizer_run(*a, **kw):
        await _send(ws, type="progress", phase="phase0", step="optimizer", status="started")
        t = time.perf_counter()
        result = await orig_optimizer(*a, **kw)
        await _send(
            ws, type="progress", phase="phase0", step="optimizer", status="completed",
            elapsed=round(time.perf_counter() - t, 1),
        )
        return result

    async def _retriever_run(*a, **kw):
        await _send(ws, type="progress", phase="phase1", step="retriever", status="started")
        t = time.perf_counter()
        result = await orig_retriever(*a, **kw)
        await _send(
            ws, type="progress", phase="phase1", step="retriever", status="completed",
            elapsed=round(time.perf_counter() - t, 1),
            detail=f"{len(result)} examples",
        )
        return result

    async def _planner_run(*a, **kw):
        await _send(ws, type="progress", phase="phase1", step="planner", status="started")
        t = time.perf_counter()
        result = await orig_planner(*a, **kw)
        await _send(
            ws, type="progress", phase="phase1", step="planner", status="completed",
            elapsed=round(time.perf_counter() - t, 1),
            detail=f"{len(result)} chars",
        )
        return result

    async def _stylist_run(*a, **kw):
        await _send(ws, type="progress", phase="phase1", step="stylist", status="started")
        t = time.perf_counter()
        result = await orig_stylist(*a, **kw)
        await _send(
            ws, type="progress", phase="phase1", step="stylist", status="completed",
            elapsed=round(time.perf_counter() - t, 1),
        )
        return result

    async def _visualizer_run(*a, **kw):
        iteration = kw.get("iteration", 0)
        await _send(
            ws, type="progress", phase="phase2", step="visualizer", status="started",
            iteration=iteration,
        )
        t = time.perf_counter()
        result = await orig_visualizer(*a, **kw)
        await _send(
            ws, type="progress", phase="phase2", step="visualizer", status="completed",
            elapsed=round(time.perf_counter() - t, 1),
            iteration=iteration,
        )
        return result

    async def _critic_run(*a, **kw):
        iteration = kw.get("iteration", 0)
        await _send(
            ws, type="progress", phase="phase2", step="critic", status="started",
            iteration=iteration,
        )
        t = time.perf_counter()
        result = await orig_critic(*a, **kw)
        await _send(
            ws, type="progress", phase="phase2", step="critic", status="completed",
            elapsed=round(time.perf_counter() - t, 1),
            iteration=iteration,
            needs_revision=result.needs_revision,
            summary=result.summary,
        )
        return result

    pipeline.optimizer.run = _optimizer_run
    pipeline.retriever.run = _retriever_run
    pipeline.planner.run = _planner_run
    pipeline.stylist.run = _stylist_run
    pipeline.visualizer.run = _visualizer_run
    pipeline.critic.run = _critic_run
