import time
import logging
from typing import List, Dict, Any, Optional

from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    ElementClickInterceptedException,
    NoSuchElementException
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import sys
from pathlib import Path
# 상위 디렉토리를 path에 추가
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))
from base_crawler import BaseCrawler

MAX_CONSECUTIVE_EMPTY = 3

class SNUCrawler(BaseCrawler):
    """
    서울대학교병원 웹사이트의 비급여 항목 데이터 수집을 위한 크롤러.
    '동작 직전 요소 재탐색' 패턴과 JavaScript 클릭 폴백(fallback)을 사용하여
    안정적인 데이터 수집을 목표로 합니다.
    """

    def crawl_tab_by_index(self, tab_index: int) -> List[Dict[str, Any]]:
        """
        지정된 탭의 모든 페이지를 순회하며 데이터를 수집하는 메인 실행 메서드.

        Args:
            tab_index (int): 크롤링할 탭의 인덱스 (0부터 시작).

        Returns:
            List[Dict[str, Any]]: 수집된 모든 데이터의 리스트.
        """
        all_rows_data = []
        if not self._switch_to_tab_by_index(tab_index):
            self.logger.error(f"탭 인덱스 {tab_index}로 전환하는 데 실패했습니다.")
            return all_rows_data

        column_mapping = self._get_column_mapping(tab_index)
        last_page_key = f'{self.internal_name} 마지막 페이지'
        last_page = self.config.get(last_page_key)
        
        current_page = 1
        consecutive_empty_pages = 0
        previous_first_row = None  # 무한 루프 방지용

        while True:
            if isinstance(last_page, int) and current_page > last_page:
                self.logger.info(f"설정된 마지막 페이지({last_page})에 도달하여 크롤링을 중단합니다.")
                break

            self.logger.info(f"페이지 {current_page} 스크래핑을 시작합니다.")
            page_data = self._scrape_current_page_table(column_mapping)

            if page_data:
                # 무한 루프 방지: 첫 번째 행이 이전 페이지와 동일한지 확인
                if previous_first_row and len(page_data) > 0:
                    current_first_row = str(page_data[0])
                    if current_first_row == previous_first_row:
                        self.logger.warning("이전 페이지와 동일한 데이터가 발견되었습니다. 무한 루프 방지를 위해 중단합니다.")
                        break
                
                all_rows_data.extend(page_data)
                consecutive_empty_pages = 0
                # 다음 페이지 비교를 위해 첫 번째 행 저장
                if len(page_data) > 0:
                    previous_first_row = str(page_data[0])
            else:
                consecutive_empty_pages += 1
                self.logger.warning(f"페이지 {current_page}에서 데이터를 찾지 못했습니다. (연속 {consecutive_empty_pages}회)")

            if consecutive_empty_pages >= MAX_CONSECUTIVE_EMPTY:
                self.logger.critical(f"{MAX_CONSECUTIVE_EMPTY}회 연속으로 빈 페이지가 발견되어 크롤링을 중단합니다.")
                break

            if not self._click_next_page():
                self.logger.info("마지막 페이지에 도달했거나 다음 페이지 버튼을 찾을 수 없어 크롤링을 종료합니다.")
                break
            
            current_page += 1
            time.sleep(0.5)  # 페이지 간 대기 시간 단축

        return all_rows_data

    def _switch_to_tab_by_index(self, tab_index: int) -> bool:
        """Stale Element Exception에 대응하기 위해 클릭 직전에 요소를 다시 찾는 로직으로 강화된 최종 버전."""
        tab_selector = self.config['tab_selector']
        if not tab_selector:
            self.logger.error("'tab_selector'가 설정에 정의되지 않았습니다.")
            return False
        
        try:
            wait = WebDriverWait(self.driver, 15)
            
            # 1. 탭들이 나타날 때까지 기다린다.
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, tab_selector)))
            
            # 2. (중요) 현재 탭인지 확인하기 위해 *최신* 탭 목록을 가져온다.
            tabs_for_check = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)
            if tab_index >= len(tabs_for_check):
                self.logger.error(f"탭 인덱스 {tab_index}가 범위를 벗어났습니다. (총 {len(tabs_for_check)}개 탭)")
                return False
            
            if "on" in (tabs_for_check[tab_index].get_attribute("class") or ""):
                self.logger.info("탭이 이미 활성화되어 있습니다.")
                return True
            
            # 3. 클릭을 시도한다.
            self.logger.info(f"{tab_index}번 인덱스 탭 클릭을 시도합니다.")
            try:
                # (중요) 클릭 직전에 요소를 *다시* 찾아서 Stale Element 문제를 회피한다.
                target_tab = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index]
                target_tab.click()
                
                # 클릭 성공 확인
                WebDriverWait(self.driver, 5).until(
                    lambda d: "on" in (d.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index].get_attribute("class") or "")
                )
                self.logger.info("탭 클릭 및 확인 성공.")
                time.sleep(2)  # 탭 로딩 대기 시간 단축
                return True
            except Exception as e:
                self.logger.warning(f"표준 클릭 실패 ({type(e).__name__}). JavaScript 클릭으로 재시도합니다.")
                try:
                    # (중요) JS 클릭 직전에도 요소를 *다시* 찾는다.
                    target_tab_js = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index]
                    self.driver.execute_script("arguments[0].click();", target_tab_js)
                    self.logger.info("JavaScript 클릭 완료. 성공으로 간주합니다.")
                    time.sleep(2)  # JS 실행 대기 시간 단축
                    return True
                except Exception as js_e:
                    self.logger.error(f"모든 클릭 시도 실패. 최종 오류: {type(js_e).__name__}")
                    return False
        
        except Exception as e:
            self.logger.error(f"탭 전환 중 치명적 오류 발생: {e}", exc_info=True)
            return False

    def _scrape_current_page_table(self, column_mapping: Dict[int, str]) -> List[Dict[str, Any]]:
        """현재 페이지의 테이블 데이터를 추출합니다."""
        page_rows_data = []
        row_selector = self.config['row_selector']
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, row_selector))
            )
        except TimeoutException:
            self.logger.warning("데이터 행을 찾지 못했습니다. 빈 페이지일 수 있습니다.")
            return page_rows_data

        num_rows = len(self.driver.find_elements(By.CSS_SELECTOR, row_selector))
        for i in range(num_rows):
            row_data = {}
            try:
                # Stale 방지를 위해 루프 내에서 row를 다시 찾음
                row = self.driver.find_elements(By.CSS_SELECTOR, row_selector)[i]
                cells = row.find_elements(By.XPATH, ".//th | .//td")
                
                visible_cells = [cell for cell in cells if cell.is_displayed()]
                
                for idx, key in column_mapping.items():
                    if idx < len(visible_cells):
                        row_data[key] = visible_cells[idx].text.strip()
                
                if row_data:
                    page_rows_data.append(row_data)
            except StaleElementReferenceException:
                self.logger.warning(f"{i}번째 행 처리 중 StaleElementReferenceException 발생. 해당 행을 건너뜁니다.")
                continue
        return page_rows_data

    def _click_next_page(self) -> bool:
        """다음 페이지로 이동하고, 페이지 변경을 검증하여 무한 루프를 방지합니다."""
        
        page_number_selector = self.config.get('page_number_selector')
        if not page_number_selector:
            # page_number_selector가 없으면 다음 버튼만 사용
            try:
                next_button = self.driver.find_element(By.CSS_SELECTOR, self.config['next_button_selector'])
                if next_button.is_displayed():
                    self.driver.execute_script("arguments[0].click();", next_button)
                    time.sleep(2)
                    return True
                return False
            except NoSuchElementException:
                return False
        
        def get_active_page_text() -> Optional[str]:
            try:
                # nextBtn, firstBtn, prevBtn, lastBtn을 제외한 페이지 번호 링크만 찾기
                page_links = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
                for link in page_links:
                    # 네비게이션 버튼들은 제외
                    link_class = link.get_attribute("class") or ""
                    if 'nextBtn' in link_class or 'prevBtn' in link_class or 'firstBtn' in link_class or 'lastBtn' in link_class:
                        continue
                    
                    # 서울대병원은 'current' 클래스를 사용 (실제 HTML 확인 결과)
                    if 'current' in link_class:
                        text = link.text.strip()
                        if text and text.isdigit():
                            self.logger.debug(f"활성 페이지 발견: '{text}' (클래스: {link_class})")
                            return text
            except (NoSuchElementException, StaleElementReferenceException) as e:
                self.logger.debug(f"활성 페이지 찾기 실패: {type(e).__name__}")
                return None
            return None

        initial_active_text = get_active_page_text()
        self.logger.info(f"현재 활성 페이지: '{initial_active_text}'")

        element_to_click = None
        
        # Case 1: 다음 숫자 페이지 버튼 찾기 (활성 페이지 + 1)
        if initial_active_text and initial_active_text.isdigit():
            try:
                page_links = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
                current_page_num = int(initial_active_text)
                next_page_num = current_page_num + 1
                
                # 다음 페이지 번호를 찾기 (네비게이션 버튼 제외)
                for link in page_links:
                    link_class = link.get_attribute("class") or ""
                    # 네비게이션 버튼들은 건너뛰기
                    if 'nextBtn' in link_class or 'prevBtn' in link_class or 'firstBtn' in link_class or 'lastBtn' in link_class:
                        continue
                    
                    text = link.text.strip()
                    if text and text.isdigit() and int(text) == next_page_num:
                        element_to_click = link
                        self.logger.info(f"다음 숫자 페이지 버튼 발견: {next_page_num}")
                        break
            except (StaleElementReferenceException, ValueError):
                self.logger.warning("페이지 번호 분석 중 오류 발생.")

        # Case 2: '다음 블록' 버튼 찾기 (Case 1이 실패했을 때만)
        if not element_to_click:
            try:
                next_block_button = self.driver.find_element(By.CSS_SELECTOR, self.config['next_button_selector'])
                if next_block_button.is_displayed():
                    element_to_click = next_block_button
                    self.logger.info("다음 블록 버튼 사용")
            except NoSuchElementException:
                self.logger.info("'다음 블록' 버튼을 찾을 수 없습니다.")

        # Case 3: 클릭 대상 없음
        if not element_to_click:
            return False

        # 클릭 전 현재 데이터 행 개수 저장 (페이지 변경 확인용)
        try:
            row_selector = self.config.get('row_selector')
            initial_row_count = len(self.driver.find_elements(By.CSS_SELECTOR, row_selector))
        except:
            initial_row_count = 0

        # 클릭 실행 (JS Fallback 포함)
        try:
            self.driver.execute_script("arguments[0].scrollIntoView(true);", element_to_click)
            WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(element_to_click))
            element_to_click.click()
            self.logger.info("페이지 버튼 클릭 완료")
        except (ElementClickInterceptedException, StaleElementReferenceException):
            self.logger.warning("표준 페이지네이션 클릭 실패. JS 클릭으로 재시도합니다.")
            try:
                self.driver.execute_script("arguments[0].click();", element_to_click)
                self.logger.info("JS로 페이지 버튼 클릭 완료")
            except Exception as e:
                self.logger.error(f"JS 페이지네이션 클릭 실패: {e}")
                return False

        # 페이지 로딩 대기
        time.sleep(2)  # 로딩 시간 단축
        self.logger.info("페이지 로딩 대기 중...")

        # 핵심 검증: 페이지 번호가 실제로 변경되었는지 확인 (삼성서울병원 방식과 동일하게 단순화)
        try:
            # 페이지 번호 변경 확인
            for attempt in range(2):  # 최대 2번 시도로 단축
                time.sleep(1)  # 각 시도마다 1초 대기로 단축
                new_active_text = get_active_page_text()
                if new_active_text and new_active_text != initial_active_text:
                    self.logger.info(f"페이지 이동 성공. 새 활성 페이지: '{new_active_text}'")
                    return True
                elif new_active_text and new_active_text == initial_active_text:
                    # 페이지 번호가 아직 변경되지 않음, 계속 대기
                    self.logger.debug(f"페이지 번호 변경 대기 중... (시도 {attempt + 1}/3)")
                    continue
                else:
                    # 활성 페이지를 찾지 못함 (첫 페이지였거나 아직 로딩 중)
                    break
            
            # 페이지 번호가 변경되지 않았지만, 데이터 행 개수로 확인
            new_row_count = len(self.driver.find_elements(By.CSS_SELECTOR, row_selector))
            if new_row_count != initial_row_count:
                self.logger.info(f"페이지 이동 성공 (데이터 행 개수 변경). 이전: {initial_row_count}, 현재: {new_row_count}")
                return True
            elif new_row_count > 0:
                # 데이터가 있으면 페이지 이동한 것으로 간주
                self.logger.info(f"페이지 이동 성공 (데이터 확인). 행 개수: {new_row_count}")
                return True
            else:
                # 데이터도 없으면 실제로 페이지가 변경되지 않았을 가능성
                self.logger.warning("페이지 번호와 데이터 모두 변경되지 않았지만 계속 진행합니다.")
                return True
                
        except Exception as e:
            self.logger.warning(f"페이지 변경 확인 중 오류 발생: {e}. 계속 진행합니다.")
            return True

    def _get_column_mapping(self, tab_index: int) -> Dict[int, str]:
        """
        서울대학교병원 테이블의 탭별 컬럼 매핑을 반환합니다.
        
        Args:
            tab_index: 탭 인덱스 (0: 행위, 1: 치료재료, 2: 약제, 3: 제증명수수료)
        """
        if tab_index == 0:  # 행위
            return {
                0: "중분류", 1: "소분류", 2: "명칭", 3: "코드", 4: "구분", 
                5: "비용", 6: "최저비용", 7: "최고비용", 8: "치료재료대 포함", 
                9: "약제비 포함", 10: "특이사항", 11: "최종 변경일"
            }
        elif tab_index == 1:  # 치료재료
            return {
                0: "중분류", 1: "명칭", 2: "코드", 3: "구분", 4: "비용",
                5: "최저비용", 6: "최고비용", 7: "특이사항", 8: "최종 변경일"
            }
        elif tab_index == 2:  # 약제
            return {
                0: "명칭", 1: "코드", 2: "비용", 3: "특이사항", 4: "최종 변경일"
            }
        elif tab_index == 3:  # 제증명수수료
            return {
                0: "명칭", 1: "코드", 2: "구분", 3: "비용", 6: "특이사항", 7: "최종 변경일"
            }
        else:
            self.logger.warning(f"알 수 없는 탭 인덱스: {tab_index}. 기본 매핑 사용.")
            return {0: "분류", 1: "코드", 2: "명칭", 3: "가격"}