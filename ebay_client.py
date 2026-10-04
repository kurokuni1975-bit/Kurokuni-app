"""eBay API 연동 래퍼.

~/workspace/ebay-api/ 의 기존 모듈(auth, listing)을 재사용한다.
- 환경별 .env 로드 + 토큰 파일(.tokens.json) 준비/동기화를 담당
- 키·토큰 값은 절대 로그·예외·반환값에 포함하지 않는다.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys

import config

log = logging.getLogger(__name__)

_EBAY_API_ON_PATH = False


def _ensure_ebay_api_path() -> None:
    global _EBAY_API_ON_PATH
    if not _EBAY_API_ON_PATH:
        p = str(config.EBAY_API_DIR)
        if p not in sys.path:
            sys.path.insert(0, p)
        _EBAY_API_ON_PATH = True


def _mask_error(exc: Exception) -> str:
    """예외 메시지에서 민감값 패턴이 새지 않도록 정리."""
    msg = str(exc)
    # 토큰이 통째로 들어갔을 경우를 대비한 최소 정리
    for key in ("EBAY_CLIENT_SECRET", "EBAY_ACCESS_TOKEN",
                "access_token", "refresh_token"):
        if key in msg:
            msg = msg.replace(key, f"<{key}>")
    return msg[:500]


class EbayClientError(Exception):
    pass


def prepare_environment(ebay_env: str | None = None) -> str:
    """eBay 호출 전 환경 준비: .env 로드 + 토큰 파일 배치.

    토큰 파일(.tokens.json)은 auth 모듈이 읽는 고정 경로이므로,
    환경별 원본(.tokens.production.json / .tokens.sandbox.json)을
    복사해 둔다. 값은 다루지 않는다.
    """
    env = (ebay_env or config.APP_EBAY_ENV).strip().lower()
    if env not in ("production", "sandbox"):
        raise EbayClientError(f"잘못된 eBay 환경: {env}")

    config.load_ebay_env(env)

    src = config.token_file_for(env)
    dst = config.EBAY_API_DIR / ".tokens.json"
    if not src.exists():
        raise EbayClientError(
            f"토큰 파일이 없습니다 ({src.name}). "
            "먼저 OAuth 동의 플로우로 토큰을 발급하세요."
        )
    # 원본이 더 새로우면 복사 (서버 재시작 시 stale 토큰 방지)
    if (not dst.exists()
            or src.stat().st_mtime > dst.stat().st_mtime):
        shutil.copy2(src, dst)
        os.chmod(dst, 0o600)
    return env


def sync_tokens_back(ebay_env: str | None = None) -> None:
    """작업 후 .tokens.json(갱신됐을 수 있음)을 환경별 원본에 반영."""
    env = (ebay_env or config.APP_EBAY_ENV).strip().lower()
    src = config.EBAY_API_DIR / ".tokens.json"
    dst = config.token_file_for(env)
    if src.exists():
        shutil.copy2(src, dst)
        os.chmod(dst, 0o600)


def token_status(ebay_env: str | None = None) -> dict:
    """토큰 상태 요약 (값 제외)."""
    _ensure_ebay_api_path()
    prepare_environment(ebay_env)
    try:
        from auth.token_store import token_status as _ts
        st = _ts()
        st.pop("token_file", None)
        return st
    except Exception as exc:  # noqa: BLE001
        return {"has_tokens": False, "error": _mask_error(exc)}


def _api_base() -> str:
    return ("https://api.sandbox.ebay.com"
            if os.environ.get("EBAY_ENV") == "sandbox"
            else "https://api.ebay.com")


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json"}


def cleanup_sku(sku: str, token: str | None = None) -> dict:
    """해당 SKU의 미발행 오퍼/인벤토리 아이템 정리 (재발행 전 멱등성 확보)."""
    _ensure_ebay_api_path()
    import requests
    from urllib.parse import quote
    if token is None:
        from auth import get_valid_token
        token = get_valid_token()
    base = _api_base()
    h = _auth_headers(token)
    cleaned = {"offers": [], "item": False}
    try:
        r = requests.get(f"{base}/sell/inventory/v1/offer",
                         params={"sku": sku}, headers=h, timeout=30)
        if r.status_code == 200:
            for o in r.json().get("offers", []):
                oid = o.get("offerId")
                if o.get("status") == "PUBLISHED":
                    continue  # 발행된 건 건드리지 않음
                d = requests.delete(
                    f"{base}/sell/inventory/v1/offer/{quote(oid, safe='')}",
                    headers=h, timeout=30)
                if d.status_code in (200, 204):
                    cleaned["offers"].append(oid)
    except Exception as exc:  # noqa: BLE001
        log.warning("오퍼 정리 중 오류 (무시): %s", _mask_error(exc))
    return cleaned


def build_listing_input(item: dict, draft: dict,
                        image_urls: list[str]) -> dict:
    """앱의 item+draft를 listing 모듈 입력 형식으로 변환."""
    description = (draft.get("description") or "").strip()
    # plain text면 기본 HTML로 변환 (eBay는 basic HTML 권장)
    if description and "<" not in description:
        paras = [p.strip() for p in description.split("\n\n") if p.strip()]
        if not paras:
            paras = [p.strip() for p in description.split("\n") if p.strip()]
        description = "".join(f"<p>{p}</p>" for p in paras)

    return {
        "sku": item["sku"],
        "title": (draft.get("title") or "").strip(),
        "description": description,
        "price_usd": float(draft.get("price_usd") or 0),
        "image_urls": image_urls,
        "category": draft.get("category") or "tshirt",
        "condition": draft.get("condition") or "USED_GOOD",
        "quantity": 1,
        "best_offer": bool(draft.get("suggested_best_offer", True)),
        "min_offer_price": draft.get("min_offer_price"),
        "box_number": draft.get("box_number") or "",
        "aspects": draft.get("aspects") or {},
    }


def publish_item(item: dict, draft: dict, image_urls: list[str],
                 ebay_env: str | None = None) -> dict:
    """리스팅 발행 (inventory -> offer -> publish). 성공 시 결과 dict 반환."""
    _ensure_ebay_api_path()
    env = prepare_environment(ebay_env)
    try:
        from listing.listing import create_listing
        payload = build_listing_input(item, draft, image_urls)
        # 재발행 시 기존 미발행 오퍼가 있으면 "already exists"로 실패하므로 미리 정리
        try:
            cleanup_sku(item["sku"])
        except Exception:  # noqa: BLE001
            pass
        result = create_listing(payload)
    except Exception as exc:  # noqa: BLE001
        raise EbayClientError(f"발행 실패: {_mask_error(exc)}") from exc
    finally:
        try:
            sync_tokens_back(env)
        except OSError:
            log.warning("토큰 동기화 실패 (무시)")
    return result


def dry_run_validate(item: dict, draft: dict,
                     image_urls: list[str]) -> dict:
    """발행 전 검증만 (API 호출 없음)."""
    _ensure_ebay_api_path()
    prepare_environment()
    from listing.listing import EbayListingClient
    payload = build_listing_input(item, draft, image_urls)
    client = EbayListingClient(dry_run=True)
    return client.create_listing(payload)
