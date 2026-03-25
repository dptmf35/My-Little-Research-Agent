"""
formatter.py - Formats analysis results into a Markdown file and saves it.
"""

import os
import re
from datetime import datetime
from pathlib import Path

REVIEWS_DIR = Path(__file__).parent.parent / "reviews"


def _sanitize_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    # Replace spaces and special chars with underscores
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "_", name).strip("_")
    return name[:80]  # Limit length


def _make_filename(paper_data: dict) -> str:
    """Generate a filename based on arXiv ID or paper title."""
    arxiv_id = paper_data.get("arxiv_id")
    if arxiv_id:
        return f"arxiv_{arxiv_id.replace('/', '_')}.md"

    title = paper_data.get("title", "").strip()
    if title:
        safe = _sanitize_filename(title)
        return f"{safe}.md"

    # Fallback: use timestamp
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"review_{ts}.md"


def format_and_save(paper_data: dict, analysis: dict) -> str:
    """
    Format the three-pass analysis into Markdown and save to reviews/ directory.

    Args:
        paper_data: Dict from fetcher.fetch_paper()
        analysis: Dict from analyzer.analyze_paper() with pass1, pass2, pass3, integrated_review

    Returns:
        Absolute path to the saved Markdown file.
    """
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    title = paper_data.get("title") or "Unknown Title"
    source = paper_data.get("source", "")
    authors = paper_data.get("authors", [])
    arxiv_id = paper_data.get("arxiv_id")
    published = paper_data.get("published")   # datetime or None
    venue = paper_data.get("venue", "")
    analyzed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    authors_str = ", ".join(authors) if authors else "Unknown"

    # Build metadata block
    meta_lines = [
        f"> **Source**: {source}  ",
        f"> **Analyzed**: {analyzed_at}  ",
        f"> **Method**: Three-Pass Approach (Integrated)  ",
    ]
    if arxiv_id:
        meta_lines.append(f"> **arXiv ID**: [{arxiv_id}](https://arxiv.org/abs/{arxiv_id})  ")
    if published:
        year = published.year
        meta_lines.append(f"> **Published**: {published.strftime('%Y-%m-%d')} ({year})  ")
    if venue:
        meta_lines.append(f"> **Venue**: {venue}  ")
    if authors:
        meta_lines.append(f"> **Authors**: {authors_str}  ")

    meta_block = "\n".join(meta_lines)

    content = f"""# {title} - Research Review

{meta_block}

---

{analysis['integrated_review']}
"""

    filename = _make_filename(paper_data)
    output_path = REVIEWS_DIR / filename

    # Handle filename collision
    if output_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = output_path.stem
        output_path = REVIEWS_DIR / f"{stem}_{ts}.md"

    output_path.write_text(content, encoding="utf-8")
    return str(output_path.resolve())
