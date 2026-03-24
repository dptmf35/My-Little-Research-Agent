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
python main.py https://arxiv.org/abs/1706.03762
```

결과는 `reviews/arxiv_1706.03762.md` 에 저장됩니다.

---

## 지원하는 입력 형식

| 입력 형식 | 예시 |
|-----------|------|
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

> Source, 분석 일시, 저자 등 메타 정보

## 🔍 Pass 1: Quick Scan (개요 파악)
## 📖 Pass 2: Structural Understanding (구조 파악)
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
│   ├── fetcher.py       ← PDF 수집 및 텍스트 추출
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
 ├── arxiv.org URL → arxiv 라이브러리로 메타데이터(제목/저자/초록) 가져오기
 │                 → PDF URL로 변환 후 다운로드
 ├── 일반 PDF URL  → requests로 직접 다운로드
 └── 로컬 파일    → 파일 경로 직접 사용
                    ↓
              pymupdf(fitz)로 텍스트 추출
              (최대 40페이지 / 100,000자 제한)
```

**토큰 초과 방지:**
논문이 너무 길면 Claude API의 context limit을 넘어버리기 때문에, 최대 40페이지 또는 100,000자로 잘라냅니다.

---

### 2단계: Three-Pass 분석 (`src/analyzer.py`)

논문을 한 번에 분석하지 않고, **사람이 논문을 읽는 방식**을 그대로 모방합니다.
Claude API를 총 4번 호출하고, 각 패스의 결과가 다음 패스의 컨텍스트로 누적됩니다.

```
논문 텍스트
    │
    ▼
[Pass 1 - Quick Scan]  ── "5분 훑어보기: 핵심 주제/기여/가치 평가"
    │  결과: pass1_result
    ▼
[Pass 2 - Structural]  ── pass1 결과 + "Introduction/Related Work/방법론/실험 구조 파악"
    │  결과: pass2_result
    ▼
[Pass 3 - Deep Dive]   ── pass1 + pass2 결과 + "수식/알고리즘/인사이트/강약점 심층 분석"
    │  결과: pass3_result
    ▼
[통합 리뷰]            ── pass1 + pass2 + pass3 결과 → 최종 구조화된 리뷰 생성
```

**누적 컨텍스트의 의미:**
Pass 3 프롬프트에는 Pass 1, 2의 결과가 모두 들어갑니다. 즉, Claude가 세 번째 분석을 할 때는 이미 "이 논문의 대략적인 구조와 핵심 기여를 알고 있는 상태"에서 더 깊은 질문을 던지게 됩니다. 사람이 논문을 두 번 읽고 세 번째 읽는 것과 같은 효과입니다.

**사용 모델:** `claude-sonnet-4-6`
**패스당 max_tokens:** 4,096

---

### 3단계: 저장 (`src/formatter.py`)

분석 결과를 마크다운으로 조립하고 `reviews/` 폴더에 저장합니다.

파일명 우선순위:
1. arXiv ID가 있으면 → `arxiv_1706.03762.md`
2. 제목이 있으면 → `Attention_Is_All_You_Need.md`
3. 둘 다 없으면 → `review_20260324_143022.md` (타임스탬프)

같은 이름 파일이 이미 있으면 타임스탬프를 붙여서 충돌 방지.

---

### CLI (`main.py`)

`rich` 라이브러리를 사용해 각 패스 진행 상황을 스피너 + 경과 시간으로 표시합니다.

```
📥 논문 가져오는 중...
  ✓ PDF 다운로드 및 텍스트 추출 완료

🧠 Three-Pass Analysis 시작

  ⠋ Pass 1: Quick Scan (개요 파악) ...         0:00:08
  ✓ Pass 2: Structural Understanding ...       0:00:21
  ✓ Pass 3: Deep Dive (심층 분석) ...           0:00:45
  ✓ 통합 리뷰: Integrated Review 생성 중 ...   0:01:03

✓ 모든 패스 완료!

💾 결과 저장 완료: reviews/arxiv_1706.03762.md
```

---

## 의존성

| 라이브러리 | 용도 |
|-----------|------|
| `anthropic` | Claude API 호출 |
| `pymupdf` | PDF 텍스트 추출 |
| `arxiv` | arXiv 메타데이터(제목, 저자, 초록) 가져오기 |
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
