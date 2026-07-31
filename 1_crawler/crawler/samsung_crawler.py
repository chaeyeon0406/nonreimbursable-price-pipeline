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

class SamsungCrawler(BaseCrawler):
    """
    삼성서울병원 웹사이트의 비급여 항목 데이터 수집을 위한 크롤러.
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

        # 행위 탭은 중분류가 연속 페이지에 걸쳐 이어질 수 있으므로
        # 페이지마다 카테고리를 추적하기 위한 상태를 초기화합니다.
        if tab_index == 0:
            self._samsung_current_category = None

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
            
            # 삼성병원은 부모 li 태그에 on 클래스가 있음
            parent_li = tabs_for_check[tab_index].find_element(By.XPATH, "./..")
            if "on" in (parent_li.get_attribute("class") or ""):
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
                    lambda d: "on" in (d.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index].find_element(By.XPATH, "./..").get_attribute("class") or "")
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
        """현재 페이지의 테이블 데이터를 추출합니다. (중분류 및 특이사항 처리 포함)"""
        page_rows_data = []
        row_selector = self.config['row_selector']
        current_category = getattr(self, '_samsung_current_category', None)
        
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, row_selector))
            )
        except TimeoutException:
            self.logger.warning("데이터 행을 찾지 못했습니다. 빈 페이지일 수 있습니다.")
            return page_rows_data

        num_rows = len(self.driver.find_elements(By.CSS_SELECTOR, row_selector))
        for i in range(num_rows):
            try:
                row = self.driver.find_elements(By.CSS_SELECTOR, row_selector)[i]
                
                # 1. 중분류 확인: th 태그에 colspan과 class="sub-title"이 있는 경우
                th_elements = row.find_elements(By.TAG_NAME, "th")
                if th_elements:
                    for th in th_elements:
                        th_class = th.get_attribute("class") or ""
                        th_colspan = th.get_attribute("colspan")
                        
                        # 중분류 헤더 확인 (colspan과 sub-title 클래스)
                        if "sub-title" in th_class and th_colspan:
                            category_text = th.text.strip()
                            if category_text:
                                current_category = category_text
                                self.logger.debug(f"중분류 발견: {current_category}")
                                # 중분류 행은 데이터 행이 아니므로 건너뜀
                                continue
                
                # 2. 특이사항 확인: td 태그에 colspan과 class="line"이 있는 경우
                td_elements = row.find_elements(By.TAG_NAME, "td")
                if td_elements:
                    # 특이사항 행인지 확인
                    is_special_note_row = False
                    special_note_text = None
                    
                    # 행이 특이사항 행인지 확인하는 방법:
                    # 1. td에 class="line"이 있고 colspan이 있는 경우
                    # 2. 특이사항 이미지가 있는 경우
                    # 3. 또는 td가 하나만 있고 일반 데이터 행으로 보이지 않는 경우
                    for td in td_elements:
                        td_class = td.get_attribute("class") or ""
                        td_colspan = td.get_attribute("colspan")
                        
                        # 특이사항 행 확인 (colspan과 line 클래스)
                        if "line" in td_class and td_colspan:
                            # 특이사항 이미지 확인
                            has_special_note_img = False
                            try:
                                img = td.find_element(By.TAG_NAME, "img")
                                img_alt = img.get_attribute("alt") or ""
                                img_src = img.get_attribute("src") or ""
                                # 특이사항 이미지 확인 (alt에 "특이사항"이 있거나 src에 특이사항 관련 키워드가 있는 경우)
                                if "특이사항" in img_alt or "e_unInsura19" in img_src or "특이사항" in img_src:
                                    has_special_note_img = True
                            except NoSuchElementException:
                                pass
                            
                            # 특이사항 텍스트 추출
                            special_note_text = td.text.strip()
                            # &nbsp; 제거 및 정리
                            special_note_text = special_note_text.replace('\u00a0', ' ').strip()
                            
                            # 특이사항 행 판단:
                            # 1. 특이사항 이미지가 있거나
                            # 2. td가 하나만 있고 텍스트가 있는 경우 (일반 데이터 행이 아닌 경우)
                            if has_special_note_img:
                                is_special_note_row = True
                                break
                            elif len(td_elements) == 1 and special_note_text:
                                # td가 하나만 있고, 일반 데이터 행으로 보이지 않는 경우
                                # (코드, 명칭, 비용 등의 패턴이 아닌 경우)
                                # 간단한 휴리스틱: 숫자만 있거나, 매우 짧은 텍스트는 데이터 행일 수 있음
                                # 하지만 긴 텍스트나 특수문자가 많으면 특이사항일 가능성이 높음
                                if len(special_note_text) > 10 or "," in special_note_text or "(" in special_note_text:
                                    is_special_note_row = True
                                    break
                    
                    # 특이사항 행인 경우, 이전 행의 특이사항 필드에 추가
                    if is_special_note_row and special_note_text:
                        if page_rows_data:
                            # 이전 행에 특이사항 필드가 없으면 추가
                            if "특이사항" not in page_rows_data[-1]:
                                page_rows_data[-1]["특이사항"] = ""
                            
                            # 기존 특이사항이 있으면 줄바꿈으로 추가
                            if page_rows_data[-1]["특이사항"]:
                                page_rows_data[-1]["특이사항"] += "\n" + special_note_text
                            else:
                                page_rows_data[-1]["특이사항"] = special_note_text
                            
                            self.logger.debug(f"특이사항 추가: {special_note_text[:50]}...")
                        continue  # 특이사항 행은 데이터 행이 아니므로 건너뜀
                
                # 3. 일반 데이터 행 처리
                cells = row.find_elements(By.TAG_NAME, "td")
                if not cells:
                    continue  # td가 없으면 건너뜀
                
                # 데이터 행인지 확인 (중분류만 있는 행이 아닌지 확인)
                # 실제 데이터가 있는지 확인 (코드, 명칭, 비용 등)
                has_data = False
                for cell in cells:
                    cell_text = cell.text.strip()
                    if cell_text:
                        has_data = True
                        break
                
                if not has_data:
                    continue  # 데이터가 없으면 건너뜀
                
                row_data = {}
                
                # 컬럼 매핑에 따라 데이터 추출
                for idx, key in column_mapping.items():
                    if idx < len(cells):
                        cell_text = cells[idx].text.strip()
                        # 빈 문자열이 아닌 경우만 추가
                        if cell_text:
                            row_data[key] = cell_text
                
                # 중분류 결정 (현재 행에서 새로 발견된 카테고리가 없을 때 이전 카테고리 사용)
                category_to_apply = current_category or getattr(self, '_samsung_current_category', None)
                if category_to_apply:
                    row_data["중분류"] = category_to_apply
                else:
                    row_data["중분류"] = ""
                
                # 행 데이터 유효성 검사
                # 중분류만 있는 행은 제외 (실제 데이터 필드가 있어야 함)
                if row_data:
                    # 중분류 필드를 제외한 다른 필드가 있는지 확인
                    other_fields = {k: v for k, v in row_data.items() if k != "중분류"}
                    if other_fields:  # 중분류 외 다른 필드가 있으면 추가
                        # 특이사항 필드가 없으면 빈 문자열로 초기화 (나중에 추가될 수 있음)
                        if "특이사항" not in row_data:
                            row_data["특이사항"] = ""
                        page_rows_data.append(row_data)
                    # 중분류만 있는 경우는 제외 (중분류 헤더 행이거나 빈 행)
                    
            except StaleElementReferenceException:
                self.logger.warning(f"{i}번째 행 처리 중 StaleElementReferenceException 발생. 해당 행을 건너뜁니다.")
                continue
            except Exception as e:
                self.logger.warning(f"{i}번째 행 처리 중 오류 발생: {e}. 해당 행을 건너뜁니다.")
                continue
        
        if getattr(self, '_samsung_current_category', None) != current_category:
            self._samsung_current_category = current_category
        
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
                page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
                for el in page_elements:
                    # 삼성서울병원은 strong 태그로 활성 페이지 표시
                    if el.tag_name == 'strong':
                        return el.text.strip()
            except (NoSuchElementException, StaleElementReferenceException):
                return None
            return None

        initial_active_text = get_active_page_text()
        self.logger.info(f"현재 활성 페이지: '{initial_active_text}'")

        element_to_click = None
        
        # Case 1: 다음 숫자 페이지 버튼 찾기 (활성 페이지 + 1)
        if initial_active_text and initial_active_text.isdigit():
            try:
                page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_number_selector)
                # 숫자로 변환 가능한 요소들 중에서 활성 페이지 다음 숫자 찾기
                current_page_num = int(initial_active_text)
                next_page_num = current_page_num + 1
                
                for el in page_elements:
                    # a 태그이면서 숫자인 요소 찾기
                    if el.tag_name == 'a':
                        try:
                            page_num = int(el.text.strip())
                            if page_num == next_page_num:
                                element_to_click = el
                                self.logger.info(f"다음 숫자 페이지 버튼 발견: {next_page_num}")
                                break
                        except ValueError:
                            continue
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

        # 클릭 실행 (JS Fallback 포함)
        try:
            self.driver.execute_script("arguments[0].scrollIntoView(true);", element_to_click)
            WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(element_to_click))
            element_to_click.click()
        except (ElementClickInterceptedException, StaleElementReferenceException):
            self.logger.warning("표준 페이지네이션 클릭 실패. JS 클릭으로 재시도합니다.")
            try:
                self.driver.execute_script("arguments[0].click();", element_to_click)
            except Exception as e:
                self.logger.error(f"JS 페이지네이션 클릭 실패: {e}")
                return False

        # 핵심 검증: 페이지 번호가 실제로 변경되었는지 확인
        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: get_active_page_text() != initial_active_text
            )
            new_active_text = get_active_page_text()
            self.logger.info(f"페이지 이동 성공. 새 활성 페이지: '{new_active_text}'")
            return True
        except TimeoutException:
            self.logger.critical("CRITICAL: 다음 페이지 버튼을 클릭했으나 페이지 번호가 변경되지 않았습니다. 무한 루프 방지를 위해 중단합니다.")
            return False

    def _get_column_mapping(self, tab_index: int) -> Dict[int, str]:
        """
        삼성서울병원 테이블의 탭별 컬럼 매핑을 반환합니다.
        
        Args:
            tab_index: 탭 인덱스 (0: 행위, 1: 치료재료, 2: 약제, 3: 제증명수수료)
        
        Note:
            행위 탭(tab_index=0)의 경우, 중분류는 th.sub-title에서 추출하고,
            특이사항은 td.line에서 추출하여 이전 행에 추가합니다.
        """
        if tab_index == 0:  # 행위
            # 중분류는 th.sub-title에서 추출하므로 매핑에 포함하지 않음
            # 특이사항은 td.line에서 추출하여 별도 처리
            return {
                0: "소분류", 1: "명칭", 2: "코드", 3: "구분", 4: "비용",
                5: "최저비용", 6: "최고비용", 7: "치료재료대 포함", 8: "약제비 포함", 9: "최종 변경일"
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
            return {0: "구분", 1: "코드", 2: "명칭", 3: "가격"}

