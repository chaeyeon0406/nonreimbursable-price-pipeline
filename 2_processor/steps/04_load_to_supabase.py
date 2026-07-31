"""
04_load_to_supabase

정제 및 매핑이 완료된 비급여 데이터를 Supabase에 적재하는 단계입니다.
- analytics_items → items 테이블 + item_cluster_map 테이블
- standard_items_master → clusters 테이블
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
SRC_ROOT = CURRENT_FILE.parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from utils.manifest_reader import get_latest_batch_id

SERVICES_DIR = CURRENT_FILE.parents[3]
DEFAULT_CRAWLER_OUTPUT_DIR = SERVICES_DIR / "1_crawler" / "src" / "output"
DEFAULT_MAPPED_OUTPUT_DIR = CURRENT_FILE.parent / "output" / "mapped"

logger = logging.getLogger(__name__)

BATCH_SIZE = 500  # Supabase bulk insert 단위


# ---------------------------------------------------------------------------
# 유틸 함수
# ---------------------------------------------------------------------------
def _chunk(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def _load_env() -> tuple[str, str]:
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError(".env에 SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY가 없습니다.")
    return url, key


def _resolve_batch_id(batch_id: Optional[str], mapped_root: Path) -> str:
    if batch_id:
        return batch_id
    latest = get_latest_batch_id(str(DEFAULT_CRAWLER_OUTPUT_DIR))
    if latest and (mapped_root / latest).exists():
        return latest
    if mapped_root.exists():
        batch_dirs = sorted([p.name for p in mapped_root.iterdir() if p.is_dir()])
        if batch_dirs:
            return batch_dirs[-1]
    raise ValueError("배치 ID를 결정할 수 없습니다. --batch-id 옵션을 지정하세요.")


def _load_dataframe(batch_dir: Path, base_name: str) -> pd.DataFrame:
    parquet_path = batch_dir / f"{base_name}.parquet"
    csv_path = batch_dir / f"{base_name}.csv"
    if parquet_path.exists():
        logger.info("Parquet 로드: %s", parquet_path)
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        logger.info("CSV 로드: %s", csv_path)
        return pd.read_csv(csv_path)
    raise FileNotFoundError(f"{base_name} 파일을 찾을 수 없습니다: {batch_dir}")


def _safe_val(val):
    """pandas NaN/NaT → None 변환"""
    if pd.isna(val):
        return None
    return val


# ---------------------------------------------------------------------------
# crawl_snapshots 기록
# ---------------------------------------------------------------------------
def _upsert_crawl_snapshot(supabase: Client, batch_id: str, item_count: int) -> int:
    """crawl_snapshots에 배치 기록 후 snapshot_id 반환"""
    existing = supabase.table("crawl_snapshots").select("id").eq("batch_id", batch_id).execute()
    if existing.data:
        snapshot_id = existing.data[0]["id"]
        logger.info("기존 crawl_snapshot 사용: snapshot_id=%s", snapshot_id)
        return snapshot_id

    res = supabase.table("crawl_snapshots").insert({
        "batch_id": batch_id,
        "cleaned_record_count": item_count,
        "note": "파이프라인 자동 적재"
    }).execute()
    snapshot_id = res.data[0]["id"]
    logger.info("crawl_snapshots 기록 완료: snapshot_id=%s", snapshot_id)
    return snapshot_id


# ---------------------------------------------------------------------------
# items 적재
# ---------------------------------------------------------------------------
def _load_items(supabase: Client, df: pd.DataFrame, snapshot_id: int) -> dict[str, int]:
    """
    items 테이블에 적재하고 {staged_id: supabase_item_id} 매핑 반환
    """
    logger.info("items 적재 시작: %s건", len(df))

    # 컬럼 매핑 (한글 → 영어)
    col_map = {
        "명칭": "name",
        "hospital_name": "hospital",
        "tab_name": "top_category",
        "중분류": "mid_category",
        "소분류": "sub_category",
        "코드": "code",
        "source_code": "code",
        "구분": "classification",
        "비용": "cost",
        "특이사항": "note",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 필수 컬럼 확인
    required = ["name", "hospital"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"items 적재에 필요한 컬럼이 없습니다: {col}")

    id_map: dict[str, int] = {}
    total = 0

    rows_to_insert = []
    staged_ids = []

    for _, row in df.iterrows():
        rows_to_insert.append({
            "snapshot_id": snapshot_id,
            "hospital": _safe_val(row.get("hospital")),
            "top_category": _safe_val(row.get("top_category")),
            "mid_category": _safe_val(row.get("mid_category")),
            "sub_category": _safe_val(row.get("sub_category")),
            "name": _safe_val(row.get("name")),
            "code": _safe_val(row.get("code")),
            "classification": _safe_val(row.get("classification")),
            "cost": _safe_val(row.get("cost")),
            "note": _safe_val(row.get("note")),
        })
        staged_ids.append(_safe_val(row.get("staged_id", "")))

    for i, batch in enumerate(_chunk(list(zip(staged_ids, rows_to_insert)), BATCH_SIZE)):
        s_ids, row_batch = zip(*batch)
        res = supabase.table("items").insert(list(row_batch)).execute()
        for staged_id, inserted in zip(s_ids, res.data):
            if staged_id:
                id_map[staged_id] = inserted["id"]
        total += len(row_batch)
        logger.info("  items %s/%s건 완료", total, len(df))

    logger.info("items 적재 완료: %s건", total)
    return id_map


# ---------------------------------------------------------------------------
# clusters 적재
# ---------------------------------------------------------------------------
def _load_clusters(supabase: Client, df: pd.DataFrame) -> None:
    logger.info("clusters 적재 시작: %s건", len(df))

    col_map = {
        "standard_item_id": "cluster_id",
        "standard_item_name": "representative_name",
        "reference_price": "avg_cost",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    total = 0
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "cluster_id": _safe_val(row.get("cluster_id")),
            "representative_name": _safe_val(row.get("representative_name")),
            "match_method": _safe_val(row.get("source", "AI클러스터링")),
            "avg_cost": _safe_val(row.get("avg_cost")),
        })

    for batch in _chunk(rows, BATCH_SIZE):
        supabase.table("clusters").upsert(batch, on_conflict="cluster_id").execute()
        total += len(batch)
        logger.info("  clusters %s/%s건 완료", total, len(rows))

    logger.info("clusters 적재 완료: %s건", total)


# ---------------------------------------------------------------------------
# item_cluster_map 적재
# ---------------------------------------------------------------------------
def _load_item_cluster_map(
    supabase: Client,
    df: pd.DataFrame,
    id_map: dict[str, int],
) -> None:
    logger.info("item_cluster_map 적재 시작")

    rows = []
    skipped = 0

    for _, row in df.iterrows():
        staged_id = _safe_val(row.get("staged_id", ""))
        item_id = id_map.get(staged_id)
        cluster_id = _safe_val(row.get("standard_item_id") or row.get("cluster_id"))
        match_method = _safe_val(row.get("mapping_method", "AI클러스터링"))

        if not item_id or not cluster_id:
            skipped += 1
            continue

        rows.append({
            "item_id": item_id,
            "cluster_id": cluster_id,
            "match_method": match_method,
            "review_status": "ai_auto",
            "assigned_by": "system",
        })

    total = 0
    for batch in _chunk(rows, BATCH_SIZE):
        supabase.table("item_cluster_map").insert(batch).execute()
        total += len(batch)
        logger.info("  item_cluster_map %s/%s건 완료", total, len(rows))

    if skipped:
        logger.warning("item_cluster_map 스킵: %s건 (item_id 또는 cluster_id 없음)", skipped)
    logger.info("item_cluster_map 적재 완료: %s건", total)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="비급여 데이터 Supabase 적재 단계")
    parser.add_argument("--batch-id", help="적재할 배치 ID")
    parser.add_argument(
        "--mapped-root",
        default=str(DEFAULT_MAPPED_OUTPUT_DIR),
        help="매핑 결과 루트 디렉토리",
    )
    parser.add_argument("--skip-items", action="store_true", help="items 적재 스킵")
    parser.add_argument("--skip-clusters", action="store_true", help="clusters 적재 스킵")
    parser.add_argument("--skip-map", action="store_true", help="item_cluster_map 적재 스킵")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    mapped_root = Path(args.mapped_root).resolve()

    try:
        batch_id = _resolve_batch_id(args.batch_id, mapped_root)
    except ValueError as exc:
        logger.error("배치 ID 결정 실패: %s", exc)
        raise SystemExit(1) from exc

    batch_dir = mapped_root / batch_id
    if not batch_dir.exists():
        logger.error("배치 디렉토리를 찾을 수 없습니다: %s", batch_dir)
        raise SystemExit(1)

    logger.info("Supabase 적재 시작 - 배치: %s", batch_id)

    # Supabase 클라이언트 초기화
    try:
        supabase_url, supabase_key = _load_env()
        supabase: Client = create_client(supabase_url, supabase_key)
    except ValueError as exc:
        logger.error("Supabase 초기화 실패: %s", exc)
        raise SystemExit(1) from exc

    try:
        # analytics_items 로드 (items + item_cluster_map 원본)
        analytics_df = _load_dataframe(batch_dir, "analytics_items")

        # crawl_snapshots 기록
        snapshot_id = _upsert_crawl_snapshot(supabase, batch_id, len(analytics_df))

        # items 적재
        id_map: dict[str, int] = {}
        if not args.skip_items:
            id_map = _load_items(supabase, analytics_df.copy(), snapshot_id)

        # clusters 적재
        if not args.skip_clusters:
            try:
                master_df = _load_dataframe(batch_dir, "standard_items_master")
                _load_clusters(supabase, master_df)
            except FileNotFoundError:
                logger.warning("standard_items_master 파일 없음 - clusters 적재 스킵")

        # item_cluster_map 적재
        if not args.skip_map and id_map:
            _load_item_cluster_map(supabase, analytics_df, id_map)

    except FileNotFoundError as exc:
        logger.error("파일 없음: %s", exc)
        raise SystemExit(1) from exc
    except Exception as exc:
        logger.error("적재 중 오류: %s", exc, exc_info=True)
        raise SystemExit(1) from exc

    logger.info("Supabase 적재 완료 - 배치: %s", batch_id)


if __name__ == "__main__":
    main()