import json
import logging
import os
import sys
import argparse
import glob
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

# 현재 파일의 디렉토리를 Python path에 추가
current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
import time

# 각 병원별 크롤러 임포트
from crawler.snu_crawler import SNUCrawler
from crawler.samsung_crawler import SamsungCrawler
from crawler.severance_crawler import SeveranceCrawler
from crawler.asan_crawler import AsanCrawler
from crawler.cmc_crawler import SeoulStMarysCrawler

# 로거 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 크롤러 매핑
CRAWLER_MAPPING = {
    "snu_hospital": SNUCrawler,
    "samsung_medical_center": SamsungCrawler,
    "severance_hospital": SeveranceCrawler,
    "asan_medical_center": AsanCrawler,
    "seoul_st_marys_hospital": SeoulStMarysCrawler,
}

def setup_driver():
    """Selenium WebDriver를 설정하고 반환합니다."""
    options = webdriver.ChromeOptions()
    # Docker 컨테이너 환경에서 실행하기 위한 필수 옵션들
    options.add_argument("--headless")  # GUI 없이 백그라운드에서 실행
    options.add_argument("--no-sandbox") # 컨테이너 환경에서의 충돌 방지
    options.add_argument("--disable-dev-shm-usage") # 공유 메모리 사용 비활성화
    options.add_argument("--disable-gpu") # GPU 가속 비활성화
    options.add_argument("window-size=1920x1080") # 일부 웹사이트는 창 크기에 따라 레이아웃이 변경될 수 있음

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def check_hospital_completed(output_dir: str, internal_name: str, timestamp: str) -> bool:
    """
    특정 병원의 크롤링이 완료되었는지 확인합니다.
    
    Args:
        output_dir: 출력 디렉토리 경로
        internal_name: 병원 내부 이름
        timestamp: 배치 타임스탬프
        
    Returns:
        완료 여부
    """
    hospital_file = os.path.join(output_dir, f'{internal_name}_{timestamp}.json')
    if os.path.exists(hospital_file):
        try:
            with open(hospital_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 데이터가 있고 에러가 없으면 완료로 간주
                if data and not any('error' in tab_info for tab_info in data.get('tabs', {}).values()):
                    return True
        except (json.JSONDecodeError, FileNotFoundError) as e:
            # 파일이 없거나 JSON 파싱 오류는 정상적인 케이스일 수 있으므로 경고 없이 넘어감
            pass
    return False

def find_latest_batch_from_files(output_dir: str, configs: dict) -> Optional[str]:
    """
    저장된 병원 파일들의 타임스탬프를 분석하여 가장 최근 배치 ID를 찾습니다.
    중단된 크롤링의 경우 manifest가 없어도 파일 타임스탬프로 배치를 찾을 수 있습니다.
    
    Args:
        output_dir: 출력 디렉토리 경로
        configs: 병원 설정 딕셔너리
        
    Returns:
        가장 최근 배치 ID (타임스탬프) 또는 None
    """
    # 모든 병원 파일 찾기
    found_timestamps = set()
    
    # 각 병원의 파일 패턴: {internal_name}_*.json 또는 {internal_name}_{tab_name}_*.json
    for internal_name in configs.keys():
        # 병원별 파일: snu_hospital_20251106_125819.json
        pattern1 = os.path.join(output_dir, f'{internal_name}_*.json')
        files1 = glob.glob(pattern1)
        
        # 탭별 파일: snu_hospital_행위_20251106_125819.json
        pattern2 = os.path.join(output_dir, f'{internal_name}_*_*.json')
        files2 = glob.glob(pattern2)
        
        all_files = files1 + files2
        
        for file_path in all_files:
            # 파일명에서 타임스탬프 추출: YYYYMMDD_HHMMSS 형식
            filename = os.path.basename(file_path)
            # 패턴: {internal_name}_{tab_name}_YYYYMMDD_HHMMSS.json 또는 {internal_name}_YYYYMMDD_HHMMSS.json
            match = re.search(r'(\d{8}_\d{6})\.json$', filename)
            if match:
                found_timestamps.add(match.group(1))
    
    if not found_timestamps:
        return None
    
    # 가장 최근 타임스탬프 반환 (문자열 정렬로 최신 순)
    latest_timestamp = sorted(found_timestamps, reverse=True)[0]
    
    # 해당 타임스탬프의 파일이 있는지 확인
    count = 0
    for internal_name in configs.keys():
        hospital_file = os.path.join(output_dir, f'{internal_name}_{latest_timestamp}.json')
        if os.path.exists(hospital_file):
            count += 1
    
    # 최소 1개 이상의 병원 파일이 있어야 유효한 배치로 간주
    if count > 0:
        return latest_timestamp
    
    return None

def load_existing_results(output_dir: str, timestamp: str, configs: dict) -> dict:
    """
    기존 크롤링 결과를 로드합니다 (재시작 시 사용).
    
    Args:
        output_dir: 출력 디렉토리 경로
        timestamp: 배치 타임스탬프
        configs: 병원 설정 딕셔너리
        
    Returns:
        기존 결과 딕셔너리
    """
    all_results = {}
    
    # 먼저 통합 파일에서 로드 시도 (더 완전한 데이터)
    all_hospitals_file = os.path.join(output_dir, f'all_hospitals_data_{timestamp}.json')
    if os.path.exists(all_hospitals_file):
        try:
            with open(all_hospitals_file, 'r', encoding='utf-8') as f:
                all_results = json.load(f)
                logging.info(f"✅ 통합 파일에서 기존 결과 로드: {len(all_results)}개 병원")
        except Exception as e:
            logging.warning(f"통합 파일 로드 실패: {e}. 개별 파일에서 로드를 시도합니다.")
    
    # 통합 파일이 없거나 실패한 경우, 개별 병원 파일에서 로드
    if not all_results:
        for internal_name in configs.keys():
            hospital_file = os.path.join(output_dir, f'{internal_name}_{timestamp}.json')
            if os.path.exists(hospital_file):
                try:
                    with open(hospital_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        all_results[internal_name] = data
                        logging.info(f"✅ 기존 결과 로드: {internal_name} ({data.get('total_item_count', 0)}개 항목)")
                except Exception as e:
                    logging.warning(f"기존 결과 로드 실패 ({internal_name}): {e}")
    
    return all_results

def main():
    """
    big5_config.json에 정의된 모든 병원의 비급여 항목을 순차적으로 크롤링합니다.
    
    명령줄 옵션:
        --resume: 기존 배치에 이어서 크롤링 (완료된 병원은 스킵)
        --batch-id: 특정 배치 ID에 이어서 크롤링 (없으면 최신 배치 사용)
        --skip-hospitals: 스킵할 병원 목록 (쉼표로 구분)
        --only-hospitals: 크롤링할 병원 목록 (쉼표로 구분, 나머지는 스킵)
    """
    parser = argparse.ArgumentParser(description='5대 병원 비급여 항목 크롤러')
    parser.add_argument('--resume', action='store_true', help='기존 배치에 이어서 크롤링 (완료된 병원은 스킵)')
    parser.add_argument('--batch-id', type=str, help='특정 배치 ID (--resume과 함께 사용)')
    parser.add_argument('--skip-hospitals', type=str, help='스킵할 병원 목록 (쉼표로 구분, 예: snu_hospital,severance_hospital)')
    parser.add_argument('--only-hospitals', type=str, help='크롤링할 병원 목록 (쉼표로 구분, 예: snu_hospital,severance_hospital)')
    args = parser.parse_args()
    
    # 설정 파일 로드
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'big5_config.json')
    logging.info(f"설정 파일 로드 중: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        configs = json.load(f)
    
    logging.info(f"설정 파일 로드 완료. 총 {len(configs)}개 병원 설정 발견: {list(configs.keys())}")

    # 출력 디렉토리 준비
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    # 병원 필터링 (먼저 수행하여 재시작 모드 결정에 사용)
    hospitals_to_process = list(configs.keys())
    
    if args.skip_hospitals:
        skip_list = [h.strip() for h in args.skip_hospitals.split(',')]
        hospitals_to_process = [h for h in hospitals_to_process if h not in skip_list]
        logging.info(f"⏭️  스킵할 병원: {skip_list}")
        logging.info(f"📋 크롤링할 병원: {hospitals_to_process}")
    
    if args.only_hospitals:
        only_list = [h.strip() for h in args.only_hospitals.split(',')]
        hospitals_to_process = [h for h in hospitals_to_process if h in only_list]
        logging.info(f"🎯 지정된 병원만 크롤링: {hospitals_to_process}")
    
    # 부분 크롤링(--only-hospitals 또는 --skip-hospitals)이 있으면 자동으로 재시작 모드로 동작
    auto_resume = args.only_hospitals is not None or args.skip_hospitals is not None
    
    # 타임스탬프 결정 및 기존 결과 로드
    if args.resume or auto_resume:
        if args.batch_id:
            timestamp = args.batch_id
            logging.info(f"🔄 지정된 배치 ID 사용: '{timestamp}'")
        else:
            # 1순위: LATEST.txt에서 최신 배치 찾기
            processing_queue_dir = os.path.join(output_dir, 'processing_queue')
            latest_file = os.path.join(processing_queue_dir, 'LATEST.txt')
            timestamp = None
            
            if os.path.exists(latest_file):
                with open(latest_file, 'r', encoding='utf-8') as f:
                    timestamp = f.read().strip()
                logging.debug(f"LATEST.txt에서 배치 ID 발견: {timestamp}")
            
            # 2순위: 저장된 병원 파일들의 타임스탬프 분석 (중단된 크롤링 감지용)
            if not timestamp:
                file_based_timestamp = find_latest_batch_from_files(output_dir, configs)
                if file_based_timestamp:
                    timestamp = file_based_timestamp
                    logging.info(f"📁 저장된 파일에서 배치 ID 감지: '{timestamp}' (중단된 크롤링으로 추정)")
            
            # 3순위: 배치를 찾을 수 없으면 새로 생성
            if not timestamp:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                if auto_resume:
                    logging.warning(f"⚠️  기존 배치를 찾을 수 없어 새 배치를 생성합니다: {timestamp}")
                    logging.info("💡 팁: 처음 실행 시에는 모든 병원을 크롤링한 후, 부분 크롤링을 사용하세요.")
                else:
                    logging.warning(f"최신 배치를 찾을 수 없어 새 배치를 생성합니다: {timestamp}")
            else:
                if auto_resume and not args.resume:
                    logging.info(f"🔄 부분 크롤링 모드: 기존 배치 '{timestamp}'에 이어서 크롤링합니다.")
                else:
                    logging.info(f"🔄 재시작 모드: 기존 배치 '{timestamp}'에 이어서 크롤링합니다.")
        
        # 재시작 모드: 기존 결과 로드 (모든 병원 정보 포함)
        all_results = load_existing_results(output_dir, timestamp, configs)
        if all_results:
            existing_hospitals = list(all_results.keys())
            logging.info(f"✅ 기존 결과 로드 완료: {len(existing_hospitals)}개 병원 ({', '.join(existing_hospitals)})")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        all_results = {}
        logging.info(f"🆕 새 배치 시작: {timestamp}")
    
    # 재시작 모드이고 부분 크롤링인 경우, 기존 완료된 병원 정보는 유지하되 크롤링은 지정된 병원만 수행
    # all_results에는 이미 기존 결과가 포함되어 있음

    driver = setup_driver()

    try:
        for internal_name, config in configs.items():
            # 필터링된 병원만 처리
            if internal_name not in hospitals_to_process:
                continue
                
            if internal_name not in CRAWLER_MAPPING:
                logging.warning(f"'{internal_name}'에 대한 크롤러가 CRAWLER_MAPPING에 정의되지 않았습니다. 건너뜁니다.")
                continue

            logger = logging.getLogger(internal_name)
            
            # 재시작 모드: 이미 완료된 병원은 스킵
            if args.resume and check_hospital_completed(output_dir, internal_name, timestamp):
                logger.info(f"⏭️  '{config['display_name']}'는 이미 크롤링 완료되었습니다. 스킵합니다.")
                continue
            
            try:
                logger.info(f"🔄 '{config['display_name']}' 크롤링을 시작합니다.")
                logger.info(f"URL: {config['url']}")
                logger.info(f"탭 셀렉터: {config.get('tab_selector', 'N/A')}")
                
                driver.get(config['url'])
                # 페이지가 완전히 로드될 때까지 대기
                logger.info("페이지 로딩 중...")
                time.sleep(5)  # 초기 로딩 대기 시간 증가
                logger.info("페이지 로딩 완료, 탭 찾기를 시도합니다.")
                
                crawler_class = CRAWLER_MAPPING[internal_name]
                crawler = crawler_class(driver, config, logger, internal_name)

                # 모든 탭을 크롤링하고 탭 이름별로 구분
                tab_selector = config.get('tab_selector')
                if not tab_selector:
                    logger.error("탭 셀렉터가 설정에 정의되지 않았습니다.")
                    continue
                
                # 탭이 로드될 때까지 대기 (타임아웃 처리 추가)
                try:
                    logger.info(f"탭 요소 찾기 대기 중... (셀렉터: {tab_selector})")
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, tab_selector))
                    )
                    tabs = driver.find_elements(By.CSS_SELECTOR, tab_selector)
                    logger.info(f"총 {len(tabs)}개 탭 발견")
                except TimeoutException:
                    logger.error(f"타임아웃: 탭 요소를 찾을 수 없습니다. (셀렉터: {tab_selector})")
                    # 페이지 소스 일부 확인
                    try:
                        page_source_snippet = driver.page_source[:1000]
                        logger.debug(f"페이지 소스 일부: {page_source_snippet}")
                    except:
                        pass
                    logger.warning("이 병원은 건너뜁니다. 다음 병원으로 진행합니다.")
                    # 에러 정보를 결과에 저장
                    hospital_info = {
                        'display_name': config['display_name'],
                        'url': config['url'],
                        'tabs': {},
                        'total_item_count': 0,
                        'tab_count': 0,
                        'error': '탭 요소를 찾을 수 없습니다.'
                    }
                    all_results[internal_name] = hospital_info
                    # 에러가 있어도 파일은 저장 (재시작 시 알 수 있도록)
                    try:
                        hospital_file = os.path.join(output_dir, f'{internal_name}_{timestamp}.json')
                        with open(hospital_file, 'w', encoding='utf-8') as f:
                            json.dump(hospital_info, f, ensure_ascii=False, indent=4)
                    except Exception as save_error:
                        logger.error(f"에러 정보 저장 실패: {save_error}")
                    continue
                
                hospital_data_by_tab = {}
                total_items = 0
                
                for tab_index in range(len(tabs)):
                    try:
                        # 탭 이름 가져오기 (Stale Element 방지를 위해 매번 다시 찾기)
                        tab_elements = driver.find_elements(By.CSS_SELECTOR, tab_selector)
                        if tab_index >= len(tab_elements):
                            logger.warning(f"탭 인덱스 {tab_index}가 범위를 벗어났습니다. 건너뜁니다.")
                            continue
                        
                        tab_element = tab_elements[tab_index]
                        tab_name = tab_element.text.strip()
                        if not tab_name:
                            # 텍스트가 없으면 innerHTML이나 다른 속성에서 가져오기 시도
                            tab_name = tab_element.get_attribute('title') or tab_element.get_attribute('alt') or tab_element.get_attribute('innerHTML') or f'탭_{tab_index + 1}'
                            tab_name = tab_name.strip()
                        
                        logger.info(f"탭 {tab_index}: '{tab_name}' 크롤링 시작")
                        
                        # 각 탭 크롤링
                        tab_data = crawler.crawl_tab_by_index(tab_index)
                        hospital_data_by_tab[tab_name] = {
                            'data': tab_data,
                            'item_count': len(tab_data)
                        }
                        total_items += len(tab_data)
                        logger.info(f"탭 '{tab_name}' 크롤링 완료. {len(tab_data)}개 항목 수집")
                        
                    except Exception as e:
                        logger.error(f"탭 {tab_index} 크롤링 중 오류 발생: {e}", exc_info=True)
                        # 탭 이름을 가져오지 못한 경우
                        tab_name = f'탭_{tab_index + 1}'
                        hospital_data_by_tab[tab_name] = {
                            'data': [],
                            'item_count': 0,
                            'error': str(e)
                        }
                
                hospital_info = {
                    'display_name': config['display_name'],
                    'url': config['url'],
                    'tabs': hospital_data_by_tab,
                    'total_item_count': total_items,
                    'tab_count': len(hospital_data_by_tab),
                    'crawled_at': datetime.now().isoformat()
                }
                all_results[internal_name] = hospital_info
                logger.info(f"✅ '{config['display_name']}' 크롤링 완료. 총 {len(hospital_data_by_tab)}개 탭, {total_items}개 항목 수집.")
                
                # 각 병원 크롤링 완료 시 즉시 저장
                try:
                    # 병원별 파일 저장
                    hospital_file = os.path.join(output_dir, f'{internal_name}_{timestamp}.json')
                    with open(hospital_file, 'w', encoding='utf-8') as f:
                        json.dump(hospital_info, f, ensure_ascii=False, indent=4)
                    logger.info(f"✅ '{config['display_name']}' 데이터 저장 완료: {hospital_file}")
                    
                    # 각 병원의 탭별로도 개별 파일 저장
                    for tab_name, tab_info in hospital_data_by_tab.items():
                        # 파일명에 사용할 수 없는 문자 제거
                        safe_tab_name = tab_name.replace('/', '_').replace('\\', '_').replace(':', '_').replace('?', '_').replace('*', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
                        tab_file = os.path.join(output_dir, f'{internal_name}_{safe_tab_name}_{timestamp}.json')
                        with open(tab_file, 'w', encoding='utf-8') as f:
                            json.dump({
                                'hospital': config['display_name'],
                                'tab_name': tab_name,
                                'data': tab_info.get('data', []),
                                'item_count': tab_info.get('item_count', 0)
                            }, f, ensure_ascii=False, indent=4)
                        logger.info(f"  ✅ 탭 '{tab_name}' 데이터 저장: {tab_file}")
                except Exception as save_error:
                    logger.error(f"데이터 저장 중 오류 발생: {save_error}", exc_info=True)
            
            except Exception as hospital_error:
                # 병원 크롤링 중 예외 발생 시에도 계속 진행
                logger.error(f"'{config['display_name']}' 크롤링 중 치명적 오류 발생: {hospital_error}", exc_info=True)
                # 에러 정보를 결과에 저장
                hospital_info = {
                    'display_name': config['display_name'],
                    'url': config['url'],
                    'tabs': {},
                    'total_item_count': 0,
                    'tab_count': 0,
                    'error': str(hospital_error),
                    'crawled_at': datetime.now().isoformat()
                }
                all_results[internal_name] = hospital_info
                # 에러가 있어도 파일은 저장
                try:
                    hospital_file = os.path.join(output_dir, f'{internal_name}_{timestamp}.json')
                    with open(hospital_file, 'w', encoding='utf-8') as f:
                        json.dump(hospital_info, f, ensure_ascii=False, indent=4)
                    logger.info(f"⚠️  에러 정보 저장 완료: {hospital_file}")
                except Exception as save_error:
                    logger.error(f"에러 정보 저장 실패: {save_error}")
                logger.info("다음 병원으로 진행합니다.")

    except Exception as e:
        logging.error(f"크롤링 중 예외 발생: {e}", exc_info=True)
    finally:
        driver.quit()
        logging.info("WebDriver를 종료했습니다.")

    # 모든 병원 크롤링 완료 후 통합 파일 저장
    # 재시작 모드인 경우, 기존에 완료된 병원들도 포함하여 저장
    if all_results:
        output_file = os.path.join(output_dir, f'all_hospitals_data_{timestamp}.json')
        try:
            # 재시작 모드 또는 auto_resume 모드인 경우, 기존 통합 파일과 병합
            is_resume_mode = args.resume or auto_resume
            if is_resume_mode and os.path.exists(output_file):
                try:
                    with open(output_file, 'r', encoding='utf-8') as f:
                        existing_all_results = json.load(f)
                    # 기존 결과와 새 결과 병합 (새 결과가 우선)
                    merged_results = {**existing_all_results, **all_results}
                    all_results = merged_results
                    logging.info(f"🔄 기존 통합 파일과 병합 완료: 총 {len(all_results)}개 병원")
                except Exception as e:
                    logging.warning(f"기존 통합 파일 병합 실패: {e}. 새로 저장합니다.")
            elif is_resume_mode:
                # 통합 파일이 없지만 재시작 모드인 경우, 로드한 기존 결과가 이미 all_results에 포함되어 있음
                # (개별 파일에서 로드했을 경우)
                logging.info(f"📋 기존 병원 데이터 포함: {len(all_results)}개 병원 (통합 파일 없음, 개별 파일에서 로드)")
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, ensure_ascii=False, indent=4)
            logging.info(f"✅ 모든 병원 통합 데이터 저장 완료: {output_file} (총 {len(all_results)}개 병원)")
        except Exception as e:
            logging.error(f"통합 파일 저장 중 오류 발생: {e}", exc_info=True)
    
    # 수집 요약 정보 출력
    total_items = sum(info.get('total_item_count', 0) for info in all_results.values())
    total_tabs = sum(info.get('tab_count', 0) for info in all_results.values())
    logging.info(f"크롤링 완료! 총 {len(all_results)}개 병원, {total_tabs}개 탭, {total_items}개 항목 수집")
    logging.info(f"데이터 저장 위치: {output_dir}")
    
    from supabase import create_client
    from datetime import timezone
    from dotenv import load_dotenv
    load_dotenv()
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    supabase.table("crawl_snapshots").insert({
        "batch_id": timestamp,
        "raw_file_name": f"all_hospitals_data_{timestamp}.json",
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "raw_record_count": total_items,
        "note": "자동 크롤링"
    }).execute()


    # 2_processor로 넘기기 위한 메타데이터 및 매니페스트 파일 생성
    if all_results:
        try:
            # 처리 대기 폴더 생성
            processing_queue_dir = os.path.join(output_dir, 'processing_queue')
            os.makedirs(processing_queue_dir, exist_ok=True)
            
            # 타임스탬프별 폴더 생성 (한 번의 크롤링 결과를 그룹화)
            batch_dir = os.path.join(processing_queue_dir, timestamp)
            os.makedirs(batch_dir, exist_ok=True)
            
            # 생성된 파일 목록 수집
            generated_files = []
            
            # 통합 파일 추가
            if os.path.exists(output_file):
                file_basename = os.path.basename(output_file)
                generated_files.append({
                    'type': 'all_hospitals',
                    'file': file_basename,
                    'path': output_file,
                    'relative_path': f'output/{file_basename}'
                })
            
            # 병원별 파일들 추가
            for internal_name in all_results.keys():
                hospital_file = os.path.join(output_dir, f'{internal_name}_{timestamp}.json')
                if os.path.exists(hospital_file):
                    file_basename = os.path.basename(hospital_file)
                    generated_files.append({
                        'type': 'hospital',
                        'hospital': internal_name,
                        'file': file_basename,
                        'path': hospital_file,
                        'relative_path': f'output/{file_basename}'
                    })
            
            # 매니페스트 파일 생성/업데이트 (2_processor가 읽을 파일)
            # 재시작 모드인 경우 기존 매니페스트를 로드하고 업데이트
            manifest_file = os.path.join(batch_dir, 'manifest.json')
            existing_manifest = None
            
            is_resume_mode = args.resume or auto_resume
            if is_resume_mode and os.path.exists(manifest_file):
                try:
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        existing_manifest = json.load(f)
                    logging.info(f"🔄 기존 매니페스트 로드: {manifest_file}")
                except Exception as e:
                    logging.warning(f"기존 매니페스트 로드 실패: {e}. 새로 생성합니다.")
            
            # 기존 매니페스트가 있으면 병합, 없으면 새로 생성
            if existing_manifest:
                # 기존 매니페스트의 파일 목록과 병원 정보 병합
                existing_files = {f['file']: f for f in existing_manifest.get('files', [])}
                existing_hospitals = existing_manifest.get('hospitals', {})
                
                # 새 파일 추가 (기존 파일은 유지)
                for new_file in generated_files:
                    if new_file['file'] not in existing_files:
                        existing_files[new_file['file']] = new_file
                    else:
                        # 파일이 업데이트되었으면 새 정보로 교체
                        existing_files[new_file['file']] = new_file
                
                # 병원 정보 병합 (새 정보가 우선)
                merged_hospitals = {**existing_hospitals, **{
                    internal_name: {
                        'display_name': info['display_name'],
                        'tab_count': info['tab_count'],
                        'total_item_count': info['total_item_count']
                    }
                    for internal_name, info in all_results.items()
                }}
                
                # 요약 정보 재계산
                merged_total_items = sum(h.get('total_item_count', 0) for h in merged_hospitals.values())
                merged_total_tabs = sum(h.get('tab_count', 0) for h in merged_hospitals.values())
                
                manifest = {
                    'batch_id': timestamp,
                    'crawled_at': existing_manifest.get('crawled_at', datetime.now().isoformat()),
                    'updated_at': datetime.now().isoformat(),  # 업데이트 시간 추가
                    'status': 'pending',  # 재시작 시 pending으로 재설정
                    'summary': {
                        'total_hospitals': len(merged_hospitals),
                        'total_tabs': merged_total_tabs,
                        'total_items': merged_total_items
                    },
                    'files': list(existing_files.values()),
                    'hospitals': merged_hospitals
                }
                logging.info(f"🔄 매니페스트 업데이트: {len(merged_hospitals)}개 병원 (기존 {len(existing_hospitals)}개 + 신규 {len(all_results)}개)")
            else:
                # 새로운 매니페스트 생성
                manifest = {
                    'batch_id': timestamp,
                    'crawled_at': datetime.now().isoformat(),
                    'status': 'pending',  # pending, processing, completed, failed
                    'summary': {
                        'total_hospitals': len(all_results),
                        'total_tabs': total_tabs,
                        'total_items': total_items
                    },
                    'files': generated_files,
                    'hospitals': {
                        internal_name: {
                            'display_name': info['display_name'],
                            'tab_count': info['tab_count'],
                            'total_item_count': info['total_item_count']
                        }
                        for internal_name, info in all_results.items()
                    }
                }
                logging.info(f"📝 새 매니페스트 생성: {len(all_results)}개 병원")
            
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=4)
            
            logging.info(f"✅ 처리 대기 매니페스트 저장: {manifest_file}")
            
            # 최신 배치를 가리키는 심볼릭 링크 생성 (Windows에서는 .bat 파일로 대체)
            # 재시작 모드여도 LATEST.txt는 업데이트 (같은 배치이므로)
            latest_link_file = os.path.join(processing_queue_dir, 'LATEST.txt')
            with open(latest_link_file, 'w', encoding='utf-8') as f:
                f.write(timestamp)
            
            logging.info(f"✅ 최신 배치 표시: {latest_link_file} -> {timestamp}")
            logging.info(f"📦 2_processor에서 처리할 배치: {batch_dir}")
            
        except Exception as e:
            logging.error(f"매니페스트 파일 생성 중 오류 발생: {e}", exc_info=True)

if __name__ == "__main__":
    main()