"""KUROKUNI 리스팅 웹앱 v1.

폰에서 상품 사진을 올리면 → AI(철수)가 초안을 작성 →
사용자가 확인/수정 후 → eBay API로 발행하는 모바일 우선 웹앱.

실행:
    cd ~/workspace/ebay-app
    APP_EBAY_ENV=production python3 app.py   # 실계정 (기본값)
    APP_EBAY_ENV=sandbox python3 app.py      # 테스트

플로우:
    /upload → 사진 업로드 (상태: 분석 대기)
    철수가 drafts/<item_id>.json 작성 (또는 /review에서 직접 입력)
    /review/<id> → 초안 확인/수정
    발행 버튼 → eBay 발행 → 상태: 발행됨 (+listing ID)
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
from pathlib import Path

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)
from PIL import Image
from werkzeug.utils import secure_filename

import config
import depop
import ebay_client
import store

log = logging.getLogger("ebay-app")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024 * config.MAX_PHOTOS

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _resize_and_save(src_bytes: bytes, dest: Path) -> None:
    """모바일 사진을 리사이즈(JPEG)해서 저장."""
    img = Image.open(io.BytesIO(src_bytes))
    img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, config.PHOTO_MAX_DIM / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=85, optimize=True)


def _photo_url(item_id: str, filename: str) -> str:
    return url_for("serve_upload", item_id=item_id, filename=filename)


def _ebay_image_urls(item: dict, draft: dict | None) -> tuple[list[str], str | None]:
    """eBay 발행용 이미지 URL 목록. (urls, error)"""
    # 1) 초안에 image_urls가 직접 있으면 우선 사용 (테스트/예외용)
    if draft and draft.get("image_urls"):
        urls = [u for u in draft["image_urls"] if str(u).startswith("https://")]
        if urls:
            return urls, None
        return [], "초안의 image_urls가 https:// 로 시작하지 않습니다."
    # 2) IMAGE_BASE_URL + 업로드 파일
    if not config.IMAGE_BASE_URL:
        return [], ("이미지 공개 URL(IMAGE_BASE_URL)이 설정되지 않았습니다. "
                    "서버에 공개 https 주소를 연결한 뒤 환경변수로 지정하세요.")
    base = config.IMAGE_BASE_URL
    return [f"{base}/uploads/{item['item_id']}/{f}" for f in item["photos"]], None


def _draft_form_defaults() -> dict:
    return {
        "title": "", "description": "", "price_usd": "",
        "category": "tshirt", "condition": "USED_GOOD",
        "pit_to_pit": "", "length": "",
        "defects": "", "suggested_best_offer": True,
        "min_offer_price": "", "box_number": "",
    }


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

@app.get("/")
def index():
    items = store.list_items()
    counts = {s: 0 for s in store.STATUSES}
    for it in items:
        counts[it.get("status", "pending")] = counts.get(it.get("status"), 0) + 1
    try:
        tok = ebay_client.token_status()
    except Exception:  # noqa: BLE001
        tok = {"has_tokens": False}
    return render_template("index.html", items=items, counts=counts,
                           labels=store.STATUS_LABEL, tok=tok,
                           ebay_env=config.APP_EBAY_ENV,
                           image_base_set=bool(config.IMAGE_BASE_URL))


@app.get("/upload")
def upload_form():
    return render_template("upload.html",
                           max_mb=config.MAX_UPLOAD_MB,
                           max_photos=config.MAX_PHOTOS)


@app.post("/upload")
def upload():
    # 배치 모드: photos_0, photos_1, ... + note_0, note_1, ... + group_count
    # 단일 모드 (하위 호환): photos + note
    groups = []
    try:
        group_count = int(request.form.get("group_count", "0"))
    except ValueError:
        group_count = 0
    if group_count > 0:
        for gi in range(group_count):
            files = [f for f in request.files.getlist(f"photos_{gi}") if f and f.filename]
            if files:
                groups.append({
                    "files": files,
                    "note": (request.form.get(f"note_{gi}") or "").strip()[:500],
                })
    else:
        files = [f for f in request.files.getlist("photos") if f and f.filename]
        if files:
            groups.append({
                "files": files,
                "note": (request.form.get("note") or "").strip()[:500],
            })

    if not groups:
        return render_template("upload.html", error="사진을 1장 이상 선택하세요.",
                               max_mb=config.MAX_UPLOAD_MB,
                               max_photos=config.MAX_PHOTOS), 400

    created = []
    try:
        for g in groups:
            files = g["files"]
            if len(files) > config.MAX_PHOTOS:
                raise ValueError(f"아이템당 사진은 최대 {config.MAX_PHOTOS}장까지.")
            item_id = store.new_item_id()
            saved = []
            for i, f in enumerate(files):
                ext = Path(f.filename).suffix.lower()
                if ext not in ALLOWED_EXT:
                    ext = ".jpg"
                fname = f"{i + 1:02d}{ext if ext != '.heic' and ext != '.heif' else '.jpg'}"
                fname = secure_filename(fname)
                data = f.read()
                if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
                    raise ValueError(f"{f.filename}: {config.MAX_UPLOAD_MB}MB 초과")
                _resize_and_save(data, config.UPLOAD_DIR / item_id / fname)
                saved.append(fname)
            item = store.create_item(saved, note=g["note"], item_id=item_id)
            log.info("업로드 완료: %s (%d장)", item["item_id"], len(saved))
            created.append(item["item_id"])
    except Exception as exc:  # noqa: BLE001
        return render_template("upload.html", error=f"업로드 실패: {exc}",
                               max_mb=config.MAX_UPLOAD_MB,
                               max_photos=config.MAX_PHOTOS), 400

    if len(created) == 1:
        return redirect(url_for("item_detail", item_id=created[0]))
    return redirect(url_for("index"))


@app.get("/item/<item_id>")
def item_detail(item_id):
    item = store.load_item(item_id)
    if not item:
        abort(404)
    draft = store.load_draft(item_id)
    photo_urls = [_photo_url(item_id, f) for f in item["photos"]]
    ebay_urls, img_err = _ebay_image_urls(item, draft)
    return render_template("item.html", item=item, draft=draft,
                           labels=store.STATUS_LABEL, photos=photo_urls,
                           ebay_urls=ebay_urls, img_err=img_err)


@app.get("/review/<item_id>")
def review_form(item_id):
    item = store.load_item(item_id)
    if not item:
        abort(404)
    draft = store.load_draft(item_id) or {}
    m = draft.get("measurements") or {}
    form = _draft_form_defaults()
    form.update({
        "title": draft.get("title", ""),
        "description": draft.get("description", ""),
        "price_usd": draft.get("price_usd", ""),
        "category": draft.get("category", "tshirt"),
        "condition": draft.get("condition", "USED_GOOD"),
        "pit_to_pit": m.get("pit_to_pit", ""),
        "length": m.get("length", ""),
        "defects": draft.get("defects", ""),
        "suggested_best_offer": bool(draft.get("suggested_best_offer", True)),
        "min_offer_price": draft.get("min_offer_price", ""),
        "box_number": draft.get("box_number", ""),
    })
    photo_urls = [_photo_url(item_id, f) for f in item["photos"]]
    return render_template("review.html", item=item, form=form,
                           photos=photo_urls, has_draft=bool(draft))


@app.post("/review/<item_id>")
def review_save(item_id):
    item = store.load_item(item_id)
    if not item:
        abort(404)
    f = request.form
    try:
        price = float(f.get("price_usd") or 0)
    except ValueError:
        price = 0
    try:
        min_offer = float(f.get("min_offer_price") or 0) or None
    except ValueError:
        min_offer = None
    draft = {
        "item_id": item_id,
        "title": (f.get("title") or "").strip(),
        "description": (f.get("description") or "").strip(),
        "price_usd": price,
        "category": (f.get("category") or "tshirt").strip(),
        "condition": (f.get("condition") or "USED_GOOD").strip(),
        "measurements": {
            "pit_to_pit": (f.get("pit_to_pit") or "").strip(),
            "length": (f.get("length") or "").strip(),
        },
        "defects": (f.get("defects") or "").strip(),
        "suggested_best_offer": bool(f.get("suggested_best_offer")),
        "min_offer_price": min_offer,
        "box_number": (f.get("box_number") or "").strip(),
        "status": "draft",
        "updated_at": int(time.time()),
    }
    # 기존 초안의 image_urls가 있으면 유지
    old = store.load_draft(item_id) or {}
    if old.get("image_urls"):
        draft["image_urls"] = old["image_urls"]
    store.save_draft(item_id, draft)
    log.info("초안 저장: %s", item_id)
    return redirect(url_for("item_detail", item_id=item_id))


@app.post("/publish/<item_id>")
def publish(item_id):
    item = store.load_item(item_id)
    if not item:
        abort(404)
    draft = store.load_draft(item_id)
    if not draft:
        return render_template("item.html", item=item, draft=None,
                               labels=store.STATUS_LABEL,
                               photos=[_photo_url(item_id, f) for f in item["photos"]],
                               ebay_urls=[], img_err="초안이 없습니다. 먼저 초안을 작성하세요."), 400
    image_urls, img_err = _ebay_image_urls(item, draft)
    if img_err:
        return render_template("item.html", item=item, draft=draft,
                               labels=store.STATUS_LABEL,
                               photos=[_photo_url(item_id, f) for f in item["photos"]],
                               ebay_urls=[], img_err=img_err), 400

    # 발행 전 검증 (API 호출 없음)
    try:
        preview = ebay_client.dry_run_validate(item, draft, image_urls)
    except Exception as exc:  # noqa: BLE001
        store.set_status(item_id, "failed", error=f"검증 실패: {exc}"[:500])
        return redirect(url_for("item_detail", item_id=item_id))
    warnings = preview.get("warnings", [])

    store.set_status(item_id, "publishing", error=None)
    try:
        result = ebay_client.publish_item(item, draft, image_urls)
    except Exception as exc:  # noqa: BLE001
        store.set_status(item_id, "failed", error=str(exc)[:500])
        log.warning("발행 실패: %s: %s", item_id, exc)
        return redirect(url_for("item_detail", item_id=item_id))

    store.set_status(item_id, "published",
                     listing_id=result.get("listing_id"),
                     offer_id=result.get("offer_id"),
                     published_at=int(time.time()), error=None)
    log.info("발행 완료: %s -> listing %s", item_id, result.get("listing_id"))
    return redirect(url_for("item_detail", item_id=item_id))


@app.get("/uploads/<item_id>/<filename>")
def serve_upload(item_id, filename):
    directory = config.UPLOAD_DIR / item_id
    if not directory.exists():
        abort(404)
    return send_from_directory(directory, secure_filename(filename))


# --------------------------------------------------------------------------
# JSON API (철수가 초안을 넣는 용도 + 상태 조회)
# --------------------------------------------------------------------------

def _check_api_token() -> bool:
    if not config.DRAFT_API_TOKEN:
        return True
    return request.headers.get("X-App-Token") == config.DRAFT_API_TOKEN


@app.post("/api/drafts/<item_id>")
def api_save_draft(item_id):
    if not _check_api_token():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    item = store.load_item(item_id)
    if not item:
        return jsonify({"ok": False, "error": "item not found"}), 404
    raw = request.get_data(as_text=True)
    try:
        draft = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        return jsonify({"ok": False, "error": "invalid json"}), 400
    if not isinstance(draft, dict):
        return jsonify({"ok": False, "error": "invalid json"}), 400
    store.save_draft(item_id, draft)
    return jsonify({"ok": True, "item_id": item_id, "status": "draft_ready"})


@app.get("/api/items")
def api_items():
    return jsonify({"ok": True, "items": store.list_items()})


@app.get("/api/items/<item_id>")
def api_item(item_id):
    item = store.load_item(item_id)
    if not item:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "item": item,
                    "draft": store.load_draft(item_id)})


@app.get("/health")
def health():
    return jsonify({"ok": True, "ebay_env": config.APP_EBAY_ENV})


# --------------------------------------------------------------------------
# Depop
# --------------------------------------------------------------------------

@app.post("/depop/queue/<item_id>")
def depop_queue(item_id):
    item = store.load_item(item_id)
    if not item:
        abort(404)
    draft = store.load_draft(item_id)
    err = depop.validate_for_queue(item, draft)
    if err:
        store.set_status(item_id, item["status"], depop_error=err)
        return redirect(url_for("item_detail", item_id=item_id))
    pkg = depop.build_package(item, draft, config.UPLOAD_DIR)
    store.set_status(item_id, item["status"],
                     depop_status="queued",
                     depop_price_cad=pkg["price_cad"],
                     depop_error=None, depop_url=None)
    log.info("Depop 대기열 등록: %s (C$%d)", item_id, pkg["price_cad"])
    return redirect(url_for("item_detail", item_id=item_id))


@app.get("/api/depop/queue")
def api_depop_queue():
    """브라우저 워커용: 대기열 목록 + 포스팅 패키지."""
    out = []
    for item in store.list_items():
        if item.get("depop_status") != "queued":
            continue
        draft = store.load_draft(item["item_id"])
        if not draft:
            continue
        out.append(depop.build_package(item, draft, config.UPLOAD_DIR))
    return jsonify({"ok": True, "queue": out,
                    "min_interval_sec": depop.DEPOP_MIN_INTERVAL_SEC})


@app.post("/api/depop/<item_id>/posted")
def api_depop_posted(item_id):
    if not _check_api_token():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    item = store.load_item(item_id)
    if not item:
        return jsonify({"ok": False, "error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    store.set_status(item_id, item["status"],
                     depop_status="posted",
                     depop_url=data.get("depop_url"),
                     depop_error=None)
    log.info("Depop 등록됨: %s -> %s", item_id, data.get("depop_url"))
    return jsonify({"ok": True})


@app.post("/api/depop/<item_id>/failed")
def api_depop_failed(item_id):
    if not _check_api_token():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    item = store.load_item(item_id)
    if not item:
        return jsonify({"ok": False, "error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    store.set_status(item_id, item["status"],
                     depop_status="failed",
                     depop_error=str(data.get("error", ""))[:500])
    log.warning("Depop 실패: %s: %s", item_id, data.get("error"))
    return jsonify({"ok": True})


def main() -> None:
    # 시작 시 eBay 환경 준비 (값은 출력하지 않음)
    try:
        ebay_client.prepare_environment()
        log.info("eBay 환경 준비 완료 (env=%s)", config.APP_EBAY_ENV)
    except Exception as exc:  # noqa: BLE001
        log.warning("eBay 환경 준비 실패: %s (업로드/초안은 사용 가능)",
                    ebay_client._mask_error(exc))
    app.run(host="127.0.0.1", port=config.FLASK_PORT, debug=config.FLASK_DEBUG)


if __name__ == "__main__":
    main()
