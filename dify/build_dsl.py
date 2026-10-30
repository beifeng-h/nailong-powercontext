"""生成 Dify Chatflow DSL（vector-zoo.dsl.yml）。

手写 YAML 很容易在代码节点里踩转义坑，所以 DSL 由这个脚本生成：
    python dify/build_dsl.py
产物：dify/vector-zoo.dsl.yml（可直接在 Dify「导入 DSL」）
"""
from __future__ import annotations

import pathlib

import yaml

HERE = pathlib.Path(__file__).resolve().parent

CODE_PARSE = '''import json
import re


def main(text: str) -> dict:
    """把 LLM 输出的 JSON 抠出来，失败就退回默认母本。"""
    m = re.search(r"\\{.*\\}", text or "", re.S)
    data = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except Exception:
            data = {}
    a = str(data.get("a") or "西瓜").strip()[:12]
    b = str(data.get("b") or "章鱼").strip()[:12]
    try:
        ratio = float(data.get("ratio") or 0.5)
    except Exception:
        ratio = 0.5
    ratio = min(0.85, max(0.15, ratio))
    return {"a": a, "b": b, "ratio": ratio}
'''

CODE_PACK = '''import json
import re


def main(text: str, forge: str) -> dict:
    """解析图鉴 JSON，并把 forge 返回的 token 一起打包给落库节点。"""
    m = re.search(r"\\{.*\\}", text or "", re.S)
    prof = {}
    if m:
        try:
            prof = json.loads(m.group(0))
        except Exception:
            prof = {}
    if not prof.get("name"):
        prof = {"name": "无名物种", "latin": "", "tagline": "", "appearance": "",
                "habitat": "", "diet": "", "behavior": "", "weakness": "",
                "lore": (text or "")[:200]}
    token = ""
    try:
        token = json.loads(forge or "{}").get("token", "")
    except Exception:
        token = ""
    return {"token": token,
            "profile_json": json.dumps(prof, ensure_ascii=False),
            "name": prof.get("name", "")}
'''

CODE_RENDER = '''import json


def main(body: str) -> dict:
    """落库接口已经返回排好版的 Markdown 卡片，直接透传。"""
    try:
        data = json.loads(body or "{}")
        md = data.get("card_markdown") or json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        md = body or ""
    return {"markdown": md}
'''

SYSTEM_SEEDS = (
    "你是『向量动物园』的接待员。用户会说自己想造一只什么样的物种。\n"
    "请从用户的话里挑出两个母本词（名词，2-6 个字，越反差越好），并给出混合比例 ratio"
    "（0.15-0.85，代表母本 A 的占比）。\n"
    "如果用户只给了一个词，你补一个反差极大的名词；如果用户给了三个以上，只保留最有画面感的两个。\n"
    '只输出 JSON，不要解释：{"a":"母本A","b":"母本B","ratio":0.5}'
)

SYSTEM_CREATURE = (
    "你是『向量动物园』的造物主。你会拿到两个母本词、一份由基因组向量投影得到的表型"
    "（8 条 0-100 的基因轴），以及园里基因最接近的几位亲戚。\n"
    "请创造一只既继承两个母本气质、又在设定上明显区别于亲戚的新物种。"
    "语气要像一本正经的博物志，带一点冷幽默。\n"
    "只输出 JSON，不要任何解释或代码块。"
)

USER_CREATURE = """母本 A：{{#1000000000003.a#}}
母本 B：{{#1000000000003.b#}}

seekdb 返回的基因组与亲缘信息（JSON）：
{{#1000000000004.body#}}

请输出严格 JSON：
{"name":"不超过6个汉字，有画面感，不要直接拼接两个母本词",
 "latin":"两段式拉丁学名",
 "tagline":"一句话，20字以内",
 "appearance":"外形，40-60字",
 "habitat":"栖息地，12字以内",
 "diet":"食性，12字以内",
 "behavior":"习性，25字以内",
 "weakness":"弱点，20字以内",
 "lore":"图鉴正文，80-120字，像博物志词条，结尾带一句冷幽默"}"""


def node(nid, ntype, title, x, data, width=244, height=98, desc=""):
    return {
        "id": str(nid),
        "type": "custom",
        "position": {"x": x, "y": 320},
        "positionAbsolute": {"x": x, "y": 320},
        "width": width,
        "height": height,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {"type": ntype, "title": title, "desc": desc, **data},
    }


def edge(a, b, ta, tb):
    return {
        "id": f"{a}-source-{b}-target",
        "source": str(a),
        "sourceHandle": "source",
        "target": str(b),
        "targetHandle": "target",
        "type": "custom",
        "zIndex": 0,
        "selected": False,
        "data": {"sourceType": ta, "targetType": tb, "isInIteration": False, "isInLoop": False},
    }


def build() -> dict:
    nodes = [
        node(1000000000001, "start", "① 对话入口", 40, {
            "variables": [],
        }, height=90, desc="用户输入一句话，比如「做个会飞的西瓜和章鱼的混种」"),
        node(1000000000002, "llm", "② 读题：挑两个母本", 330, {
            "model": {"provider": "langgenius/tongyi/tongyi", "name": "qwen-plus",
                      "mode": "chat", "completion_params": {"temperature": 0.7}},
            "prompt_template": [
                {"role": "system", "text": SYSTEM_SEEDS},
                {"role": "user", "text": "{{#sys.query#}}"},
            ],
            "variables": [],
            "context": {"enabled": False, "variable_selector": []},
            "vision": {"enabled": False},
        }, desc="从自然语言里挑出两个母本词和混合比例"),
        node(1000000000003, "code", "③ 解析意图", 620, {
            "code": CODE_PARSE,
            "code_language": "python3",
            "variables": [{"variable": "text", "value_selector": ["1000000000002", "text"]}],
            "outputs": {"a": {"type": "string", "children": None},
                        "b": {"type": "string", "children": None},
                        "ratio": {"type": "number", "children": None}},
        }, height=110),
        node(1000000000004, "http-request", "④ 造基因组 + 亲缘检索（seekdb）", 910, {
            "method": "POST",
            "url": "{{#env.ZOO_API#}}/api/dify/forge",
            "authorization": {"type": "no-auth"},
            "headers": "Content-Type: application/json",
            "params": "",
            "body": {
                "type": "json",
                "data": '{"a": "{{#1000000000003.a#}}", "b": "{{#1000000000003.b#}}", '
                        '"ratio": {{#1000000000003.ratio#}}, "mutation": 0.08}',
            },
            "timeout": {"connect": 10, "read": 60, "write": 30},
            "retry_config": {"enabled": False, "max_retries": 1, "retry_interval": 1000},
        }, height=120, desc="服务端把两个词 embedding 后混合成基因组，再用 seekdb 的 HNSW 找出最近的亲戚、"
                             "算出新颖度与稀有度"),
        node(1000000000005, "llm", "⑤ 撰写图鉴", 1200, {
            "model": {"provider": "langgenius/tongyi/tongyi", "name": "qwen-plus",
                      "mode": "chat", "completion_params": {"temperature": 0.9}},
            "prompt_template": [
                {"role": "system", "text": SYSTEM_CREATURE},
                {"role": "user", "text": USER_CREATURE},
            ],
            "variables": [],
            "context": {"enabled": False, "variable_selector": []},
            "vision": {"enabled": False},
        }, desc="根据基因轴和亲戚，写名字、习性和图鉴正文"),
        node(1000000000006, "code", "⑥ 打包 token + 图鉴", 1490, {
            "code": CODE_PACK,
            "code_language": "python3",
            "variables": [
                {"variable": "text", "value_selector": ["1000000000005", "text"]},
                {"variable": "forge", "value_selector": ["1000000000004", "body"]},
            ],
            "outputs": {"token": {"type": "string", "children": None},
                        "profile_json": {"type": "string", "children": None},
                        "name": {"type": "string", "children": None}},
        }, height=110),
        node(1000000000007, "http-request", "⑦ 落库（seekdb）", 1780, {
            "method": "POST",
            "url": "{{#env.ZOO_API#}}/api/dify/commit",
            "authorization": {"type": "no-auth"},
            "headers": "",
            "params": "",
            "body": {
                "type": "x-www-form-urlencoded",
                "data": [
                    {"key": "token", "type": "text", "value": "{{#1000000000006.token#}}"},
                    {"key": "profile_json", "type": "text",
                     "value": "{{#1000000000006.profile_json#}}"},
                ],
            },
            "timeout": {"connect": 10, "read": 30, "write": 30},
            "retry_config": {"enabled": False, "max_retries": 1, "retry_interval": 1000},
        }, height=120, desc="用 token 把图鉴写进 seekdb 的 creatures 表（向量 + JSON + 全文一次性落库）"),
        node(1000000000008, "code", "⑧ 渲染图鉴卡片", 2070, {
            "code": CODE_RENDER,
            "code_language": "python3",
            "variables": [{"variable": "body", "value_selector": ["1000000000007", "body"]}],
            "outputs": {"markdown": {"type": "string", "children": None}},
        }, height=110),
        node(1000000000009, "answer", "⑨ 图鉴出炉", 2360, {
            "answer": "{{#1000000000008.markdown#}}",
            "variables": [],
        }, height=90),
    ]

    chain = [
        (1000000000001, 1000000000002, "start", "llm"),
        (1000000000002, 1000000000003, "llm", "code"),
        (1000000000003, 1000000000004, "code", "http-request"),
        (1000000000004, 1000000000005, "http-request", "llm"),
        (1000000000005, 1000000000006, "llm", "code"),
        (1000000000006, 1000000000007, "code", "http-request"),
        (1000000000007, 1000000000008, "http-request", "code"),
        (1000000000008, 1000000000009, "code", "answer"),
    ]

    return {
        "version": "0.6.0",
        "kind": "app",
        "app": {
            "name": "向量动物园 Vector Zoo",
            "description": "输入两个词，让它们在向量空间里交配，生出一只新物种并写进 seekdb 图鉴。"
                           "基因组、亲缘、稀有度全部由 seekdb 的向量检索决定，Dify 负责理解意图与撰写图鉴。",
            "icon": "🧬",
            "icon_type": "emoji",
            "icon_background": "#0A0C10",
            "mode": "advanced-chat",
            "use_icon_as_answer_icon": False,
        },
        "dependencies": [],
        "workflow": {
            "conversation_variables": [],
            "environment_variables": [{
                "id": "6f0f0e8e-1a2b-4c3d-9e8f-000000000001",
                "name": "ZOO_API",
                "value": "http://host.docker.internal:8077",
                "value_type": "string",
                "description": "zoo service 地址。Dify 跑在 Docker 里用 host.docker.internal；本机直连用 127.0.0.1",
            }],
            "features": {
                "file_upload": {"enabled": False},
                "opening_statement": "说出两个八竿子打不着的词，比如「西瓜 × 章鱼」「台风 × 仓鼠」，"
                                     "我来让它们在向量空间里交配。",
                "retriever_resource": {"enabled": False},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False},
                "suggested_questions": ["西瓜 × 章鱼", "快递箱 × 萤火虫", "月亮 × 榴莲"],
                "suggested_questions_after_answer": {"enabled": False},
                "text_to_speech": {"enabled": False, "language": "", "voice": ""},
            },
            "graph": {
                "nodes": nodes,
                "edges": [edge(*e) for e in chain],
                "viewport": {"x": 0, "y": 0, "zoom": 0.5},
            },
        },
    }


if __name__ == "__main__":
    dsl = build()
    out = HERE / "vector-zoo.dsl.yml"
    out.write_text(yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False, width=1000),
                   encoding="utf-8")
    again = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert again["workflow"]["graph"]["nodes"], "DSL 生成失败"
    print("written", out, "nodes", len(again["workflow"]["graph"]["nodes"]),
          "edges", len(again["workflow"]["graph"]["edges"]))
