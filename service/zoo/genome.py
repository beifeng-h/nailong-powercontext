"""基因组：词向量嵌入、双母本混合、突变、8 条基因轴的投影。

设计要点：
- 基因组就是一个 512 维向量，直接存进 seekdb 的 VECTOR 列；
- 亲缘、稀有度、杂交全部只依赖向量距离，不依赖 LLM 的"感觉"；
- 基因轴是把向量投影到 8 个固定方向上得到的"表型"，让雷达图有据可依。

嵌入模型用 BAAI/bge-small-zh-v1.5（CLS pooling + L2 归一化），
只用 transformers，不依赖 sentence-transformers，减少环境变量。
"""
from __future__ import annotations

import hashlib
import os

import numpy as np

EMB_MODEL = os.getenv("EMB_MODEL", "BAAI/bge-small-zh-v1.5")
AXIS_NAMES = ["攻击", "防御", "速度", "体型", "智慧", "毒性", "繁殖", "亲和"]
_BASIS: np.ndarray | None = None
_TOK = None
_MODEL = None


def _load_embedder():
    global _TOK, _MODEL
    if _MODEL is not None:
        return _TOK, _MODEL
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(int(os.getenv("EMB_THREADS", "16")))
    _TOK = AutoTokenizer.from_pretrained(EMB_MODEL)
    _MODEL = AutoModel.from_pretrained(EMB_MODEL)
    _MODEL.eval()
    return _TOK, _MODEL


def embed(texts: list[str]) -> list[list[float]]:
    import torch
    tok, model = _load_embedder()
    out: list[list[float]] = []
    with torch.inference_mode():
        for i in range(0, len(texts), 16):
            batch = texts[i:i + 16]
            enc = tok(batch, padding=True, truncation=True, max_length=128, return_tensors="pt")
            hidden = model(**enc).last_hidden_state[:, 0]  # bge 用 [CLS]
            hidden = torch.nn.functional.normalize(hidden, dim=-1)
            out += hidden.float().numpy().tolist()
    return out


def _basis(dim: int) -> np.ndarray:
    """固定随机正交基：同一维度下永远得到同样的 8 条轴。"""
    global _BASIS
    if _BASIS is not None and _BASIS.shape[1] == dim:
        return _BASIS
    rng = np.random.default_rng(20251030)
    m = rng.standard_normal((dim, 8))
    q, _ = np.linalg.qr(m)
    _BASIS = (q.T).astype(np.float32)  # (8, dim)
    return _BASIS


def axes_of(vec: list[float]) -> dict[str, int]:
    v = np.asarray(vec, dtype=np.float32)
    v = v / (np.linalg.norm(v) + 1e-9)
    proj = _basis(v.shape[0]) @ v
    vals = 1 / (1 + np.exp(-proj * 9.0))
    return {name: int(round(float(x) * 100)) for name, x in zip(AXIS_NAMES, vals)}


def mix(a: list[float], b: list[float], ratio: float = 0.5,
        mutation: float = 0.08, seed: str | None = None) -> np.ndarray:
    """两个母本向量按比例混合，再叠一层可复现的"突变噪声"。"""
    va, vb = np.asarray(a, np.float32), np.asarray(b, np.float32)
    va /= np.linalg.norm(va) + 1e-9
    vb /= np.linalg.norm(vb) + 1e-9
    r = float(min(max(ratio, 0.05), 0.95))
    g = r * va + (1 - r) * vb
    if mutation > 0:
        key = seed or (",".join(f"{x:.3f}" for x in va[:4]) + ",".join(f"{x:.3f}" for x in vb[:4]))
        h = int(hashlib.sha256(f"{key}|{mutation}".encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(h)
        noise = rng.standard_normal(g.shape).astype(np.float32)
        g = g + mutation * noise
    return (g / (np.linalg.norm(g) + 1e-9)).astype(np.float32)


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, np.float32), np.asarray(b, np.float32)
    return float(va @ vb / ((np.linalg.norm(va) * np.linalg.norm(vb)) + 1e-9))


def gene_digest(vec: list[float], n: int = 10) -> str:
    h = hashlib.sha256(",".join(f"{x:.4f}" for x in vec).encode()).hexdigest()
    return h[:n].upper()


def genetic_distance(a: list[float], b: list[float]) -> float:
    return 1.0 - cosine(a, b)
