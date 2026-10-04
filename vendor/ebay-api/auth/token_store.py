"""토큰 저장소.

CONVENTIONS.md 토큰 파일 형식:
    {"access_token": "...", "refresh_token": "...",
     "expires_at": 1234567890, "token_type": "Bearer"}

- 저장 위치: ~/workspace/ebay-api/.tokens.json (프로젝트 루트 기준)
- 파일 권한 0o600 (소유자만 읽기/쓰기) — git/외부 공유 절대 금지
- expires_at: access token 만료 시점 (epoch 초, UTC)
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = PROJECT_ROOT / ".tokens.json"


def save_tokens(
    access_token: str,
    refresh_token: str,
    expires_at: float,
    token_type: str = "Bearer",
) -> None:
    """토큰을 파일에 저장한다. 토큰 값은 로그에 찍지 않는다."""
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": int(expires_at),
        "token_type": token_type,
    }
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    logger.info("토큰 저장 완료: %s", TOKEN_FILE)


def load_tokens() -> dict | None:
    """저장된 토큰 dict 반환. 파일이 없거나 깨졌으면 None."""
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("토큰 파일 읽기 실패 (%s): %s", TOKEN_FILE, exc)
        return None
    if not isinstance(data, dict) or not data.get("access_token"):
        return None
    return data


def clear_tokens() -> None:
    """저장된 토큰 삭제."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        logger.info("토큰 삭제 완료: %s", TOKEN_FILE)


def token_status() -> dict:
    """토큰 상태 요약 (값은 포함하지 않음 — --status CLI용)."""
    data = load_tokens()
    if not data:
        return {"has_tokens": False}
    remaining = data.get("expires_at", 0) - time.time()
    return {
        "has_tokens": True,
        "access_token_expired": remaining <= 0,
        "access_token_expires_in_sec": int(remaining),
        "has_refresh_token": bool(data.get("refresh_token")),
        "token_file": str(TOKEN_FILE),
    }
