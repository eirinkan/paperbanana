"""PaperBanana Web UI — FastAPIサーバー。

WebSocketで生成リクエストを受け取り、パイプラインを実行しながら
各ステップの進捗をリアルタイムでブラウザに送信する。
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from paperbanana.core.config import Settings
from paperbanana.core.logging import configure_logging
from paperbanana.core.types import DiagramType, GenerationInput
from paperbanana.web.progress import attach_progress_hooks

load_dotenv()

app = FastAPI(title="PaperBanana Web")

STATIC_DIR = Path(__file__).parent / "static"
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 静的ファイル配信
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def _ensure_outputs_dir():
    """outputs/ ディレクトリが存在しない場合は作成する。"""
    outputs = PROJECT_ROOT / "outputs"
    outputs.mkdir(exist_ok=True)
    # 生成画像の配信
    app.mount("/outputs", StaticFiles(directory=str(outputs)), name="outputs")


@app.get("/")
async def index():
    """メインページを返す。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws/generate")
async def ws_generate(ws: WebSocket):
    """WebSocket経由で図表を生成する。

    1. クライアントからJSONパラメータを受信
    2. パイプラインを初期化し、進捗フックを接続
    3. 生成実行（各ステップの進捗はフック経由でWebSocketへ送信）
    4. 完了時に結果画像のURLを返す
    """
    await ws.accept()
    try:
        params = await ws.receive_json()

        configure_logging(verbose=False)

        settings = Settings(
            refinement_iterations=params.get("iterations", 3),
            optimize_inputs=params.get("optimize", False),
        )

        from paperbanana.core.pipeline import PaperBananaPipeline

        pipeline = PaperBananaPipeline(settings=settings)
        attach_progress_hooks(pipeline, ws)

        diagram_type = DiagramType(params.get("diagram_type", "methodology"))

        gen_input = GenerationInput(
            source_context=params["source_context"],
            communicative_intent=params["caption"],
            diagram_type=diagram_type,
            raw_data=params.get("raw_data"),
        )

        await ws.send_json({"type": "status", "message": "生成を開始します..."})

        result = await pipeline.generate(gen_input)

        # image_pathからWebで配信可能なURLに変換
        image_url = "/" + result.image_path.replace("\\", "/")

        iteration_images = []
        for it in result.iterations:
            iteration_images.append({
                "iteration": it.iteration,
                "image_url": "/" + it.image_path.replace("\\", "/"),
                "needs_revision": it.critique.needs_revision if it.critique else False,
                "suggestions": it.critique.critic_suggestions[:3] if it.critique else [],
            })

        await ws.send_json({
            "type": "complete",
            "image_url": image_url,
            "run_id": result.metadata.get("run_id", ""),
            "total_seconds": round(result.metadata.get("timing", {}).get("total_seconds", 0), 1),
            "iterations": iteration_images,
        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
