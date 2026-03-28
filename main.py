"""PDF OCR using PaddleOCR."""

import argparse
import os
import base64
import json
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from paddleocr import PaddleOCR


def _box_to_rect(box) -> list[float]:
    """Convert 4-point box to [xmin, ymin, xmax, ymax]."""
    import numpy as np

    arr = np.array(box).reshape(-1, 2)
    return [
        float(arr[:, 0].min()),
        float(arr[:, 1].min()),
        float(arr[:, 0].max()),
        float(arr[:, 1].max()),
    ]


def pdf_to_images(pdf_path: str) -> list[tuple[int, bytes, int, int]]:
    """Convert PDF pages to PNG images. Returns list of (page_index, png_bytes, width, height)."""
    doc = fitz.open(pdf_path)
    pages = []
    for i in range(len(doc)):
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=150)
        pages.append((i, pix.tobytes("png"), pix.width, pix.height))
    doc.close()
    return pages


def _resolve_paddle_device(explicit: str | None) -> str | None:
    """None / auto → Paddle 기본값(CUDA 가능 시 gpu:0, 아니면 cpu)."""
    if explicit is not None:
        s = explicit.strip()
        if not s or s.lower() == "auto":
            return None
        return s
    env = os.environ.get("PADDLE_OCR_DEVICE")
    if env is None:
        return None
    s = env.strip()
    if not s or s.lower() == "auto":
        return None
    return s


def ocr_pdf(pdf_path: str, device: str | None = None) -> list[dict]:
    """
    Perform OCR on a PDF file. Returns list of page results.
    Each page result: {"page": int, "texts": list[{"text": str, "score": float}]}
    device: None 또는 'auto'면 PaddleOCR 기본(가능하면 GPU, 아니면 CPU).
    """
    _device = _resolve_paddle_device(device)
    # PIR↔oneDNN 버그 회피: CPU 폴백 시에도 MKLDNN 경로 회피
    ocr = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        return_word_box=True,
        device=_device,
        lang="korean",
        enable_mkldnn=False,
    )

    pages = pdf_to_images(pdf_path)
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for page_idx, png_bytes, img_w, img_h in pages:
            tmp_path = Path(tmpdir) / f"page_{page_idx}.png"
            tmp_path.write_bytes(png_bytes)

            result = ocr.ocr(str(tmp_path), cls=False)
            page_texts = []

            if result and result[0]:
                for line in result[0]:
                    if line:
                        box, (text, score) = line
                        if text.strip():
                            bbox = _box_to_rect(box)
                            page_texts.append({
                                "text": text,
                                "score": float(score),
                                "bbox": bbox,
                            })

            results.append({
                "page": page_idx + 1,
                "image": base64.b64encode(png_bytes).decode(),
                "width": img_w,
                "height": img_h,
                "texts": page_texts,
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="PDF OCR using PaddleOCR")
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument(
        "--device",
        default="auto",
        metavar="STR",
        help="auto(기본) | cpu | gpu:N — auto는 CUDA 있으면 gpu:0, 없으면 cpu",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output text file path (default: print to stdout)",
    )
    parser.add_argument(
        "--json",
        "-j",
        help="Output as JSON (for viewer). Use with -o.",
        action="store_true",
    )
    args = parser.parse_args()

    dev = args.device.strip()
    results = ocr_pdf(args.pdf_path, device=None if dev.lower() == "auto" else dev)

    if args.json:
        out = args.output or "ocr_result.json"
        data = {"pages": results}
        Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OCR 결과(JSON)가 {out}에 저장되었습니다.")
    else:
        output_lines = []
        for page_result in results:
            output_lines.append(f"--- Page {page_result['page']} ---")
            for item in page_result["texts"]:
                output_lines.append(item["text"])
            output_lines.append("")

        output_text = "\n".join(output_lines)

        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
            print(f"OCR 결과가 {args.output}에 저장되었습니다.")
        else:
            print(output_text)


if __name__ == "__main__":
    main()
