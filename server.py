"""OCR 뷰어 웹 서버 (FastAPI)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from main import ocr_pdf

app = FastAPI(title="OCR 뷰어")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

_STORE_LOCK = Lock()
_SESSIONS: dict[str, tuple[dict[str, Any], float]] = {}
TTL_SEC = 3600
_MAX_PDF_BYTES = int(os.environ.get("OCR_TEST_MAX_PDF_BYTES", str(80 * 1024 * 1024)))


def _clean_expired() -> None:
    now = time.time()
    for key in [k for k, (_, ts) in _SESSIONS.items() if now - ts > TTL_SEC]:
        del _SESSIONS[key]


@app.get("/")
def index():
    """pdfparser / ocr-test 기본 화면(업로드·검색 UI). ?token= 으로 세션 로드."""
    return FileResponse(BASE / "static" / "viewer.html")


def _navigate_response(pages: list[Any], meta: dict[str, Any]) -> dict[str, Any]:
    payload = {"pages": pages, "navigate": meta}
    token = str(uuid.uuid4())
    with _STORE_LOCK:
        _clean_expired()
        _SESSIONS[token] = (payload, time.time())
    return {
        "token": token,
        "query": f"token={token}",
        "viewer_path": f"/?token={token}",
        "expires_in": TTL_SEC,
    }


async def _ocr_pdf_bytes(raw: bytes, meta: dict[str, Any]) -> dict[str, Any]:
    if len(raw) > _MAX_PDF_BYTES:
        raise HTTPException(413, "PDF 용량이 제한을 초과했습니다.")
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, raw)
        os.close(fd)
        fd = -1
        pages = await asyncio.to_thread(ocr_pdf, tmp_path)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        Path(tmp_path).unlink(missing_ok=True)
    return _navigate_response(pages, meta)


@app.post("/api/navigate")
async def api_navigate(request: Request):
    """
    multipart/form-data만 허용: `file`(PDF) + `filename`, `page`, `article_title`, `bbox`(JSON 문자열).
    moleg-search는 브라우저가 moleg-app 등에서 PDF를 받은 뒤 본문만 전송합니다.
    ocr-test는 pdf_url로 재요청하지 않습니다.
    """
    ct = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in ct:
        raise HTTPException(
            415,
            "Content-Type은 multipart/form-data 이어야 합니다. PDF는 file 필드로 첨부하세요.",
        )

    form = await request.form()
    uploaded = form.get("file")
    if uploaded is None:
        raise HTTPException(400, "multipart 요청에는 file 필드가 필요합니다.")
    if not hasattr(uploaded, "read"):
        raise HTTPException(400, "유효한 파일 업로드가 아닙니다.")
    raw = await uploaded.read()  # type: ignore[union-attr]
    if not raw:
        raise HTTPException(400, "빈 파일입니다.")
    fn = str(form.get("filename") or "").strip()
    if not fn:
        fn = getattr(uploaded, "filename", None) or "document.pdf"
    try:
        page = max(1, int(form.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    at = form.get("article_title")
    article_title = str(at).strip() if at else None
    bbox = None
    bstr = form.get("bbox")
    if bstr:
        try:
            bbox = json.loads(str(bstr))
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"bbox JSON 오류: {e}") from e
    meta = {
        "filename": fn,
        "page": page,
        "pdf_url": None,
        "article_title": article_title,
        "bbox": bbox,
    }
    return await _ocr_pdf_bytes(raw, meta)


@app.get("/api/session/{token}")
def api_session(token: str):
    with _STORE_LOCK:
        _clean_expired()
        if token not in _SESSIONS:
            raise HTTPException(404, "세션이 없거나 만료되었습니다.")
        data, _ts = _SESSIONS[token]
        return data


@app.post("/api/ocr")
async def run_ocr(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 업로드 가능합니다.")

    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(content)
        tmp_path = f.name

    try:
        pages = ocr_pdf(tmp_path)
        return {"pages": pages}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OCR 뷰어 서버")
    p.add_argument(
        "--device",
        default="auto",
        metavar="STR",
        help="auto(기본) | cpu | gpu:N — auto는 CUDA 가능 시 첫 GPU, 아니면 CPU",
    )
    p.add_argument("--host", default="0.0.0.0", help="바인드 주소 (기본: 0.0.0.0)")
    p.add_argument("--port", type=int, default=18001, help="포트 (기본: 18001, moleg-app은 18000)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    dev = args.device.strip()
    if dev.lower() == "auto":
        os.environ.pop("PADDLE_OCR_DEVICE", None)
    else:
        os.environ["PADDLE_OCR_DEVICE"] = dev

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
