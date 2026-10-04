#!/bin/bash
# KUROKUNI 리스팅 웹앱 시작 스크립트 (로컬 실행용)
#
# 주의 (2026-10-04): 이 VM에서는 외부 터널이 동작하지 않음
# (Cloudflare/ngrok/localtunnel 모두 프록시 환경에서 차단).
# 폰 접속이 필요하면 DEPLOY.md의 Render.com 배포 가이드를 따를 것.
#
# 재부팅 후: bash ~/workspace/ebay-app/start.sh
set -u

APP_DIR="$HOME/workspace/ebay-app"
LOG_DIR="$APP_DIR/logs"
FLASK_LOG="$LOG_DIR/flask.log"
PORT="${APP_PORT:-5000}"

mkdir -p "$LOG_DIR"
cd "$APP_DIR" || exit 1

# 기존 Flask 정리 (패턴이 자기 자신과 매칭되지 않도록 주의)
for p in $(pgrep -f "python3 app\.py"); do
    kill "$p" 2>/dev/null && echo "[start] 기존 Flask 종료: $p"
done
sleep 2

export APP_EBAY_ENV="${APP_EBAY_ENV:-production}"
export APP_PORT="$PORT"
# IMAGE_BASE_URL 미설정 시 eBay 발행이 차단됨 (로컬 테스트용)
if [ -z "${IMAGE_BASE_URL:-}" ]; then
    echo "[start] 경고: IMAGE_BASE_URL 미설정 — eBay 발행 불가 (로컬 UI 테스트만 가능)"
fi

echo "[start] Flask 앱 시작 (포트 $PORT)..."
nohup python3 app.py > "$FLASK_LOG" 2>&1 &
FLASK_PID=$!
sleep 3
if kill -0 "$FLASK_PID" 2>/dev/null; then
    echo "[start] OK — http://127.0.0.1:$PORT (PID $FLASK_PID)"
else
    echo "[start] ERROR: Flask 시작 실패"
    tail -20 "$FLASK_LOG"
    exit 1
fi
