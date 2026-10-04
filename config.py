"""KUROKUNI 리스팅 웹앱 설정.

보안 규칙:
- .env* / .tokens* 파일의 키·토큰 값을 코드·로그·응답에 노출하지 않는다.
- 이 모듈은 값을 읽어 os.environ에만 넣고, 값을 반환·출력하지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
EBAY_API_DIR = Path(os.environ.get("EBAY_API_DIR",
                                   str(Path.home() / "workspace" / "ebay-api")))

UPLOAD_DIR = APP_ROOT / "uploads"
DRAFT_DIR = APP_ROOT / "drafts"
ITEM_DIR = APP_ROOT / "items"

# eBay 환경: production | sandbox (기본 production)
APP_EBAY_ENV = os.environ.get("APP_EBAY_ENV", "production").strip().lower()
if APP_EBAY_ENV not in ("production", "sandbox"):
    APP_EBAY_ENV = "production"

# 업로드된 사진을 eBay에 전달할 때 쓰는 공개 HTTPS 베이스 URL.
# 예: https://example.com/uploads  →  이미지 URL은
#     https://example.com/uploads/<item_id>/<파일명> 이 된다.
# 미설정 시 발행이 차단된다 (리뷰 화면에 안내 표시).
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "").strip().rstrip("/")

# 업로드 제한
MAX_UPLOAD_MB = int(os.environ.get("APP_MAX_UPLOAD_MB", "12"))
MAX_PHOTOS = int(os.environ.get("APP_MAX_PHOTOS", "12"))
PHOTO_MAX_DIM = int(os.environ.get("APP_PHOTO_MAX_DIM", "1600"))  # 긴 변 기준 리사이즈

# draft 제출 API용 간이 토큰 (미설정 시 체크 안 함 — localhost 전용 v1)
DRAFT_API_TOKEN = os.environ.get("APP_DRAFT_API_TOKEN", "")

# Flask
FLASK_PORT = int(os.environ.get("APP_PORT", "5000"))
FLASK_DEBUG = os.environ.get("APP_DEBUG", "0") == "1"


def env_file_for(ebay_env: str) -> Path:
    """환경에 맞는 .env 파일 경로."""
    if ebay_env == "production":
        return EBAY_API_DIR / ".env.production"
    return EBAY_API_DIR / ".env"


def token_file_for(ebay_env: str) -> Path:
    """환경에 맞는 토큰 원본 파일 경로."""
    if ebay_env == "production":
        return EBAY_API_DIR / ".tokens.production.json"
    return EBAY_API_DIR / ".tokens.sandbox.json"


def load_ebay_env(ebay_env: str) -> None:
    """eBay .env 파일에서 EBAY_ 변수만 os.environ에 로드. 값은 반환하지 않음."""
    path = env_file_for(ebay_env)
    if not path.exists():
        raise RuntimeError(f"eBay 설정 파일 없음: {path}")
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key.startswith("EBAY_"):
                os.environ[key] = value
    os.environ["EBAY_ENV"] = ebay_env
    for d in (UPLOAD_DIR, DRAFT_DIR, ITEM_DIR):
        d.mkdir(parents=True, exist_ok=True)
