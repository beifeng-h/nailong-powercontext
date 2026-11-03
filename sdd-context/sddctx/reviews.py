"""评审基线的持久化。

评审基线要跟着仓库走——否则换个机器或重新 clone，"先前的验证是否还适用"
这个问题就没人答得上了。所以基线存成 `spec/reviews.json`（可提交），
数据库里那份只是运行时缓存。
"""

from __future__ import annotations

import json
from pathlib import Path

from .store import Review

REVIEWS_FILENAME = "reviews.json"


def reviews_path(spec_root: str | Path) -> Path:
    return Path(spec_root) / REVIEWS_FILENAME


def load_reviews(spec_root: str | Path) -> list[Review]:
    path = reviews_path(spec_root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[Review] = []
    for item in data.get("reviews", []) if isinstance(data, dict) else []:
        spec_id = str(item.get("spec_id") or "")
        if not spec_id:
            continue
        out.append(
            Review(
                spec_id=spec_id,
                content_hash=str(item.get("content_hash") or ""),
                reviewed_at=str(item.get("reviewed_at") or ""),
                note=str(item.get("note") or ""),
            )
        )
    return out


def save_review(spec_root: str | Path, review: Review) -> Path:
    """写入/更新一条评审基线，返回文件路径。"""
    path = reviews_path(spec_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {item.spec_id: item for item in load_reviews(spec_root)}
    merged[review.spec_id] = review
    payload = {
        "reviews": [
            {
                "spec_id": item.spec_id,
                "content_hash": item.content_hash,
                "reviewed_at": item.reviewed_at,
                "note": item.note,
            }
            for item in sorted(merged.values(), key=lambda r: r.spec_id)
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

