"""向量动物园 HTTP 服务。

两层用法：
1) 本地独立 demo：/api/synthesize /api/search /api/stats 直接给 web/ 用；
2) Dify 工具层：/api/embed /api/genome /api/kinship /api/dify/forge /api/dify/commit
   给 Dify 的 HTTP 请求节点逐段调用（见 dify/vector-zoo.dsl.yml）。
"""
from __future__ import annotations

import json
import os
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from zoo import genome as G
from zoo.db import ZooDB
from zoo.domain import ZooKeeper
from zoo.llm import LLM

app = FastAPI(title="Vector Zoo", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db = ZooDB()
keeper = ZooKeeper(db=db, llm=LLM())
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")


# ---------- Dify 工具节点用的原子接口 ----------
class EmbedIn(BaseModel):
    texts: list[str]


@app.post("/api/embed")
def api_embed(body: EmbedIn):
    """文本 -> 向量，供 Dify 的代码节点做基因混合。"""
    vecs = G.embed([t.strip() for t in body.texts if t.strip()])
    return {"vectors": vecs, "dim": len(vecs[0]) if vecs else 0}


class GenomeIn(BaseModel):
    a: list[float]
    b: list[float]
    ratio: float = 0.5
    mutation: float = 0.08


@app.post("/api/genome")
def api_genome(body: GenomeIn):
    """两个向量 -> 一个新基因组 + 基因轴（纯数学，不调 LLM）。"""
    g = G.mix(body.a, body.b, ratio=body.ratio, mutation=body.mutation)
    vec = g.tolist()
    return {"genome": vec, "axes": G.axes_of(vec), "digest": G.gene_digest(vec)}


class KinshipIn(BaseModel):
    genome: list[float]
    k: int = 5


@app.post("/api/kinship")
def api_kinship(body: KinshipIn):
    """基因组 -> 最近的亲戚 + 新颖度。这一步就是 seekdb 的 HNSW KNN。"""
    kin = db.nearest(body.genome, k=body.k)
    novelty = float(kin[0]["dist"]) if kin else 1.0
    pct = db.novelty_percentile(novelty)
    return {"kin": kin, "novelty": round(novelty, 4),
            "percentile": pct, "rarity": ZooKeeper._rarity(pct),
            "query_sql": ("SELECT id, name, COSINE_DISTANCE(genome, :vec) AS dist "
                          "FROM creatures ORDER BY dist APPROXIMATE LIMIT %d" % body.k)}


# ---------- 本地 demo 用的编排接口 ----------
class SynthIn(BaseModel):
    a: str
    b: str
    ratio: float = 0.5
    mutation: float = 0.08
    force: bool = False


@app.post("/api/synthesize")
def api_synthesize(body: SynthIn):
    if not body.a.strip() or not body.b.strip():
        raise HTTPException(400, "两个母本词都要填")
    return keeper.synthesize(body.a, body.b, body.ratio, body.mutation, body.force)


class BreedIn(BaseModel):
    a: int
    b: int
    mutation: float = 0.12


@app.post("/api/breed")
def api_breed(body: BreedIn):
    try:
        return keeper.breed(body.a, body.b, body.mutation)
    except ValueError as e:
        raise HTTPException(404, str(e))


class SearchIn(BaseModel):
    q: str
    habitat: str | None = None
    rarity: str | None = None
    k: int = 8


@app.post("/api/search")
def api_search(body: SearchIn):
    q = body.q.strip()
    if not q:
        raise HTTPException(400, "查询不能为空")
    qvec = G.embed([q])[0]
    return db.hybrid_search(q, qvec, k=body.k, habitat=body.habitat, rarity=body.rarity)


@app.get("/api/creatures")
def api_list(limit: int = 24):
    return {"items": db.list_creatures(limit)}


@app.get("/api/creatures/{cid}")
def api_get(cid: int):
    rec = db.get(cid)
    if not rec:
        raise HTTPException(404, "没有这个物种")
    return rec


@app.get("/api/creatures/{cid}/kin")
def api_kin(cid: int, k: int = 4):
    return {"kin": db.kin_of(cid, k)}


@app.get("/api/stats")
def api_stats():
    return db.stats()


@app.get("/api/health")
def api_health():
    return {"seekdb": db.ping(), "llm": keeper.llm.backend, "model": keeper.llm.model_id}


# ---------- Dify Chatflow 专用的两阶段接口 ----------
# Dify 的 HTTP 节点不方便来回传 512 维数组，所以：
#   forge  -> 服务端算好基因组/基因轴/亲缘，返回 token（暂存）
#   commit -> Dify 的 LLM 节点写完图鉴后，凭 token 落库
PENDING: dict[str, dict] = {}
PENDING_TTL = 3600


class ForgeIn(BaseModel):
    a: str
    b: str
    ratio: float = 0.5
    mutation: float = 0.08


def _card_md(rec: dict) -> str:
    t = rec.get("traits", {})
    axes = rec.get("axes", {})
    axes_txt = " · ".join(f"{k}{v}" for k, v in axes.items())
    kin_txt = "\n".join(
        f"- {k['code']} {k['name']}（基因距离 {k['dist']:.3f}）" for k in rec.get("kin", [])
    ) or "- 暂无"
    return (
        f"### {rec.get('code','')} · {rec.get('name','')}\n\n"
        f"*{rec.get('latin','')}*\n\n"
        f"> {rec.get('tagline','')}\n\n"
        f"**稀有度** {rec.get('rarity','')}　**基因指纹** G-{rec.get('genome_digest','')}\n\n"
        f"**母本** {' × '.join(rec.get('seeds') or [])}\n\n"
        f"**基因轴** {axes_txt}\n\n"
        f"{rec.get('lore','')}\n\n"
        f"| 项目 | 内容 |\n| --- | --- |\n"
        f"| 栖息地 | {t.get('habitat','-')} |\n"
        f"| 食性 | {t.get('diet','-')} |\n"
        f"| 习性 | {t.get('behavior','-')} |\n"
        f"| 弱点 | {t.get('weakness','-')} |\n\n"
        f"**亲缘最近的物种**\n\n{kin_txt}"
    )


@app.post("/api/dify/forge")
def api_forge(body: ForgeIn):
    a, b = body.a.strip(), body.b.strip()
    if not a or not b:
        raise HTTPException(400, "两个母本词都要填")
    vecs = G.embed([a, b])
    gen = G.mix(vecs[0], vecs[1], ratio=body.ratio, mutation=body.mutation, seed=f"{a}|{b}")
    gen_list = gen.tolist()
    dup = db.duplicate_of(gen_list)
    kin = db.nearest(gen_list, k=4)
    novelty = float(kin[0]["dist"]) if kin else 1.0
    pct = db.novelty_percentile(novelty)
    rarity = ZooKeeper._rarity(pct)
    axes = G.axes_of(gen_list)
    token = uuid.uuid4().hex[:12]
    PENDING[token] = {"genome": gen_list, "seeds": [a, b], "axes": axes,
                      "novelty": novelty, "pct": pct, "rarity": rarity,
                      "kin": kin, "ts": time.time()}
    return {
        "token": token, "a": a, "b": b, "axes": axes,
        "axes_text": " / ".join(f"{k}{v}" for k, v in axes.items()),
        "kin": [{"code": k["code"], "name": k["name"], "dist": round(k["dist"], 4)} for k in kin],
        "novelty": round(novelty, 4), "percentile": pct, "rarity": rarity,
        "duplicate": ({"code": dup["code"], "name": dup["name"]} if dup else None),
        "note": "把这段 JSON 交给 LLM 写图鉴，然后带上 token 调 /api/dify/commit",
    }


@app.post("/api/dify/commit")
async def api_commit(request: Request):
    ctype = (request.headers.get("content-type") or "").lower()
    if "json" in ctype:
        payload = await request.json()
        token = payload.get("token")
        profile = payload.get("profile") or json.loads(payload.get("profile_json") or "{}")
    else:
        form = await request.form()
        token = form.get("token")
        profile = json.loads(form.get("profile_json") or "{}")

    slot = PENDING.get(token or "")
    if not slot or time.time() - slot["ts"] > PENDING_TTL:
        raise HTTPException(404, "token 不存在或已过期，请重新 forge")
    PENDING.pop(token, None)

    # 同一个基因组只允许诞生一次（和本地 demo 的行为一致）
    dup = db.duplicate_of(slot["genome"])
    if dup:
        card = _card_md({**dup, "kin": slot["kin"],
                         "genome_digest": G.gene_digest(slot["genome"])})
        return {"status": "duplicate", "id": dup["id"], "code": dup["code"],
                "name": dup["name"], "rarity": dup["rarity"],
                "message": f"这个组合已经诞生过了：{dup['code']} {dup['name']}",
                "card_markdown": f"> 这个组合已经诞生过了：{dup['code']} {dup['name']}\n\n{card}"}

    rec = {
        "name": profile.get("name") or "无名物种",
        "latin": profile.get("latin", ""),
        "tagline": profile.get("tagline", ""),
        "seeds": slot["seeds"],
        "genome": slot["genome"],
        "axes": slot["axes"],
        "traits": {
            "habitat": profile.get("habitat", ""),
            "diet": profile.get("diet", ""),
            "behavior": profile.get("behavior", ""),
            "weakness": profile.get("weakness", ""),
            "appearance": profile.get("appearance", ""),
            "rarity": slot["rarity"],
        },
        "lore": profile.get("lore", ""),
        "rarity": slot["rarity"],
        "novelty": slot["novelty"],
        "parents": [],
        "generation": 0,
    }
    saved = db.insert_creature(rec)
    rec.update(saved)
    # 入库后按全园分位重排稀有度
    rarities = db.recompute_rarity()
    rec["rarity"] = rarities.get(rec["id"], rec["rarity"])
    rec["traits"]["rarity"] = rec["rarity"]
    rec["genome_digest"] = G.gene_digest(slot["genome"])
    rec["kin"] = slot["kin"]
    rec["novelty_pct"] = slot["pct"]
    return {
        **{k: rec[k] for k in ("id", "code", "name", "latin", "tagline", "rarity",
                               "novelty", "genome_digest", "lore", "traits", "axes", "seeds")},
        "card_markdown": _card_md(rec),
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
