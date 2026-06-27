"""
ByFly браузер-ИИ: МИНИМАЛЬНЫЙ интерфейс вместо перегруженного Gradio.

Один сервер на порту 7788 с тремя ручками:
  POST /run   { "task": "..." }   — запустить задачу для ИИ-агента
  GET  /stream                    — SSE-поток шагов (живой лог)
  POST /stop                      — остановить текущую задачу
  GET  /health                    — статус

Никаких настроек модели/провайдера в UI — Claude зашит по умолчанию.
Браузер headful на DISPLAY=:99, поэтому всё видно в noVNC (порт 6080).
Переиспользует рабочие классы из browser-use/web-ui (CustomBrowser,
BrowserUseAgent, CustomController).
"""
import os
import asyncio
import json
import logging
import traceback

os.environ.setdefault("DISPLAY", ":99")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from browser_use.browser.browser import BrowserConfig
from browser_use.browser.context import BrowserContextConfig
from langchain_anthropic import ChatAnthropic

from src.browser.custom_browser import CustomBrowser
from src.agent.browser_use.browser_use_agent import BrowserUseAgent
from src.controller.custom_controller import CustomController

WIDTH = int(os.getenv("RESOLUTION_WIDTH", "1280"))
HEIGHT = int(os.getenv("RESOLUTION_HEIGHT", "900"))
MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-20250514")
MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "40"))
PORT = int(os.getenv("PORT", "7788"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("byfly-simple")

app = FastAPI(title="ByFly Browser AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class S:
    browser = None
    context = None
    agent = None
    task = None         # asyncio.Task
    running = False
    queue = None        # asyncio.Queue для SSE
    history = []        # последние события (для подключившихся позже)
    last_error = None   # полный traceback последней ошибки (для диагностики)


def emit(ev: dict):
    S.history.append(ev)
    if len(S.history) > 500:
        S.history.pop(0)
    if S.queue is not None:
        try:
            S.queue.put_nowait(ev)
        except Exception:
            pass


async def ensure_browser():
    if S.browser is None:
        S.browser = CustomBrowser(config=BrowserConfig(
            headless=False,
            disable_security=True,
            extra_browser_args=[],
            new_context_config=BrowserContextConfig(
                window_width=WIDTH, window_height=HEIGHT,
            ),
        ))
    if S.context is None:
        S.context = await S.browser.new_context(config=BrowserContextConfig(
            window_width=WIDTH, window_height=HEIGHT,
        ))


async def step_cb(state, output, step_num):
    """Превращаем шаг агента в понятную строку лога."""
    goal, evalp, actions, url = "", "", [], ""
    try:
        url = getattr(state, "url", "") or ""
    except Exception:
        url = ""
    try:
        cs = output.current_state.model_dump(exclude_none=True)
        goal = cs.get("next_goal", "") or ""
        evalp = cs.get("evaluation_previous_goal", "") or ""
    except Exception:
        pass
    try:
        for a in output.action:
            d = a.model_dump(exclude_none=True)
            for k in d.keys():
                actions.append(k)
    except Exception:
        pass
    emit({
        "type": "step",
        "n": step_num,
        "goal": goal,
        "eval": evalp,
        "actions": actions,
        "url": url,
    })


def done_cb(history):
    final = None
    try:
        final = history.final_result()
    except Exception:
        final = None
    emit({"type": "done", "result": final or "Готово"})


class RunReq(BaseModel):
    task: str


@app.get("/health")
async def health():
    return {"ok": True, "running": S.running, "model": MODEL, "last_error": S.last_error}


@app.post("/run")
async def run(req: RunReq):
    if S.running:
        return JSONResponse({"ok": False, "error": "Уже выполняется задача"}, status_code=409)
    text = (req.task or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "Пустая задача"}, status_code=400)

    S.history = []
    S.last_error = None
    S.running = True
    emit({"type": "start", "task": text})

    async def runner():
        done_emitted = False
        try:
            await ensure_browser()
            llm = ChatAnthropic(
                model=MODEL,
                temperature=0.2,
                timeout=120,
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
            )
            controller = CustomController()
            S.agent = BrowserUseAgent(
                task=text,
                llm=llm,
                browser=S.browser,
                browser_context=S.context,
                controller=controller,
                register_new_step_callback=step_cb,
                register_done_callback=done_cb,
                use_vision=True,
                source="byfly-simple",
            )
            result = await S.agent.run(max_steps=MAX_STEPS)
            # гарантированный финал: даже если done_callback не вызвался
            final = None
            try:
                if result is not None and hasattr(result, "final_result"):
                    final = result.final_result()
                elif getattr(S.agent, "state", None) is not None:
                    final = S.agent.state.history.final_result()
            except Exception:
                final = None
            emit({"type": "done", "result": final or "Готово"})
            done_emitted = True
        except asyncio.CancelledError:
            emit({"type": "stopped", "result": "Остановлено пользователем"})
            done_emitted = True
        except BaseException as e:
            S.last_error = traceback.format_exc()
            log.error("agent error:\n%s", S.last_error)
            emit({"type": "error", "error": f"{type(e).__name__}: {e}"})
            done_emitted = True
        finally:
            if not done_emitted:
                emit({"type": "error", "error": "Завершилось без результата"})
            S.running = False
            S.agent = None

    S.task = asyncio.create_task(runner())
    return {"ok": True}


@app.post("/stop")
async def stop():
    if S.task is not None and not S.task.done():
        S.task.cancel()
    S.running = False
    return {"ok": True}


@app.get("/stream")
async def stream(request: Request):
    S.queue = asyncio.Queue()
    backlog = list(S.history)

    async def gen():
        for ev in backlog:
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                ev = await asyncio.wait_for(S.queue.get(), timeout=15)
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
