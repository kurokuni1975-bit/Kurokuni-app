#!/usr/bin/env python3
"""KUROKUNI 앱 실시간 감시 — 새 업로드를 수초 내 감지해서 처리.

Render API를 10초마다 폴링:
- pending 아이템 → 초안 생성 서브에이전트 실행
- draft_ready 아이템 → 자동 발행

사용법: nohup python3 watcher.py > watcher.log 2>&1 &
"""
import json
import subprocess
import sys
import time
import urllib.request

API_BASE = "https://kurokuni-app.onrender.com"
POLL_SECS = 10
SEEN_FILE = "/home/hatch/workspace/ebay-app/watcher_seen.json"

# 안전장치
MIN_AUTO_PRICE = 5.0
MAX_AUTO_PRICE = 500.0
MAX_DAILY_PUBLISH = 50


def api_get(path):
    req = urllib.request.Request(f"{API_BASE}{path}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def api_post(path, data=None):
    body = json.dumps(data or {}).encode() if data else None
    req = urllib.request.Request(
        f"{API_BASE}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"pending": [], "draft_ready": [], "published_today": 0,
                "publish_date": ""}


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f)


def spawn_draft_agent(item_id, photos):
    """초안 생성 서브에이전트 실행 (별도 프로세스로)."""
    prompt = f"""KUROKUNI 앱 아이템 초안 작성.

item_id: {item_id}
사진 URL:
{chr(10).join(f'- {API_BASE}/uploads/{item_id}/{p}' for p in photos)}

작업:
1. 위 URL에서 사진들을 /tmp에 다운로드 후 확인
2. ~/workspace/ebay-api/ 모듈로 myvintage73의 유사 리스팅 3~5개 조회 (제목/설명/가격 참고)
3. ~/workspace/ebay-listing/style-guide.md 준수
4. 제목: VINTAGE 시작, 대문자, 80자 이내
5. 설명: 토비 스타일
6. 가격: sold comps 기반
7. 카테고리/상태/Best Offer: 유사 기존 상품에서 복사
8. 절대 금지: Promoted Listings 5%, 정가 95% 자동수락
9. 완성된 draft JSON을 /tmp/draft_{item_id}.json에 저장 후:
   curl -s -X POST -H "Content-Type: application/json" --data @/tmp/draft_{item_id}.json {API_BASE}/api/drafts/{item_id}

보고: 제목과 가격만 출력."""
    # 서브에이전트는 cron 워커가 처리하므로 여기서는 표시만
    print(f"[DRAFT] {item_id}: 에이전트 필요", flush=True)
    return False


def main():
    print("Watcher 시작", flush=True)
    seen = load_seen()
    today = time.strftime("%Y-%m-%d")

    while True:
        try:
            # 날짜 바뀌면 발행 카운터 리셋
            if seen.get("publish_date") != today:
                seen["publish_date"] = today
                seen["published_today"] = 0

            data = api_get("/api/items")
            items = data.get("items", []) if isinstance(data, dict) else data

            for it in items:
                iid = it.get("item_id")
                status = it.get("status")

                if status == "pending" and iid not in seen["pending"]:
                    seen["pending"].append(iid)
                    print(f"[NEW] pending: {iid}", flush=True)
                    # TODO: 여기서 subagent.spawn 호출 (cron 워커가 처리)

                elif status == "draft_ready" and iid not in seen["draft_ready"]:
                    # 자동 발행 안전장치 체크
                    detail = api_get(f"/api/items/{iid}")
                    draft = (detail.get("draft") or {}) if isinstance(detail, dict) else {}
                    price = float(draft.get("price_usd") or 0)
                    title = (draft.get("title") or "").strip()

                    if not title or not price:
                        print(f"[SKIP] {iid}: 제목/가격 없음", flush=True)
                        continue
                    if price < MIN_AUTO_PRICE or price > MAX_AUTO_PRICE:
                        print(f"[SKIP] {iid}: 가격 범위 초과 ${price}", flush=True)
                        continue
                    if seen["published_today"] >= MAX_DAILY_PUBLISH:
                        print(f"[SKIP] {iid}: 일일 한도 초과", flush=True)
                        continue

                    print(f"[PUBLISH] {iid}: {title[:50]} ${price}", flush=True)
                    try:
                        result = api_post(f"/publish/{iid}")
                        print(f"[PUBLISHED] {iid}: {result}", flush=True)
                        seen["draft_ready"].append(iid)
                        seen["published_today"] += 1
                    except Exception as e:
                        print(f"[FAIL] {iid}: {e}", flush=True)

            save_seen(seen)

        except Exception as e:
            print(f"[ERROR] {e}", flush=True)

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
