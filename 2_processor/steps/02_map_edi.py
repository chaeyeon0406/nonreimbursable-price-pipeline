"""02_map_edi

01_cleanse 단계에서 준비된 비급여 데이터를 EDI 코드 보유 여부에 따라 분리하고,
향후 비교 분석과 BERT 분석을 위한 산출물을 생성합니다.
EDI 참조 데이터는 선택 사항으로, 제공되는 경우에만 메타정보를 보강합니다.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd

# 경로 설정 및 공용 유틸 임포트 -----------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
SRC_ROOT = CURRENT_FILE.parent.parent  # services/2_processor/src
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from utils.manifest_reader import (  # pylint: disable=wrong-import-position
    get_latest_batch_id,
    load_manifest,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SERVICES_DIR = CURRENT_FILE.parents[3]
DEFAULT_CLEANED_ROOT = SRC_ROOT / "steps" / "output" / "cleaned"
DEFAULT_MAPPED_ROOT = SRC_ROOT / "steps" / "output" / "mapped"
DEFAULT_PENDING_ROOT = SRC_ROOT / "steps" / "output" / "pending_bert"
DEFAULT_MASTER_PATH = DEFAULT_MAPPED_ROOT / "standard_items_master.parquet"
DEFAULT_CRAWLER_OUTPUT_DIR = SERVICES_DIR / "1_crawler" / "src" / "output"
STAGED_FILENAME = "staged_hospital_data.parquet"


# 데이터 모델 -----------------------------------------------------------------
@dataclass
class MappingOutputs:
    batch_id: str
    with_code: pd.DataFrame
    without_code: pd.DataFrame


# 헬퍼 함수 --------------------------------------------------------------------
def _sanitize_code(value: object) -> Optional[str]:
    if value is None:
        return None
    string_value = str(value).strip().upper()
    if string_value in {"", "NONE", "NAN", "NULL"}:
        return None
    cleaned = re.sub(r"[^A-Z0-9]", "", string_value)
    return cleaned or None


def _first_non_null(values: Iterable[object]) -> Optional[object]:
    for val in values:
        if pd.notna(val) and val not in ("", None):
            return val
    return None


def _load_optional_edi_reference(path: Optional[Path]) -> Optional[pd.DataFrame]:
    if not path:
        return None
    if not path.exists():
        logger.warning("EDI 참조 파일을 찾을 수 없어 무시합니다: %s", path)
        return None

    if path.suffix.lower() in {".csv", ".txt"}:
        df = pd.read_csv(path)
    elif path.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        logger.warning("지원하지 않는 EDI 참조 파일 형식입니다: %s", path.suffix)
        return None

    if df.empty:
        logger.warning("EDI 참조 파일이 비어있습니다: %s", path)
        return None

    rename_map = {}
    for col in df.columns:
        lower = col.lower()
        if "code" in lower or "코드" in lower:
            rename_map[col] = "edi_code"
        elif "name" in lower or "수가명" in lower or "항목명" in lower:
            rename_map[col] = "edi_name"
        elif "price" in lower or "금액" in lower or "fee" in lower:
            rename_map[col] = "edi_price"
        elif "date" in lower or "적용" in lower:
            rename_map[col] = "edi_effective_date"
        elif "desc" in lower or "설명" in lower:
            rename_map[col] = "edi_description"
        elif "category" in lower:
            rename_map[col] = "edi_category"
    df = df.rename(columns=rename_map)

    if "edi_code" not in df.columns:
        logger.warning("EDI 참조 데이터에 'edi_code' 컬럼이 없어 무시합니다: %s", path)
        return None

    df["edi_code_clean"] = df["edi_code"].map(_sanitize_code)
    df = df[df["edi_code_clean"].notna()].drop_duplicates("edi_code_clean", keep="last")
    if df.empty:
        logger.warning("EDI 참조 데이터에 유효한 코드가 없습니다: %s", path)
        return None
    logger.info("EDI 참조 데이터 로드 완료: %s (총 %s건)", path, len(df))
    return df


def _flatten_cleaned_payload(
    hospital_key: str, hospital_data: dict, batch_id: str
) -> pd.DataFrame:
    records: List[dict] = []
    display_name = hospital_data.get("display_name", hospital_key)
    tabs = hospital_data.get("tabs", {})
    for tab_name, tab_info in tabs.items():
        items = tab_info.get("data", [])
        for idx, item in enumerate(items):
            record = {
                "batch_id": batch_id,
                "hospital_code": hospital_key,
                "hospital_name": display_name,
                "tab_name": tab_name,
                "row_index": idx,
            }
            record.update(item)
            records.append(record)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def _build_staged_dataframe(batch_cleaned_dir: Path, batch_id: str) -> pd.DataFrame:
    all_dfs: List[pd.DataFrame] = []
    # 01_cleanse 단계의 출력은 asan_20231120.json과 같은 형식을 가짐
    json_files = list(batch_cleaned_dir.glob("*.json"))

    if not json_files:
        raise FileNotFoundError(f"정제된 파일을 찾을 수 없습니다: {batch_cleaned_dir} (01_cleanse 결과 확인 필요)")

    for file_path in json_files:
        # 파일명에서 병원 코드 추출 (예: 'asan_20231120.json' -> 'asan')
        hospital_key = file_path.stem.split("_")[0]

        with file_path.open("r", encoding="utf-8") as f:
            try:
                # 이제 payload는 단일 병원의 데이터 dict
                payload = json.load(f)
                df = _flatten_cleaned_payload(hospital_key, payload, batch_id=batch_id)
                if not df.empty:
                    all_dfs.append(df)
            except json.JSONDecodeError:
                logger.warning(f"JSON 파일 파싱 실패: {file_path}")
                continue
    
    if not all_dfs:
        return pd.DataFrame()

    df = pd.concat(all_dfs, ignore_index=True)

    code_candidates = [col for col in df.columns if "코드" in col or col.lower() == "code"]
    if code_candidates:
        primary_code_col = code_candidates[0]
        df["source_code"] = df[primary_code_col]
    else:
        df["source_code"] = None

    df["edi_code_clean"] = df["source_code"].map(_sanitize_code)

    for numeric_field in ("비용", "최저비용", "최고비용"):
        if numeric_field not in df.columns:
            df[numeric_field] = None
    if "최종 변경일" not in df.columns:
        df["최종 변경일"] = None

    return df


def _load_staged_dataframe(batch_cleaned_dir: Path, batch_id: str) -> Tuple[pd.DataFrame, Path]:
    staged_path = batch_cleaned_dir / STAGED_FILENAME
    if staged_path.exists():
        df = pd.read_parquet(staged_path)
        return df, staged_path

    df = _build_staged_dataframe(batch_cleaned_dir, batch_id)
    try:
        df.to_parquet(staged_path, index=False)
        logger.info("스테이징 데이터 생성 및 저장: %s", staged_path)
    except Exception as exc:
        logger.warning("스테이징 데이터 저장 실패: %s", exc)
    return df, staged_path


def _resolve_batch_id_and_cleaned_root(
    batch_id: Optional[str], cleaned_root: Path
) -> Tuple[str, Path]:
    cleaned_root = cleaned_root.resolve()
    if not cleaned_root.exists():
        raise FileNotFoundError(f"정제 결과 디렉토리를 찾을 수 없습니다: {cleaned_root}")

    resolved_batch_id = batch_id
    if not resolved_batch_id:
        resolved_batch_id = get_latest_batch_id(str(DEFAULT_CRAWLER_OUTPUT_DIR))
        if not resolved_batch_id:
            raise ValueError("배치 ID를 결정할 수 없습니다. --batch-id 옵션을 사용하거나 LATEST.txt를 확인하세요.")

    batch_dir = cleaned_root / resolved_batch_id
    if not batch_dir.exists():
        raise FileNotFoundError(f"정제 데이터 배치 폴더를 찾을 수 없습니다: {batch_dir}")

    return resolved_batch_id, batch_dir


def _save_dataframe(df: pd.DataFrame, path: Path, *, also_csv: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        df.to_parquet(path, index=False)
        if also_csv:
            df.to_csv(path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
        logger.info("빈 데이터 저장: %s", path)
        return

    df.to_parquet(path, index=False)
    if also_csv:
        df.to_csv(path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    logger.info("데이터 저장: %s (%s건)", path, len(df))


def _append_master_table(master_path: Path, master_df: pd.DataFrame) -> None:
    if master_df.empty:
        logger.info("마스터 테이블에 추가할 항목이 없습니다.")
        return
    master_path.parent.mkdir(parents=True, exist_ok=True)
    if master_path.exists():
        existing = pd.read_parquet(master_path)
        combined = pd.concat([existing, master_df], ignore_index=True)
        combined = combined.drop_duplicates("edi_code_clean", keep="last")
    else:
        combined = master_df
    combined.to_parquet(master_path, index=False)
    logger.info("표준 마스터 테이블 업데이트: %s (총 %s개 항목)", master_path, len(combined))


# 메인 로직 --------------------------------------------------------------------
def _perform_mapping(
    batch_id: str,
    batch_cleaned_dir: Path,
    edi_reference_path: Optional[Path],
    mapped_output_root: Path,
    pending_root: Path,
    master_path: Path,
) -> MappingOutputs:
    staged_df, staged_path = _load_staged_dataframe(batch_cleaned_dir, batch_id)
    logger.info("스테이징 데이터 로드: %s (총 %s건)", staged_path, len(staged_df))

    if "edi_code_clean" not in staged_df.columns:
        staged_df["edi_code_clean"] = staged_df.get("source_code").map(_sanitize_code)

    with_code = staged_df[staged_df["edi_code_clean"].notna()].copy()
    without_code = staged_df[staged_df["edi_code_clean"].isna()].copy()

    logger.info("EDI 코드 보유: %s건, 미보유: %s건", len(with_code), len(without_code))

    edi_reference = _load_optional_edi_reference(edi_reference_path)

    if edi_reference is not None:
        with_code = with_code.merge(
            edi_reference,
            on="edi_code_clean",
            how="left",
            suffixes=("", "_edi"),
        )
        with_code["standard_item_id"] = with_code["edi_code_clean"].map(lambda x: f"EDI_{x}")
        with_code["reference_name"] = with_code.get("edi_name")
        with_code["reference_price"] = with_code.get("edi_price")
        with_code["mapping_method"] = "edi_code"
        master_df = with_code[[
            "edi_code_clean",
            "standard_item_id",
            "reference_name",
            "reference_price",
        ]].drop_duplicates("edi_code_clean")
        master_df["last_seen_at"] = datetime.utcnow().isoformat()
        master_df["standard_item_name"] = master_df["reference_name"].fillna(master_df["reference_price"])
        _append_master_table(master_path, master_df)
    else:
        with_code["standard_item_id"] = with_code["edi_code_clean"].map(lambda x: f"EDI_{x}")
        with_code["mapping_method"] = "edi_code"

    timestamp = datetime.utcnow().isoformat()
    with_code["mapping_source"] = "EDI"
    with_code["mapping_status"] = "has_edi_code"
    with_code["mapping_timestamp"] = timestamp

    without_code["mapping_status"] = "awaiting_bert"
    without_code["mapping_timestamp"] = timestamp

    analytics_output_path = mapped_output_root / batch_id / "items_with_edi.parquet"
    _save_dataframe(with_code, analytics_output_path)

    pending_output_path = pending_root / batch_id / "items_pending_bert.parquet"
    _save_dataframe(without_code, pending_output_path)

    return MappingOutputs(
        batch_id=batch_id,
        with_code=with_code,
        without_code=without_code,
    )


def main() -> None:  # pragma: no cover - CLI 실행용
    parser = argparse.ArgumentParser(description="EDI 매핑 단계 (02_map_edi)")
    parser.add_argument("--batch-id", help="처리할 배치 ID (생략 시 LATEST.txt 사용)")
    parser.add_argument(
        "--cleaned-root",
        default=str(DEFAULT_CLEANED_ROOT),
        help="01_cleanse 결과 디렉토리",
    )
    parser.add_argument(
        "--edi-reference",
        help="EDI 참조 데이터 파일 경로 (선택 사항)",
    )
    parser.add_argument(
        "--mapped-output-root",
        default=str(DEFAULT_MAPPED_ROOT),
        help="코드가 있는 항목(analytics)을 저장할 루트",
    )
    parser.add_argument(
        "--pending-root",
        default=str(DEFAULT_PENDING_ROOT),
        help="BERT 분석 대기 데이터를 저장할 루트",
    )
    parser.add_argument(
        "--master-path",
        default=str(DEFAULT_MASTER_PATH),
        help="표준 마스터(standard_items_master) 파일 경로",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    batch_id, batch_cleaned_dir = _resolve_batch_id_and_cleaned_root(
        args.batch_id, Path(args.cleaned_root)
    )

    logger.info("EDI 매핑 대상 배치: %s", batch_id)

    edi_reference_path = Path(args.edi_reference).resolve() if args.edi_reference else None

    outputs = _perform_mapping(
        batch_id=batch_id,
        batch_cleaned_dir=batch_cleaned_dir,
        edi_reference_path=edi_reference_path,
        mapped_output_root=Path(args.mapped_output_root).resolve(),
        pending_root=Path(args.pending_root).resolve(),
        master_path=Path(args.master_path).resolve(),
    )

    logger.info("EDI 매핑 완료 - 배치 %s", outputs.batch_id)
    logger.info("  ▸ items_with_edi: %s건", len(outputs.with_code))
    logger.info("  ▸ items_pending_bert: %s건", len(outputs.without_code))


if __name__ == "__main__":  # pragma: no cover
    main()
