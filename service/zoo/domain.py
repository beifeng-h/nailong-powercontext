"""领域逻辑：把「两个词」变成一只可入库的物种。"""
from __future__ import annotations

import json
import random
import threading
import time

from . import genome as G
from .db import ZooDB
from .llm import LLM, extract_json

SYSTEM = (
    "你是《向量动物园图鉴》的撰写者。文字风格：博物志的精确 + 冷幽默，短句，"
    "不要用『神秘的』『奇妙的』这类空形容词。"
    "必须只输出一个 JSON 对象，不要代码块、不要解释、不要多余字段。"
    "除 latin 外所有字段用简体中文。"
)

EXAMPLE = """【范例 1】
母本 A：火锅　母本 B：水母
基因轴（0-100）：攻击20 / 防御35 / 速度70 / 体型40 / 智慧55 / 毒性80 / 繁殖60 / 亲和30
输出：{"name":"麻辣浮游体","latin":"Medusa Sichuanensis","tagline":"在沸腾里优雅地漂着","appearance":"伞盖半透明，里面翻滚着红油，触手挂满花椒，游动时整只都在冒泡。","habitat":"温泉与老火锅店后厨","diet":"辣味浮游生物","behavior":"受惊时变成一锅红汤，趁观察者愣神卷走一片毛肚。","weakness":"遇清汤立即失去毒性","lore":"麻辣浮游体最早出现在一家火锅店的下水道里，靠锅底的辣椒素维持渗透压。它不捕食，只安静地漂着，等客人自己把毛肚掉进来。研究者试过清汤饲养，它在三分钟内褪成一张透明塑料袋。"}

【范例 2】
母本 A：旧键盘　母本 B：蒲公英
基因轴（0-100）：攻击10 / 防御45 / 速度30 / 体型20 / 智慧70 / 毒性5 / 繁殖90 / 亲和60
输出：{"name":"回车絮","latin":"Taraxacum Clavis","tagline":"按下去，就飘走一个念头","appearance":"键帽状的瘦果，缝隙里塞满灰尘与绒毛，敲击时会弹出一小团白色的种子。","habitat":"废弃工位与写字楼通风口","diet":"灰尘、碎屑与没保存的文档","behavior":"每到下班时间集体弹射，把种子撒进隔壁工位的键盘缝里。","weakness":"进水后彻底失灵","lore":"回车絮是办公室生态里最顽强的物种，靠人类打字的震动完成传粉。物业清理过三次，每次都从通风管道里长出新的。它唯一的天敌是保洁阿姨手里那罐压缩空气。"}
"""


def build_user_prompt(a: str, b: str, axes_s: str, kin_s: str, extra: str = "") -> str:
    return f"""【本次任务】
母本 A：{a}　母本 B：{b}
基因轴（0-100）：{axes_s}
最近亲戚：{kin_s}
{extra}
{EXAMPLE}
现在轮到这一只，规则：
- name 必须同时让人联想到 A 和 B，但不能出现 A、B 里的任何一个字（例如 A=西瓜、B=章鱼，就不要出现「西」「瓜」「章」「鱼」）；
- name 四个字以内最佳；appearance 40-60 字；lore 70-110 字，结尾一句冷幽默；
- habitat / diet / behavior / weakness 各不超过 25 字；
- 只输出 JSON，字段固定为：name, latin, tagline, appearance, habitat, diet, behavior, weakness, lore。"""


class ZooKeeper:
    def __init__(self, db: ZooDB | None = None, llm: LLM | None = None):
        self.db = db or ZooDB()
        self.llm = llm or LLM()
        self._gen_lock = threading.Lock()

    # ---------- 造物 ----------
    def synthesize(self, a: str, b: str, ratio: float = 0.5, mutation: float = 0.08,
                   force: bool = False) -> dict:
        t0 = time.time()
        a, b = a.strip(), b.strip()
        vecs = G.embed([a, b])
        gen = G.mix(vecs[0], vecs[1], ratio=ratio, mutation=mutation, seed=f"{a}|{b}")
        gen_list = gen.tolist()

        if not force:
            dup = self.db.duplicate_of(gen_list)
            if dup:
                return {"status": "duplicate", "creature": dup,
                        "message": f"这个组合已经诞生过了：{dup['code']} {dup['name']}"}

        kin = self.db.nearest(gen_list, k=4)
        novelty = float(kin[0]["dist"]) if kin else 1.0
        pct = self.db.novelty_percentile(novelty)
        rarity = self._rarity(pct)
        axes = G.axes_of(gen_list)

        profile, llm_ms, raw = self._profile(a, b, axes, kin)
        rec = {
            "name": profile.get("name") or f"{a[:2]}{b[-2:]}兽",
            "latin": profile.get("latin", ""),
            "tagline": profile.get("tagline", ""),
            "seeds": [a, b],
            "genome": gen_list,
            "axes": axes,
            "traits": {
                "habitat": profile.get("habitat", ""),
                "diet": profile.get("diet", ""),
                "behavior": profile.get("behavior", ""),
                "weakness": profile.get("weakness", ""),
                "appearance": profile.get("appearance", ""),
                "rarity": rarity,
            },
            "lore": profile.get("lore", ""),
            "rarity": rarity,
            "novelty": round(novelty, 4),
            "parents": [],
            "generation": 0,
        }
        saved = self.db.insert_creature(rec)
        rec.update(saved)
        # 入库后重排全园稀有度：新物种会挤动别人的稀有度
        rarities = self.db.recompute_rarity()
        rec["rarity"] = rarities.get(rec["id"], rec["rarity"])
        rec["traits"]["rarity"] = rec["rarity"]
        rec["genome_digest"] = G.gene_digest(gen_list)
        rec["kin"] = kin
        rec["novelty_pct"] = pct
        rec["elapsed_ms"] = int((time.time() - t0) * 1000)
        rec["llm_ms"] = llm_ms
        rec["status"] = "created"
        return rec

    def breed(self, id_a: int, id_b: int, mutation: float = 0.12) -> dict:
        ca, cb = self.db.get(id_a), self.db.get(id_b)
        if not ca or not cb:
            raise ValueError("父母不存在")
        with self.db.conn() as c, c.cursor() as cur:
            cur.execute("SELECT genome FROM creatures WHERE id IN (%s,%s)", [id_a, id_b])
            ga = [r["genome"] for r in cur.fetchall()]
        from .db import parse_vec
        va, vb = parse_vec(ga[0]), parse_vec(ga[1])
        gen = G.mix(va, vb, ratio=0.5, mutation=mutation, seed=f"{id_a}-{id_b}")
        gen_list = gen.tolist()
        if dup := self.db.duplicate_of(gen_list):
            return {"status": "duplicate", "creature": dup}
        kin = self.db.nearest(gen_list, k=4)
        novelty = float(kin[0]["dist"]) if kin else 1.0
        pct = self.db.novelty_percentile(novelty)
        rarity = self._rarity(pct)
        axes = G.axes_of(gen_list)
        profile, llm_ms, _ = self._profile(
            ca["name"], cb["name"], axes, kin,
            extra=f"这是一次杂交：父本 {ca['code']} {ca['name']} × 母本 {cb['code']} {cb['name']}，"
                  f"请体现两个物种特征的怪异融合。")
        rec = {
            "name": profile.get("name") or f"{ca['name'][:2]}{cb['name'][-2:]}",
            "latin": profile.get("latin", ""),
            "tagline": profile.get("tagline", ""),
            "seeds": [ca["name"], cb["name"]],
            "genome": gen_list,
            "axes": axes,
            "traits": {
                "habitat": profile.get("habitat", ""),
                "diet": profile.get("diet", ""),
                "behavior": profile.get("behavior", ""),
                "weakness": profile.get("weakness", ""),
                "appearance": profile.get("appearance", ""),
                "rarity": rarity,
            },
            "lore": profile.get("lore", ""),
            "rarity": rarity,
            "novelty": round(novelty, 4),
            "parents": [id_a, id_b],
            "generation": max(ca.get("generation", 0), cb.get("generation", 0)) + 1,
        }
        saved = self.db.insert_creature(rec)
        rec.update(saved)
        rarities = self.db.recompute_rarity()
        rec["rarity"] = rarities.get(rec["id"], rec["rarity"])
        rec["traits"]["rarity"] = rec["rarity"]
        rec["genome_digest"] = G.gene_digest(gen_list)
        rec["kin"] = kin
        rec["novelty_pct"] = pct
        rec["llm_ms"] = llm_ms
        rec["status"] = "bred"
        return rec

    # ---------- 内部 ----------
    @staticmethod
    def _rarity(pct: float) -> str:
        if pct >= 0.88:
            return "传说"
        if pct >= 0.66:
            return "稀有"
        if pct >= 0.33:
            return "少见"
        return "常见"

    def _profile(self, a: str, b: str, axes: dict, kin: list[dict],
                 extra: str = "") -> tuple[dict, int, str]:
        axes_s = " / ".join(f"{k}{v}" for k, v in axes.items())
        kin_s = "、".join(f"{r['name']}(基因距离{r['dist']:.2f})" for r in kin) or "（园里还没有别的物种）"
        prompt = build_user_prompt(a, b, axes_s, kin_s,
                                   extra=(extra + "\n") if extra else "")
        seed_chars = set(a) | set(b)
        t0 = time.time()
        raw, prof = "", None
        for attempt in range(2):
            with self._gen_lock:
                raw = self.llm.chat(SYSTEM, prompt, max_new_tokens=400,
                                    temperature=0.85 + 0.1 * attempt)
            prof = extract_json(raw)
            if not prof or not prof.get("name"):
                continue
            # 名字里出现两个以上母本字，说明它在偷懒，换一次
            if len(set(prof["name"]) & seed_chars) < 2:
                break
            prompt += "\n\n注意：上一版名字太像母本了。名字里不要出现母本中的任何字。"
        ms = int((time.time() - t0) * 1000)
        if not prof or not prof.get("name"):
            prof = self._fallback(a, b, axes)
            prof["_fallback"] = True
        return prof, ms, raw

    @staticmethod
    def _fallback(a: str, b: str, axes: dict) -> dict:
        rng = random.Random(hash((a, b)) & 0xFFFF)
        name = f"{a[:2]}{b[-1]}兽"
        return {
            "name": name,
            "latin": f"Creatura {a[:2]}ensis",
            "tagline": f"{a}与{b}的意外混种",
            "appearance": f"躯体保留{a}的轮廓，却长出了{b}式的附肢，表面覆盖会反光的鳞片。",
            "habitat": "动物园第 3 展区",
            "diet": "杂食",
            "behavior": f"情绪稳定时会模仿{a}的气味，受惊时像{b}一样喷出墨汁。",
            "weakness": "对强光与突然的掌声过敏",
            "lore": (f"{name}由{a}与{b}的基因片段拼接而成，是向量动物园里最难以归类的居民之一。"
                     f"饲养员发现它每天固定时间面壁发呆，似乎在进行某种内部检索。"
                     f"至于它到底在想什么，园方表示「这不是我们能回答的问题」。"),
        }
