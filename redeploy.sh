#!/bin/bash
# ByFly браузер-ИИ — пересоздание RunPod-пода byfly-browser-ai.
# Авто-находит старый под по имени, терминирует, деплоит свежий образ с env.
# GPU берётся по списку fallback (важен только CPU/RAM, GPU — ради on-demand).
#
# Секреты НЕ хардкодим. Берём так (в порядке приоритета):
#   RUNPOD_API_KEY  : env  ->  ~/.byfly_runpod.key
#   ANTHROPIC_API_KEY: env ->  ~/.byfly_anthropic.key
# Локально ключи лежат в manager_byfly.kz/.cursor/SECRETS.local.md (не в git).
#
# Использование:
#   RUNPOD_API_KEY=rpa_... ANTHROPIC_API_KEY=sk-ant-... ./redeploy.sh
#   (или положи ключи в ~/.byfly_runpod.key и ~/.byfly_anthropic.key и просто ./redeploy.sh)
set -u

RP="${RUNPOD_API_KEY:-$(cat ~/.byfly_runpod.key 2>/dev/null)}"
ANTH="${ANTHROPIC_API_KEY:-$(cat ~/.byfly_anthropic.key 2>/dev/null)}"
IMG="${IMAGE:-ghcr.io/alexwabix/byfly-browser-ai:latest}"
NAME="${POD_NAME:-byfly-browser-ai}"
MODEL="${AGENT_MODEL:-claude-sonnet-4-5-20250929}"
MAXSTEPS="${AGENT_MAX_STEPS:-40}"

if [ -z "$RP" ]; then echo "[FAIL] нет RUNPOD_API_KEY (env или ~/.byfly_runpod.key)"; exit 1; fi
if [ -z "$ANTH" ]; then echo "[FAIL] нет ANTHROPIC_API_KEY (env или ~/.byfly_anthropic.key)"; exit 1; fi

GQL="https://api.runpod.io/graphql?api_key=$RP"
UA="ByFly-Deploy/1.0"
post(){ curl -s -A "$UA" -H "Content-Type: application/json" -X POST "$GQL" -d "$1"; }

# --- 1. найти и терминировать ВСЕ поды с этим именем ---
echo "[*] ищу старые поды '$NAME'..."
LIST=$(post '{"query":"query { myself { pods { id name desiredStatus } } }"}')
OLD_IDS=$(printf '%s' "$LIST" | NAME="$NAME" python3 -c "
import sys,json,os
d=json.loads(sys.stdin.read(),strict=False)
pods=((d.get('data') or {}).get('myself') or {}).get('pods') or []
print('\n'.join(p['id'] for p in pods if p.get('name')==os.environ['NAME']))
" 2>/dev/null)
for OID in $OLD_IDS; do
  echo "[*] terminate $OID"
  post "$(python3 -c "import json;print(json.dumps({'query':'mutation { podTerminate(input:{podId:\"$OID\"}) }'}))")" >/dev/null
done
[ -z "$OLD_IDS" ] && echo "    старых не найдено"

# --- 2. деплой нового с GPU-fallback ---
GPUS=("NVIDIA RTX A5000" "NVIDIA RTX A4000" "NVIDIA GeForce RTX 3090" "NVIDIA GeForce RTX 4090" "NVIDIA RTX A4500")
for G in "${GPUS[@]}"; do
  echo "[*] deploy on: $G"
  Q=$(ANTH="$ANTH" IMG="$IMG" NAME="$NAME" G="$G" MODEL="$MODEL" MAXSTEPS="$MAXSTEPS" python3 <<'PY'
import os,json
env=[("ANTHROPIC_API_KEY",os.environ["ANTH"]),
     ("VNC_PASSWORD","byflyvnc"),
     ("RESOLUTION","1280x900x24"),
     ("RESOLUTION_WIDTH","1280"),
     ("RESOLUTION_HEIGHT","900"),
     ("CHROME_PERSISTENT_SESSION","true"),
     ("AGENT_MODEL",os.environ["MODEL"]),
     ("AGENT_MAX_STEPS",os.environ["MAXSTEPS"])]
env_str=",".join('{key:"%s",value:%s}'%(k,json.dumps(v)) for k,v in env)
m=('mutation { podFindAndDeployOnDemand(input:{'
   'cloudType: ALL, gpuCount: 1, gpuTypeId: %s, '
   'name: %s, imageName: %s, '
   'containerDiskInGb: 40, volumeInGb: 0, '
   'ports: "7788/http,6080/http,5901/http,9222/http,22/tcp", '
   'env: [%s] }){ id imageName desiredStatus } }'
   )%(json.dumps(os.environ["G"]),json.dumps(os.environ["NAME"]),json.dumps(os.environ["IMG"]),env_str)
print(json.dumps({"query":m}))
PY
)
  R=$(post "$Q"); echo "$R"
  ID=$(printf '%s' "$R" | python3 -c "import sys,json;d=json.loads(sys.stdin.read(),strict=False);p=(d.get('data') or {}).get('podFindAndDeployOnDemand');print(p['id'] if p else '')" 2>/dev/null)
  if [ -n "$ID" ]; then echo "[OK] deployed pod=$ID on $G"; echo "$ID" > /tmp/new_pod_id; exit 0; fi
  echo "    no capacity/err on $G"
done
echo "[FAIL] no GPU capacity"
exit 1
