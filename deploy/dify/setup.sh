#!/usr/bin/env bash
# 一键把 Dify 起起来，并让 seekdb 同时当元数据库 + 向量库。
# 需要：docker + docker compose；Linux/macOS 或 Windows 的 Git Bash。
set -euo pipefail

DIFY_DIR="${DIFY_DIR:-$HOME/dify}"

echo "==> 1/3 准备 Dify 源码"
if [ ! -d "$DIFY_DIR" ]; then
  git clone --depth 1 https://github.com/langgenius/dify.git "$DIFY_DIR"
fi
cd "$DIFY_DIR/docker"
[ -f .env ] || cp .env.example .env

echo "==> 2/3 写入 seekdb 配置"
python3 - <<'PY'
import pathlib, re

env = pathlib.Path(".env")
text = env.read_text(encoding="utf-8")
want = {
    "DB_TYPE": "mysql",
    "DB_USERNAME": "root",
    "DB_PASSWORD": "",
    "DB_HOST": "seekdb",
    "DB_PORT": "2881",
    "DB_DATABASE": "test",
    "VECTOR_STORE": "oceanbase",
    "OCEANBASE_VECTOR_HOST": "seekdb",
    "OCEANBASE_VECTOR_USER": "root",
    "COMPOSE_PROFILES": "seekdb",
}
for k, v in want.items():
    line = f"{k}={v}"
    if re.search(rf"^{re.escape(k)}=.*$", text, re.M):
        text = re.sub(rf"^{re.escape(k)}=.*$", line, text, count=1, flags=re.M)
    else:
        text += "\n" + line + "\n"
env.write_text(text, encoding="utf-8")
print("   .env updated:", ", ".join(want))
PY

echo "==> 3/3 启动（首次会拉约 5GB 镜像）"
docker compose up -d
docker compose ps

cat <<'EOF'

Dify 起来了： http://localhost/install （先建管理员，再配模型供应商）

接着：
  1) 回到本仓库，起 zoo service：  bash scripts/start.sh
  2) Dify 里「导入 DSL」→ dify/vector-zoo.dsl.yml
  3) 环境变量 ZOO_API 改成 http://host.docker.internal:8077
  4) 三个 LLM 节点重选模型

EOF
