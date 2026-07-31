# 빅5 병원 비급여 항목 가격 비교 파이프라인

> *End-to-end pipeline (crawling → AI clustering → human-review dashboard) comparing non-reimbursable medical item pricing across Korea's top 5 hospitals. Solo-built, from data collection to production-facing UI.*

병원마다 같은 시술/재료를 다른 이름으로 공시하기 때문에("PET CT" vs "양전자단층촬영" 등), 명칭 문자열만으로는 병원 간 비급여 진료비 비교가 불가능합니다. 이 프로젝트는 **크롤링 → 표준화 → AI 클러스터링 → 사람 검토(Human-in-the-loop)**까지 전 과정을 혼자 설계·구현한 파이프라인입니다.

건강보험심사평가원 특허 출원("환자에 대한 건강보험 급여 충족 여부를 제공하는 방법", 10-2025-0138818)의 실제 구현체이기도 합니다.

## 왜 만들었나

빅5 병원(서울대·삼성서울·세브란스·아산·서울성모)은 「의료법」에 따라 비급여 항목 가격을 각자의 웹사이트에 의무 공시합니다. 하지만:
- 병원마다 명칭/분류 체계가 달라 단순 비교 불가
- 페이지 구조가 병원마다 전부 달라 자동 수집 자체가 난이도 있는 문제
- 표준 코드가 없는 항목(전체의 상당수)은 AI로 유사 항목을 묶어야 함

## 스크린샷

| 탐색기 (메인) | 클러스터 상세 (가격 비교) | 리뷰 큐 |
|---|---|---|
| ![탐색기](docs/screenshots/explorer.png) | ![상세](docs/screenshots/detail.png) | ![리뷰큐](docs/screenshots/feedback.png) |

## 파이프라인 구조

```
1_crawler/     Selenium 기반, 병원별 크롤러 5개 (config 기반 설계)
      ↓
2_processor/   정제 → EDI 코드 매칭 → BERT 클러스터링 → Supabase 적재
      ↓
3_dashboard/   Next.js 기반 리뷰/탐색 대시보드
```

### 1. Crawler — `1_crawler/`
- `crawler/base_crawler.py`: 공통 부모 클래스(재시도, 로깅 등)
- 병원별 크롤러 5개(`snu_crawler.py`, `samsung_crawler.py`, `severance_crawler.py`, `asan_crawler.py`, `cmc_crawler.py`): 병원마다 다른 탭 전환/페이지네이션/DOM 구조에 대응 — stale element 재탐색, JS 클릭 폴백 등 안정성 처리 포함
- **설계 포인트**: 크롤러 로직과 사이트별 설정(URL, CSS 셀렉터)을 분리한 config-driven 구조. `config/big5_config.example.json`은 스키마를 보여주는 예시이며, 실제 대상 병원의 URL/셀렉터는 각 사이트 이용약관 보호를 위해 비공개 처리했습니다.

### 2. Processor — `2_processor/`
1. `01_cleanse.py` — 비용/날짜 정제, 중분류 누락 보정
2. `02_map_edi.py` — EDI 표준 코드 유무로 분리(코드 있으면 바로 매칭)
3. `03_analyze_bert.py` — 코드 없는 잔여 항목만 AI 클러스터링
   - 모델: `klue/bert-base` 임베딩
   - 유사도 = 텍스트(0.7) + 가격 로그스케일(0.3), threshold 0.85
   - AgglomerativeClustering(average linkage)
4. `04_load_to_supabase.py` — 결과 적재 (16,000건+)

### 3. Dashboard — `3_dashboard/`
Next.js 16 + React 19 + Recharts + TanStack Table.
- **탐색기**(`/`): 클러스터별 병원 가격 비교, 막대그래프, CSV 다운로드
- **리뷰 큐**(`/feedback`): AI 자동 매칭 결과를 사람이 확인/재분류하는 human-in-the-loop 워크플로우
- **HIRA 비교**(`/hira`): 건강보험심사평가원 공식 데이터와 교차검증
- **리포트**(`/reports`): 통계 대시보드

`/data/*.json`에 실제 클러스터링 결과가 포함되어 있어 `npm install && npm run dev`로 바로 동작 확인 가능합니다. `/feedback`, `/hira` 페이지는 현재 UI/워크플로우 프로토타입 단계로 목업 데이터를 사용합니다.

## 기술 스택

Python (Selenium, pandas, transformers/klue-bert, scikit-learn) · Supabase · Next.js 16 · React 19 · TypeScript · Recharts

## 본인 기여

기획 → 크롤러 설계 → 데이터 정제/EDI 매칭 → AI 클러스터링 → 리뷰 대시보드 UI/UX까지 전 과정 단독 설계·구현 (기여도 100%).

## 참고

- 크롤링 대상 병원별 URL/CSS 셀렉터는 대상 사이트 보호를 위해 비공개입니다.
- 다루는 가격 데이터는 「의료법」에 따라 병원이 의무적으로 공시하는 공개 정보입니다.
- 이 저장소는 포트폴리오 공개용으로 별도 정리한 버전입니다.
