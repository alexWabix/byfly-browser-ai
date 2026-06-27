# byfly-browser-ai

Сборочный пайплайн для образа **browser-use web-ui** (Chrome + Gradio + noVNC),
который используется в браузер-ИИ лаборатории ByFly (RunPod-под `byfly-browser-ai`).

GitHub Actions клонирует upstream `browser-use/web-ui`, собирает Docker-образ и
публикует его в `ghcr.io/<owner>/byfly-browser-ai:latest`.

Подробности: `manager_byfly.kz/.cursor/rules/browser-ai-lab.mdc`.
