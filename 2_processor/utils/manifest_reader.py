"""
2_processor에서 크롤링 결과를 읽기 위한 유틸리티 모듈
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


def get_latest_batch_id(crawler_output_dir: str) -> Optional[str]:
    """
    가장 최근 크롤링 배치 ID를 반환합니다.
    
    Args:
        crawler_output_dir: 1_crawler/src/output 디렉토리 경로
        
    Returns:
        최신 배치 ID (타임스탬프) 또는 None
    """
    latest_file = os.path.join(crawler_output_dir, 'processing_queue', 'LATEST.txt')
    if os.path.exists(latest_file):
        with open(latest_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return None


def get_pending_batches(crawler_output_dir: str) -> List[str]:
    """
    처리 대기 중인 모든 배치 ID 목록을 반환합니다.
    
    Args:
        crawler_output_dir: 1_crawler/src/output 디렉토리 경로
        
    Returns:
        배치 ID 목록 (오래된 것부터)
    """
    processing_queue_dir = os.path.join(crawler_output_dir, 'processing_queue')
    if not os.path.exists(processing_queue_dir):
        return []
    
    batches = []
    for item in os.listdir(processing_queue_dir):
        batch_dir = os.path.join(processing_queue_dir, item)
        if os.path.isdir(batch_dir) and item != 'LATEST.txt':
            manifest_file = os.path.join(batch_dir, 'manifest.json')
            if os.path.exists(manifest_file):
                try:
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                        if manifest.get('status') == 'pending':
                            batches.append(item)
                except:
                    continue
    
    # 타임스탬프 순으로 정렬 (오래된 것부터)
    batches.sort()
    return batches


def load_manifest(crawler_output_dir: str, batch_id: str) -> Optional[Dict]:
    """
    특정 배치의 매니페스트를 로드합니다.
    
    Args:
        crawler_output_dir: 1_crawler/src/output 디렉토리 경로
        batch_id: 배치 ID (타임스탬프)
        
    Returns:
        매니페스트 딕셔너리 또는 None
    """
    manifest_file = os.path.join(
        crawler_output_dir, 
        'processing_queue', 
        batch_id, 
        'manifest.json'
    )
    
    if os.path.exists(manifest_file):
        with open(manifest_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def update_manifest_status(crawler_output_dir: str, batch_id: str, status: str, error: Optional[str] = None):
    """
    매니페스트의 상태를 업데이트합니다.
    
    Args:
        crawler_output_dir: 1_crawler/src/output 디렉토리 경로
        batch_id: 배치 ID
        status: 새로운 상태 (pending, processing, completed, failed)
        error: 오류 메시지 (선택사항)
    """
    manifest_file = os.path.join(
        crawler_output_dir,
        'processing_queue',
        batch_id,
        'manifest.json'
    )
    
    if os.path.exists(manifest_file):
        with open(manifest_file, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        manifest['status'] = status
        manifest['updated_at'] = datetime.now().isoformat()
        
        if error:
            manifest['error'] = error
        
        if status == 'completed':
            manifest['completed_at'] = datetime.now().isoformat()
        
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=4)


def get_data_files_from_manifest(manifest: Dict, crawler_output_dir: str) -> List[str]:
    """
    매니페스트에서 실제 데이터 파일 경로 목록을 반환합니다.
    
    Args:
        manifest: 매니페스트 딕셔너리
        crawler_output_dir: 1_crawler/src/output 디렉토리 경로
        
    Returns:
        데이터 파일 경로 목록
    """
    files = []
    for file_info in manifest.get('files', []):
        # 절대 경로 사용
        file_path = file_info.get('path')
        if file_path and os.path.exists(file_path):
            files.append(file_path)
    
    return files

