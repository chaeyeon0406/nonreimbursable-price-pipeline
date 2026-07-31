import time
import logging
import re
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

class AsanCrawler(BaseCrawler):
    """
    서울아산병원 웹사이트의 비급여 항목 데이터 수집을 위한 크롤러.
    """

    def crawl_tab_by_index(self, tab_index: int) -> List[Dict[str, Any]]:
        """
        지정된 탭의 모든 페이지를 순회하며 데이터를 수집하는 메인 실행 메서드.
        """
        all_rows_data = []
        
        # 탭 전환 시도 (최대 3번 재시도)
        tab_switched = False
        for retry in range(3):
            if self._switch_to_tab_by_index(tab_index):
                # 탭 전환 후 테이블이 실제로 로드되었는지 확인
                if self._verify_table_loaded():
                    tab_switched = True
                    break
                else:
                    self.logger.warning(f"탭 전환 후 테이블 로드 확인 실패 (재시도 {retry + 1}/3)")
                    time.sleep(2)
            else:
                self.logger.warning(f"탭 인덱스 {tab_index}로 전환 실패 (재시도 {retry + 1}/3)")
                time.sleep(2)
        
        if not tab_switched:
            self.logger.error(f"탭 인덱스 {tab_index}로 전환하는 데 실패했습니다. 탭을 건너뜁니다.")
            return all_rows_data

        column_mapping = self._get_column_mapping(tab_index)
        last_page_key = f'{self.internal_name} 마지막 페이지'
        last_page = self.config.get(last_page_key)
        
        current_page = 1
        consecutive_empty_pages = 0
        max_pages = 10000  # 무한 루프 방지
        previous_first_row = None  # 무한 루프 방지: 이전 페이지의 첫 번째 행 데이터
        previous_page_row_count = None  # 이전 페이지의 행 개수
        same_data_count = 0  # 동일한 데이터가 반복된 횟수

        while current_page <= max_pages:
            if isinstance(last_page, int) and current_page > last_page:
                self.logger.info(f"설정된 마지막 페이지({last_page})에 도달하여 크롤링을 중단합니다.")
                break

            self.logger.info(f"📄 페이지 {current_page} 스크래핑을 시작합니다.")
            page_data = self._scrape_current_page_table(column_mapping)

            if page_data:
                # 무한 루프 방지: 첫 번째 행이 이전 페이지와 동일한지 확인
                if previous_first_row and len(page_data) > 0:
                    current_first_row = str(page_data[0])
                    if current_first_row == previous_first_row:
                        same_data_count += 1
                        self.logger.warning(f"⚠️  이전 페이지와 동일한 첫 번째 행 데이터가 발견되었습니다. (반복 {same_data_count}회)")
                        if same_data_count >= 2:
                            self.logger.critical(f"❌ 동일한 데이터가 {same_data_count}회 반복되었습니다. 무한 루프 방지를 위해 중단합니다.")
                            break
                    else:
                        same_data_count = 0  # 다른 데이터가 나오면 리셋
                
                # 행 개수 확인 (페이지네이션 컨테이너가 없을 때 마지막 페이지 판단용)
                current_row_count = len(page_data)
                if previous_page_row_count is not None and current_row_count == previous_page_row_count:
                    # 행 개수가 동일하고, 첫 번째 행도 동일하면 마지막 페이지일 가능성
                    if previous_first_row and len(page_data) > 0:
                        if str(page_data[0]) == previous_first_row:
                            self.logger.warning(f"⚠️  페이지 {current_page}: 행 개수와 첫 번째 행이 이전 페이지와 동일합니다. 마지막 페이지로 판단합니다.")
                            break
                
                all_rows_data.extend(page_data)
                self.logger.info(f"✅ 페이지 {current_page}에서 {len(page_data)}개 항목 수집")
                consecutive_empty_pages = 0
                # 다음 페이지 비교를 위해 첫 번째 행과 행 개수 저장
                if len(page_data) > 0:
                    previous_first_row = str(page_data[0])
                previous_page_row_count = current_row_count
            else:
                consecutive_empty_pages += 1
                self.logger.warning(f"⚠️  페이지 {current_page}에서 데이터를 찾지 못했습니다. (연속 {consecutive_empty_pages}회)")

            if consecutive_empty_pages >= MAX_CONSECUTIVE_EMPTY:
                self.logger.critical(f"❌ {MAX_CONSECUTIVE_EMPTY}회 연속으로 빈 페이지가 발견되어 크롤링을 중단합니다.")
                break

            # 다음 페이지로 이동 시도
            next_page_result = self._click_next_page()
            if next_page_result is False:
                self.logger.info(f"🏁 마지막 페이지에 도달했습니다. 총 {len(all_rows_data)}개 항목 수집 완료.")
                break
            elif next_page_result is None:
                # None 반환 시 에러 발생, 한 번 더 시도
                self.logger.warning("⚠️  페이지 이동 중 에러 발생. 다시 시도합니다.")
                time.sleep(2)
                if not self._click_next_page():
                    self.logger.info("🏁 재시도 후에도 다음 페이지로 이동할 수 없습니다. 크롤링을 종료합니다.")
                    break
            
            current_page += 1

        if current_page > max_pages:
            self.logger.error(f"❌ 최대 페이지 수({max_pages})에 도달했습니다. 무한 루프 방지를 위해 중단합니다.")

        self.logger.info(f"✅ 탭 {tab_index} 크롤링 완료: 총 {len(all_rows_data)}개 항목 수집")
        return all_rows_data

    def _switch_to_tab_by_index(self, tab_index: int) -> bool:
        """탭 전환 로직 - 강화된 버전 (테이블 변경 확인 추가)"""
        tab_selector = self.config['tab_selector']
        row_selector = self.config.get('row_selector')
        table_selector = self.config.get('table_selector')
        
        if not tab_selector:
            self.logger.error("'tab_selector'가 설정에 정의되지 않았습니다.")
            return False
        
        try:
            wait = WebDriverWait(self.driver, 15)
            
            # 1. 탭들이 나타날 때까지 기다린다.
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, tab_selector)))
            
            # 2. 현재 탭인지 확인하기 위해 *최신* 탭 목록을 가져온다.
            tabs_for_check = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)
            if tab_index >= len(tabs_for_check):
                self.logger.error(f"탭 인덱스 {tab_index}가 범위를 벗어났습니다. (총 {len(tabs_for_check)}개 탭)")
                return False
            
            # 3. 현재 테이블 내용 저장 (탭 전환 후 변경 확인용)
            previous_table_content = None
            if row_selector:
                try:
                    previous_rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                    if previous_rows:
                        # 첫 번째 행의 텍스트를 저장
                        previous_table_content = previous_rows[0].text.strip() if len(previous_rows) > 0 else None
                except Exception as e:
                    self.logger.debug(f"이전 테이블 내용 저장 실패: {e}")
            
            # 4. 서울아산병원은 li 태그에 active 클래스가 있음
            tab_element = tabs_for_check[tab_index]
            tab_class = tab_element.get_attribute("class") or ""
            
            # li 안에 a 태그가 있는지 확인하고, a 태그를 클릭해야 할 수도 있음
            clickable_element = tab_element
            try:
                # li 안에 a 태그가 있으면 a 태그를 클릭
                a_tag = tab_element.find_element(By.TAG_NAME, "a")
                clickable_element = a_tag
                self.logger.debug(f"탭 {tab_index}: li 안의 a 태그를 찾았습니다.")
            except NoSuchElementException:
                # a 태그가 없으면 li 자체를 클릭
                self.logger.debug(f"탭 {tab_index}: a 태그가 없어 li를 클릭합니다.")
                pass
            
            # active 클래스 확인 (li 태그 또는 부모 요소에서)
            is_active = "active" in tab_class
            if not is_active:
                # 부모 요소에서도 확인
                try:
                    parent = tab_element.find_element(By.XPATH, "./..")
                    parent_class = parent.get_attribute("class") or ""
                    is_active = "active" in parent_class
                except:
                    pass
            
            if is_active:
                self.logger.info(f"✅ 탭 {tab_index}이 이미 활성화되어 있습니다.")
                # 이미 활성화되어 있어도 테이블이 로드되었는지 확인
                if self._verify_table_loaded():
                    return True
                else:
                    self.logger.warning("⚠️  탭이 활성화되어 있지만 테이블이 로드되지 않았습니다. 재시도합니다.")
            
            # 5. 클릭을 시도한다.
            self.logger.info(f"🔀 탭 {tab_index}로 전환을 시도합니다.")
            
            # 클릭 직전에 요소를 다시 찾아서 Stale Element 문제를 회피
            try:
                tabs_refresh = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)
                if tab_index >= len(tabs_refresh):
                    self.logger.error(f"탭 인덱스 {tab_index}가 범위를 벗어났습니다.")
                    return False
                
                target_tab = tabs_refresh[tab_index]
                # 다시 a 태그 찾기 시도
                try:
                    clickable_target = target_tab.find_element(By.TAG_NAME, "a")
                except NoSuchElementException:
                    clickable_target = target_tab
                
                # 스크롤하여 요소가 보이도록 함
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", clickable_target)
                time.sleep(0.5)
                
                # 클릭 시도
                try:
                    clickable_target.click()
                    self.logger.debug("표준 클릭 성공")
                except Exception as click_err:
                    self.logger.debug(f"표준 클릭 실패 ({type(click_err).__name__}), JavaScript 클릭 시도")
                    self.driver.execute_script("arguments[0].click();", clickable_target)
                
                # 6. 탭 전환 확인 (여러 방법으로 확인)
                time.sleep(1)  # 초기 대기
                
                # 방법 1: active 클래스 확인 (최대 5초)
                try:
                    WebDriverWait(self.driver, 5).until(
                        lambda d: "active" in (d.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index].get_attribute("class") or "")
                    )
                    self.logger.debug("✅ active 클래스로 탭 전환 확인")
                except TimeoutException:
                    self.logger.debug("⚠️  active 클래스 확인 실패, 테이블 변경으로 확인 시도")
                    
                    # 방법 2: 테이블 내용이 변경되었는지 확인 (최대 5초)
                    if previous_table_content and row_selector:
                        try:
                            WebDriverWait(self.driver, 5).until(
                                lambda d: self._is_table_changed(d, row_selector, previous_table_content)
                            )
                            self.logger.debug("✅ 테이블 변경으로 탭 전환 확인")
                        except TimeoutException:
                            self.logger.debug("⚠️  테이블 변경 확인도 실패, 테이블 로드 확인으로 시도")
                    
                    # 방법 3: 테이블이 로드되었는지 확인
                    if not self._verify_table_loaded():
                        # 마지막 시도: 추가 대기 후 테이블 확인
                        time.sleep(2)
                        if not self._verify_table_loaded():
                            self.logger.warning("⚠️  탭 전환 후 테이블 로드 확인 실패했지만 계속 진행합니다.")
                            # 그래도 계속 진행 (페이지가 로드되었을 수 있음)
                
                # 방법 4: 최종적으로 테이블이 나타났는지 확인
                time.sleep(1)  # 추가 대기
                if table_selector:
                    try:
                        WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, table_selector))
                        )
                        self.logger.info(f"✅ 탭 {tab_index} 전환 성공 (테이블 요소 확인)")
                        return True
                    except TimeoutException:
                        pass
                
                # 테이블 선택자가 없거나 확인 실패한 경우, 행이 있는지 확인
                if row_selector:
                    try:
                        rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                        if len(rows) > 0:
                            self.logger.info(f"✅ 탭 {tab_index} 전환 성공 (행 개수: {len(rows)})")
                            return True
                    except:
                        pass
                
                # 페이지네이션이라도 있으면 성공으로 간주
                try:
                    pagination = self.driver.find_elements(By.CSS_SELECTOR, "div.pagingWrapSec, span.numPagingSec")
                    if len(pagination) > 0:
                        self.logger.info(f"✅ 탭 {tab_index} 전환 성공 (페이지네이션 확인)")
                        return True
                except:
                    pass
                
                # 모든 확인 실패했지만, 클릭은 성공했으므로 일단 성공으로 간주
                self.logger.warning(f"⚠️  탭 {tab_index} 전환 확인은 실패했지만 클릭은 성공했습니다. 계속 진행합니다.")
                return True
                
            except Exception as e:
                self.logger.error(f"❌ 탭 {tab_index} 전환 중 오류: {type(e).__name__}: {e}")
                return False
        
        except Exception as e:
            self.logger.error(f"❌ 탭 전환 중 치명적 오류 발생: {e}", exc_info=True)
            return False
    
    def _is_table_changed(self, driver, row_selector: str, previous_content: str) -> bool:
        """테이블 내용이 변경되었는지 확인"""
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, row_selector)
            if rows and len(rows) > 0:
                current_content = rows[0].text.strip()
                return current_content != previous_content
        except:
            pass
        return False
    
    def _verify_table_loaded(self) -> bool:
        """탭 전환 후 테이블이 실제로 로드되었는지 확인"""
        row_selector = self.config.get('row_selector')
        table_selector = self.config.get('table_selector')
        
        try:
            # 테이블이나 행이 나타날 때까지 대기 (최대 5초)
            wait = WebDriverWait(self.driver, 5)
            
            # 테이블 선택자가 있으면 먼저 테이블 확인
            if table_selector:
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, table_selector)))
                    self.logger.debug("✅ 테이블 요소 확인됨")
                except TimeoutException:
                    self.logger.debug("⚠️  테이블 요소를 찾을 수 없습니다. 행이나 페이지네이션으로 확인합니다.")
            
            # 행이 나타나는지 확인 (최소 1개 이상의 행이 있어야 함, 또는 페이지네이션이 있어야 함)
            try:
                # 행이 있거나 페이지네이션이 있으면 테이블이 로드된 것으로 간주
                rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector) if row_selector else []
                pagination = self.driver.find_elements(By.CSS_SELECTOR, "div.pagingWrapSec, span.numPagingSec")
                
                if len(rows) > 0:
                    self.logger.debug(f"✅ 테이블 로드 확인: {len(rows)}개 행")
                    return True
                elif len(pagination) > 0:
                    self.logger.debug(f"✅ 테이블 로드 확인: 페이지네이션 요소 {len(pagination)}개")
                    return True
                else:
                    # 행도 페이지네이션도 없으면, 테이블 요소라도 있으면 성공으로 간주
                    if table_selector:
                        try:
                            table_elem = self.driver.find_element(By.CSS_SELECTOR, table_selector)
                            if table_elem:
                                self.logger.debug("✅ 테이블 요소만 확인됨 (행이나 페이지네이션 없음)")
                                return True
                        except:
                            pass
                    self.logger.debug("⚠️  테이블에 행이 없고 페이지네이션도 없습니다.")
                    return False
            except Exception as e:
                self.logger.debug(f"⚠️  테이블 확인 중 오류: {e}")
                return False
        except Exception as e:
            self.logger.debug(f"⚠️  테이블 로드 확인 중 오류: {e}")
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

    def _click_next_page(self) -> Optional[bool]:
        """
        강화된 페이지네이션 로직: nextPageBtn의 onclick 속성을 확인하여 마지막 페이지를 정확히 감지.
        - nextPageBtn의 onclick="fnList(현재페이지); return false;" 형태면 마지막 페이지
        - 페이지 번호를 우선적으로 찾고, 없으면 nextPageBtn 사용
        - 페이지 변경을 확실하게 검증
        """
        
        page_number_selector = self.config.get('page_number_selector')
        next_block_selector = self.config.get('next_button_selector')
        row_selector = self.config.get('row_selector')
        
        # Helper: 현재 활성 페이지 번호를 찾습니다.
        # 아산병원 구조: <span class="numPagingSec"><a class="nowPage"><span>67</span></a></span>
        def get_active_page_number() -> Optional[int]:
            try:
                if not page_number_selector:
                    return None
                page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
                for element in page_elements:
                    # 아산병원: 활성 페이지는 a 태그에 class="nowPage"
                    el_class = element.get_attribute('class') or ''
                    if 'nowPage' in el_class:
                        # 페이지 번호는 내부 span 태그에 있음
                        try:
                            span_tag = element.find_element(By.TAG_NAME, 'span')
                            text = span_tag.text.strip()
                            if text and text.isdigit():
                                return int(text)
                        except NoSuchElementException:
                            # span이 없으면 직접 텍스트 사용
                            text = element.text.strip()
                            if text and text.isdigit():
                                return int(text)
            except Exception as e:
                self.logger.debug(f"활성 페이지 번호 찾기 실패: {e}")
            return None
        
        # Helper: nextPageBtn의 onclick 속성에서 페이지 번호 추출
        def get_next_button_page() -> Optional[int]:
            """nextPageBtn의 onclick 속성에서 페이지 번호를 추출합니다.
            예: onclick="fnList(67); return false;" -> 67 반환
            """
            try:
                if not next_block_selector:
                    return None
                next_button = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                onclick = next_button.get_attribute('onclick') or ''
                # fnList(숫자) 패턴 찾기
                match = re.search(r'fnList\((\d+)\)', onclick)
                if match:
                    return int(match.group(1))
            except Exception as e:
                self.logger.debug(f"nextPageBtn 페이지 번호 추출 실패: {e}")
            return None
        
        try:
            # 1. 페이지네이션 컨테이너가 나타날 때까지 대기 (찾지 못해도 계속 진행)
            pagination_container_found = False
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.pagingWrapSec, span.numPagingSec"))
                )
                pagination_container_found = True
                time.sleep(0.5)  # 안정화 대기
                self.logger.debug("✅ 페이지네이션 컨테이너 발견")
            except TimeoutException:
                self.logger.warning("⚠️  페이지네이션 컨테이너를 찾을 수 없습니다. nextPageBtn으로 직접 이동을 시도합니다.")
                # 페이지네이션 컨테이너가 없어도 nextPageBtn이 있으면 계속 진행
                # 하지만 마지막 페이지인지 정확히 확인해야 함
                if next_block_selector:
                    try:
                        # nextPageBtn이 있는지 확인
                        next_button = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                        
                        # nextPageBtn이 비활성화되어 있으면 마지막 페이지
                        if not next_button.is_displayed() or not next_button.is_enabled():
                            self.logger.info("🏁 nextPageBtn이 비활성화되어 있습니다. 마지막 페이지로 판단합니다.")
                            return False
                        
                        # nextPageBtn의 onclick 확인하여 마지막 페이지인지 판단
                        next_button_page = get_next_button_page()
                        
                        # 현재 페이지 번호를 추정 시도 (URL이나 다른 방법으로)
                        # 일단 현재 페이지를 알 수 없으므로, nextPageBtn의 onclick을 기준으로 판단
                        # 하지만 정확한 판단은 클릭 후 데이터 변경으로 확인
                        
                        self.logger.info(f"✅ nextPageBtn을 찾았습니다. onclick={next_button_page}, 페이지네이션 컨테이너 없이도 진행합니다.")
                        
                        # nextPageBtn 클릭은 나중에 처리 (일반 로직으로 처리)
                        # 여기서는 False를 반환하지 않고 계속 진행하도록 함
                        # (아래 로직에서 nextPageBtn을 사용하도록 설정)
                        
                    except NoSuchElementException:
                        self.logger.info("🏁 nextPageBtn도 찾을 수 없습니다. 마지막 페이지로 판단합니다.")
                        return False
                    except Exception as e:
                        self.logger.warning(f"nextPageBtn 확인 중 오류: {e}")
                        # 오류가 발생해도 계속 진행 시도
                else:
                    self.logger.info("🏁 next_block_selector가 설정되지 않았습니다. 마지막 페이지로 판단합니다.")
                    return False
            
            # 2. 현재 페이지 번호 확인
            current_page = get_active_page_number()
            
            # 현재 페이지를 찾지 못한 경우 (첫 페이지일 수 있음), 페이지 번호 요소에서 1번 페이지 찾기
            if current_page is None and page_number_selector:
                try:
                    page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
                    for element in page_elements:
                        try:
                            element_text = None
                            try:
                                span_tag = element.find_element(By.TAG_NAME, 'span')
                                element_text = span_tag.text.strip()
                            except NoSuchElementException:
                                element_text = element.text.strip()
                            
                            if element_text == '1' or (element_text.isdigit() and int(element_text) == 1):
                                el_class = element.get_attribute('class') or ''
                                if 'nowPage' in el_class:
                                    current_page = 1
                                    self.logger.info(f"📄 현재 페이지: {current_page} (첫 페이지로 감지)")
                                    break
                        except Exception:
                            continue
                except Exception as e:
                    self.logger.debug(f"첫 페이지 확인 중 오류: {e}")
            
            # 여전히 현재 페이지를 찾지 못한 경우
            if current_page is None:
                # 페이지네이션 컨테이너가 없었고, nextPageBtn만 있는 경우
                if not pagination_container_found and next_block_selector:
                    # nextPageBtn의 onclick에서 현재 페이지 추정 시도
                    try:
                        next_button_page = get_next_button_page()
                        if next_button_page is not None:
                            # nextPageBtn의 onclick이 일반적으로 다음 페이지 번호이므로,
                            # 현재 페이지는 그보다 1 작은 값으로 추정
                            # 하지만 정확하지 않을 수 있으므로, nextPageBtn만 사용
                            self.logger.warning(f"⚠️  현재 페이지 번호를 찾을 수 없지만, nextPageBtn onclick={next_button_page}을 확인했습니다.")
                            # nextPageBtn을 직접 사용하도록 element_to_click에 설정
                            # (아래 로직에서 처리)
                    except:
                        pass
                
                # 그래도 찾지 못했으면 경고만 하고 계속 진행 (nextPageBtn으로 처리)
                if current_page is None:
                    self.logger.warning("⚠️  현재 페이지 번호를 찾을 수 없습니다. nextPageBtn만 사용합니다.")
            
            if current_page is not None:
                self.logger.info(f"📄 현재 페이지: {current_page}")
            else:
                self.logger.info(f"📄 현재 페이지: 알 수 없음 (nextPageBtn 사용)")
            
            # 3. nextPageBtn의 onclick 속성 확인하여 마지막 페이지인지 판단
            element_to_click = None
            if next_block_selector:
                try:
                    next_button_page = get_next_button_page()
                    if next_button_page is not None:
                        if current_page is not None:
                            # nextPageBtn의 onclick이 현재 페이지와 같으면 마지막 페이지
                            if next_button_page == current_page:
                                self.logger.info(f"🏁 마지막 페이지 감지: nextPageBtn onclick={next_button_page}, 현재 페이지={current_page}")
                                return False
                            self.logger.debug(f"nextPageBtn onclick={next_button_page}, 현재 페이지={current_page} (다음 페이지 가능)")
                        else:
                            # 현재 페이지를 찾지 못했지만 nextPageBtn은 있음
                            # nextPageBtn의 onclick이 의미가 있는지 확인
                            self.logger.debug(f"nextPageBtn onclick={next_button_page} (현재 페이지 알 수 없음)")
                except Exception as e:
                    self.logger.debug(f"nextPageBtn 확인 중 오류 (무시): {e}")
            
            # 4. 페이지 번호 요소에서 다음 페이지 찾기 (페이지네이션 컨테이너가 있는 경우만)
            if pagination_container_found and page_number_selector and current_page is not None:
                try:
                    page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
                    if page_elements:  # 페이지 번호 요소가 있는 경우만
                        next_page_num = current_page + 1
                        
                        # 다음 페이지 번호를 가진 요소 찾기
                        for element in page_elements:
                            try:
                                # 페이지 번호는 내부 span 태그에 있음
                                element_text = None
                                try:
                                    span_tag = element.find_element(By.TAG_NAME, 'span')
                                    element_text = span_tag.text.strip()
                                except NoSuchElementException:
                                    element_text = element.text.strip()
                                
                                if element_text and element_text.isdigit() and int(element_text) == next_page_num:
                                    # nowPage 클래스가 없고, a 태그이고, 클릭 가능한지 확인
                                    el_class = element.get_attribute('class') or ''
                                    if 'nowPage' not in el_class and element.tag_name == 'a':
                                        if element.is_enabled() and element.is_displayed():
                                            element_to_click = element
                                            self.logger.info(f"✅ 다음 페이지 번호 '{next_page_num}' 발견")
                                            break
                            except Exception as e:
                                self.logger.debug(f"요소 확인 중 오류: {e}")
                                continue
                except Exception as e:
                    self.logger.debug(f"페이지 번호 요소 찾기 실패: {e}")
            
            # 5. 다음 페이지 번호를 찾지 못했거나 페이지네이션 컨테이너가 없으면 nextPageBtn 사용
            if not element_to_click and next_block_selector:
                try:
                    next_button = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                    if next_button.is_displayed() and next_button.is_enabled():
                        # 다시 한 번 onclick 확인 (최신 상태)
                        next_button_page = get_next_button_page()
                        if next_button_page is not None:
                            if current_page is not None:
                                if next_button_page == current_page:
                                    self.logger.info(f"🏁 nextPageBtn onclick이 현재 페이지와 동일: 마지막 페이지")
                                    return False
                            else:
                                # 현재 페이지를 찾지 못했지만, nextPageBtn이 있으면 사용
                                # (139페이지 같은 경우)
                                self.logger.info(f"✅ nextPageBtn 사용 (현재 페이지 알 수 없음, onclick={next_button_page})")
                        element_to_click = next_button
                        if pagination_container_found:
                            self.logger.info(f"✅ nextPageBtn 사용 (다음 블록으로 이동)")
                        else:
                            self.logger.info(f"✅ nextPageBtn 사용 (페이지네이션 컨테이너 없음)")
                except NoSuchElementException:
                    self.logger.info("🏁 nextPageBtn을 찾을 수 없습니다. 마지막 페이지입니다.")
                    return False
                except Exception as e:
                    self.logger.warning(f"nextPageBtn 확인 중 오류: {e}")
            
            # 6. 클릭할 요소를 찾지 못한 경우
            if not element_to_click:
                self.logger.info(f"🏁 다음 페이지로 이동할 수 없습니다. 마지막 페이지로 판단합니다.")
                return False
            
            # 7. 요소 클릭
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element_to_click)
                time.sleep(0.3)
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(element_to_click))
                element_to_click.click()
                self.logger.debug("페이지 요소 클릭 완료")
            except Exception as click_e:
                self.logger.warning(f"표준 클릭 실패: {type(click_e).__name__}. JS 클릭으로 재시도합니다.")
                try:
                    self.driver.execute_script("arguments[0].click();", element_to_click)
                except Exception as js_e:
                    self.logger.error(f"JS 클릭도 실패: {type(js_e).__name__}")
                    return None  # 에러 발생
            
            # 8. 페이지 변경 확인 (최대 5초 대기)
            time.sleep(1.5)  # 페이지 로딩 대기 (139페이지 같은 경우를 위해 더 길게)
            
            # 페이지네이션 컨테이너가 없었던 경우, row count나 테이블 변경으로만 확인
            if not pagination_container_found:
                self.logger.debug("페이지네이션 컨테이너가 없었으므로 row count와 데이터 변경으로 확인합니다.")
                time.sleep(2)  # 페이지 로딩 대기
                try:
                    if row_selector:
                        rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                        row_count = len(rows)
                        if row_count > 0:
                            self.logger.info(f"✅ 페이지 이동 성공 (행 개수: {row_count}개, 페이지네이션 컨테이너 없음)")
                            # 주의: 실제 페이지 변경 여부는 crawl_tab_by_index에서 데이터 중복 확인으로 검증됨
                            return True
                        else:
                            # 행이 없으면 마지막 페이지일 가능성
                            self.logger.warning("⚠️  페이지 이동 후 행이 없습니다. 마지막 페이지일 수 있습니다.")
                            # 하지만 일단 True 반환 (crawl_tab_by_index에서 빈 페이지 처리)
                            return True
                except Exception as e:
                    self.logger.debug(f"row count 확인 중 오류: {e}")
                
                # row count 확인 실패해도 클릭은 성공했으므로 일단 성공으로 간주
                # 실제 페이지 변경 여부는 crawl_tab_by_index에서 데이터 중복 확인으로 검증됨
                self.logger.info("✅ 페이지 이동 시도 완료 (페이지네이션 컨테이너 없음, 데이터 변경은 상위 로직에서 확인)")
                return True
            
            # 페이지네이션 컨테이너가 있는 경우, 정상적인 확인 진행
            for attempt in range(5):
                try:
                    new_page = get_active_page_number()
                    if new_page is not None:
                        if current_page is not None:
                            if new_page != current_page:
                                self.logger.info(f"✅ 페이지 이동 성공: {current_page} -> {new_page}")
                                return True
                            elif attempt < 4:
                                # 아직 페이지가 변경되지 않았으면 대기
                                time.sleep(1)
                                continue
                        else:
                            # 현재 페이지를 찾지 못했지만, 새 페이지 번호를 찾았으면 성공
                            self.logger.info(f"✅ 페이지 이동 성공: 알 수 없음 -> {new_page}")
                            return True
                    elif attempt < 4:
                        # 페이지 번호를 찾지 못했으면 대기
                        time.sleep(1)
                        continue
                except Exception as e:
                    self.logger.debug(f"페이지 확인 중 오류 (시도 {attempt + 1}/5): {e}")
                    if attempt < 4:
                        time.sleep(1)
                        continue
                
                # 마지막 시도
                if attempt == 4:
                    # 페이지 번호가 변경되지 않았지만, row count로 확인
                    try:
                        if row_selector:
                            initial_rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                            # row가 있으면 페이지 로드된 것으로 간주
                            if len(initial_rows) > 0:
                                self.logger.info(f"✅ 페이지 이동 성공 (행 개수 확인: {len(initial_rows)}개)")
                                return True
                    except:
                        pass
                    
                    # 그래도 확인되지 않으면 경고하고 계속 진행 (페이지가 실제로 변경되었을 수 있음)
                    if current_page is not None:
                        self.logger.warning(f"⚠️  페이지 변경 확인 실패 (현재 페이지: {current_page}), 하지만 계속 진행합니다.")
                    else:
                        self.logger.warning(f"⚠️  페이지 변경 확인 실패, 하지만 계속 진행합니다.")
                    return True  # 일단 성공으로 간주하고 계속 진행
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 페이지네이션 중 치명적 오류 발생: {e}", exc_info=True)
            return None  # 에러 발생 시 None 반환

    def _get_column_mapping(self, tab_index: int) -> Dict[int, str]:
        """
        서울아산병원 테이블의 탭별 컬럼 매핑을 반환합니다.
        
        Args:
            tab_index: 탭 인덱스 (0: 행위, 1: 치료재료, 2: 약제, 3: 제증명수수료)
        """
        if tab_index == 0:  # 행위
            return {
                0: "중분류", 1: "소분류", 2: "코드", 3: "명칭", 4: "구분", 5: "비용",
                6: "최저비용", 7: "최고비용", 8: "치료재료대 포함", 9: "약제비 포함", 10: "특이사항", 11: "최종 변경일"
            }
        elif tab_index == 1:  # 치료재료
            return {
                0: "중분류", 1: "코드", 2: "명칭", 3: "구분", 4: "비용",
                5: "최저비용", 6: "최고비용", 7: "특이사항", 8: "최종 변경일"
            }
        elif tab_index == 2:  # 약제
            return {
                0: "코드", 1: "명칭", 2: "비용", 5: "특이사항", 6: "최종 변경일"
            }
        elif tab_index == 3:  # 제증명수수료
            return {
                0: "코드", 1: "명칭", 2: "구분", 3: "비용", 4: "특이사항", 5: "최종 변경일"
            }
        else:
            self.logger.warning(f"알 수 없는 탭 인덱스: {tab_index}. 기본 매핑 사용.")
            return {0: "구분", 1: "분류", 2: "코드", 3: "명칭", 4: "상세설명", 5: "금액"}

