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
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

import fitz  # pymupdf
import requests
import arxiv


MAX_PAGES = 40
MAX_CHARS = 100_000
MAX_FIGURES = 20       # Pass 2에 전달할 최대 figure 수
MIN_FIG_SIZE = 150     # 최소 너비/높이 (px) - 아이콘/로고 제외
# Claude Vision API 지원 형식
_SUPPORTED_MEDIA = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
                    "gif": "image/gif", "webp": "image/webp"}


def _extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file using pymupdf."""
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    pages_to_read = min(total_pages, MAX_PAGES)
    texts = []
    for page_num in range(pages_to_read):
        page = doc[page_num]
        texts.append(page.get_text())
    doc.close()
    full_text = "\n".join(texts)
    full_text = full_text.replace("\x00", "")  # null byte 제거 (일부 PDF에서 발생)
    if total_pages > MAX_PAGES:
        full_text += f"\n\n[... 원본 PDF는 총 {total_pages}페이지이나 앞의 {MAX_PAGES}페이지만 사용, 이후 페이지 생략 ...]"
    if len(full_text) > MAX_CHARS:
        full_text = full_text[:MAX_CHARS] + "\n\n[... 텍스트 길이 초과로 이후 내용 생략 ...]"
    return full_text


def _extract_pdf_metadata(pdf_path: str) -> tuple:
    """
    PDF 내장 메타데이터에서 저자/venue를 시도 추출.
    arXiv API 메타데이터가 없는 소스(직접 PDF URL, 로컬 파일)에서 사용.
    메타데이터가 비어 있으면 빈 값을 반환한다 (본문 텍스트 추측은 하지 않음).
    """
    doc = fitz.open(pdf_path)
    meta = doc.metadata or {}
    doc.close()

    authors = []
    author_field = (meta.get("author") or "").strip()
    if author_field:
        authors = [a.strip() for a in re.split(r"[;,]| and | & ", author_field) if a.strip()]

    venue = (meta.get("subject") or "").strip()
    return authors, venue


_FIGURE_CAPTION_RE = re.compile(r"\b(?:Figure|Table)\s+\d+", re.IGNORECASE)
_RENDER_DPI = 150


def _extract_figures(pdf_path: str) -> list:
    """
    PDF에서 figure 이미지를 추출하여 base64 인코딩된 리스트로 반환.
    작은 이미지(아이콘, 로고 등)는 제외하고 의미 있는 figure만 추출.

    페이지 순서대로 앞에서부터 채우는 방식은 두 가지 이유로 논문 전체를
    대표하지 못한다:
    1) 하나의 복합 Figure가 여러 서브 이미지로 이루어진 페이지를 만나면 그
       Figure 혼자 MAX_FIGURES 예산을 다 써버려 나머지 Figure가 통째로 누락됨.
    2) matplotlib 등으로 그린 벡터 그래픽 차트/다이어그램은 애초에 임베디드
       래스터 이미지가 아니라서 get_images()로는 절대 추출되지 않음.

    따라서 "Figure N"/"Table N" 캡션이 있는 페이지 + 래스터 이미지가 있는
    페이지를 모두 "관심 페이지"로 모은 뒤, 예산이 허용하는 한 **모든 관심
    페이지에 최소 1장씩** 먼저 배정하고 (래스터 이미지가 있으면 그중 가장 큰
    것을, 없으면 페이지 전체를 렌더링), 예산이 남을 때만 이미지가 여러 장인
    페이지에 추가로 배정한다.

    Returns:
        list of dicts: [{"page": int, "data": str(base64), "media_type": str}, ...]
    """
    doc = fitz.open(pdf_path)
    last_page = min(len(doc), MAX_PAGES)

    page_candidates = defaultdict(list)  # page_no -> 크기 조건을 만족하는 임베디드 이미지들
    pages_with_caption = set()
    seen_xrefs = set()

    for page_num in range(last_page):
        page_no = page_num + 1
        page = doc[page_num]

        if _FIGURE_CAPTION_RE.search(page.get_text()):
            pages_with_caption.add(page_no)

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

            page_candidates[page_no].append({
                "page": page_no,
                "width": w,
                "height": h,
                "data": base_image["image"],
                "media_type": media_type,
            })

    # 페이지 내에서는 가장 큰 이미지를 그 페이지의 대표로 우선 사용
    for page_no in page_candidates:
        page_candidates[page_no].sort(key=lambda f: f["width"] * f["height"], reverse=True)

    pages_of_interest = sorted(set(page_candidates) | pages_with_caption)

    figures = []

    # 1차: 관심 페이지 전체에 최소 1장씩 배정 (래스터 우선, 없으면 페이지 렌더링)
    for page_no in pages_of_interest:
        if len(figures) >= MAX_FIGURES:
            break
        if page_candidates.get(page_no):
            figures.append(page_candidates[page_no].pop(0))
        else:
            page = doc[page_no - 1]
            pix = page.get_pixmap(dpi=_RENDER_DPI)
            figures.append({
                "page": page_no,
                "width": pix.width,
                "height": pix.height,
                "data": pix.tobytes("png"),
                "media_type": "image/png",
            })

    # 2차: 예산이 남으면 이미지가 여러 장 남은 페이지에서 추가로 채움 (라운드로빈)
    while len(figures) < MAX_FIGURES and any(page_candidates.get(p) for p in pages_of_interest):
        for page_no in pages_of_interest:
            if len(figures) >= MAX_FIGURES:
                break
            if page_candidates.get(page_no):
                figures.append(page_candidates[page_no].pop(0))

    doc.close()

    figures.sort(key=lambda f: f["page"])
    for fig in figures:
        fig["data"] = base64.b64encode(fig["data"]).decode("utf-8")

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


def fetch_paper(source: str, extract_figures: bool = True) -> dict:
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

        # Fetch metadata via arxiv library (optional - continue if rate limited)
        try:
            client = arxiv.Client(delay_seconds=3.0, num_retries=2)
            search = arxiv.Search(id_list=[arxiv_id], max_results=1)
            papers = list(client.results(search))
            if papers:
                paper_meta = papers[0]
                result["title"] = paper_meta.title
                result["authors"] = [str(a) for a in paper_meta.authors]
                result["abstract"] = paper_meta.summary.replace("\n", " ")
                result["published"] = paper_meta.published  # datetime
                result["venue"] = getattr(paper_meta, "journal_ref", "") or ""
        except Exception as e:
            print(f"  메타데이터 가져오기 실패 (무시하고 계속): {e}")

        # Download the PDF
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        tmp_path = _download_pdf(pdf_url)
        try:
            result["text"] = _extract_text_from_pdf(tmp_path)
            if extract_figures:
                result["figures"] = _extract_figures(tmp_path)
        finally:
            os.unlink(tmp_path)

    # --- Case 2: Direct PDF URL ---
    elif source.startswith("http://") or source.startswith("https://"):
        tmp_path = _download_pdf(source)
        try:
            result["text"] = _extract_text_from_pdf(tmp_path)
            if extract_figures:
                result["figures"] = _extract_figures(tmp_path)
            result["authors"], result["venue"] = _extract_pdf_metadata(tmp_path)
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
        if extract_figures:
            result["figures"] = _extract_figures(str(local_path))
        result["authors"], result["venue"] = _extract_pdf_metadata(str(local_path))

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
