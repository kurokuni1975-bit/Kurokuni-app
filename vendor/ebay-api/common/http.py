"""공용 HTTP 헬퍼.

모든 외부 API 호출 규칙 (CONVENTIONS.md):
- 타임아웃 기본 30초
- 429 / 5xx 응답 시 exponential backoff 재시도
- 민감값(토큰/시크릿)은 로그에 찍지 않는다
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_ERRORS = (requests.ConnectionError, requests.Timeout)


def request_with_retry(
    method: str,
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    **kwargs,
) -> requests.Response:
    """requests.request 래퍼: 네트워크 오류/429/5xx 시 재시도.

    주의: Authorization 헤더 등 민감값은 로그에 절대 찍지 않는다.
    """
    attempt = 0
    while True:
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except _NETWORK_ERRORS as exc:
            attempt += 1
            if attempt > max_retries:
                logger.error("%s %s: 네트워크 오류로 재시도 초과 (%s)", method, url, type(exc).__name__)
                raise
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "%s %s: %s, %.1f초 후 재시도 (%d/%d)",
                method, url, type(exc).__name__, wait, attempt, max_retries,
            )
            time.sleep(wait)
            continue

        if resp.status_code in _RETRYABLE_STATUS and attempt < max_retries:
            attempt += 1
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = max(wait, int(retry_after))
            logger.warning(
                "%s %s: HTTP %d, %.1f초 후 재시도 (%d/%d)",
                method, url, resp.status_code, wait, attempt, max_retries,
            )
            time.sleep(wait)
            continue

        return resp


def post_form(url: str, data: dict, auth_header: str, **kwargs) -> requests.Response:
    """eBay OAuth 토큰 엔드포인트용 form-encoded POST.

    eBay 요구사항: Content-Type: application/x-www-form-urlencoded,
    Authorization: Basic base64(client_id:client_secret)
    """
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": auth_header,
    }
    return request_with_retry("POST", url, data=data, headers=headers, **kwargs)
