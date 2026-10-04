"""상품/초안 상태 저장소 (JSON 파일 기반).

items/<item_id>.json:
    {item_id, created_at, status, photos[], note, listing_id, offer_id,
     sku, error, published_at}
drafts/<item_id>.json: 초안 스키마 (config 참조)

status: pending(분석대기) -> draft_ready(초안완료) -> publishing(발행중)
        -> published(발행됨) | failed(실패)
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import config

STATUSES = ("pending", "draft_ready", "publishing", "published", "failed")

STATUS_LABEL = {
    "pending": "분석 대기",
    "draft_ready": "초안 완료",
    "publishing": "발행 중",
    "published": "발행됨",
    "failed": "실패",
}


def new_item_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def item_path(item_id: str) -> Path:
    return config.ITEM_DIR / f"{item_id}.json"


def draft_path(item_id: str) -> Path:
    return config.DRAFT_DIR / f"{item_id}.json"


def save_item(item: dict) -> None:
    p = item_path(item["item_id"])
    p.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")


def load_item(item_id: str) -> dict | None:
    p = item_path(item_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_items() -> list[dict]:
    items = []
    if not config.ITEM_DIR.exists():
        return items
    for p in sorted(config.ITEM_DIR.glob("*.json"), reverse=True):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return items


def create_item(photos: list[str], note: str = "",
                item_id: str | None = None) -> dict:
    item_id = item_id or new_item_id()
    item = {
        "item_id": item_id,
        "created_at": int(time.time()),
        "status": "pending",
        "photos": photos,
        "note": note,
        "sku": f"KUROKUNI-{item_id}",
        "listing_id": None,
        "offer_id": None,
        "error": None,
        "published_at": None,
    }
    save_item(item)
    return item


def set_status(item_id: str, status: str, **fields) -> dict | None:
    item = load_item(item_id)
    if not item:
        return None
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    item["status"] = status
    item.update(fields)
    save_item(item)
    return item


def save_draft(item_id: str, draft: dict) -> Path:
    """초안 JSON 저장. item 상태도 draft_ready로 전환."""
    draft = dict(draft)
    draft["item_id"] = item_id
    draft.setdefault("status", "draft")
    p = draft_path(item_id)
    p.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    item = load_item(item_id)
    if item and item["status"] == "pending":
        set_status(item_id, "draft_ready")
    return p


def load_draft(item_id: str) -> dict | None:
    p = draft_path(item_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
