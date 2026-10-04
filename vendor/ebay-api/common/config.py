"""eBay API 공용 설정 로더.

CONVENTIONS.md 보안 규칙: API 키/시크릿/토큰은 코드에 하드코딩하지 않고,
환경변수에서만 읽는다. 이 모듈이 환경변수를 읽는 유일한 곳이다.

환경변수:
    EBAY_CLIENT_ID      eBay Developer Portal에서 발급받은 Client ID (App ID)
    EBAY_CLIENT_SECRET  eBay Developer Portal에서 발급받은 Client Secret (Cert ID)
    EBAY_REDIRECT_URI   eBay Developer Portal에 등록한 Redirect URL Name (RuName).
                        개발자 포털 "Application access" > "Your auth accepted URL"
                        또는 "Redirect URL name"에 등록된 값.
    EBAY_ENV            sandbox | production (기본값: sandbox)
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(Exception):
    """환경변수 설정이 없거나 잘못됐을 때 발생한다."""


@dataclass(frozen=True)
class EbayConfig:
    """eBay API 설정. `EbayConfig.from_env()` 로 생성한다."""

    client_id: str
    client_secret: str
    redirect_uri: str  # eBay Developer Portal에 등록된 RuName
    env: str = "sandbox"

    def __post_init__(self) -> None:
        if self.env not in ("sandbox", "production"):
            raise ConfigError(
                f"EBAY_ENV must be 'sandbox' or 'production', got {self.env!r}"
            )

    @property
    def authorize_url(self) -> str:
        """OAuth 동의(인가 코드) 엔드포인트."""
        if self.env == "production":
            return "https://auth.ebay.com/oauth2/authorize"
        return "https://auth.sandbox.ebay.com/oauth2/authorize"

    @property
    def token_url(self) -> str:
        """토큰 교환/갱신 엔드포인트."""
        if self.env == "production":
            return "https://api.ebay.com/identity/v1/oauth2/token"
        return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

    @property
    def api_base_url(self) -> str:
        """REST API 베이스 URL (listing/monitor/sku 모듈용)."""
        if self.env == "production":
            return "https://api.ebay.com"
        return "https://api.sandbox.ebay.com"

    @classmethod
    def from_env(cls, environ: dict | None = None) -> "EbayConfig":
        """환경변수에서 설정을 읽는다. 키 발급 전에는 ConfigError를 낸다."""
        env = environ if environ is not None else os.environ

        client_id = (env.get("EBAY_CLIENT_ID") or "").strip()
        client_secret = (env.get("EBAY_CLIENT_SECRET") or "").strip()
        redirect_uri = (env.get("EBAY_REDIRECT_URI") or "").strip()
        ebay_env = (env.get("EBAY_ENV") or "sandbox").strip().lower()

        missing = [
            name
            for name, value in (
                ("EBAY_CLIENT_ID", client_id),
                ("EBAY_CLIENT_SECRET", client_secret),
                ("EBAY_REDIRECT_URI", redirect_uri),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                "eBay API 키가 설정되지 않았습니다: "
                + ", ".join(missing)
                + ". README.md '내일 키 받으면 할 일' 섹션을 참고하세요."
            )

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            env=ebay_env,
        )
