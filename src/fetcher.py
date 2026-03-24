"""
fetcher.py - Handles fetching and extracting text from papers.

Supports:
- arXiv abstract URLs (https://arxiv.org/abs/XXXX.XXXXX)
- Direct PDF URLs
- Local PDF file paths
"""

import base64
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

import fitz  # pymupdf
import requests
import arxiv


MAX_PAGES = 40
MAX_CHARS = 100_000
MAX_FIGURES = 12       # Pass 2에 전달할 최대 figure 수
MIN_FIG_SIZE = 150     # 최소 너비/높이 (px) - 아이콘/로고 제외
# Claude Vision API 지원 형식
_SUPPORTED_MEDIA = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
                    "gif": "image/gif", "webp": "image/webp"}


def _extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file using pymupdf."""
    doc = fitz.open(pdf_path)
    pages_to_read = min(len(doc), MAX_PAGES)
    texts = []
    for page_num in range(pages_to_read):
        page = doc[page_num]
        texts.append(page.get_text())
    doc.close()
    full_text = "\n".join(texts)
    if len(full_text) > MAX_CHARS:
        full_text = full_text[:MAX_CHARS] + "\n\n[... 텍스트 길이 초과로 이후 내용 생략 ...]"
    return full_text


def _extract_figures(pdf_path: str) -> list:
    """
    PDF에서 figure 이미지를 추출하여 base64 인코딩된 리스트로 반환.
    작은 이미지(아이콘, 로고 등)는 제외하고 의미 있는 figure만 추출.

    Returns:
        list of dicts: [{"page": int, "data": str(base64), "media_type": str}, ...]
    """
    doc = fitz.open(pdf_path)
    figures = []
    seen_xrefs = set()

    for page_num in range(min(len(doc), MAX_PAGES)):
        page = doc[page_num]
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            ext = base_image.get("ext", "").lower()
            media_type = _SUPPORTED_MEDIA.get(ext)
            if not media_type:
                continue  # svg, jbig2 등 미지원 형식 건너뜀

            w, h = base_image.get("width", 0), base_image.get("height", 0)
            if w < MIN_FIG_SIZE or h < MIN_FIG_SIZE:
                continue  # 너무 작은 이미지 제외

            img_b64 = base64.b64encode(base_image["image"]).decode("utf-8")
            figures.append({
                "page": page_num + 1,
                "width": w,
                "height": h,
                "data": img_b64,
                "media_type": media_type,
            })

            if len(figures) >= MAX_FIGURES:
                break

        if len(figures) >= MAX_FIGURES:
            break

    doc.close()
    return figures


def _download_pdf(url: str) -> str:
    """Download a PDF from a URL and save to a temp file. Returns the temp file path."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ResearchAgent/1.0)"
    }
    response = requests.get(url, headers=headers, timeout=60, stream=True)
    response.raise_for_status()

    suffix = ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            tmp.write(chunk)
    tmp.close()
    return tmp.name


def _parse_arxiv_id(url: str) -> Optional[str]:
    """Extract arXiv paper ID from an arXiv URL."""
    # Matches patterns like arxiv.org/abs/2310.12345 or arxiv.org/pdf/2310.12345
    pattern = r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)"
    match = re.search(pattern, url, re.IGNORECASE)
    if match:
        return match.group(1)
    # Also match older IDs like arxiv.org/abs/cs/0501001
    pattern_old = r"arxiv\.org/(?:abs|pdf)/([\w.-]+/\d+)"
    match_old = re.search(pattern_old, url, re.IGNORECASE)
    if match_old:
        return match_old.group(1)
    return None


def fetch_paper(source: str) -> dict:
    """
    Fetch a paper from arXiv URL, direct PDF URL, or local file path.

    Returns:
        dict with keys:
            - title (str): Paper title if available
            - text (str): Extracted plain text from the PDF
            - source (str): Original source (URL or path)
            - authors (list[str]): Author names if available
            - abstract (str): Abstract if available
            - arxiv_id (str | None): arXiv ID if applicable
    """
    result = {
        "title": "",
        "text": "",
        "source": source,
        "authors": [],
        "abstract": "",
        "arxiv_id": None,
        "published": None,   # datetime object
        "venue": "",         # journal/conference name
        "figures": [],       # list of extracted figure images
    }

    source = source.strip()

    # --- Case 1: arXiv URL ---
    if "arxiv.org" in source:
        arxiv_id = _parse_arxiv_id(source)
        if not arxiv_id:
            raise ValueError(f"arXiv URL에서 논문 ID를 파싱할 수 없습니다: {source}")

        result["arxiv_id"] = arxiv_id

        # Fetch metadata via arxiv library
        search = arxiv.Search(id_list=[arxiv_id], max_results=1)
        papers = list(search.results())
        if papers:
            paper_meta = papers[0]
            result["title"] = paper_meta.title
            result["authors"] = [str(a) for a in paper_meta.authors]
            result["abstract"] = paper_meta.summary.replace("\n", " ")
            result["published"] = paper_meta.published  # datetime
            result["venue"] = getattr(paper_meta, "journal_ref", "") or ""

        # Download the PDF
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        tmp_path = _download_pdf(pdf_url)
        try:
            result["text"] = _extract_text_from_pdf(tmp_path)
            result["figures"] = _extract_figures(tmp_path)
        finally:
            os.unlink(tmp_path)

    # --- Case 2: Direct PDF URL ---
    elif source.startswith("http://") or source.startswith("https://"):
        tmp_path = _download_pdf(source)
        try:
            result["text"] = _extract_text_from_pdf(tmp_path)
            result["figures"] = _extract_figures(tmp_path)
        finally:
            os.unlink(tmp_path)

        # Try to extract title from first page text heuristically
        lines = result["text"].split("\n")
        for line in lines[:10]:
            line = line.strip()
            if len(line) > 10:
                result["title"] = line
                break

    # --- Case 3: Local PDF file ---
    else:
        local_path = Path(source).expanduser().resolve()
        if not local_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {local_path}")
        if local_path.suffix.lower() != ".pdf":
            raise ValueError(f"PDF 파일이 아닙니다: {local_path}")

        result["source"] = str(local_path)
        result["text"] = _extract_text_from_pdf(str(local_path))
        result["figures"] = _extract_figures(str(local_path))

        # Try to extract title from first page text
        lines = result["text"].split("\n")
        for line in lines[:10]:
            line = line.strip()
            if len(line) > 10:
                result["title"] = line
                break

    if not result["text"].strip():
        raise ValueError("PDF에서 텍스트를 추출할 수 없습니다. 스캔된 이미지 PDF일 수 있습니다.")

    return result
