"""OCR 뷰어 웹 서버 (FastAPI)."""

import argparse
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from main import ocr_pdf

app = FastAPI(title="OCR 뷰어")

BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "viewer.html")


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
    p.add_argument("--port", type=int, default=8000, help="포트 (기본: 8000)")
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
