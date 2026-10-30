# 在 Dify 里跑起来（约 5 分钟）

`vector-zoo.dsl.yml` 是一个 Dify **Chatflow（advanced-chat）**应用，9 个节点，导入即用。

## 1. 先起 zoo service

DSL 里的 HTTP 节点要访问一个本地服务（负责 embedding、基因组、seekdb 读写）：

```bash
cd vector_zoo
pip install -r requirements.txt
LLM_MODEL=/path/to/Qwen2.5-7B-Instruct bash scripts/start.sh   # 默认监听 0.0.0.0:8077
```

服务起来后 `http://127.0.0.1:8077/api/health` 应该返回 seekdb 版本和模型信息。

## 2. 导入 DSL

Dify → 「创建应用」→「导入 DSL 文件」→ 选 `vector-zoo.dsl.yml`。

## 3. 改一个环境变量

应用 →「环境变量」→ `ZOO_API`：

| Dify 部署方式 | ZOO_API |
| --- | --- |
| Docker Compose（官方默认） | `http://host.docker.internal:8077` |
| 与本服务同机且同网络 | `http://127.0.0.1:8077` |
| Dify 在另一台机器 | `http://<本机内网 IP>:8077` |

> Linux 上的 Docker 如果 `host.docker.internal` 不通，把它换成宿主机内网 IP，或在 compose 里加
> `extra_hosts: ["host.docker.internal:host-gateway"]`。

## 4. 选模型

DSL 里三个 LLM 节点默认写的是 `langgenius/tongyi/tongyi` 的 `qwen-plus`。
如果你的工作区没装通义插件，点开每个 LLM 节点重新选一个你已配置的模型即可（推荐 qwen-plus / qwen-max / deepseek-chat）。

## 5. 开始玩

输入「西瓜 × 章鱼」「台风 × 仓鼠」「月亮 × 榴莲」，会依次走：

```
① 对话入口
② 读题：挑两个母本        ← LLM 解析自然语言
③ 解析意图                ← Code 节点兜底 JSON
④ 造基因组 + 亲缘检索      ← HTTP → seekdb（embedding 混合 + HNSW KNN + 稀有度）
⑤ 撰写图鉴                ← LLM 根据基因轴与亲戚写文案
⑥ 打包 token + 图鉴        ← Code 节点
⑦ 落库                    ← HTTP → seekdb（向量 + JSON + 全文一次写入）
⑧ 渲染图鉴卡片             ← Code 节点
⑨ 图鉴出炉                ← Answer
```

## 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| ④ 节点连接失败 | Dify 容器访问不到宿主服务 | 改 `ZOO_API` 为宿主内网 IP；确认服务监听 `0.0.0.0` |
| ⑤ 输出一堆解释而不是 JSON | 模型指令跟随较弱 | 换 qwen-plus 以上；或调低 temperature |
| ⑦ 返回 404 token 过期 | forge 与 commit 间隔超过 1 小时 | 重新跑一次 |
| 图鉴写进去了但中文乱码 | 数据库/连接字符集 | 用 DSL 默认的 `utf8mb4` 连接串，别改 |

## 为什么不全放在 Dify 里做？

- 512 维向量在 Dify 的节点之间来回传既慢又容易在 JSON body 里被转义搞坏，所以用 `forge → token → commit` 两段式；
- 基因组混合、KNN、稀有度这类"数据库侧"的逻辑放服务里，Dify 只负责它最擅长的两件事：**理解人话**和**写图鉴**；
- 这样 seekdb 的向量索引、全文索引、JSON 过滤都能被显式用到，而不是被包装成黑盒。
