# My Little Research Agent 🔬

논문 링크 하나만 던져주면 **Three-Pass Approach**로 논문을 깊이 분석하고, 읽기 좋은 마크다운 리뷰 파일로 저장해주는 나만의 AI 리서처.

---

## 빠른 시작

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. API 키 설정
cp .env.example .env
# .env 파일 열어서 ANTHROPIC_API_KEY=sk-ant-... 입력

# 3. 실행
python3 main.py https://arxiv.org/abs/1706.03762
```

결과는 `reviews/arxiv_1706.03762.md` 에 저장됩니다.

---

## 지원하는 입력 형식

| 입력 형식 | 예시 |
|:----------|:-----|
| arXiv 추상 URL | `https://arxiv.org/abs/2310.06825` |
| arXiv PDF URL | `https://arxiv.org/pdf/2310.06825` |
| 직접 PDF URL | `https://example.com/paper.pdf` |
| 로컬 PDF 파일 | `/home/user/papers/my_paper.pdf` |

---

## 출력 형식

`reviews/` 폴더에 마크다운 파일로 저장됩니다.

```
reviews/
└── arxiv_1706.03762.md    ← arXiv 논문
└── My_Paper_Title.md      ← URL/로컬 PDF
```

파일 내부 구조:

```markdown
# 논문 제목 - Research Review

> Source · Analyzed · Published · Venue · Authors

## 🔍 Pass 1: Quick Scan (개요 파악)
## 📖 Pass 2: Structural Understanding (구조 파악 + Figure 분석)
## 🧠 Pass 3: Deep Dive (심층 분석)
## 📝 통합 리뷰 (Integrated Review)
   - 📋 논문 기본 정보
   - 🎯 인트로덕션
   - 💡 핵심 아이디어
   - 📚 관련 연구
   - 🔬 제안 방법론
   - 📊 실험
   - 🏁 결론
   - ⭐ 총평
```

---

## 구현 구조

```
My-Little-Research-Agent/
├── main.py              ← CLI 진입점
├── src/
│   ├── fetcher.py       ← PDF 수집, 텍스트/Figure 추출
│   ├── analyzer.py      ← Three-Pass Claude 분석 엔진
│   └── formatter.py     ← 마크다운 포맷 & 저장
├── reviews/             ← 결과 저장 폴더
├── requirements.txt
└── .env.example
```

---

## 어떻게 동작하는가

### 1단계: PDF 수집 (`src/fetcher.py`)

입력 소스에 따라 3가지 경로로 분기합니다.

```
입력
 ├── arxiv.org URL → arxiv 라이브러리로 메타데이터(제목/저자/초록/게재년도/학회) 가져오기
 │                 → PDF URL로 변환 후 다운로드
 ├── 일반 PDF URL  → requests로 직접 다운로드
 └── 로컬 파일    → 파일 경로 직접 사용
                    ↓
              pymupdf(fitz)로 텍스트 추출 (최대 40페이지 / 100,000자)
                    +
              Figure 이미지 추출 (150px 이상, 최대 12개)
```

**토큰 초과 방지:** 최대 40페이지 / 100,000자로 제한합니다.

**Figure 필터링:** 아이콘·로고 등 작은 이미지(150px 미만)를 제외하고 의미 있는 그래프·다이어그램·테이블만 추출합니다.

---

### 2단계: Three-Pass 분석 (`src/analyzer.py`)

논문을 한 번에 분석하지 않고, **사람이 논문을 읽는 방식**을 그대로 모방합니다.
각 패스의 결과가 다음 패스의 컨텍스트로 누적됩니다.

```
논문 텍스트
    │
    ▼
[Pass 1 - Quick Scan]     텍스트만
"5분 훑어보기: 핵심 주제/기여/가치 평가"
    │  결과: pass1_result
    ▼
[Pass 2 - Structural]     텍스트 + Figure 이미지 (Vision API)
"Introduction/Related Work/방법론 구조 파악
 + 모든 Figure를 실제로 보고 하나씩 분석"
    │  결과: pass2_result
    ▼
[Pass 3 - Deep Dive]      텍스트만
"수식/알고리즘/인사이트/강약점 심층 분석"
    │  결과: pass3_result
    ▼
[통합 리뷰]               pass1 + pass2 + pass3 결과 통합
"최종 구조화된 리뷰 생성"
```

**누적 컨텍스트:** Pass 3는 Pass 1, 2 결과를 모두 알고 있는 상태에서 더 깊은 분석을 수행합니다. 사람이 논문을 세 번 읽는 것과 같은 효과입니다.

**Pass 2 Vision 분석:** Three-Pass Approach 2단계의 핵심은 "그림과 도표를 실제로 보는 것"입니다. PDF에서 추출한 Figure 이미지를 Claude Vision API로 전달하여 다음을 분석합니다:
- 그래프: x축/y축 의미, 비교 대상, 수치 트렌드
- 아키텍처 다이어그램: 구성 요소, 데이터 흐름, 설계 의도
- 결과 테이블: 비교 방법들, 주요 수치, 제안 방법의 우위

**자동 이어쓰기:** 응답이 토큰 한도에 도달하면 자동으로 멀티턴 대화로 이어서 생성합니다 (최대 3회 연장).

**패스별 토큰 한도:**

| 패스 | max_tokens |
|:-----|:----------:|
| Pass 1 | 4,096 |
| Pass 2 | 5,120 |
| Pass 3 | 6,144 |
| 통합 리뷰 | 8,192 |

**사용 모델:** `claude-sonnet-4-6`

---

### 3단계: 저장 (`src/formatter.py`)

분석 결과를 마크다운으로 조립하고 `reviews/` 폴더에 저장합니다.

메타 블록 (arXiv 논문 기준):
```
> Source · Analyzed · Method · arXiv ID · Published: 2017-06-12 (2017) · Venue · Authors
```

파일명 우선순위:
1. arXiv ID → `arxiv_1706.03762.md`
2. 논문 제목 → `Attention_Is_All_You_Need.md`
3. 둘 다 없음 → `review_20260324_143022.md`

같은 이름 파일이 이미 있으면 타임스탬프를 붙여 충돌 방지.

---

### CLI (`main.py`)

`rich` 라이브러리로 진행 상황을 표시합니다.

```
╭─────────────────────────────────╮
│   🔬 AI Research Paper Analyzer  │
│   Three-Pass Approach | Claude   │
╰─────────────────────────────────╯

📥 논문 가져오는 중...
┌──────────────────────────────────────────┐
│ Attention Is All You Need                │
│ Ashish Vaswani, Noam Shazeer, ...        │
│                                          │
│ 텍스트 추출 완료: 87,432 자              │
│ Figure 추출 완료: 8개 (Pass 2 Vision 분석) │
└──────────────────────────────────────────┘

🧠 Three-Pass Analysis 시작

  ⠋ Pass 1: Quick Scan (개요 파악) ...              0:00:08
  ⠋ Pass 2: Structural Understanding (구조 파악) ... 0:00:35
  ⠋ Pass 3: Deep Dive (심층 분석) ...               0:01:02
  ⠋ 통합 리뷰: Integrated Review 생성 중 ...        0:01:48

✓ 모든 패스 완료!

💾 결과 저장 완료: reviews/arxiv_1706.03762.md
```

---

## 의존성

| 라이브러리 | 용도 |
|:----------|:-----|
| `anthropic` | Claude API 호출 (텍스트 + Vision) |
| `pymupdf` | PDF 텍스트 및 Figure 이미지 추출 |
| `arxiv` | arXiv 메타데이터(제목, 저자, 초록, 게재일, 학회) 가져오기 |
| `requests` | PDF URL 다운로드 |
| `python-dotenv` | `.env` 파일에서 API 키 로드 |
| `rich` | 터미널 UI (스피너, 패널, 컬러) |

---

## 환경 변수

`.env` 파일에 설정:

```
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxx...
```

API 키는 [Anthropic Console](https://console.anthropic.com/)에서 발급.
