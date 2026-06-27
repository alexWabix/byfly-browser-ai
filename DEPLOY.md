# Развёртывание браузер-ИИ ByFly (с нуля и повтор)

Полный playbook. Парная память агента: `manager_byfly.kz/.cursor/rules/browser-ai-lab.mdc`.

## Архитектура (TL;DR)

- **Образ** `ghcr.io/alexwabix/byfly-browser-ai:latest` собирается этим репо
  (GitHub Actions): берёт upstream `browser-use/web-ui`, накладывает overlay
  (`overlay/simple_app.py`) и патчит `supervisord.conf`, чтобы вместо тяжёлого
  Gradio запускался мой минимальный FastAPI.
- **Под** на RunPod с именем `byfly-browser-ai` крутит этот образ.
  Порты: `7788` (FastAPI: `/run`,`/stream`,`/stop`,`/health`),
  `6080` (noVNC), `5901` (VNC), `9222` (Chrome debug), `22` (SSH).
- **Прод-страница** `https://api.v.2.byfly.kz/browser_lab.html` — слева свой
  чат (`/run`+`/stream`), справа noVNC. Под находится **по имени** через
  `browser_lab_api.php` (self-healing, ID пода нигде не зашит).
- **Модель зашита**: `claude-sonnet-4-5-20250929` (в UI настроек нет).

## Секреты (НЕ в git)

| Что | Где взять | Куда положить локально (опц.) |
|---|---|---|
| `RUNPOD_API_KEY` (`rpa_…`) | `manager_byfly.kz/.cursor/SECRETS.local.md` / прод `/var/www/www-root/data/.byfly_runpod.key` | `~/.byfly_runpod.key` |
| `ANTHROPIC_API_KEY` (`sk-ant-…`) | `manager_byfly.kz/.cursor/SECRETS.local.md` | `~/.byfly_anthropic.key` |

## A. Изменить поведение агента/UI → пересобрать образ

1. Правишь `overlay/simple_app.py` (логика агента, эндпоинты) или
   `.github/workflows/build.yml` (overlay/патч supervisord/requirements).
2. `git commit && git push` в `main` → GitHub Actions собирает и пушит
   `:latest` в ghcr (~3 мин). Следить:
   `gh run list --repo alexWabix/byfly-browser-ai -L 1` или вкладка Actions.
3. Дождаться `completed/success`, затем пересоздать под (раздел B), чтобы
   подтянулся свежий `:latest`.

## B. Пересоздать под (подтянуть свежий образ / починить)

```bash
# ключи из env или из ~/.byfly_*.key
RUNPOD_API_KEY=rpa_... ANTHROPIC_API_KEY=sk-ant-... ./redeploy.sh
```

Скрипт сам: находит все поды с именем `byfly-browser-ai`, терминирует их,
деплоит новый с GPU-fallback (A5000→A4000→3090→4090→A4500), пишет новый id в
`/tmp/new_pod_id`. На проде **менять ничего не надо** — страница найдёт под по имени.

## C. Проверка после деплоя

```bash
# 1) под виден эндпоинту и RUNNING
curl -s "https://api.v.2.byfly.kz/browser_lab_api.php?action=status"

# 2) FastAPI жив, ключ доехал, модель верная
PID=$(curl -s "https://api.v.2.byfly.kz/browser_lab_api.php?action=status" \
      | python3 -c "import sys,json;print(json.load(sys.stdin)['podId'])")
curl -s "https://$PID-7788.proxy.runpod.net/health"
#  ждём: {"ok":true,"model":"claude-sonnet-4-5-20250929","has_key":true,...}
```
Первый старт пода дольше (тянет образ). `has_key:false` → ключ не доехал
(см. патч supervisord в build.yml). Затем открыть `browser_lab.html` и дать
тестовую задачу.

## D. Прод-файлы (на сервере byfly-new, 91.147.95.66)

- `/var/www/www-root/data/www/api.v.2.byfly.kz/browser_lab.html` — страница.
- `/var/www/www-root/data/www/api.v.2.byfly.kz/browser_lab_api.php` — self-heal/kill-switch
  (`?action=status|stop|start`, токен действий `byfly-lab-2026`,
  RunPod-ключ читает из `/var/www/www-root/data/.byfly_runpod.key`).

Эти файлы НЕ пересоздаются при редеплое пода — правятся отдельно через `ssh byfly-new`.

## Грабли (решены 27.06.2026)

- Модель `claude-sonnet-4-20250514` у аккаунта **недоступна** (`not_found`).
  Дефолт — `claude-sonnet-4-5-20250929`. Список: `GET api.anthropic.com/v1/models`.
- `ANTHROPIC_API_KEY` не доезжал в программу supervisord → агент `Error 401`.
  Лечится явным `%(ENV_ANTHROPIC_API_KEY)s` в `environment=` программы webui (в build.yml).
- browser-use не всегда звал `register_done_callback` → `simple_app.py` строит
  **гарантированный финал** из `agent.state.history`. Не убирать.
