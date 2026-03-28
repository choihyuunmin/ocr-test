# OCR Test

PaddleOCR을 사용한 PDF OCR 및 웹 뷰어

## 설치

```bash
uv sync
```

## 환경 변수

- `PADDLE_OCR_DEVICE`: OCR 연산 디바이스 (기본값: `cpu`)
  - `cpu`: CPU
  - `gpu:0`: NVIDIA GPU (CUDA)
  - macOS에서는 `cpu` 사용

## 사용법

### 웹 뷰어 (PDF 업로드)

```bash
uv run python server.py
```

브라우저에서 http://localhost:8000 접속 후, "PDF 업로드"로 파일을 선택하면 서버에서 OCR을 수행하고 결과를 표시합니다. 검색창에서 단어 검색 및 위치 이동이 가능합니다.

### CLI (텍스트/JSON 출력)

```bash
# 텍스트 출력
uv run python main.py document.pdf

# JSON 출력 (뷰어용)
uv run python main.py document.pdf -j -o result.json
```
