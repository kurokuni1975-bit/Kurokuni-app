"""Depop 업로드 지원.

Depop은 공식 API가 없으므로 브라우저 자동화로 올린다.
이 모듈은 패키지 준비(설명/가격/사진)와 상태 관리를 담당하고,
실제 브라우저 포스팅은 부모 에이전트가 수행한다.

가격: eBay USD → CAD 변환 (정수 반올림). Depop Canada는 CAD 고정.
설명 규칙 (기존 크로스포스트 규칙):
- Depop 자동 생성 제목이므로 상세 내용은 설명에 전부 기입
- "Also available on Depop." 문구 제외 (Depop 자체에는 무의미)
- eBay 링크 포함: "Also listed on eBay: https://www.ebay.ca/itm/<id>"
- "Price negotiable — offers welcome." 포함
- usa-customs-slide.jpg 제외 (앱 업로드에는 해당 없음, 참고용)

봇 감지 주의: 업로드 간격 4~5분 유지 (워커에서 강제).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# USD → CAD 환율 (환경변수로 조정, 기본값은 최근 실측치)
USD_CAD_RATE = float(os.environ.get("DEPOP_USD_CAD_RATE", "1.42"))

# 봇 감지 회피: 리스팅 간 최소 간격 (초)
DEPOP_MIN_INTERVAL_SEC = int(os.environ.get("DEPOP_MIN_INTERVAL_SEC", "270"))

DEPOP_SHOP_URL = "https://depop.com/vintagetoby"


def usd_to_cad(usd: float) -> int:
    """USD → CAD, 정수로 반올림."""
    return int(round(float(usd) * USD_CAD_RATE))


def build_description(item: dict, draft: dict) -> str:
    """Depop 설명문 생성."""
    parts: list[str] = []

    title = (draft.get("title") or "").strip()
    if title:
        parts.append(title)

    m = draft.get("measurements") or {}
    size_bits = []
    if m.get("pit_to_pit"):
        size_bits.append(f"Pit to pit: {m['pit_to_pit']}in")
    if m.get("length"):
        size_bits.append(f"Length: {m['length']}in")
    if size_bits:
        parts.append("Measurements: " + ", ".join(size_bits) + ".")

    cond = (draft.get("condition") or "").replace("_", " ").title()
    defects = (draft.get("defects") or "").strip()
    cond_line = f"Condition: {cond}."
    if defects:
        cond_line += f" Notes: {defects.upper()}"
    parts.append(cond_line)

    parts.append("Price negotiable \u2014 offers welcome.")

    listing_id = item.get("listing_id")
    if listing_id:
        parts.append(f"Also listed on eBay: https://www.ebay.ca/itm/{listing_id}")

    return "\n".join(parts)


def build_package(item: dict, draft: dict, upload_dir: Path) -> dict:
    """브라우저 포스팅용 패키지."""
    price_cad = usd_to_cad(draft.get("price_usd") or 0)
    photos = [str(upload_dir / item["item_id"] / f) for f in item.get("photos", [])]
    return {
        "item_id": item["item_id"],
        "title_hint": (draft.get("title") or "")[:80],
        "description": build_description(item, draft),
        "price_cad": price_cad,
        "price_usd": draft.get("price_usd"),
        "photos": photos,
        "ebay_listing_id": item.get("listing_id"),
        "depop_shop": DEPOP_SHOP_URL,
    }


def validate_for_queue(item: dict, draft: dict | None) -> str | None:
    """대기열 등록 가능 여부. 문제 있으면 에러 메시지, 없으면 None."""
    if not draft:
        return "초안이 없습니다."
    if not item.get("listing_id"):
        return "eBay에 먼저 발행해야 합니다."
    if not (draft.get("price_usd") or 0) > 0:
        return "가격이 설정되지 않았습니다."
    if not item.get("photos"):
        return "사진이 없습니다."
    status = item.get("depop_status")
    if status in ("queued", "posting"):
        return "이미 대기열에 있습니다."
    if status == "posted":
        return "이미 Depop에 올라갔습니다."
    return None


DEPOP_STATUSES = ("queued", "posting", "posted", "failed")

DEPOP_STATUS_LABEL = {
    "queued": "Depop 대기",
    "posting": "Depop 등록 중",
    "posted": "Depop 등록됨",
    "failed": "Depop 실패",
}
