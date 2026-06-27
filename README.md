# byfly-browser-ai

Сборочный пайплайн + минимальный UI для браузер-ИИ лаборатории ByFly
(RunPod-под `byfly-browser-ai`, Chrome + browser-use + noVNC).

GitHub Actions клонирует upstream `browser-use/web-ui`, накладывает **overlay**
(`overlay/simple_app.py` — мой минимальный FastAPI вместо тяжёлого Gradio) и
патчит `supervisord.conf`, собирает Docker-образ и публикует его в
`ghcr.io/<owner>/byfly-browser-ai:latest` (публичный).

- **Как развернуть / повторить / починить:** [`DEPLOY.md`](./DEPLOY.md)
- **Пересоздать под:** `./redeploy.sh` (ключи из env или `~/.byfly_*.key`)
- **Память агента (полный контекст):**
  `manager_byfly.kz/.cursor/rules/browser-ai-lab.mdc`
