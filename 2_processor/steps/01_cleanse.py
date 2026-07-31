"""01_cleanse

크롤링된 비급여 데이터를 정제(cleanse)하는 단계.
- 비용 관련 컬럼에서 통화 단위를 제거하고 숫자로 변환
- 최종 변경일 컬럼의 날짜 형식을 YYYY-MM-DD로 표준화
- 최신 배치(LATEST.txt) 기반 자동 입력 지원

이 모듈은 단독 실행이 가능하며, 다른 단계에서 import 하여 사용할 수도 있습니다.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

# 프로젝트 경로 설정 및 manifest reader import를 위한 PATH 구성
CURRENT_FILE = Path(__file__).resolve()
SRC_ROOT = CURRENT_FILE.parent.parent  # services/2_processor/src
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from utils.manifest_reader import (  # pylint: disable=wrong-import-position
    get_data_files_from_manifest,
    get_latest_batch_id,
    load_manifest,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 정제 대상 컬럼 정의
NUMERIC_FIELDS = ["비용", "최저비용", "최고비용"]
DATE_FIELDS = ["최종 변경일", "최종변경일"]
EMPTY_TOKENS = {None, "", "-", "–", "—", "N/A", "n/a", "None"}

# 기본 크롤러 출력 경로 (services/1_crawler/src/output)
SERVICES_DIR = CURRENT_FILE.parents[3]
DEFAULT_CRAWLER_OUTPUT_DIR = SERVICES_DIR / "1_crawler" / "src" / "output"


def _sanitize_numeric(value: Any) -> Optional[int]:
    """금액 필드를 정리하여 정수 또는 None으로 반환합니다."""
    if value in EMPTY_TOKENS:
        return None

    string_value = str(value).strip()
    if string_value in EMPTY_TOKENS:
        return None

    # 숫자와 소수점만 남기고 제거
    cleaned = re.sub(r"[^0-9.]", "", string_value)
    if not cleaned:
        return None

    # 소수점이 존재하면 반올림하여 정수로 변환
    try:
        if "." in cleaned:
            return int(round(float(cleaned)))
        return int(cleaned)
    except ValueError:
        return None


def _sanitize_date(value: Any) -> Optional[str]:
    """다양한 날짜 표현을 YYYY-MM-DD 문자열로 변환합니다."""
    if value in EMPTY_TOKENS:
        return None

    string_value = str(value).strip()
    if string_value in EMPTY_TOKENS:
        return None

    try:
        ts = pd.to_datetime(string_value, errors="coerce")
    except Exception:
        ts = pd.NaT

    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


@dataclass
class CleanseResult:
    input_path: Path
    output_path: Path
    record_count: int


def _resolve_inputs_from_latest(
    crawler_output_dir: Path, batch_id: Optional[str], data_files: Optional[List[str]]
) -> Tuple[str, List[str]]:
    """LATEST.txt와 manifest를 이용하여 배치 ID와 입력 파일을 자동으로 결정합니다."""

    resolved_batch_id = batch_id
    output_dir_str = str(crawler_output_dir)

    if not resolved_batch_id:
        resolved_batch_id = get_latest_batch_id(output_dir_str)
        if not resolved_batch_id:
            raise ValueError(
                "LATEST.txt에서 배치 ID를 찾을 수 없습니다. --batch-id 옵션을 지정해주세요."
            )

    if not data_files:
        manifest = load_manifest(output_dir_str, resolved_batch_id)
        if not manifest:
            raise ValueError(
                f"배치 {resolved_batch_id} 의 manifest.json을 찾을 수 없습니다."
            )

        files_from_manifest = get_data_files_from_manifest(manifest, output_dir_str)
        if not files_from_manifest:
            raise ValueError(
                f"배치 {resolved_batch_id} 에 대한 데이터 파일을 manifest에서 찾을 수 없습니다."
            )
        data_files = files_from_manifest

    if not data_files:
        raise ValueError("정제할 입력 파일을 찾을 수 없습니다.")

    return resolved_batch_id, data_files


def _cleanse_record(record: Dict[str, Any], current_category: Optional[str] = None) -> Dict[str, Any]:
    """단일 레코드를 정제하고 중분류가 없다면 상위 카테고리를 유지합니다."""
    cleaned = dict(record)  # 원본 변형 방지

    # 중분류 보정
    category_candidates = [cleaned.get("중분류"), cleaned.get("중분모"), cleaned.get("중분류명")]
    detected_category = next((c for c in category_candidates if isinstance(c, str) and c.strip()), None)
    if detected_category:
        cleaned["중분류"] = detected_category.strip()
    elif current_category:
        cleaned["중분류"] = current_category
    else:
        cleaned["중분류"] = cleaned.get("중분류", "") or ""

    # 금액 필드 정제
    for field in NUMERIC_FIELDS:
        if field in cleaned:
            cleaned[field] = _sanitize_numeric(cleaned.get(field))

    # 날짜 필드 정제 (최종변경일 -> 최종 변경일로 통일)
    date_value = None
    for field in DATE_FIELDS:
        if field in cleaned and cleaned[field] not in EMPTY_TOKENS:
            date_value = cleaned[field]
            if field != "최종 변경일":
                # 중복 컬럼 제거를 위해 최종 변경일로 통합
                cleaned.pop(field, None)
            break

    if date_value is not None:
        normalized_date = _sanitize_date(date_value)
        if normalized_date:
            cleaned["최종 변경일"] = normalized_date
        else:
            cleaned.pop("최종 변경일", None)
    else:
        # 날짜가 존재하지 않는 경우 기존 필드를 제거
        cleaned.pop("최종 변경일", None)

    return cleaned


def _cleanse_data_list(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """레코드 리스트를 정제하고 중분류를 전파합니다."""
    cleansed: List[Dict[str, Any]] = []
    current_category: Optional[str] = None

    for record in records:
        raw_category = record.get("중분류")
        if isinstance(raw_category, str) and raw_category.strip():
            current_category = raw_category.strip()

        cleaned = _cleanse_record(record, current_category=current_category)
        # 정제 후 중분류가 비어 있지 않다면 다음 레코드를 위해 상태 업데이트
        if cleaned.get("중분류"):
            current_category = cleaned["중분류"]

        cleansed.append(cleaned)

    return cleansed


def _cleanse_payload(payload: Any) -> Any:
    """JSON Payload 전체를 순회하며 data 리스트를 정제합니다."""
    if isinstance(payload, dict):
        if "data" in payload and isinstance(payload["data"], list):
            payload["data"] = _cleanse_data_list(payload["data"])
        else:
            for key, value in list(payload.items()):
                payload[key] = _cleanse_payload(value)
    elif isinstance(payload, list):
        return [_cleanse_payload(item) for item in payload]
    return payload


def cleanse_file(input_path: Path, output_path: Path) -> CleanseResult:
    """단일 파일을 정제하여 output_path에 저장합니다."""
    logger.info("정제 시작: %s", input_path)
    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    record_count = 0
    
    def count_records(payload: Any) -> int:
        count = 0
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                count += len(payload["data"])
            else:
                for key, value in payload.items():
                    count += count_records(value)
        elif isinstance(payload, list):
            for item in payload:
                count += count_records(item)
        return count

    record_count = count_records(payload)

    cleansed_payload = _cleanse_payload(payload)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(cleansed_payload, f, ensure_ascii=False, indent=2)

    logger.info("정제 완료: %s -> %s (%s건)", input_path.name, output_path.name, record_count)
    return CleanseResult(input_path=input_path, output_path=output_path, record_count=record_count)


def run_cleanse_step(
    data_files: List[str],
    batch_id: str,
    output_root: Path,
) -> List[CleanseResult]:
    """여러 파일에 대해 정제 작업을 수행합니다."""
    output_root = Path(output_root)
    batch_output_dir = output_root / batch_id
    batch_output_dir.mkdir(parents=True, exist_ok=True)

    results: List[CleanseResult] = []
    for file_path in data_files:
        input_path = Path(file_path)
        if not input_path.exists():
            logger.warning("입력 파일을 찾을 수 없습니다: %s", input_path)
            continue
        output_path = batch_output_dir / input_path.name
        result = cleanse_file(input_path, output_path)
        results.append(result)

    logger.info("총 %s개 파일 정제 완료", len(results))
    return results


def main():  # pragma: no cover - CLI 실행용
    import argparse

    parser = argparse.ArgumentParser(description="비급여 데이터 정제 단계")
    parser.add_argument("--batch-id", help="처리할 배치 ID (생략 시 LATEST.txt 사용)")
    parser.add_argument(
        "--input",
        nargs="+",
        help="정제할 JSON 파일 경로 목록 (생략 시 manifest에서 자동 수집)",
    )
    parser.add_argument(
        "--output-root",
        default=str(SRC_ROOT / "steps" / "output" / "cleaned"),
        help="정제 결과를 저장할 루트 디렉토리 (배치 ID 하위에 저장)",
    )
    parser.add_argument(
        "--crawler-output-dir",
        default=str(DEFAULT_CRAWLER_OUTPUT_DIR),
        help="1_crawler 출력 디렉토리 경로 (LATEST 및 manifest 조회에 사용)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    crawler_output_dir = Path(args.crawler_output_dir).resolve()

    try:
        batch_id, data_files = _resolve_inputs_from_latest(
            crawler_output_dir,
            args.batch_id,
            args.input,
        )
    except ValueError as exc:
        logger.error("입력 파라미터를 결정하는 중 오류가 발생했습니다: %s", exc)
        raise SystemExit(1) from exc

    logger.info("정제 대상 배치: %s", batch_id)
    logger.info("정제 대상 파일 수: %s", len(data_files))

    run_cleanse_step(data_files, batch_id, Path(args.output_root))


if __name__ == "__main__":  # pragma: no cover
    main()
