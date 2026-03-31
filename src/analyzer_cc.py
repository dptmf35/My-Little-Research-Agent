"""
analyzer_cc.py - Claude Code CLI 버전의 논문 분석기.

API 키 없이 `claude -p` subprocess를 호출하여 Claude Code 구독을 그대로 활용.
프롬프트/로직은 analyzer.py와 동일하게 재사용하고, LLM 호출 부분만 교체.

Vision(이미지) 지원: --input-format stream-json으로 base64 이미지 전달.
"""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# 모든 프롬프트/상수는 analyzer.py에서 재사용 (중복 없이)
from src.analyzer import (
    PASS1_PROMPT,
    PASS2_PROMPT,
    PASS3_PROMPT,
    INTEGRATED_PART_A,
    INTEGRATED_PART_B,
    INTEGRATED_PART_C_DYNAMIC,
    INTEGRATED_PART_C_FALLBACK,
    _FIGURE_SECTION,
    MAX_TOKENS,
    _extract_section_list,
)

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_CC_TIMEOUT = int(os.environ.get("CLAUDE_CC_TIMEOUT", "600"))  # 초 (기본 10분)


def _subprocess_env() -> dict:
    """ANTHROPIC_API_KEY를 제거한 환경변수 반환. Claude.ai 구독 사용을 강제."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _call_claude_cc(prompt: str, figures: list = None) -> str:
    """
    `claude -p` subprocess로 Claude 호출.

    - figures 없음: 단순 텍스트 프롬프트
    - figures 있음: stream-json input format으로 멀티모달 메시지 전송
    """
    if figures:
        return _call_claude_cc_multimodal(prompt, figures)

    result = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=CLAUDE_CC_TIMEOUT,
        env=_subprocess_env(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:500]
        raise RuntimeError(
            f"claude CLI 오류 (exit {result.returncode}):\n{detail}"
        )
    return result.stdout.strip()


def _call_claude_cc_multimodal(prompt: str, figures: list) -> str:
    """
    stream-json input format으로 텍스트 + 이미지 함께 전송.

    각 figure는 {"data": "<base64>", "media_type": "image/png",
                  "page": N, "width": W, "height": H} 형식.
    """
    content = [{"type": "text", "text": prompt}]
    for i, fig in enumerate(figures):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": fig["media_type"],
                "data": fig["data"],
            },
        })
        content.append({
            "type": "text",
            "text": f"[Figure {i + 1} - page {fig['page']}, {fig['width']}×{fig['height']}px]",
        })

    message_line = json.dumps({
        "type": "user",
        "message": {"role": "user", "content": content},
    })

    result = subprocess.run(
        [
            CLAUDE_BIN, "-p",
            "--input-format", "stream-json",
            "--output-format", "text",
        ],
        input=message_line,
        capture_output=True,
        text=True,
        timeout=CLAUDE_CC_TIMEOUT,
        env=_subprocess_env(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:500]
        raise RuntimeError(
            f"claude CLI 멀티모달 오류 (exit {result.returncode}):\n{detail}"
        )
    return result.stdout.strip()


def analyze_paper(paper_data: dict, progress_callback=None) -> dict:
    """
    Three-Pass 분석 수행 (Claude Code CLI 버전).

    인터페이스는 analyzer.analyze_paper()와 동일.

    Args:
        paper_data: fetcher.fetch_paper() 반환값
                    keys: title, text, source, authors, abstract, arxiv_id, figures
        progress_callback: Optional callable(pass_name: str)

    Returns:
        Dict with keys: pass1, pass2, pass3, integrated_review
    """
    text = paper_data.get("text", "")
    figures = paper_data.get("figures", [])
    results = {}

    # --- Pass 1 ---
    if progress_callback:
        progress_callback("pass1")
    results["pass1"] = _call_claude_cc(PASS1_PROMPT.format(text=text))
    section_list = _extract_section_list(results["pass1"])

    # --- Pass 2 (멀티모달: 텍스트 + figures) ---
    if progress_callback:
        progress_callback("pass2")
    results["pass2"] = _call_claude_cc(
        PASS2_PROMPT.format(pass1_result=results["pass1"], text=text),
        figures=figures,
    )

    # --- Pass 3 ---
    if progress_callback:
        progress_callback("pass3")
    results["pass3"] = _call_claude_cc(
        PASS3_PROMPT.format(
            pass1_result=results["pass1"],
            pass2_result=results["pass2"],
            text=text,
        )
    )

    # --- Integrated Review (3개 파트 병렬 실행) ---
    if progress_callback:
        progress_callback("integrated")

    figure_section = _FIGURE_SECTION if figures else ""
    fmt = dict(
        pass1_result=results["pass1"],
        pass2_result=results["pass2"],
        pass3_result=results["pass3"],
    )

    if section_list:
        section_list_str = "\n".join(f"- {s}" for s in section_list)
        part_c_prompt = INTEGRATED_PART_C_DYNAMIC.format(
            **fmt,
            section_list=section_list_str,
            figure_section=figure_section,
        )
    else:
        part_c_prompt = INTEGRATED_PART_C_FALLBACK.format(
            **fmt,
            figure_section=figure_section,
        )

    parts = {
        "A": INTEGRATED_PART_A.format(**fmt),
        "B": INTEGRATED_PART_B.format(**fmt),
        "C": part_c_prompt,
    }
    part_results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_call_claude_cc, prompt): key
            for key, prompt in parts.items()
        }
        for future in as_completed(futures):
            part_results[futures[future]] = future.result()

    results["integrated_review"] = (
        part_results["A"] + "\n\n" + part_results["B"] + "\n\n" + part_results["C"]
    )

    return results
