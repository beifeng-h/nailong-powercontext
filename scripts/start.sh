#!/usr/bin/env bash
# 一键启动：建表 -> 起 HTTP 服务（web/ 静态页 + API）
set -euo pipefail
cd "$(dirname "$0")/../service"

export SEEKDB_HOST="${SEEKDB_HOST:-127.0.0.1}"
export SEEKDB_PORT="${SEEKDB_PORT:-2881}"
export SEEKDB_USER="${SEEKDB_USER:-root}"
export SEEKDB_DB="${SEEKDB_DB:-vector_zoo}"
export LLM_MODEL="${LLM_MODEL:-Qwen/Qwen2.5-7B-Instruct}"
export LLM_DEVICE="${LLM_DEVICE:-auto}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

python - <<'PY'
from zoo.db import ZooDB
db = ZooDB()
db.init_schema()
print("seekdb ready:", db.ping()["version"])
PY

exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8077}"
