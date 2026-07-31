"""
2_processor/main.py

크롤링 결과를 순서대로 처리합니다.
01_cleanse → 02_map_edi → 03_analyze_bert → 04_load_to_supabase
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

# 경로 설정
CURRENT_DIR = Path(__file__).parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CURRENT_DIR))

from utils.manifest_reader import (
    get_latest_batch_id,
    load_manifest,
    update_manifest_status,
    get_data_files_from_manifest,
)

# 파일명이 숫자로 시작하므로 importlib으로 동적 로드
_cleanse_mod  = importlib.import_module("steps.01_cleanse")
_map_edi_mod  = importlib.import_module("steps.02_map_edi")
_bert_mod     = importlib.import_module("steps.03_analyze_bert")
_supabase_mod = importlib.import_module("steps.04_load_to_supabase")

run_cleanse_step   = _cleanse_mod.run_cleanse_step
perform_mapping    = _map_edi_mod._perform_mapping
run_ai_clustering  = _bert_mod.run_ai_clustering
load_to_supabase   = _supabase_mod  # 모듈 전체 사용

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 경로 상수
CRAWLER_OUTPUT_DIR  = PROJECT_ROOT / "services" / "1_crawler" / "src" / "output"
CLEANED_OUTPUT_ROOT = CURRENT_DIR / "output" / "cleaned"
MAPPED_OUTPUT_ROOT  = CURRENT_DIR / "output" / "mapped"
PENDING_BERT_ROOT   = CURRENT_DIR / "output" / "pending_bert"
MASTER_PATH         = MAPPED_OUTPUT_ROOT / "standard_items_master.parquet"


def main() -> None:
    logger.info("=" * 60)
    logger.info("2_processor 시작")
    logger.info("=" * 60)

    # ── 배치 ID 확인 ──────────────────────────────────────────
    if not CRAWLER_OUTPUT_DIR.exists():
        logger.error("크롤러 출력 디렉토리 없음: %s", CRAWLER_OUTPUT_DIR)
        return

    batch_id = get_latest_batch_id(str(CRAWLER_OUTPUT_DIR))
    if not batch_id:
        logger.warning("처리할 크롤링 배치가 없습니다. 크롤러를 먼저 실행하세요.")
        return
    logger.info("최신 배치 발견: %s", batch_id)

    # ── 매니페스트 확인 ───────────────────────────────────────
    manifest = load_manifest(str(CRAWLER_OUTPUT_DIR), batch_id)
    if not manifest:
        logger.error("매니페스트 로드 실패: %s", batch_id)
        return

    status = manifest.get("status")
    if status == "completed":
        logger.info("배치 %s 이미 처리 완료. 종료.", batch_id)
        return
    if status == "processing":
        logger.warning("배치 %s 처리 중. 종료.", batch_id)
        return

    # ── 처리 시작 ─────────────────────────────────────────────
    update_manifest_status(str(CRAWLER_OUTPUT_DIR), batch_id, "processing")
    logger.info("배치 %s 처리 시작", batch_id)

    try:
        data_files = get_data_files_from_manifest(manifest, str(CRAWLER_OUTPUT_DIR))
        logger.info("처리 파일 수: %s", len(data_files))

        # ── Step 1: cleanse ───────────────────────────────────
        logger.info("── Step 1: cleanse 시작")
        cleanse_results = run_cleanse_step(data_files, batch_id, CLEANED_OUTPUT_ROOT)
        logger.info("── Step 1 완료: %s개 파일", len(cleanse_results))

        batch_cleaned_dir = CLEANED_OUTPUT_ROOT / batch_id

        # ── Step 2: map_edi ───────────────────────────────────
        logger.info("── Step 2: map_edi 시작")
        mapping_outputs = perform_mapping(
            batch_id=batch_id,
            batch_cleaned_dir=batch_cleaned_dir,
            edi_reference_path=None,       # EDI 참조 파일 없으면 None
            mapped_output_root=MAPPED_OUTPUT_ROOT,
            pending_root=PENDING_BERT_ROOT,
            master_path=MASTER_PATH,
        )
        logger.info(
            "── Step 2 완료: 코드보유 %s건 / BERT대기 %s건",
            len(mapping_outputs.with_code),
            len(mapping_outputs.without_code),
        )

        # ── Step 3: analyze_bert ──────────────────────────────
        logger.info("── Step 3: analyze_bert 시작")
        bert_outputs = run_ai_clustering(
            batch_id=batch_id,
            pending_root=PENDING_BERT_ROOT,
            mapped_root=MAPPED_OUTPUT_ROOT,
            model_name="klue/bert-base",
            threshold=0.85,
            batch_size=32,
        )
        logger.info(
            "── Step 3 완료: AI클러스터 %s건",
            len(bert_outputs.ai_clusters),
        )

        # ── Step 4: load_to_supabase ──────────────────────────
        logger.info("── Step 4: Supabase 적재 시작")
        supabase_url, supabase_key = load_to_supabase._load_env()
        from supabase import create_client
        supabase = create_client(supabase_url, supabase_key)

        batch_dir = MAPPED_OUTPUT_ROOT / batch_id

        # analytics_items 로드 (items + map 원본)
        analytics_df = load_to_supabase._load_dataframe(batch_dir, "analytics_items")

        snapshot_id = load_to_supabase._upsert_crawl_snapshot(supabase, batch_id, len(analytics_df))
        id_map = load_to_supabase._load_items(supabase, analytics_df.copy(), snapshot_id)

        try:
            master_df = load_to_supabase._load_dataframe(batch_dir, "standard_items_master")
            load_to_supabase._load_clusters(supabase, master_df)
        except FileNotFoundError:
            logger.warning("standard_items_master 없음 - clusters 적재 스킵")

        if id_map:
            load_to_supabase._load_item_cluster_map(supabase, analytics_df, id_map)

        logger.info("── Step 4 완료")

        # ── 완료 ─────────────────────────────────────────────
        update_manifest_status(str(CRAWLER_OUTPUT_DIR), batch_id, "completed")
        logger.info("=" * 60)
        logger.info("배치 %s 전체 처리 완료", batch_id)
        logger.info("=" * 60)

    except Exception as exc:
        logger.error("배치 %s 처리 중 오류: %s", batch_id, exc, exc_info=True)
        update_manifest_status(str(CRAWLER_OUTPUT_DIR), batch_id, "failed", error=str(exc))


if __name__ == "__main__":
    main()