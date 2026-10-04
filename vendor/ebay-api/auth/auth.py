"""eBay OAuth 2.0 Authorization Code Grant 플로우 (모듈 1).

흐름:
    1. get_authorization_url() → 사용자가 브라우저에서 열고 eBay 로그인 + 동의
    2. eBay가 redirect_uri(RuName)로 리다이렉트 → URL의 ?code=... 복사
    3. exchange_code_for_tokens(code) → access/refresh token 저장
    4. 이후 get_valid_token() 만 호출하면 됨 (만료 시 자동 refresh)

다른 모듈 사용법:
    from auth import get_valid_token
    token = get_valid_token()
    headers = {"Authorization": f"Bearer {token}"}
"""

from __future__ import annotations

import base64
import logging
import time
import urllib.parse

from common import http as httpc
from common.config import ConfigError, EbayConfig

from . import scopes as ebay_scopes
from . import token_store

logger = logging.getLogger(__name__)

# access token 만료 N초 전에 미리 갱신 (경계값)
TOKEN_REFRESH_BUFFER_SECONDS = 120


class AuthError(Exception):
    """OAuth 플로우 중 발생한 오류 (토큰 없음/교환 실패 등)."""


def _config() -> EbayConfig:
    return EbayConfig.from_env()


def _basic_auth_header(cfg: EbayConfig) -> str:
    raw = f"{cfg.client_id}:{cfg.client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _mask(value: str) -> str:
    """로그용 토큰 마스킹 (앞 4자리만 표시)."""
    if not value:
        return "<empty>"
    return value[:4] + "…" + f"({len(value)}자)"


def _check_token_response(resp, step: str) -> dict:
    """토큰 엔드포인트 응답 검증. 실패 시 AuthError (민감값 제외)."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code != 200 or not body.get("access_token"):
        error = body.get("error", f"HTTP {resp.status_code}")
        desc = body.get("error_description", "")
        raise AuthError(f"{step} 실패: {error} {desc}".strip())
    return body


def get_authorization_url(scopes: list[str] | None = None, state: str | None = None) -> str:
    """사용자 동의 URL 생성.

    사용자는 이 URL을 브라우저에서 열어 eBay에 로그인하고 앱 접근을 승인한다.
    승인 후 eBay가 redirect_uri(RuName)로 리다이렉트하며 ?code=<인가코드>를 붙여준다.
    """
    cfg = _config()
    scopes = scopes or ebay_scopes.DEFAULT_SCOPES
    params = {
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,  # RuName (개발자 포털에 등록된 값)
        "response_type": "code",
        "scope": " ".join(scopes),
    }
    if state:
        params["state"] = state
    return cfg.authorize_url + "?" + urllib.parse.urlencode(params)


def exchange_code_for_tokens(code: str) -> dict:
    """인가 코드를 access/refresh 토큰으로 교환하고 파일에 저장한다."""
    cfg = _config()
    if not code or not code.strip():
        raise AuthError("인가 코드가 비어 있습니다.")

    data = {
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": cfg.redirect_uri,  # authorize 단계와 동일한 RuName
    }
    resp = httpc.post_form(cfg.token_url, data=data, auth_header=_basic_auth_header(cfg))
    body = _check_token_response(resp, "인가 코드 교환")

    expires_at = time.time() + int(body.get("expires_in", 7200))
    token_store.save_tokens(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", ""),
        expires_at=expires_at,
        token_type=body.get("token_type", "Bearer"),
    )
    logger.info(
        "토큰 교환 완료: access_token=%s (약 %d초 유효)",
        _mask(body["access_token"]),
        int(body.get("expires_in", 7200)),
    )
    return body


def refresh_access_token() -> str:
    """refresh token으로 access token을 갱신하고 새 access token을 반환한다.

    eBay 특이사항:
    - refresh 요청에 scope 파라미터가 필수다.
    - refresh 응답에는 새 refresh_token이 포함되지 않는다 → 기존 refresh token 유지.
    """
    cfg = _config()
    stored = token_store.load_tokens()
    if not stored or not stored.get("refresh_token"):
        raise AuthError(
            "저장된 refresh token이 없습니다. "
            "먼저 `python -m auth.main --auth-url` 로 동의하고 "
            "`--exchange <code>` 로 토큰을 받으세요."
        )

    data = {
        "grant_type": "refresh_token",
        "refresh_token": stored["refresh_token"],
        "scope": " ".join(ebay_scopes.DEFAULT_SCOPES),  # eBay는 refresh 시 scope 필수
    }
    resp = httpc.post_form(cfg.token_url, data=data, auth_header=_basic_auth_header(cfg))
    body = _check_token_response(resp, "토큰 갱신")

    # eBay는 refresh 시 새 refresh_token을 주지 않으므로 기존 것을 유지한다.
    refresh_token = body.get("refresh_token") or stored["refresh_token"]
    expires_at = time.time() + int(body.get("expires_in", 7200))
    token_store.save_tokens(
        access_token=body["access_token"],
        refresh_token=refresh_token,
        expires_at=expires_at,
        token_type=body.get("token_type", "Bearer"),
    )
    logger.info("access token 갱신 완료: %s", _mask(body["access_token"]))
    return body["access_token"]


def get_valid_token() -> str:
    """다른 모듈이 공통으로 쓰는 함수: 유효한 access token 반환.

    - 저장된 토큰이 아직 유효하면 그대로 반환
    - 만료됐거나(버퍼 120초) 없으면 refresh token으로 자동 갱신
    - 토큰 자체가 없으면 AuthError (안내 메시지 포함)
    """
    stored = token_store.load_tokens()
    now = time.time()

    if stored and stored.get("access_token"):
        if stored.get("expires_at", 0) > now + TOKEN_REFRESH_BUFFER_SECONDS:
            return stored["access_token"]
        logger.info("access token이 만료됐거나 곧 만료됨 → 자동 갱신")

    if stored and stored.get("refresh_token"):
        return refresh_access_token()

    raise AuthError(
        "토큰이 없습니다. 다음 순서로 인증하세요:\n"
        "  1) python -m auth.main --auth-url   # 동의 URL 출력\n"
        "  2) 브라우저에서 열고 eBay 로그인 + 승인 → ?code=... 복사\n"
        "  3) python -m auth.main --exchange <code>"
    )


__all__ = [
    "AuthError",
    "exchange_code_for_tokens",
    "get_authorization_url",
    "get_valid_token",
    "refresh_access_token",
]
