"""03_analyze_bert

EDI 코드가 없는 비급여 항목(items_pending_bert)을 중분류별로 묶어
BERT 임베딩 + 가격 유사도 기반 AgglomerativeClustering으로 클러스터링합니다.

변경사항 (v4 기준):
  - 모델: distiluse-base-multilingual → klue/bert-base
  - 클러스터링: community_detection → AgglomerativeClustering (average linkage)
  - 유사도: 텍스트(0.7) + 가격 로그스케일(0.3)
  - 임계값: 0.95 → 0.85
  - 중분류별 분리 클러스터링 (전체 한꺼번에 X)
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

CURRENT_FILE = Path(__file__).resolve()
SRC_ROOT = CURRENT_FILE.parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from utils.manifest_reader import get_latest_batch_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SERVICES_DIR = CURRENT_FILE.parents[3]
DEFAULT_PENDING_ROOT       = SRC_ROOT / "steps" / "output" / "pending_bert"
DEFAULT_MAPPED_ROOT        = SRC_ROOT / "steps" / "output" / "mapped"
DEFAULT_CRAWLER_OUTPUT_DIR = SERVICES_DIR / "1_crawler" / "src" / "output"

BERT_MODEL_NAME      = "klue/bert-base"
SIMILARITY_THRESHOLD = 0.85
TEXT_WEIGHT          = 0.7
PRICE_WEIGHT         = 0.3
BERT_BATCH_SIZE      = 64


@dataclass
class MappingOutputs:
    batch_id: str
    ai_clusters: pd.DataFrame
    pending_items: pd.DataFrame


# ──────────────────────────────────────────────
# 텍스트 전처리
# ──────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    if not isinstance(text, str):
        return ''
    text = re.sub(r'\([노너누나]\d+[가-힣()\d/]*\)', '', text)
    text = re.sub(r'\((?:국외)?(?:외국)?위탁\)', '', text)
    text = re.sub(r'\(국외\)', '', text)
    text = re.sub(r'\[?비급여\]?', '', text)
    text = re.sub(r'비\]', '', text)
    text = re.sub(r'\[본인부담\d+\]', '', text)
    text = re.sub(r'\[신의료\]', '', text)
    text = re.sub(r'\[평가유예\]', '', text)
    text = re.sub(r'\(EY\)', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_gene_name(text: str) -> Optional[str]:
    for pattern in [
        r'유전자[돌연변이]*검사[-\s]*([A-Z][A-Z0-9]+)',
        r'([A-Z][A-Z0-9]{2,})\s*(?:유전자|gene|Gene)',
        r'([A-Z][A-Z0-9]{2,})\s*\[',
    ]:
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return None


def _build_embedding_text(row: pd.Series) -> str:
    name_col = '명칭' if '명칭' in row.index else 'name'
    name = _normalize_text(str(row.get(name_col, '')))
    gene = _extract_gene_name(name)
    if gene:
        name = f"{gene} {name}"
    parts = [name]
    div_col = '구분' if '구분' in row.index else 'classification'
    div = str(row.get(div_col, '')).strip()
    if div and div != 'nan':
        parts.append(div)
    return " ".join(parts)


def _select_representative_name(names: list, hospitals: list) -> str:
    if not names:
        return ''
    count: dict = defaultdict(int)
    for n, h in zip(names, hospitals):
        count[n] += 1
    def has_korean(t: str) -> bool:
        return bool(re.search(r'[가-힣]', str(t)))
    return sorted(count.keys(), key=lambda x: (-int(has_korean(x)), -count[x], len(x)))[0]


# ──────────────────────────────────────────────
# BERT 임베딩
# ──────────────────────────────────────────────

_tokenizer = None
_model = None

def _get_model():
    global _tokenizer, _model
    if _tokenizer is None:
        from transformers import AutoTokenizer, AutoModel
        logger.info("BERT 모델 로딩: %s", BERT_MODEL_NAME)
        _tokenizer = AutoTokenizer.from_pretrained(BERT_MODEL_NAME)
        _model = AutoModel.from_pretrained(BERT_MODEL_NAME)
        _model.eval()
        logger.info("BERT 로드 완료")
    return _tokenizer, _model


def _create_embeddings(texts: List[str]) -> np.ndarray:
    import torch
    tokenizer, model = _get_model()
    embs = []
    with torch.no_grad():
        for i in range(0, len(texts), BERT_BATCH_SIZE):
            batch = texts[i:i + BERT_BATCH_SIZE]
            enc = tokenizer(batch, padding=True, truncation=True, max_length=128, return_tensors="pt")
            out = model(**enc)
            embs.append(out.last_hidden_state[:, 0, :].numpy())
    return np.vstack(embs)


# ──────────────────────────────────────────────
# 가격 유사도
# ──────────────────────────────────────────────

def _price_similarity(prices: list) -> np.ndarray:
    n = len(prices)
    sim = np.full((n, n), 0.5)
    valid_idx, log_p = [], []
    for i, p in enumerate(prices):
        try:
            val = float(p)
            if val > 0:
                valid_idx.append(i)
                log_p.append(np.log(val))
        except (TypeError, ValueError):
            pass
    if len(valid_idx) < 2:
        return sim
    log_p_arr = np.array(log_p)
    max_diff = max(log_p_arr.max() - log_p_arr.min(), 1e-6)
    for ii, i in enumerate(valid_idx):
        for jj, j in enumerate(valid_idx):
            sim[i, j] = 1.0 if i == j else max(0.0, 1.0 - abs(log_p_arr[ii] - log_p_arr[jj]) / max_diff)
    return sim


# ──────────────────────────────────────────────
# 중분류별 클러스터링
# ──────────────────────────────────────────────

def _cluster_one_category(df_cat: pd.DataFrame, start_id: int) -> Tuple[pd.DataFrame, int]:
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics.pairwise import cosine_similarity

    df_cat = df_cat.copy()

    if len(df_cat) == 1:
        df_cat['cluster_id'] = start_id
        return df_cat, start_id + 1

    texts = [_build_embedding_text(row) for _, row in df_cat.iterrows()]
    embs = _create_embeddings(texts)

    cost_col = '비용' if '비용' in df_cat.columns else 'cost'
    prices = df_cat[cost_col].tolist() if cost_col in df_cat.columns else [None] * len(df_cat)

    text_sim = cosine_similarity(embs)
    p_sim = _price_similarity(prices)
    combined = 1 - (text_sim * TEXT_WEIGHT + p_sim * PRICE_WEIGHT)
    np.fill_diagonal(combined, 0)
    combined = np.maximum(combined, 0)

    try:
        labels = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=1 - SIMILARITY_THRESHOLD,
            metric='precomputed',
            linkage='average',
        ).fit_predict(combined)
    except Exception:
        labels = list(range(len(df_cat)))

    label_map: dict = {}
    nid = start_id
    result = []
    for lb in labels:
        if lb not in label_map:
            label_map[lb] = nid
            nid += 1
        result.append(label_map[lb])

    df_cat['cluster_id'] = result
    return df_cat, nid


def _run_clustering_by_category(pending_df: pd.DataFrame, start_id: int) -> pd.DataFrame:
    """중분류별로 분리하여 클러스터링 수행"""
    mid_col = '표준_중분류명' if '표준_중분류명' in pending_df.columns else 'middle_category'
    tab_col = '최상위계층' if '최상위계층' in pending_df.columns else 'tab_name'

    groups = pending_df.groupby([tab_col, mid_col])
    total = len(groups)
    nid = start_id
    result_dfs = []

    for idx, ((tab, mid), group) in enumerate(groups):
        logger.info("[%s/%s] %s > %s (%s건)", idx + 1, total, tab, mid, len(group))
        clustered, nid = _cluster_one_category(group, nid)
        result_dfs.append(clustered)

    return pd.concat(result_dfs, ignore_index=True) if result_dfs else pd.DataFrame()


# ──────────────────────────────────────────────
# 마스터 테이블 생성
# ──────────────────────────────────────────────

def _build_master_table(ai_df: pd.DataFrame, edi_df: pd.DataFrame) -> pd.DataFrame:
    """클러스터별 대표명칭, 평균가격 등 요약"""
    name_col  = '명칭' if '명칭' in ai_df.columns else 'name'
    hosp_col  = '병원' if '병원' in ai_df.columns else 'hospital'
    cost_col  = '비용' if '비용' in ai_df.columns else 'cost'
    mid_col   = '표준_중분류명' if '표준_중분류명' in ai_df.columns else 'middle_category'
    tab_col   = '최상위계층' if '최상위계층' in ai_df.columns else 'tab_name'

    summaries = []
    for cid in sorted(ai_df['cluster_id'].unique()):
        c = ai_df[ai_df['cluster_id'] == cid]
        hospitals = sorted(c[hosp_col].unique()) if hosp_col in c.columns else []
        costs = pd.to_numeric(c[cost_col], errors='coerce').dropna() if cost_col in c.columns else pd.Series(dtype=float)
        rep_name = _select_representative_name(c[name_col].tolist(), c[hosp_col].tolist() if hosp_col in c.columns else [''] * len(c))

        summaries.append({
            'cluster_id':          cid,
            'top_category':        c[tab_col].iloc[0] if tab_col in c.columns else None,
            'mid_category':        c[mid_col].iloc[0] if mid_col in c.columns else None,
            'match_method':        'AI클러스터링',
            'representative_name': rep_name,
            'item_count':          len(c),
            'hospital_count':      len(hospitals),
            'avg_cost':            int(costs.mean()) if len(costs) > 0 else None,
            'min_cost':            int(costs.min()) if len(costs) > 0 else None,
            'max_cost':            int(costs.max()) if len(costs) > 0 else None,
            'source':              'AI_BERT',
            'last_seen_at':        datetime.utcnow().isoformat(),
        })

    return pd.DataFrame(summaries)


# ──────────────────────────────────────────────
# 파일 IO
# ──────────────────────────────────────────────

def _save_dataframe(df: pd.DataFrame, path: Path, *, also_csv: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    if also_csv:
        df.to_csv(path.with_suffix('.csv'), index=False, encoding='utf-8-sig')
    logger.info("저장: %s (%s건)", path, len(df))


def _load_pending_dataframe(pending_root: Path, batch_id: str) -> pd.DataFrame:
    batch_dir = pending_root / batch_id
    for fname in ['items_pending_bert.parquet', 'items_pending_bert.csv']:
        p = batch_dir / fname
        if p.exists():
            logger.info("BERT 대기 데이터 로드: %s", p)
            return pd.read_parquet(p) if p.suffix == '.parquet' else pd.read_csv(p)
    raise FileNotFoundError(f"BERT 대기 데이터 없음: {batch_dir}")


def _load_items_with_edi(mapped_root: Path, batch_id: str) -> pd.DataFrame:
    batch_dir = mapped_root / batch_id
    for fname in ['items_with_edi.parquet', 'items_with_edi.csv']:
        p = batch_dir / fname
        if p.exists():
            return pd.read_parquet(p) if p.suffix == '.parquet' else pd.read_csv(p)
    return pd.DataFrame()


def _save_outputs(ai_df: pd.DataFrame, edi_df: pd.DataFrame, mapped_root: Path, batch_id: str) -> None:
    batch_dir = mapped_root / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    # 개별 AI 결과
    _save_dataframe(ai_df, batch_dir / "items_with_ai.parquet")

    # 통합본 (04_load_to_supabase가 읽는 것)
    combined = pd.concat([edi_df, ai_df], ignore_index=True, sort=False)
    _save_dataframe(combined, batch_dir / "analytics_items.parquet")

    # 마스터 테이블
    master_df = _build_master_table(ai_df, edi_df)
    _save_dataframe(master_df, batch_dir / "standard_items_master.parquet")

    logger.info("출력 완료: items_with_ai / analytics_items / standard_items_master")


# ──────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────

def run_ai_clustering(
    batch_id: str,
    pending_root: Path,
    mapped_root: Path,
    model_name: str = BERT_MODEL_NAME,
    threshold: float = SIMILARITY_THRESHOLD,
    min_community_size: int = 1,
    batch_size: int = BERT_BATCH_SIZE,
) -> MappingOutputs:
    global BERT_MODEL_NAME, SIMILARITY_THRESHOLD, BERT_BATCH_SIZE
    BERT_MODEL_NAME      = model_name
    SIMILARITY_THRESHOLD = threshold
    BERT_BATCH_SIZE      = batch_size

    pending_df = _load_pending_dataframe(pending_root, batch_id)
    edi_df     = _load_items_with_edi(mapped_root, batch_id)

    if pending_df.empty:
        logger.info("BERT 대기 항목 없음 — 클러스터링 스킵")
        return MappingOutputs(batch_id, pd.DataFrame(), pending_df)

    logger.info("클러스터링 시작: %s건 (중분류별 분리)", len(pending_df))

    # EDI 클러스터 다음 ID에서 AI 클러스터 시작
    edi_max_id = int(edi_df['cluster_id'].max()) + 1 if not edi_df.empty and 'cluster_id' in edi_df.columns else 0

    ai_df = _run_clustering_by_category(pending_df, start_id=edi_max_id)
    ai_df['match_method'] = 'AI클러스터링'

    _save_outputs(ai_df, edi_df, mapped_root, batch_id)

    total_clusters = ai_df['cluster_id'].nunique()
    logger.info("클러스터링 완료: %s개 클러스터 생성", total_clusters)

    return MappingOutputs(batch_id, ai_df, pending_df)


def main() -> None:
    parser = argparse.ArgumentParser(description="BERT 기반 비급여 항목 클러스터링 (v4)")
    parser.add_argument("--batch-id")
    parser.add_argument("--pending-root", default=str(DEFAULT_PENDING_ROOT))
    parser.add_argument("--mapped-root",  default=str(DEFAULT_MAPPED_ROOT))
    parser.add_argument("--model-name",   default=BERT_MODEL_NAME)
    parser.add_argument("--threshold",    type=float, default=SIMILARITY_THRESHOLD)
    parser.add_argument("--batch-size",   type=int,   default=BERT_BATCH_SIZE)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    batch_id = args.batch_id or get_latest_batch_id(str(DEFAULT_CRAWLER_OUTPUT_DIR))
    if not batch_id:
        raise SystemExit("배치 ID를 결정할 수 없습니다.")

    logger.info("AI 클러스터링 시작: %s", batch_id)
    run_ai_clustering(
        batch_id=batch_id,
        pending_root=Path(args.pending_root).resolve(),
        mapped_root=Path(args.mapped_root).resolve(),
        model_name=args.model_name,
        threshold=args.threshold,
        batch_size=args.batch_size,
    )
    logger.info("AI 클러스터링 완료")


if __name__ == "__main__":
    main()