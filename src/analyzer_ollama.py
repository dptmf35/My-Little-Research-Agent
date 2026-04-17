"""
analyzer_ollama.py - Three-pass analysis using local Ollama models (e.g., Gemma 4).
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import ollama

from .analyzer import (
    PASS1_PROMPT, PASS2_PROMPT, PASS3_PROMPT,
    INTEGRATED_PART_A, INTEGRATED_PART_B,
    INTEGRATED_PART_C_DYNAMIC, INTEGRATED_PART_C_FALLBACK,
    _FIGURE_SECTION, _extract_section_list, MAX_CONTINUATIONS,
)

_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_MODEL_ALIASES = {
    "gemma4": "gemma4:e4b",
    "gemma3": "gemma3:4b",
}

_MAX_TOKENS = {
    "pass1": 4096,
    "pass2": 5120,
    "pass3": 6144,
    "integrated_part": 5120,
}

_CTX_WINDOW = 32768  # Ollama context window (num_ctx)


def resolve_model_name(model: str) -> str:
    """gemma4 → gemma4:4b 같은 단축 별칭 해소."""
    return _MODEL_ALIASES.get(model, model)


def check_connection(model: str):
    """Ollama 서버 연결 및 모델 존재 여부 확인."""
    client = ollama.Client(host=_OLLAMA_HOST)
    try:
        client.show(model)
    except ollama.ResponseError as e:
        msg = str(e).lower()
        if "not found" in msg or "404" in msg:
            raise RuntimeError(
                f"Ollama 모델 '{model}'이 없습니다.\n"
                f"  → 다운로드: ollama pull {model}"
            ) from e
        raise RuntimeError(f"Ollama 오류: {e}") from e
    except Exception as e:
        raise RuntimeError(
            f"Ollama 서버({_OLLAMA_HOST})에 연결할 수 없습니다.\n"
            f"  → Ollama 실행 확인: ollama serve\n"
            f"  → 오류: {e}"
        ) from e


def _call_ollama(model: str, prompt: str, max_tokens: int, figures: list = None) -> str:
    """Ollama 모델 호출 (텍스트 + 선택적 Vision). max_tokens 도달 시 자동 이어쓰기."""
    client = ollama.Client(host=_OLLAMA_HOST)
    options = {"num_predict": max_tokens, "num_ctx": _CTX_WINDOW}

    if figures:
        images = [fig["data"] for fig in figures]
        labels = "\n".join(
            f"[Figure {i+1} - page {fig['page']}, {fig['width']}×{fig['height']}px]"
            for i, fig in enumerate(figures)
        )
        messages = [{"role": "user", "content": f"{prompt}\n\n{labels}", "images": images}]
    else:
        messages = [{"role": "user", "content": prompt}]

    full_text = ""
    for _ in range(1 + MAX_CONTINUATIONS):
        response = client.chat(model=model, messages=messages, options=options)
        chunk = response.message.content
        full_text += chunk

        if response.done_reason != "length":
            break

        messages.append({"role": "assistant", "content": chunk})
        messages.append({"role": "user", "content": "방금 작성하다 멈춘 부분부터 자연스럽게 이어서 계속 작성해주세요."})

    return full_text


def analyze_paper(paper_data: dict, progress_callback=None, model: str = "gemma4:4b") -> dict:
    """Ollama 로컬 모델로 Three-Pass 논문 분석 수행."""
    text = paper_data.get("text", "")
    figures = paper_data.get("figures", [])
    results = {}

    if progress_callback:
        progress_callback("pass1")
    results["pass1"] = _call_ollama(model, PASS1_PROMPT.format(text=text), _MAX_TOKENS["pass1"])
    section_list = _extract_section_list(results["pass1"])

    if progress_callback:
        progress_callback("pass2")
    results["pass2"] = _call_ollama(
        model,
        PASS2_PROMPT.format(pass1_result=results["pass1"], text=text),
        _MAX_TOKENS["pass2"],
        figures=figures,
    )

    if progress_callback:
        progress_callback("pass3")
    results["pass3"] = _call_ollama(
        model,
        PASS3_PROMPT.format(
            pass1_result=results["pass1"],
            pass2_result=results["pass2"],
            text=text,
        ),
        _MAX_TOKENS["pass3"],
    )

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
            **fmt, section_list=section_list_str, figure_section=figure_section
        )
    else:
        part_c_prompt = INTEGRATED_PART_C_FALLBACK.format(**fmt, figure_section=figure_section)

    parts = {
        "A": INTEGRATED_PART_A.format(**fmt),
        "B": INTEGRATED_PART_B.format(**fmt),
        "C": part_c_prompt,
    }
    part_results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_call_ollama, model, prompt, _MAX_TOKENS["integrated_part"]): key
            for key, prompt in parts.items()
        }
        for future in as_completed(futures):
            part_results[futures[future]] = future.result()

    results["integrated_review"] = (
        part_results["A"] + "\n\n" + part_results["B"] + "\n\n" + part_results["C"]
    )
    return results
