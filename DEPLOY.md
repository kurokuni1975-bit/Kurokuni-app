# KUROKUNI 앱 폰 접속 — 배포 가이드

## 현재 상태 (2026-10-04)
이 VM에서는 외부 터널이 동작하지 않음. 시도한 방법과 결과:
- Cloudflare Tunnel: Go 클라이언트가 프록시와 TLS 호환 안 됨 (등록 API는 Python으로 성공, 엣지 연결 불가 — UDP/TCP 7844 차단)
- ngrok: 무료 플랜은 프록시 환경에서 동작 안 함 (유료 기능)
- localtunnel: Node 클라이언트가 프록시와 호환 안 됨
- SSH 터널: 프록시가 차단

## 권장 방법: Render.com 무료 배포

### 1단계: GitHub에 코드 올리기 (1회)
```bash
cd ~/workspace/ebay-app
git init && git add . && git commit -m "KUROKUNI app v1"
# GitHub에서 새 저장소 만들고 push
```

### 2단계: Render 가입 및 배포 (무료)
1. https://render.com 가입 (GitHub 계정으로 가능)
2. New > Web Service > GitHub 저장소 연결
3. `render.yaml`이 자동 인식됨 → Create Web Service
4. 발급 URL 예: `https://kurokuni-ebay-app.onrender.com`

### 3단계: 환경변수 설정 (Render 대시보드)
- `IMAGE_BASE_URL` = `https://kurokuni-ebay-app.onrender.com` (발급된 URL)
- eBay API 키/토큰: Secret Files로 `.env.production`, `.tokens.production.json` 업로드
  (키는 절대 GitHub에 올리지 말 것)

### 4단계: 폰에서 접속
- 발급된 URL을 폰 브라우저로 열기
- 홈 화면에 추가하면 앱처럼 사용 가능

## 대안: 채팅 방식 (지금 바로 가능)
별도 설정 없이 폰에서 사진을 채팅으로 보내면 철수가 초안 작성 → 확인 → 발행.
