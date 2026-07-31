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

class SeveranceCrawler(BaseCrawler):
    """
    세브란스병원 웹사이트의 비급여 항목 데이터 수집을 위한 크롤러.
    """

    def crawl_tab_by_index(self, tab_index: int) -> List[Dict[str, Any]]:
        """
        지정된 탭의 모든 페이지를 순회하며 데이터를 수집하는 메인 실행 메서드.
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

        while True:
            if isinstance(last_page, int) and current_page > last_page:
                self.logger.info(f"설정된 마지막 페이지({last_page})에 도달하여 크롤링을 중단합니다.")
                break

            self.logger.info(f"페이지 {current_page} 스크래핑을 시작합니다.")
            page_data = self._scrape_current_page_table(column_mapping)

            if page_data:
                all_rows_data.extend(page_data)
                consecutive_empty_pages = 0
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
            
            # 세브란스병원은 부모 li 태그에 is-active 클래스가 있음
            parent_li = tabs_for_check[tab_index].find_element(By.XPATH, "./..")
            if "is-active" in (parent_li.get_attribute("class") or ""):
                self.logger.info("탭이 이미 활성화되어 있습니다.")
                return True
            
            # 3. 클릭을 시도한다.
            self.logger.info(f"{tab_index}번 인덱스 탭 클릭을 시도합니다.")
            try:
                # (중요) 클릭 직전에 요소를 *다시* 찾아서 Stale Element 문제를 회피한다.
                target_tab = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index]
                target_tab.click()
                
                # 클릭 성공 확인 (부모 li의 클래스 확인)
                WebDriverWait(self.driver, 5).until(
                    lambda d: "is-active" in (d.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index].find_element(By.XPATH, "./..").get_attribute("class") or "")
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
                EC.presence_of_element_located((By.CSS_SELECTOR, row_selector))
            )
        except TimeoutException:
            self.logger.warning("데이터 행을 찾지 못했습니다. 빈 페이지일 수 있습니다.")
            return page_rows_data

        num_rows = len(self.driver.find_elements(By.CSS_SELECTOR, row_selector))
        for i in range(num_rows):
            row_data = {}
            try:
                row = self.driver.find_elements(By.CSS_SELECTOR, row_selector)[i]
                cells = row.find_elements(By.TAG_NAME, "td")
                
                for idx, key in column_mapping.items():
                    if idx < len(cells):
                        row_data[key] = cells[idx].text.strip()
                
                if row_data:
                    page_rows_data.append(row_data)
            except StaleElementReferenceException:
                self.logger.warning(f"{i}번째 행 처리 중 StaleElementReferenceException 발생. 해당 행을 건너뜁니다.")
                continue
        return page_rows_data

    def _click_next_page(self) -> bool:
        """
        강화된 페이지네이션 로직: 페이지 번호를 우선적으로 찾고 변경을 검증합니다.
        기존 작동 코드 기반으로 개선된 버전.
        """
        
        page_number_selector = self.config.get('page_number_selector')
        next_block_selector = self.config.get('next_button_selector')
        
        # Helper: 현재 활성 페이지 번호의 텍스트를 찾습니다.
        def get_active_page_text() -> Optional[str]:
            try:
                page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
                for element in page_elements:
                    el_class = element.get_attribute('class') or ''
                    # 세브란스병원은 여러 클래스 패턴을 사용할 수 있음
                    is_active = 'is-active' in el_class or 'active' in el_class or 'on' in el_class or 'ac' in el_class
                    
                    if not is_active:
                        # 내부에 a 태그가 있는 경우도 확인
                        try:
                            link_tag = element.find_element(By.TAG_NAME, 'a')
                            a_class = link_tag.get_attribute('class') or ''
                            is_active = 'active' in a_class or 'on' in a_class or 'ac' in a_class or 'is-active' in a_class
                        except NoSuchElementException:
                            pass
                    
                    if is_active:
                        text = element.text.strip()
                        if text:
                            return text
            except Exception:
                return None
            return None
        
        try:
            if not page_number_selector:
                # page_number_selector가 없으면 다음 버튼만 사용
                if not next_block_selector:
                    return False
                try:
                    next_button = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                    if next_button.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                        WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(next_button))
                        next_button.click()
                        time.sleep(2)
                        return True
                    return False
                except NoSuchElementException:
                    return False
            
            initial_active_text = get_active_page_text()
            self.logger.info(f"현재 활성 페이지 텍스트: '{initial_active_text}'. 다음 페이지 요소를 찾는 중...")
            
            page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
            if not page_elements:
                self.logger.warning("페이지 번호 요소를 찾을 수 없습니다.")
                return False
            
            # 활성 페이지의 인덱스 찾기
            active_idx = -1
            if initial_active_text:
                for i, element in enumerate(page_elements):
                    if element.text.strip() == initial_active_text:
                        active_idx = i
                        break
            
            element_to_click = None
            
            # Case 1: 활성 페이지가 발견되었고, 블록 내에 다음 페이지가 있는 경우
            if active_idx != -1 and active_idx < len(page_elements) - 1:
                # 다음 인덱스의 요소를 클릭
                element_to_click = page_elements[active_idx + 1]
                # 클릭 가능한 요소가 a 태그인지 확인
                try:
                    if element_to_click.tag_name != 'a':
                        a_tag = element_to_click.find_element(By.TAG_NAME, 'a')
                        element_to_click = a_tag
                except NoSuchElementException:
                    pass
                self.logger.info(f"대상: 다음 페이지 번호 '{element_to_click.text.strip()}'")
            
            # Case 2: 활성 페이지가 블록의 끝이거나 찾지 못한 경우, '다음 블록' 버튼 사용
            elif next_block_selector:
                try:
                    element_to_click = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                    self.logger.info(f"대상: '다음 블록' 버튼")
                except NoSuchElementException:
                    self.logger.info("'다음 블록' 버튼을 찾을 수 없습니다. 페이지네이션 종료.")
                    return False
            else:
                self.logger.info("추가 페이지 번호나 '다음 블록' 버튼이 없습니다. 페이지네이션 종료.")
                return False
            
            # 안정적인 클릭 실행
            try:
                self.driver.execute_script("arguments[0].scrollIntoView(true);", element_to_click)
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(element_to_click))
                element_to_click.click()
            except Exception as click_e:
                self.logger.warning(f"표준 클릭 실패: {type(click_e).__name__}. JS 클릭으로 재시도합니다.")
                self.driver.execute_script("arguments[0].click();", element_to_click)
            
            # 핵심: 활성 페이지 번호가 실제로 변경되었는지 검증
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: get_active_page_text() != initial_active_text
                )
                new_active_text = get_active_page_text()
                self.logger.info(f"페이지 이동 성공. 새 활성 페이지 텍스트: '{new_active_text}'")
                return True
            except TimeoutException:
                self.logger.error(f"CRITICAL: 페이지 클릭이 효과가 없었습니다. 페이지가 '{initial_active_text}'에서 변경되지 않았습니다. 무한 루프 방지를 위해 페이지네이션을 중단합니다.")
                return False
                
        except Exception as e:
            self.logger.error(f"페이지네이션 중 치명적 오류 발생: {e}", exc_info=True)
            return False

    def _get_column_mapping(self, tab_index: int) -> Dict[int, str]:
        """
        세브란스병원 테이블의 탭별 컬럼 매핑을 반환합니다.
        
        Args:
            tab_index: 탭 인덱스 (0: 행위, 1: 치료재료, 2: 약제, 3: 제증명수수료)
        """
        if tab_index == 0:  # 행위
            return {
                0: "중분류", 1: "소분류", 2: "코드", 3: "명칭", 4: "구분", 5: "비용",
                6: "최저비용", 7: "최고비용", 8: "치료재료대 포함", 9: "약제비 포함", 11: "특이사항", 10: "최종 변경일"
            }
        elif tab_index == 1:  # 치료재료
            return {
                0: "중분류", 2: "코드", 3: "명칭", 4: "구분", 5: "비용",
                6: "최저비용", 7: "최고비용", 11: "특이사항", 10: "최종 변경일"
            }
        elif tab_index == 2:  # 약제
            return {
                2: "코드", 3: "명칭", 5: "비용", 11: "특이사항", 10: "최종 변경일"
            }
        elif tab_index == 3:  # 제증명수수료
            return {
                2: "코드", 3: "명칭", 4: "구분", 5: "비용", 11: "특이사항", 10: "최종 변경일"
            }
        else:
            self.logger.warning(f"알 수 없는 탭 인덱스: {tab_index}. 기본 매핑 사용.")
            return {0: "분류", 1: "코드", 2: "명칭", 3: "가격"}
