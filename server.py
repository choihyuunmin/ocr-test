"""OCR 뷰어 웹 서버 (FastAPI)."""

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
        device = os.environ.get("PADDLE_OCR_DEVICE", "cpu")
        pages = ocr_pdf(tmp_path, device=device)
        return {"pages": pages}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
