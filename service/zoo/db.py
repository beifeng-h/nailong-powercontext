"""seekdb 访问层：建表、写入、KNN 亲缘、混合检索、生态统计。

所有 SQL 都集中在 ZooDB 里，方便在 README / 文档里逐条展示"数据库真的在干活"。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

DSN = dict(
    host=os.getenv("SEEKDB_HOST", "127.0.0.1"),
    port=int(os.getenv("SEEKDB_PORT", "2881")),
    user=os.getenv("SEEKDB_USER", "root"),
    password=os.getenv("SEEKDB_PASSWORD", ""),
    database=os.getenv("SEEKDB_DB", "vector_zoo"),
    charset="utf8mb4",
    autocommit=True,
    cursorclass=DictCursor,
)

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "sql", "schema.sql")


def vec_literal(vec: list[float]) -> str:
    """Python list -> seekdb VECTOR 字面量 '[0.1,0.2,...]'。"""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def parse_vec(raw: Any) -> list[float]:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "ignore")
    if isinstance(raw, str):
        return [float(x) for x in re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", raw)]
    return list(raw)


def _json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "ignore")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


class ZooDB:
    def __init__(self, dsn: dict | None = None):
        self.dsn = dict(DSN if dsn is None else dsn)

    # ---------- 基础设施 ----------
    def conn(self, with_db: bool = True):
        dsn = dict(self.dsn)
        if not with_db:
            dsn.pop("database", None)
        return pymysql.connect(**dsn)

    def init_schema(self) -> None:
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if not ln.strip().startswith("--")]
        sql = "\n".join(lines)
        stmts = [s.strip() for s in sql.split(";") if s.strip()]
        with self.conn(with_db=False) as c, c.cursor() as cur:
            for s in stmts:
                cur.execute(s)

    def ping(self) -> dict:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT VERSION() AS v, NOW() AS t")
            row = cur.fetchone()
            cur.execute("SHOW INDEX FROM creatures")
            idx = cur.fetchall()
        return {"version": row["v"], "now": str(row["t"]),
                "indexes": [{"name": r["Key_name"], "type": r["Index_type"]} for r in idx]}

    # ---------- 写入 ----------
    def insert_creature(self, rec: dict) -> dict:
        sql = """
            INSERT INTO creatures
              (code, name, latin, tagline, seeds, genome, axes, traits, lore,
               rarity, novelty, parents, generation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id),0)+1 AS nid FROM creatures")
            nid = int(cur.fetchone()["nid"])
            code = f"ZK-{nid:04d}"
            cur.execute(sql, (
                code,
                rec["name"],
                rec.get("latin", ""),
                rec.get("tagline", ""),
                json.dumps(rec.get("seeds", []), ensure_ascii=False),
                vec_literal(rec["genome"]),
                json.dumps(rec.get("axes", {}), ensure_ascii=False),
                json.dumps(rec.get("traits", {}), ensure_ascii=False),
                rec.get("lore", ""),
                rec.get("rarity", "普通"),
                float(rec.get("novelty", 0.0)),
                json.dumps(rec.get("parents", []), ensure_ascii=False),
                int(rec.get("generation", 0)),
            ))
            new_id = cur.lastrowid
        return {"id": new_id, "code": code}

    # ---------- 邻居 / 亲缘 ----------
    def nearest(self, genome: list[float], k: int = 5, exclude_id: int | None = None) -> list[dict]:
        where, args = "", []
        if exclude_id:
            where, args = "WHERE id <> %s", [exclude_id]
        sql = f"""
            SELECT id, code, name, latin, tagline, rarity, generation, novelty,
                   seeds, traits, axes, parents,
                   COSINE_DISTANCE(genome, %s) AS dist
            FROM creatures
            {where}
            ORDER BY dist APPROXIMATE
            LIMIT %s
        """
        with self.conn() as c, c.cursor() as cur:
            cur.execute(sql, [vec_literal(genome), *args, int(k)])
            rows = cur.fetchall()
        for r in rows:
            r["dist"] = float(r["dist"])
            r["seeds"] = _json(r["seeds"])
            r["traits"] = _json(r["traits"])
            r["axes"] = _json(r.get("axes"))
            r["parents"] = _json(r["parents"])
        return rows

    def duplicate_of(self, genome: list[float], threshold: float = 0.03) -> dict | None:
        """同一个词组合只允许诞生一次：距离足够近就返回已有物种。"""
        rows = self.nearest(genome, k=1)
        if rows and rows[0]["dist"] <= threshold:
            return rows[0]
        return None

    # ---------- 混合检索 ----------
    def hybrid_search(self, q: str, qvec: list[float], k: int = 12,
                      habitat: str | None = None, rarity: str | None = None) -> dict:
        where, args = [], []
        if habitat:
            where.append("traits->>'$.habitat' = %s")
            args.append(habitat)
        if rarity:
            where.append("rarity = %s")
            args.append(rarity)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        inner = f"""
            SELECT id, code, name, latin, tagline, rarity, generation, novelty,
                   seeds, traits, axes, parents, lore,
                   COSINE_DISTANCE(genome, %s) AS dist,
                   MATCH(name, latin, tagline, lore) AGAINST(%s) AS text_score
            FROM creatures
            {where_sql}
        """
        sql = f"""
            SELECT *, 0.62 * (1 - dist) + 0.38 * LEAST(IFNULL(text_score, 0), 1) AS score
            FROM ({inner}) ranked
            ORDER BY score DESC
            LIMIT %s
        """
        with self.conn() as c, c.cursor() as cur:
            cur.execute(sql, [vec_literal(qvec), q, *args, int(k)])
            rows = cur.fetchall()
        for r in rows:
            r["dist"] = float(r["dist"])
            r["text_score"] = float(r["text_score"] or 0)
            r["score"] = float(r["score"])
            r["seeds"] = _json(r["seeds"])
            r["traits"] = _json(r["traits"])
            r["axes"] = _json(r.get("axes"))
            r["parents"] = _json(r["parents"])
        return {"results": rows, "sql": re.sub(r"\s+", " ", sql).strip()}

    # ---------- 生态统计 ----------
    def stats(self) -> dict:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT COUNT(*) total, AVG(generation) avg_gen, SUM(generation>0) bred, "
                        "AVG(novelty) avg_novelty FROM creatures")
            base = cur.fetchone()
            cur.execute("SELECT rarity, COUNT(*) c FROM creatures GROUP BY rarity ORDER BY c DESC")
            rarities = cur.fetchall()
            cur.execute("SELECT traits->>'$.habitat' h, COUNT(*) c FROM creatures "
                        "GROUP BY h ORDER BY c DESC")
            habitats = cur.fetchall()
            cur.execute("SELECT genome FROM creatures LIMIT 400")
            vecs = [parse_vec(r["genome"]) for r in cur.fetchall()]

        import numpy as np
        diversity, avg_nn, endangered = 0.0, 0.0, 0
        if len(vecs) > 1:
            m = np.asarray(vecs, dtype=np.float32)
            m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
            sim = m @ m.T
            dist = 1.0 - sim
            np.fill_diagonal(dist, np.inf)
            nearest = dist.min(axis=1)
            avg_nn = round(float(nearest.mean()), 4)
            endangered = int((nearest > 0.9).sum())
            iu = np.triu_indices(len(vecs), k=1)
            diversity = round(float(dist[iu].mean()), 4)

        return {
            "total": int(base["total"] or 0),
            "avg_generation": round(float(base["avg_gen"] or 0), 2),
            "bred": int(base["bred"] or 0),
            "avg_novelty": round(float(base["avg_novelty"] or 0), 4),
            "avg_nearest": avg_nn,
            "rarities": {r["rarity"]: int(r["c"]) for r in rarities},
            "habitats": [{"habitat": h["h"], "count": int(h["c"])} for h in habitats],
            "endangered": endangered,
            "diversity": diversity,
        }

    def set_rarity(self, cid: int, rarity: str) -> None:
        with self.conn() as c, c.cursor() as cur:
            cur.execute(
                "UPDATE creatures SET rarity=%s, traits=JSON_SET(traits, '$.rarity', %s) WHERE id=%s",
                [rarity, rarity, int(cid)],
            )

    def recompute_rarity(self) -> dict[int, str]:
        """按"新颖度"在全园的分位重排稀有度。

        新物种入库会挤动别人的稀有度，这也是玩法的一部分：
        越不像别人越稀有；园子越挤，传说越难。
        """
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT id, novelty, rarity FROM creatures ORDER BY novelty DESC, id ASC")
            rows = cur.fetchall()
        n = len(rows)
        out: dict[int, str] = {}
        for i, r in enumerate(rows):
            q = i / n if n else 1.0
            rarity = ("传说" if q < 0.12 else "稀有" if q < 0.34
                      else "少见" if q < 0.67 else "常见")
            cid = int(r["id"])
            out[cid] = rarity
            if r.get("rarity") != rarity:
                self.set_rarity(cid, rarity)
        return out

    def list_creatures(self, limit: int = 24) -> list[dict]:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("""
                SELECT id, code, name, latin, tagline, rarity, generation, novelty,
                       seeds, traits, axes, parents, created_at
                FROM creatures ORDER BY id DESC LIMIT %s
            """, [int(limit)])
            rows = cur.fetchall()
        for r in rows:
            for f in ("seeds", "traits", "axes", "parents"):
                r[f] = _json(r[f])
            r["created_at"] = str(r["created_at"])
        return rows

    def get(self, cid: int) -> dict | None:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT * FROM creatures WHERE id=%s", [cid])
            r = cur.fetchone()
        if not r:
            return None
        for f in ("seeds", "traits", "axes", "parents"):
            r[f] = _json(r[f])
        r.pop("genome", None)
        r["created_at"] = str(r["created_at"])
        return r

    def kin_of(self, cid: int, k: int = 4) -> list[dict]:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT genome FROM creatures WHERE id=%s", [cid])
            row = cur.fetchone()
        if not row:
            return []
        return self.nearest(parse_vec(row["genome"]), k=k, exclude_id=cid)

    def novelty_percentile(self, novelty: float) -> float:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT COUNT(*) total, SUM(novelty < %s) below FROM creatures", [novelty])
            row = cur.fetchone()
        total = int(row["total"] or 0)
        return round(float(row["below"] or 0) / total, 3) if total else 0.5
