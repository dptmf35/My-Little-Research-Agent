"""
analyzer.py - Performs three-pass analysis of a paper using Claude API.

Three-Pass Approach:
  Pass 1: Quick Scan    (~5 min)  - Big picture, key contributions
  Pass 2: Structural    (~1 hr)   - Detailed structure, methods, results
  Pass 3: Deep Dive     (~4-5 hr) - Full comprehension, methodology, insights
  Integrated Review              - Consolidated structured review
"""

import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS_PER_PASS = 6144

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

이제 논문을 더 꼼꼼히 읽고 다음을 파악하세요:
- 📖 Introduction: 연구 배경과 동기
- 🔗 Related Work: 기존 연구들과의 관계
- 💡 핵심 아이디어: 논문의 핵심 제안
- 🔬 방법론 개요: 어떤 방식으로 문제를 해결했는지
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

INTEGRATED_REVIEW_PROMPT = """당신은 논문을 체계적으로 읽는 AI 연구자입니다. 세 번의 패스 분석을 바탕으로 최종 통합 리뷰를 작성합니다.
{format_rules}
[통합 리뷰 작성]
Pass 1 분석: {{pass1_result}}
Pass 2 분석: {{pass2_result}}
Pass 3 분석: {{pass3_result}}

위 세 패스의 분석을 통합하여 아래 형식으로 완전한 논문 리뷰를 작성하세요.
각 섹션 헤딩은 ## 레벨을 사용하세요 (통합 리뷰 섹션의 서브섹션이므로 ## 사용):

## 📋 논문 기본 정보
(제목, 저자, 발표 연도/학회/저널, arXiv ID 등)

## 🎯 인트로덕션 (Introduction)
(연구 배경, 동기, 문제 정의)

## 💡 핵심 아이디어 (Key Idea)
(이 논문의 핵심 기여와 독창성)

## 📚 관련 연구 (Related Work)
(기존 연구들과의 관계, 차별점)

## 🔬 제안 방법론 (Proposed Method)
(방법론 상세, 수식/알고리즘/아키텍처 설명)

## 📊 실험 (Experiments)
(실험 설정, 주요 결과, ablation study)

## 🏁 결론 (Conclusion)
(연구 요약, 한계점, 향후 연구)

## ⭐ 총평
(이 논문의 전체적인 평가, 읽어야 할 독자층)"""

INTEGRATED_REVIEW_PROMPT = INTEGRATED_REVIEW_PROMPT.format(format_rules=_FORMAT_RULES).replace("{{pass1_result}}", "{pass1_result}").replace("{{pass2_result}}", "{pass2_result}").replace("{{pass3_result}}", "{pass3_result}")


def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.\n"
            ".env 파일을 생성하고 ANTHROPIC_API_KEY=your_key_here를 설정하세요.\n"
            "또는 export ANTHROPIC_API_KEY=your_key_here 명령을 실행하세요."
        )
    return anthropic.Anthropic(api_key=api_key)


def _call_claude(client: anthropic.Anthropic, prompt: str) -> str:
    """Make a single Claude API call and return the text response."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_PER_PASS,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )
    return message.content[0].text


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
    results = {}

    # --- Pass 1 ---
    if progress_callback:
        progress_callback("pass1")
    pass1_prompt = PASS1_PROMPT.format(text=text)
    results["pass1"] = _call_claude(client, pass1_prompt)

    # --- Pass 2 ---
    if progress_callback:
        progress_callback("pass2")
    pass2_prompt = PASS2_PROMPT.format(
        pass1_result=results["pass1"],
        text=text,
    )
    results["pass2"] = _call_claude(client, pass2_prompt)

    # --- Pass 3 ---
    if progress_callback:
        progress_callback("pass3")
    pass3_prompt = PASS3_PROMPT.format(
        pass1_result=results["pass1"],
        pass2_result=results["pass2"],
        text=text,
    )
    results["pass3"] = _call_claude(client, pass3_prompt)

    # --- Integrated Review ---
    if progress_callback:
        progress_callback("integrated")
    integrated_prompt = INTEGRATED_REVIEW_PROMPT.format(
        pass1_result=results["pass1"],
        pass2_result=results["pass2"],
        pass3_result=results["pass3"],
    )
    results["integrated_review"] = _call_claude(client, integrated_prompt)

    return results
