"""모듈 1 CLI. 프로젝트 루트(~/workspace/ebay-api)에서 실행한다.

    python -m auth.main --auth-url        # 사용자 동의 URL 출력
    python -m auth.main --exchange <code> # 인가 코드를 토큰으로 교환 후 저장
    python -m auth.main --refresh         # refresh token으로 access token 갱신 테스트
    python -m auth.main --status          # 토큰 상태 확인 (값은 출력하지 않음)
    python -m auth.main --logout          # 저장된 토큰 삭제
"""

from __future__ import annotations

import argparse
import logging
import sys

from auth import (
    AuthError,
    exchange_code_for_tokens,
    get_authorization_url,
    refresh_access_token,
)
from auth import token_store
from common.config import ConfigError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def cmd_auth_url() -> int:
    url = get_authorization_url()
    print(url)
    print()
    print("위 URL을 브라우저에서 열고 eBay에 로그인한 뒤 앱 접근을 승인하세요.")
    print("승인 후 리다이렉트된 주소의 ?code=... 값을 복사해서")
    print("  python -m auth.main --exchange <code>  로 토큰을 받으세요.")
    return 0


def cmd_exchange(code: str) -> int:
    exchange_code_for_tokens(code)
    print("토큰 교환 및 저장 완료. 이제 다른 모듈에서 get_valid_token()을 쓰면 됩니다.")
    return 0


def cmd_refresh() -> int:
    token = refresh_access_token()
    print(f"갱신 성공. 새 access token 앞 4자리: {token[:4]}…")
    return 0


def cmd_status() -> int:
    st = token_store.token_status()
    if not st["has_tokens"]:
        print("저장된 토큰 없음. --auth-url 로 인증을 시작하세요.")
        return 1
    if st["access_token_expired"]:
        print("access token 만료됨 (refresh token으로 자동 갱신 가능).")
    else:
        print(f"access token 유효 (남은 시간 약 {st['access_token_expires_in_sec']}초).")
    print(f"refresh token 보유: {'예' if st['has_refresh_token'] else '아니오'}")
    print(f"토큰 파일: {st['token_file']}")
    return 0


def cmd_logout() -> int:
    token_store.clear_tokens()
    print("저장된 토큰을 삭제했습니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eBay OAuth 인증 CLI (모듈 1)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--auth-url", action="store_true", help="사용자 동의 URL 출력")
    group.add_argument("--exchange", metavar="CODE", help="인가 코드를 토큰으로 교환")
    group.add_argument("--refresh", action="store_true", help="access token 갱신 테스트")
    group.add_argument("--status", action="store_true", help="토큰 상태 확인")
    group.add_argument("--logout", action="store_true", help="저장된 토큰 삭제")
    args = parser.parse_args(argv)

    try:
        if args.auth_url:
            return cmd_auth_url()
        if args.exchange:
            return cmd_exchange(args.exchange)
        if args.refresh:
            return cmd_refresh()
        if args.status:
            return cmd_status()
        if args.logout:
            return cmd_logout()
    except (AuthError, ConfigError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
