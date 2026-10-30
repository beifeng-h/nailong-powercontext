# 本地部署 Dify（并让 seekdb 一库两用）

Dify 官方只提供 **Docker Compose** 部署方式，所以这一页的路径是：
装 Docker → 拉 Dify → 改 4 个环境变量让 seekdb 同时当元数据库和向量库 → 导入我们的 Chatflow。

> 如果本机暂时装不了 Docker（Windows 需要在 BIOS 开虚拟化 + 重启），先用仓库根目录 README 的「A. 纯本地 demo」演示，功能完全一样，只是没有 Dify 那层编排界面。

## 0. 前置：Docker

| 系统 | 做法 |
| --- | --- |
| Windows 10/11 | BIOS 打开 VT-x/SVM → `wsl --install` → 重启 → 装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，后端选 WSL2 |
| macOS | 装 Docker Desktop（Apple Silicon 原生） |
| Linux | `curl -fsSL https://get.docker.com \| sh`，然后 `sudo usermod -aG docker $USER` |

验证：

```bash
docker version && docker compose version
```

## 1. 先起 seekdb

Dify 需要 2881 端口上的 MySQL 兼容库。两种都行：

```bash
# 方式一：本机已有 seekdb（服务器模式）
mysql -h127.0.0.1 -P2881 -uroot -e 'select version();'

# 方式二：用 pyseekdb 的嵌入式模式（不需要独立进程，但 Dify 只能走服务器模式，
#         所以更推荐把 seekdb 起成服务器模式：/seekdb_workspace/scripts/start_observer.sh）
```

## 2. 拉 Dify 并改配置

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
```

把下面几行写进 `.env`（**替换**原有的同名项，不是追加）：

```dotenv
# 元数据库：用 seekdb（MySQL 协议）
DB_TYPE=mysql
DB_USERNAME=root
DB_PASSWORD=
DB_HOST=seekdb
DB_PORT=2881
DB_DATABASE=test

# 向量库：还是 seekdb（Dify ≥ 1.10.1 才有 oceanbase 这个 vector store）
VECTOR_STORE=oceanbase
OCEANBASE_VECTOR_HOST=seekdb
OCEANBASE_VECTOR_USER=root

# 只起 seekdb 这一个附加服务
COMPOSE_PROFILES=seekdb
```

> 如果你已经有独立的 seekdb / OceanBase，把 `DB_HOST` / `OCEANBASE_VECTOR_HOST` 改成它的地址，
> 并把 `COMPOSE_PROFILES` 里去掉 `seekdb`，就不用让 compose 起库了。
> Linux 上容器访问宿主机用 `DB_HOST=host.docker.internal` 时，需要在 compose 里加
> `extra_hosts: ["host.docker.internal:host-gateway"]`。

## 3. 起服务

```bash
docker compose up -d
docker compose ps          # 等 api / worker / web / plugin_daemon / seekdb 都 Up
docker compose logs -f api | grep -m1 "Database migration successful"
```

打开 <http://localhost/install> 建管理员账号，然后在「设置 → 模型供应商」里配一个模型
（通义千问 / DeepSeek / 任意 OpenAI 兼容端点都行）。

## 4. 起我们的 zoo service

```bash
cd <本仓库>
pip install -r requirements.txt
LLM_MODEL=/path/to/Qwen2.5-7B-Instruct bash scripts/start.sh   # 默认 0.0.0.0:8077
```

没有本地模型就直接接线上模型：

```bash
LLM_BACKEND=openai \
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
OPENAI_API_KEY=sk-xxx LLM_MODEL=qwen-plus \
bash scripts/start.sh
```

## 5. 导入 Chatflow

Dify → 「创建空白应用」→「导入 DSL 文件」→ 选 `dify/vector-zoo.dsl.yml`。

然后改两处：

1. **环境变量** `ZOO_API` → `http://host.docker.internal:8077`（Docker Desktop 默认可用；Linux 换成宿主机内网 IP）；
2. **三个 LLM 节点**（② 读题 / ⑤ 撰写图鉴）→ 重新选你已配置的模型。

输入「冰箱 × 蝴蝶」试一发。

## 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `docker compose up` 卡在 pull | 镜像源慢 | 配 registry mirror，或改用国内镜像加速 |
| api 起不来，日志连不上 mysql | seekdb 没起 / 端口不通 | `docker compose logs seekdb`，确认 2881 可连 |
| ④ 节点 500 / 连接超时 | 容器访问不到宿主的 8077 | 改 `ZOO_API` 为宿主机内网 IP；确认 `scripts/start.sh` 监听 `0.0.0.0` |
| ⑦ 返回 404 token 过期 | forge 与 commit 间隔 > 1 小时 | 重跑一次 |
| 导入后 LLM 节点红色 | 工作区没装对应模型供应商 | 点开节点重选模型 |

## 为什么让 seekdb 同时当元数据库和向量库

Dify 默认要 PostgreSQL + Redis + 一个向量库（Weaviate/Qdrant/…）。把元数据库和向量库都换成
seekdb 之后：**一份数据、一套备份、一个连接串**，而且知识库检索可以直接吃到 seekdb 的
向量 + 全文混合能力。这也是 `docs/architecture.md` 里"一个库顶三个组件"的由来。
