# KUROKUNI 리스팅 웹앱 v1

폰에서 상품 사진을 올리면 → AI(철수)가 제목/설명/가격 초안을 만들고 →
사용자가 확인/수정 후 → eBay API로 발행하는 모바일 우선 웹앱.
eBay 발행 후 Depop(@vintagetoby) 대기열 등록도 지원.

## 실행

```bash
cd ~/workspace/ebay-app
pip install -r requirements.txt

# 실계정 (기본값)
APP_EBAY_ENV=production python3 app.py

# 테스트 (샌드박스)
APP_EBAY_ENV=sandbox python3 app.py
```

브라우저에서 http://127.0.0.1:5000 접속 (기본 포트 5000, `APP_PORT`로 변경 가능).

### 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_EBAY_ENV` | `production` | `production` \| `sandbox` |
| `APP_PORT` | `5000` | 서버 포트 |
| `IMAGE_BASE_URL` | (없음) | 업로드 사진의 공개 HTTPS 베이스 URL. 예: `https://example.com/uploads`. 미설정 시 eBay 발행 차단됨 |
| `DEPOP_USD_CAD_RATE` | `1.42` | USD→CAD 환율 (Depop 가격용) |
| `DEPOP_MIN_INTERVAL_SEC` | `270` | Depop 리스팅 간 최소 간격 (봇 감지 회피) |
| `APP_DRAFT_API_TOKEN` | (없음) | 설정 시 draft/API 호출에 `X-App-Token` 헤더 필요 |
| `APP_MAX_UPLOAD_MB` | `12` | 사진 1장당 최대 MB |
| `APP_MAX_PHOTOS` | `12` | 상품당 최대 사진 수 |

## 전체 플로우

```
1. /upload — 사진 업로드 (앞/뒤/브랜드택/사이즈택/소재택/줄자/하자)
   → 상태: "분석 대기", 사진은 uploads/<item_id>/ 에 리사이즈 저장

2. 철수가 초안 작성 — 아래 중 하나:
   a) POST /api/drafts/<item_id> 에 JSON 전송 (권장, 자동화용)
   b) /review/<item_id> 에서 직접 입력
   → 상태: "초안 완료"

3. /review/<item_id> — 초안 확인/수정 (제목/설명/가격/카테고리/상태/실측/하자/박스번호)

4. "eBay에 발행" 버튼 — dry-run 검증 → 발행 → 상태: "발행됨" (+listing ID)
   - 실패 시 eBay 에러 메시지를 그대로 표시 (예: "Brand is missing" → 초안에 aspects 추가 후 재시도)
   - 재발행 시 기존 미발행 오퍼는 자동 정리됨

5. "Depop에도 올리기" 버튼 (eBay 발행 후) — 상태: "Depop 대기"
   → 브라우저 워커가 올려주고 결과 보고 → "Depop 등록됨" (+URL)
```

### 초안 JSON 스키마

```json
{
  "item_id": "20261004-143022-ab12",
  "title": "VINTAGE 90' ... SZ LARGE",
  "description": "설명 (plain text 또는 basic HTML)",
  "price_usd": 99.0,
  "category": "tshirt",
  "condition": "USED_GOOD",
  "measurements": {"pit_to_pit": "21", "length": "28"},
  "defects": "FADED",
  "suggested_best_offer": true,
  "min_offer_price": 80.0,
  "box_number": "A-3",
  "aspects": {"Brand": "...", "Size Type": "Regular", "Department": "Men"},
  "image_urls": ["https://..."],
  "status": "draft"
}
```

- `aspects`: eBay 카테고리별 필수 Item Specifics. 누락 시 발행 에러에 명시됨.
  (예: 티셔츠 15687 → Brand, Size Type, Size, Color, Department 필수)
- `image_urls`: 직접 지정 시 우선 사용. 없으면 `IMAGE_BASE_URL` + 업로드 파일로 자동 구성.

## Depop 연동

Depop은 공식 API가 없어 브라우저 자동화로 올린다.

```
앱: "Depop에도 올리기" → depop_status=queued, C$ 가격 계산
워커(부모 에이전트): python3 depop_worker.py list → 패키지 확인
                     브라우저로 Depop에 수동/자동 포스팅 (4~5분 간격)
                     python3 depop_worker.py posted <id> --url <URL>
                     또는 python3 depop_worker.py failed <id> --error "사유"
앱: 상태 대시보드에 반영
```

- 가격: USD × 환율 → 정수로 반올림 (Depop Canada는 CAD 고정)
- 설명: 제목 + 실측 + 상태 + "Price negotiable — offers welcome." + eBay 링크
  ("Also available on Depop." 문구는 Depop 설명에서 제외)

## API 목록

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 대시보드 |
| GET/POST | `/upload` | 사진 업로드 |
| GET | `/item/<id>` | 상품 상세 + 발행/Depop 버튼 |
| GET/POST | `/review/<id>` | 초안 검토/수정 |
| POST | `/publish/<id>` | eBay 발행 |
| POST | `/depop/queue/<id>` | Depop 대기열 등록 |
| GET | `/uploads/<id>/<file>` | 사진 서빙 |
| POST | `/api/drafts/<id>` | 초안 JSON 저장 |
| GET | `/api/items`, `/api/items/<id>` | 상태 조회 |
| GET | `/api/depop/queue` | Depop 대기열 + 패키지 |
| POST | `/api/depop/<id>/posted` | Depop 성공 보고 |
| POST | `/api/depop/<id>/failed` | Depop 실패 보고 |
| GET | `/health` | 상태 체크 |

## 보안

- `.env*`, `.tokens*` 파일의 키/토큰 값은 코드·로그·API 응답에 절대 노출하지 않음
- 토큰 파일은 600 권한 유지, 서버가 환경별 원본과 자동 동기화
- 이 서버는 localhost 전용. 외부 공개 시 반드시 리버스 프록시 + HTTPS + 인증 적용할 것
- `IMAGE_BASE_URL`이 공개 HTTPS여야 eBay가 사진을 가져갈 수 있음

## 남은 작업 (배포)

1. **공개 접속**: 폰에서 접속하려면 서버를 외부에 노출해야 함
   (예: Cloudflare Tunnel, Tailscale, 또는 VPS + nginx + HTTPS)
2. **이미지 호스팅**: `IMAGE_BASE_URL`에 공개 HTTPS 주소 설정
   (업로드 디렉토리를 그대로 서빙하면 됨)
3. **프로세스 관리**: systemd/supervisor 등록 (현재는 수동 실행)
4. **WSGI**: 운영 시 gunicorn 등 WSGI 서버 사용 권장

## 테스트 결과 (2026-10-04)

- 업로드→초안→리뷰→발행 전체 플로우: ✅ (Production 발행 성공, listing 278433695569, 즉시 삭제)
- 에러 케이스: 빈 업로드 400, 없는 상품 404, 초안 없이 발행 400, 잘못된 JSON 400 ✅
- Depop: 대기열→패키지→posted 보고 ✅ (C$ 변환, eBay 링크 포함 확인)
- 발견한 이슈와 수정:
  - 재발행 시 "Offer entity already exists" → 발행 전 미발행 오퍼 자동 정리 추가
  - 카테고리 필수 aspects 누락 (Brand/Size Type/Department) → draft에 `aspects` 필드 추가, 에러 메시지 그대로 표시
  - 잘못된 JSON이 빈 초안으로 저장되던 문제 → 400으로 수정
