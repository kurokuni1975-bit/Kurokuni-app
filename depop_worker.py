#!/usr/bin/env python3
"""Depop 대기열 워커 (부모 에이전트용 헬퍼).

Depop은 공식 API가 없어 브라우저 자동화로 올린다.
이 스크립트는 대기열을 조회하고 포스팅 패키지를 준비한다.
실제 브라우저 포스팅은 부모 에이전트가 수행하고,
결과는 앱 API로 보고한다.

사용법:
    python3 depop_worker.py --list              # 대기열 목록
    python3 depop_worker.py --package <item_id> # 포스팅 패키지 JSON 출력
    python3 depop_worker.py --posted <item_id> --url <depop_url>
    python3 depop_worker.py --failed <item_id> --error "사유"

봇 감지 주의: 리스팅 간 최소 4~5분 간격 유지.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

APP_BASE = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5001")
APP_TOKEN = os.environ.get("APP_DRAFT_API_TOKEN", "")
LAST_POST_FILE = "/tmp/depop_last_post.txt"


def _get(path: str) -> dict:
    req = urllib.request.Request(APP_BASE + path)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        APP_BASE + path, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-App-Token": APP_TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def cmd_list(_args) -> int:
    data = _get("/api/depop/queue")
    q = data.get("queue", [])
    print(f"대기열: {len(q)}건 (최소 간격 {data.get('min_interval_sec', 270)}초)")
    for p in q:
        print(f"  - {p['item_id']}: C${p['price_cad']} "
              f"(US${p['price_usd']}), 사진 {len(p['photos'])}장")
        print(f"    {p['title_hint'][:60]}")
    return 0


def cmd_package(args) -> int:
    data = _get("/api/depop/queue")
    for p in data.get("queue", []):
        if p["item_id"] == args.item_id:
            print(json.dumps(p, ensure_ascii=False, indent=2))
            return 0
    print(f"대기열에 없음: {args.item_id}", file=sys.stderr)
    return 1


def _check_pacing() -> tuple[bool, int]:
    """마지막 포스팅 이후 경과 확인. (가능여부, 남은초)"""
    try:
        with open(LAST_POST_FILE) as f:
            last = float(f.read().strip())
    except (OSError, ValueError):
        return True, 0
    min_interval = int(os.environ.get("DEPOP_MIN_INTERVAL_SEC", "270"))
    elapsed = time.time() - last
    if elapsed >= min_interval:
        return True, 0
    return False, int(min_interval - elapsed)


def _mark_posted() -> None:
    with open(LAST_POST_FILE, "w") as f:
        f.write(str(time.time()))


def cmd_posted(args) -> int:
    _mark_posted()
    r = _post(f"/api/depop/{args.item_id}/posted",
              {"depop_url": args.url})
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def cmd_failed(args) -> int:
    r = _post(f"/api/depop/{args.item_id}/failed",
              {"error": args.error})
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def cmd_can_post(_args) -> int:
    ok, remain = _check_pacing()
    print(json.dumps({"can_post": ok, "wait_sec": remain}))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Depop 대기열 워커")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="대기열 목록")
    sp = sub.add_parser("package", help="포스팅 패키지 출력")
    sp.add_argument("item_id")
    sp = sub.add_parser("posted", help="포스팅 성공 보고")
    sp.add_argument("item_id")
    sp.add_argument("--url", required=True)
    sp = sub.add_parser("failed", help="포스팅 실패 보고")
    sp.add_argument("item_id")
    sp.add_argument("--error", required=True)
    sub.add_parser("can-post", help="포스팅 가능 여부 (pacing 체크)")
    args = p.parse_args(argv)
    return {
        "list": cmd_list, "package": cmd_package, "posted": cmd_posted,
        "failed": cmd_failed, "can-post": cmd_can_post,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
