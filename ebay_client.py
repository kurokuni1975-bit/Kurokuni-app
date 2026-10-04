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
import time

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

    # 필수 item specifics 기본값 (eBay가 요구하는 항목)
    aspects = dict(draft.get("aspects") or {})
    # T-Shirts 카테고리 필수 항목들
    if (draft.get("category") or "tshirt") == "tshirt":
        aspects.setdefault("Size Type", "Regular")
        aspects.setdefault("Department", "Men")
        # Color, Size, Brand는 초안에서 추출 시도, 없으면 기본값
        if "Color" not in aspects:
            # 설명에서 색상 추출 시도
            desc = (draft.get("description") or "").lower()
            for color in ["black", "white", "blue", "red", "green", "gray", "grey"]:
                if color in desc:
                    aspects["Color"] = color.capitalize()
                    break
            else:
                aspects["Color"] = "Black"
        if "Size" not in aspects:
            # 제목에서 사이즈 추출 시도
            title = (draft.get("title") or "").upper()
            for sz in ["XXL", "XL", "LARGE", "MEDIUM", "SMALL", "XXL", "3XL"]:
                if sz in title:
                    aspects["Size"] = {"LARGE": "L", "MEDIUM": "M", "SMALL": "S"}.get(sz, sz)
                    break
            else:
                aspects["Size"] = "L"
        # Brand: 초안의 brand 필드 또는 설명에서 추출, 없으면 Unbranded
        if "Brand" not in aspects:
            brand = (draft.get("brand") or "").strip()
            if not brand:
                # 흔한 택 브랜드를 설명에서 찾기
                desc_up = (draft.get("description") or "").upper()
                for b in ["DELTA", "GILDAN", "HANES", "FRUIT OF THE LOOM", "ANVIL",
                          "ALSTYLE", "BELLA", "NEXT LEVEL", "COMFORT COLORS",
                          "CHAMPION", "NIKE", "ADIDAS", "REEBOK"]:
                    if b in desc_up:
                        brand = b.title() if b != "FRUIT OF THE LOOM" else "Fruit of the Loom"
                        break
            aspects["Brand"] = brand or "Unbranded"

    return {
        "sku": item["sku"],
        "title": (draft.get("title") or "").strip(),
        "description": description,
        "price_usd": float(draft.get("price_usd") or 0),
        "image_urls": image_urls,
        "category": draft.get("category") or "tshirt",
        "condition": draft.get("condition") or "USED_EXCELLENT",
        "quantity": 1,
        "best_offer": bool(draft.get("suggested_best_offer", True)),
        "min_offer_price": draft.get("min_offer_price"),
        "box_number": draft.get("box_number") or "",
        "aspects": aspects,
    }


def verify_image_urls(image_urls: list[str],
                      max_retries: int = 3,
                      retry_interval: int = 5) -> list[str]:
    """발행 전 이미지 URL 접근성 검증.

    각 URL에 HTTP HEAD 요청을 보내 200 OK인지 확인한다.
    실패한 URL은 max_retries번 재시도 (retry_interval초 간격) 후에도
    안 되면 제외한다. 최소 1장은 있어야 하며, 없으면 EbayClientError 발생.
    """
    import requests

    verified = []
    for url in image_urls:
        ok = False
        for attempt in range(max_retries):
            try:
                r = requests.head(url, timeout=30, allow_redirects=True)
                if r.status_code == 200:
                    # content-type이 이미지인지 확인 (관대하게 처리)
                    ctype = (r.headers.get("Content-Type") or "").lower()
                    if "image" in ctype or not ctype:
                        ok = True
                        break
                    # content-type이 이상해도 200이면 일단 통과 시도 (GET으로 재확인)
                    r2 = requests.get(url, timeout=30, stream=True)
                    if r2.status_code == 200:
                        ok = True
                        r2.close()
                        break
                    r2.close()
                else:
                    log.warning("이미지 URL 응답 %s: %s (시도 %d/%d)",
                                r.status_code, url[:80], attempt + 1, max_retries)
            except Exception as exc:  # noqa: BLE001
                log.warning("이미지 URL 접근 실패: %s (시도 %d/%d): %s",
                            url[:80], attempt + 1, max_retries,
                            _mask_error(exc))
            if attempt < max_retries - 1:
                time.sleep(retry_interval)
        if ok:
            verified.append(url)
        else:
            log.error("이미지 URL 제외 (접근 불가): %s", url[:80])
    if not verified:
        raise EbayClientError(
            f"발행 중단: 이미지 URL {len(image_urls)}장 모두 접근 불가. "
            "eBay가 사진을 다운로드할 수 없어 사진 없는 리스팅이 올라갑니다."
        )
    if len(verified) < len(image_urls):
        log.warning("이미지 %d장 중 %d장만 검증됨",
                    len(image_urls), len(verified))
    return verified


def verify_listing_images(listing_id: str,
                          expected_min: int = 1) -> bool:
    """발행 후 eBay 리스팅의 사진 등록 여부 확인 (best-effort).

    Browse API로 실제 리스팅을 조회해 이미지가 있는지 확인한다.
    eBay의 이미지 처리는 비동기라 즉시 반영 안 될 수 있으므로,
    실패해도 예외를 던지지 않고 False만 반환한다.
    """
    _ensure_ebay_api_path()
    import requests
    try:
        from auth import get_valid_token
        token = get_valid_token()
    except Exception as exc:  # noqa: BLE001
        log.warning("발행 후 이미지 확인 불가 (토큰): %s", _mask_error(exc))
        return False
    try:
        r = requests.get(
            f"https://api.ebay.com/buy/browse/v1/item/{listing_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30)
        if r.status_code != 200:
            log.warning("리스팅 조회 실패 (%s): %s", r.status_code, listing_id)
            return False
        data = r.json()
        images = data.get("image", {}).get("imageUrl", "")
        additional = data.get("additionalImages", [])
        count = (1 if images else 0) + len(additional)
        if count >= expected_min:
            log.info("리스팅 %s: 사진 %d장 확인됨", listing_id, count)
            return True
        log.warning("리스팅 %s: 사진 %d장만 확인됨 (기대 %d장). "
                    "eBay 이미지 처리 중일 수 있음.",
                    listing_id, count, expected_min)
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("발행 후 이미지 확인 실패: %s", _mask_error(exc))
        return False


def publish_item(item: dict, draft: dict, image_urls: list[str],
                 ebay_env: str | None = None) -> dict:
    """리스팅 발행 (inventory -> offer -> publish). 성공 시 결과 dict 반환."""
    _ensure_ebay_api_path()
    env = prepare_environment(ebay_env)
    try:
        from listing.listing import create_listing
        # 1) 발행 전 이미지 URL 검증 (접근 불가 URL 제외)
        verified_urls = verify_image_urls(image_urls)
        payload = build_listing_input(item, draft, verified_urls)
        # 재발행 시 기존 미발행 오퍼가 있으면 "already exists"로 실패하므로 미리 정리
        try:
            cleanup_sku(item["sku"])
        except Exception:  # noqa: BLE001
            pass
        result = create_listing(payload)
        # 2) 발행 후 사진 등록 확인 (best-effort, 실패해도 발행은 유지)
        listing_id = result.get("listing_id")
        if listing_id:
            # eBay 이미지 비동기 처리를 감안해 잠시 대기 후 확인
            time.sleep(10)
            if not verify_listing_images(listing_id, len(verified_urls)):
                log.warning("리스팅 %s: 사진 미확인. eBay 이미지 처리 지연 가능. "
                            "수동 확인 권장.", listing_id)
                result["images_verified"] = False
            else:
                result["images_verified"] = True
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
