"""OCR 뷰어 웹 서버 (FastAPI)."""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

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


def _absolutize_pdf_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    base = (os.environ.get("OCR_TEST_PDF_FETCH_BASE") or "http://127.0.0.1:18000").rstrip("/")
    if u.startswith("/"):
        return f"{base}{u}"
    return f"{base}/pdfs/{u}"


class BBox(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x0: Optional[float] = None
    y0: Optional[float] = None
    x1: Optional[float] = None
    y1: Optional[float] = None
    left: Optional[float] = None
    top: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None


class NavigateIn(BaseModel):
    """moleg-search / 파서 연동: 파일·페이지·조항·정규화 bbox(0~1)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    filename: str = Field(validation_alias=AliasChoices("filename", "file_name"))
    page: int = Field(ge=1, validation_alias=AliasChoices("page", "page_number"))
    pdf_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("pdf_url", "file_url", "url"),
    )
    article_title: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "article_title",
            "jo_subject",
            "subject",
            "조제목",
        ),
    )
    bbox: Optional[BBox] = None

    def normalized_navigate(self) -> dict[str, Any]:
        nbb: Optional[dict[str, float]] = None
        if self.bbox is not None:
            b = self.bbox
            nbb = {}
            if b.x0 is not None:
                nbb["x0"] = b.x0
            if b.y0 is not None:
                nbb["y0"] = b.y0
            if b.x1 is not None:
                nbb["x1"] = b.x1
            if b.y1 is not None:
                nbb["y1"] = b.y1
            if b.left is not None and b.width is not None:
                nbb.setdefault("x0", b.left)
                nbb.setdefault("x1", b.left + b.width)
            if b.top is not None and b.height is not None:
                nbb.setdefault("y0", b.top)
                nbb.setdefault("y1", b.top + b.height)
            if not nbb:
                nbb = None
        resolved = _absolutize_pdf_url(self.pdf_url or "")
        return {
            "filename": self.filename,
            "page": self.page,
            "pdf_url": resolved or None,
            "article_title": self.article_title,
            "bbox": nbb,
        }


@app.get("/")
def index():
    """pdfparser / ocr-test 기본 화면(업로드·검색 UI). ?token= 으로 세션 로드."""
    return FileResponse(BASE / "static" / "viewer.html")


@app.post("/api/navigate")
async def api_navigate(body: NavigateIn):
    """
    PDF URL을 받아 OCR 후 세션에 저장하고 token 을 반환합니다.
    뷰어: GET /?token={token}
    """
    meta = body.normalized_navigate()
    pdf_url = meta.get("pdf_url") or ""
    if not pdf_url:
        raise HTTPException(400, "pdf_url(또는 /pdfs/… 상대 경로)이 필요합니다.")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
            r = await client.get(pdf_url)
            r.raise_for_status()
            buf = r.content
    except httpx.HTTPError as e:
        raise HTTPException(502, f"PDF를 가져올 수 없습니다: {e!s}") from e

    if len(buf) > _MAX_PDF_BYTES:
        raise HTTPException(413, "PDF 용량이 제한을 초과했습니다.")

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, buf)
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
