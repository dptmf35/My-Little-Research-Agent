"""
analyzer.py - Performs three-pass analysis of a paper using Claude API.

Three-Pass Approach:
  Pass 1: Quick Scan    (~5 min)  - Big picture, key contributions
  Pass 2: Structural    (~1 hr)   - Detailed structure, methods, results
  Pass 3: Deep Dive     (~4-5 hr) - Full comprehension, methodology, insights
  Integrated Review              - Consolidated structured review
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = {
    "pass1": 4096,
    "pass2": 5120,
    "pass3": 6144,
    "integrated_part": 4096,   # 파트별 (3개 병렬)
}
MAX_CONTINUATIONS = 3  # 최대 이어쓰기 횟수

_FORMAT_RULES = """
## 마크다운 포맷 규칙 (반드시 준수)
- 응답 맨 앞에 제목(타이틀)을 쓰지 마세요. 내용부터 바로 시작하세요.
- 헤딩은 ### 또는 그 이하 레벨만 사용하세요. (#, ## 사용 금지)
- 섹션 구분에 --- 수평선을 사용하지 마세요. 빈 줄로만 구분하세요.
- 수식: 별도 줄 수식은 $$...$$, 인라인 수식은 $...$  형식을 사용하세요.
- 아키텍처 다이어그램/ASCII 아트는 반드시 ```text ... ``` 코드 블록 안에 작성하세요.
- 표(테이블)는 표준 마크다운 형식을 사용하고, 헤더 구분자에 정렬을 명시하세요.
  예: | 열1 | 열2 | 열3 |\\n|:---|:---:|---:|
"""

# 통합 리뷰 전용 포맷 규칙: ## 허용 (통합 리뷰의 최상위 섹션에 사용)
_FORMAT_RULES_INTEGRATED = """
## 마크다운 포맷 규칙 (반드시 준수)
- 응답 맨 앞에 제목(타이틀)을 쓰지 마세요. 내용부터 바로 시작하세요.
- 최상위 섹션 헤딩은 반드시 ## 레벨을 사용하세요. (# 사용 금지)
- 서브 섹션은 ### 또는 #### 을 사용하세요.
- 섹션 구분에 --- 수평선을 사용하지 마세요. 빈 줄로만 구분하세요.
- 수식: 별도 줄 수식은 $$...$$, 인라인 수식은 $...$  형식을 사용하세요.
- 아키텍처 다이어그램/ASCII 아트는 반드시 ```text ... ``` 코드 블록 안에 작성하세요.
- 표(테이블)는 표준 마크다운 형식을 사용하고, 헤더 구분자에 정렬을 명시하세요.
  예: | 열1 | 열2 | 열3 |\\n|:---|:---:|---:|
"""

PASS1_PROMPT = """당신은 논문을 체계적으로 읽는 AI 연구자입니다. Three-Pass Approach의 첫 번째 패스를 수행합니다.
{format_rules}
[Pass 1: Quick Scan - 5분 훑어보기]
다음 논문의 제목, 초록, 섹션 헤더, 결론을 빠르게 훑어보고 다음을 파악하세요:
- 📌 논문의 핵심 주제 (1-2문장)
- 🏷️ 연구 분야/카테고리
- 🎯 주요 기여/주장 (bullet 3-5개)
- ❓ 이 논문이 해결하려는 문제
- ⭐ 읽을 가치 평가 (1-10점) + 이유

논문 내용:
{{text}}"""

PASS1_PROMPT = PASS1_PROMPT.format(format_rules=_FORMAT_RULES).replace("{{text}}", "{text}")

PASS2_PROMPT = """당신은 논문을 체계적으로 읽는 AI 연구자입니다. Three-Pass Approach의 두 번째 패스를 수행합니다.
{format_rules}
[Pass 2: Structural Understanding - 구조 파악]
Pass 1 요약: {{pass1_result}}

이제 논문 텍스트와 첨부된 Figure/Table 이미지들을 꼼꼼히 읽고 분석하세요.
Three-Pass Approach 2단계의 핵심은 **그림, 도표, 그래프를 실제로 자세히 보는 것**입니다.

다음 항목을 분석하세요:
- 📖 Introduction: 연구 배경과 동기
- 🔗 Related Work: 기존 연구들과의 관계
- 💡 핵심 아이디어: 논문의 핵심 제안
- 🔬 방법론 개요: 어떤 방식으로 문제를 해결했는지
- 🖼️ Figure/Table 분석: **첨부된 모든 이미지를 하나씩 설명하세요**
  - 각 Figure/Table의 번호(추정), 제목, 내용을 상세히 기술
  - 그래프라면: x축/y축 의미, 비교 대상, 주요 수치 및 트렌드
  - 아키텍처 다이어그램이라면: 구성 요소, 데이터 흐름, 핵심 설계
  - 결과 테이블이라면: 비교 방법들, 주요 수치, 제안 방법의 우위
- 📊 실험 결과 요약: 주요 수치와 비교 결과
- ⚠️ 놓친 부분이나 이해 안 된 부분

논문 내용:
{{text}}"""

PASS2_PROMPT = PASS2_PROMPT.format(format_rules=_FORMAT_RULES).replace("{{pass1_result}}", "{pass1_result}").replace("{{text}}", "{text}")

PASS3_PROMPT = """당신은 논문을 체계적으로 읽는 AI 연구자입니다. Three-Pass Approach의 세 번째 패스를 수행합니다.
{format_rules}
[Pass 3: Deep Dive - 심층 분석]
Pass 1 요약: {{pass1_result}}
Pass 2 요약: {{pass2_result}}

이제 논문을 완전히 이해하기 위한 심층 분석을 수행하세요:
- 🏗️ 방법론 세부사항: 수식, 알고리즘, 아키텍처 상세 설명
- 📈 실험 세부 분석: 각 실험의 의미와 ablation study 해석
- 🔍 숨겨진 인사이트: 논문에서 명시적으로 언급되지 않은 중요한 점
- 💪 강점: 이 논문이 잘 한 것
- 😤 약점/한계: 개선이 필요한 부분
- 🚀 향후 연구 방향: 이 논문이 열어준 가능성

논문 내용:
{{text}}"""

PASS3_PROMPT = PASS3_PROMPT.format(format_rules=_FORMAT_RULES).replace("{{pass1_result}}", "{pass1_result}").replace("{{pass2_result}}", "{pass2_result}").replace("{{text}}", "{text}")

_INTEGRATED_BASE = """당신은 논문을 체계적으로 읽는 AI 연구자입니다. 세 번의 패스 분석을 바탕으로 통합 리뷰의 일부를 작성합니다.
{format_rules}
Pass 1 분석: {{pass1_result}}
Pass 2 분석: {{pass2_result}}
Pass 3 분석: {{pass3_result}}

위 분석을 바탕으로 아래 섹션들만 작성하세요. 각 섹션 헤딩은 ## 레벨을 사용하세요.
"""

# 병렬 실행할 3개 파트
INTEGRATED_PART_A = (_INTEGRATED_BASE + """
## 📋 논문 기본 정보
(제목, 저자, 발표 연도/학회/저널, arXiv ID 등)

## 🎯 인트로덕션 (Introduction)
(연구 배경, 동기, 문제 정의)

## 💡 핵심 아이디어 (Key Idea)
(이 논문의 핵심 기여와 독창성)

## 📚 관련 연구 (Related Work)
(기존 연구들과의 관계, 차별점)""").format(format_rules=_FORMAT_RULES_INTEGRATED).replace("{{pass1_result}}", "{pass1_result}").replace("{{pass2_result}}", "{pass2_result}").replace("{{pass3_result}}", "{pass3_result}")

INTEGRATED_PART_B = (_INTEGRATED_BASE + """
## 🔬 제안 방법론 (Proposed Method)
(방법론 상세, 핵심 수식/알고리즘/아키텍처, 설계 선택의 이유)""").format(format_rules=_FORMAT_RULES_INTEGRATED).replace("{{pass1_result}}", "{pass1_result}").replace("{{pass2_result}}", "{pass2_result}").replace("{{pass3_result}}", "{pass3_result}")

INTEGRATED_PART_C = (_INTEGRATED_BASE + """
## 📊 실험 (Experiments)
(실험 설정, 주요 결과, ablation study)

## 🏁 결론 (Conclusion)
(연구 요약, 한계점, 향후 연구)

## ⭐ 총평
(이 논문의 전체적인 평가, 읽어야 할 독자층)""").format(format_rules=_FORMAT_RULES_INTEGRATED).replace("{{pass1_result}}", "{pass1_result}").replace("{{pass2_result}}", "{pass2_result}").replace("{{pass3_result}}", "{pass3_result}")


def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.\n"
            ".env 파일을 생성하고 ANTHROPIC_API_KEY=your_key_here를 설정하세요.\n"
            "또는 export ANTHROPIC_API_KEY=your_key_here 명령을 실행하세요."
        )
    return anthropic.Anthropic(api_key=api_key)


def _call_claude(client: anthropic.Anthropic, prompt: str, max_tokens: int,
                 figures: list = None) -> str:
    """
    Claude API 호출 (텍스트 + 선택적 이미지).
    응답이 max_tokens에 도달하면 자동으로 이어쓰기 요청.
    최대 MAX_CONTINUATIONS번 반복하여 완전한 응답을 반환한다.

    Args:
        figures: fetcher에서 추출한 figure 리스트. 있으면 멀티모달 요청.
    """
    # 첫 번째 user 메시지 content 구성
    if figures:
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
                "text": f"[Figure {i+1} - page {fig['page']}, {fig['width']}×{fig['height']}px]",
            })
    else:
        content = prompt

    messages = [{"role": "user", "content": content}]
    full_text = ""

    for _ in range(1 + MAX_CONTINUATIONS):
        message = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            messages=messages,
        )
        chunk = message.content[0].text
        full_text += chunk

        if message.stop_reason != "max_tokens":
            break

        messages.append({"role": "assistant", "content": chunk})
        messages.append({"role": "user", "content": "방금 작성하다 멈춘 부분부터 자연스럽게 이어서 계속 작성해주세요."})

    return full_text


def analyze_paper(paper_data: dict, progress_callback=None) -> dict:
    """
    Perform three-pass analysis on the paper.

    Args:
        paper_data: Dict from fetcher.fetch_paper() with keys: title, text, source, authors, abstract, arxiv_id
        progress_callback: Optional callable(pass_name: str) called before each pass

    Returns:
        Dict with keys: pass1, pass2, pass3, integrated_review
    """
    client = _get_client()
    text = paper_data.get("text", "")
    figures = paper_data.get("figures", [])
    results = {}

    # --- Pass 1 ---
    if progress_callback:
        progress_callback("pass1")
    results["pass1"] = _call_claude(client, PASS1_PROMPT.format(text=text), MAX_TOKENS["pass1"])

    # --- Pass 2 (멀티모달: 텍스트 + figures) ---
    if progress_callback:
        progress_callback("pass2")
    results["pass2"] = _call_claude(
        client,
        PASS2_PROMPT.format(pass1_result=results["pass1"], text=text),
        MAX_TOKENS["pass2"],
        figures=figures,
    )

    # --- Pass 3 ---
    if progress_callback:
        progress_callback("pass3")
    results["pass3"] = _call_claude(
        client,
        PASS3_PROMPT.format(pass1_result=results["pass1"], pass2_result=results["pass2"], text=text),
        MAX_TOKENS["pass3"],
    )

    # --- Integrated Review (3개 파트 병렬 실행) ---
    if progress_callback:
        progress_callback("integrated")

    fmt = dict(
        pass1_result=results["pass1"],
        pass2_result=results["pass2"],
        pass3_result=results["pass3"],
    )
    parts = {
        "A": INTEGRATED_PART_A.format(**fmt),
        "B": INTEGRATED_PART_B.format(**fmt),
        "C": INTEGRATED_PART_C.format(**fmt),
    }
    part_results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_call_claude, client, prompt, MAX_TOKENS["integrated_part"]): key
            for key, prompt in parts.items()
        }
        for future in as_completed(futures):
            part_results[futures[future]] = future.result()

    results["integrated_review"] = (
        part_results["A"] + "\n\n" + part_results["B"] + "\n\n" + part_results["C"]
    )

    return results
