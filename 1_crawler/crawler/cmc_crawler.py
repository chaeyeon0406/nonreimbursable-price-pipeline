import time
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    ElementClickInterceptedException,
    NoSuchElementException
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.common.action_chains import ActionChains

import sys
from pathlib import Path
# 상위 디렉토리를 path에 추가
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))
from base_crawler import BaseCrawler

MAX_CONSECUTIVE_EMPTY = 3

class SeoulStMarysCrawler(BaseCrawler):
    """
    서울성모병원(CMC) 웹사이트의 비급여 항목 데이터 수집을 위한 크롤러.
    '행위료' 탭에만 하위 카테고리가 있으며, 드롭다운 또는 탭 형태로 제공됩니다.
    """

    def crawl_tab_by_index(self, tab_index: int) -> List[Dict[str, Any]]:
        """
        지정된 탭의 모든 페이지를 순회하며 데이터를 수집하는 메인 실행 메서드.
        '행위료' 탭인 경우 하위 카테고리를 처리합니다.
        """
        # 탭 이름 가져오기
        tab_name = self._get_tab_name_by_index(tab_index)
        if not tab_name:
            self.logger.error(f"탭 인덱스 {tab_index}에 해당하는 탭 이름을 찾을 수 없습니다.")
            return []
        
        # '행위료' 또는 '행위' 탭인지 확인
        is_acts_tab = '행위' in tab_name
        
        self.logger.info(f"[{self.internal_name}] 탭 인덱스 {tab_index} ('{tab_name}') 크롤링 시작")
        
        # 탭 전환 시도 (최대 3번 재시도)
        tab_switched = False
        for retry in range(3):
            try:
                if self._switch_to_tab_by_index(tab_index):
                    # 탭 전환 후 테이블이 실제로 로드되었는지 확인
                    table_selector = self.config.get('table_selector')
                    row_selector = self.config.get('row_selector')
                    if self._verify_table_loaded(table_selector, row_selector):
                        tab_switched = True
                        break
                    else:
                        self.logger.warning(f"⚠️  [{self.internal_name}] 탭 전환 후 테이블 로드 확인 실패 (재시도 {retry + 1}/3)")
                        time.sleep(2)
                else:
                    self.logger.warning(f"⚠️  [{self.internal_name}] 탭 인덱스 {tab_index}로 전환 실패 (재시도 {retry + 1}/3)")
                    time.sleep(2)
            except Exception as e:
                self.logger.warning(f"⚠️  [{self.internal_name}] 탭 전환 중 오류 (재시도 {retry + 1}/3): {e}")
                time.sleep(2)
        
        if not tab_switched:
            self.logger.error(f"❌ [{self.internal_name}] 탭 인덱스 {tab_index}로 전환하는 데 실패했습니다. 탭을 건너뜁니다.")
            return []
        
        try:
            if is_acts_tab:
                return self._crawl_acts_sub_categories()
            else:
                # 다른 탭은 일반 페이지네이션으로 처리
                return self._paginate_and_scrape_all_pages(tab_name)

        except Exception as e:
            self.logger.error(f"❌ [{self.internal_name}] 탭 인덱스 {tab_index} ('{tab_name}') 크롤링 중 치명적 오류 발생: {e}", exc_info=True)
            return []

    def _get_tab_name_by_index(self, tab_index: int) -> Optional[str]:
        """탭 인덱스로부터 탭 이름을 가져옵니다."""
        try:
            tab_selector = self.config.get('tab_selector')
            if not tab_selector:
                return None
            
            tabs = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)
            if tab_index >= len(tabs):
                return None
            
            tab_element = tabs[tab_index]
            tab_name = tab_element.text.strip()
            if not tab_name:
                tab_name = tab_element.get_attribute('title') or tab_element.get_attribute('alt') or f'탭_{tab_index + 1}'
            return tab_name
        except Exception as e:
            self.logger.error(f"탭 이름 가져오기 실패: {e}")
            return None

    def _crawl_acts_sub_categories(self) -> List[Dict[str, Any]]:
        """'행위료' 탭의 하위 카테고리를 감지하고 크롤링합니다."""
        # 하위 카테고리 선택자 확인 (dropdown_selector는 행위 탭의 하위 그룹 메뉴 선택자)
        dropdown_selector = self.config.get('dropdown_selector')
        
        if not dropdown_selector:
            self.logger.info(f"[{self.internal_name}] '행위료' 하위 카테고리 선택자가 없습니다. 일반 페이지네이션으로 처리합니다.")
            return self._paginate_and_scrape_all_pages('행위료')

        # 드롭다운 또는 탭 컨테이너 확인 (dropdown_selector로 찾은 요소의 태그로 구분)
        # 드롭다운을 찾기 위해 여러 방법 시도
        element = None
        wait = WebDriverWait(self.driver, 15)
        
        # 방법 1: 직접 드롭다운 찾기 시도
        try:
            element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, dropdown_selector)))
            self.logger.info(f"✅ [{self.internal_name}] 드롭다운 요소 발견 (방법 1: 직접 찾기)")
        except TimeoutException:
            # 방법 2: 호버 후 드롭다운 찾기
            try:
                self.logger.info(f"🔄 [{self.internal_name}] 드롭다운을 찾기 위해 호버 시도")
                tab_selector = self.config.get('tab_selector')
                if tab_selector:
                    main_tab_element = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)[0]
                    ActionChains(self.driver).move_to_element(main_tab_element).perform()
                    time.sleep(1)  # 호버 후 대기 시간 증가
                    
                    # 호버 후 드롭다운 찾기 재시도
                    element = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, dropdown_selector))
                    )
                    self.logger.info(f"✅ [{self.internal_name}] 드롭다운 요소 발견 (방법 2: 호버 후 찾기)")
            except TimeoutException:
                # 방법 3: 페이지 로드 후 다시 시도
                try:
                    self.logger.info(f"🔄 [{self.internal_name}] 페이지 완전 로드 대기 후 드롭다운 찾기 재시도")
                    time.sleep(3)  # 페이지 완전 로드 대기
                    element = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, dropdown_selector))
                    )
                    self.logger.info(f"✅ [{self.internal_name}] 드롭다운 요소 발견 (방법 3: 대기 후 찾기)")
                except TimeoutException:
                    # 방법 4: JavaScript로 요소 확인
                    try:
                        self.logger.info(f"🔄 [{self.internal_name}] JavaScript로 드롭다운 요소 확인")
                        element_exists = self.driver.execute_script(
                            f"return document.querySelector('{dropdown_selector}') !== null;"
                        )
                        if element_exists:
                            element = self.driver.find_element(By.CSS_SELECTOR, dropdown_selector)
                            self.logger.info(f"✅ [{self.internal_name}] 드롭다운 요소 발견 (방법 4: JavaScript 확인)")
                        else:
                            raise TimeoutException("드롭다운 요소를 찾을 수 없습니다.")
                    except Exception as js_err:
                        self.logger.error(f"❌ [{self.internal_name}] 모든 방법으로 드롭다운을 찾을 수 없습니다: {js_err}")
                        self.logger.warning(f"⚠️  [{self.internal_name}] 하위 카테고리 컨테이너를 찾을 수 없습니다. 일반 페이지네이션으로 처리합니다.")
                        return self._paginate_and_scrape_all_pages('행위료')
        
        # 드롭다운 요소를 찾았으면 처리
        if element:
            try:
                # 요소가 표시될 때까지 대기
                WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, dropdown_selector)))
            except:
                # 표시되지 않아도 계속 진행
                pass
            
            if element.tag_name.lower() == 'select':
                # select 태그인 경우 드롭다운 처리
                self.logger.info(f"✅ [{self.internal_name}] 드롭다운 감지됨 (태그: select, 옵션 개수 확인 중...)")
                try:
                    select = Select(element)
                    num_options = len(select.options)
                    self.logger.info(f"✅ [{self.internal_name}] 드롭다운 옵션 {num_options}개 확인됨")
                except Exception as select_err:
                    self.logger.warning(f"⚠️  [{self.internal_name}] Select 객체 생성 실패: {select_err}")
                
                return self._execute_dropdown_logic(dropdown_selector)
            else:
                # select가 아닌 경우 탭 컨테이너로 처리
                self.logger.info(f"✅ [{self.internal_name}] 탭 컨테이너 감지됨 (태그: {element.tag_name})")
                return self._execute_sub_tab_logic(dropdown_selector)
        else:
            self.logger.warning(f"⚠️  [{self.internal_name}] 드롭다운 요소를 찾을 수 없습니다. 일반 페이지네이션으로 처리합니다.")
            return self._paginate_and_scrape_all_pages('행위료')

    def _execute_dropdown_logic(self, selector: str) -> List[Dict[str, Any]]:
        """드롭다운 옵션을 순회하며 데이터를 크롤링합니다. (강화된 에러 처리)"""
        all_data = []
        try:
            # 드롭다운 요소가 나타날 때까지 대기
            wait = WebDriverWait(self.driver, 15)
            dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
            select = Select(dropdown_element)
            num_options = len(select.options)
            
            self.logger.info(f"✅ [{self.internal_name}] 드롭다운 옵션 {num_options}개 발견")

            for i in range(num_options):
                try:
                    # Stale Element 방지를 위해 매번 다시 찾기
                    try:
                        select_el = Select(WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        ))
                    except TimeoutException:
                        self.logger.error(f"❌ [{self.internal_name}] 드롭다운 요소를 찾을 수 없습니다. 종료합니다.")
                        break
                    
                    if i >= len(select_el.options):
                        self.logger.warning(f"⚠️  [{self.internal_name}] 옵션 인덱스 {i}가 범위를 벗어났습니다. (총 {len(select_el.options)}개)")
                        break
                    
                    option_text = select_el.options[i].text.strip()
                    if not option_text:
                        self.logger.debug(f"[{self.internal_name}] 옵션 [{i+1}/{num_options}] 비어있음. 스킵합니다.")
                        continue  # 빈 옵션 스킵

                    self.logger.info(f"🔀 [{self.internal_name}] 드롭다운 옵션 [{i+1}/{num_options}] 처리: '{option_text}'")
                    
                    # 드롭다운 선택
                    try:
                        select_el.select_by_index(i)
                        time.sleep(1.5)  # 선택 반영 대기
                        self.logger.debug(f"✅ [{self.internal_name}] 드롭다운 옵션 '{option_text}' 선택 완료")
                    except Exception as select_err:
                        self.logger.error(f"❌ [{self.internal_name}] 드롭다운 선택 실패: {type(select_err).__name__}: {select_err}")
                        continue

                    # 검색 버튼이 있으면 반드시 클릭 (필수)
                    search_button_selector = self.config.get('search_button_selector')
                    if search_button_selector:
                        self.logger.info(f"🔍 [{self.internal_name}] 검색 버튼 클릭 시도 (필수)")
                        search_clicked = self._click_search_button(search_button_selector)
                        if not search_clicked:
                            self.logger.error(f"❌ [{self.internal_name}] 검색 버튼 클릭 실패. 옵션 '{option_text}'를 건너뜁니다.")
                            continue  # 검색 버튼 클릭 실패 시 이 옵션 건너뜀
                        time.sleep(2)  # 검색 결과 로딩 대기 (더 길게)
                    else:
                        self.logger.warning(f"⚠️  [{self.internal_name}] 검색 버튼 선택자가 설정되지 않았습니다. 드롭다운 선택 후 검색이 필요할 수 있습니다.")

                    # 테이블이 로드되었는지 확인
                    table_selector = self.config.get('table_selector')
                    if table_selector:
                        try:
                            WebDriverWait(self.driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, table_selector))
                            )
                            self.logger.debug(f"✅ [{self.internal_name}] 테이블 로드 확인")
                        except TimeoutException:
                            self.logger.warning(f"⚠️  [{self.internal_name}] 테이블이 나타나지 않았지만 계속 진행합니다.")

                    # 페이지네이션 및 스크래핑
                    data_for_option = self._paginate_and_scrape_all_pages(
                        '행위료', 
                        dropdown_text_for_injection=option_text, 
                        dropdown_index=i
                    )
                    all_data.extend(data_for_option)
                    self.logger.info(f"✅ [{self.internal_name}] 옵션 '{option_text}' 크롤링 완료: {len(data_for_option)}개 항목")

                    # 다음 옵션을 위해 원래 페이지로 돌아가기 (마지막 옵션이 아닌 경우에만)
                    if i < num_options - 1:  # 마지막 옵션이 아니면 복귀
                        try:
                            self.logger.info(f"🔄 [{self.internal_name}] 드롭다운 페이지로 돌아가기 (다음 옵션 처리 준비: {i+1}/{num_options})")
                            
                            # 원본 URL로 이동 (드롭다운 선택 전 상태로 복원)
                            original_url = self.config.get('url')
                            if original_url:
                                self.logger.debug(f"[{self.internal_name}] 원본 URL로 이동: {original_url}")
                                self.driver.get(original_url)
                            else:
                                # 원본 URL이 없으면 현재 URL에서 페이지 파라미터만 제거
                                current_url = self.driver.current_url
                                parsed = urlparse(current_url)
                                params = parse_qs(parsed.query)
                                # 페이지 파라미터 제거
                                if 'p' in params:
                                    del params['p']
                                new_query = urlencode(params, doseq=True)
                                new_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                                self.logger.debug(f"[{self.internal_name}] 수정된 URL로 이동: {new_url}")
                                self.driver.get(new_url)
                            
                            # 페이지 로드 대기
                            time.sleep(3)  # 페이지 완전 로드 대기 시간 증가
                            
                            # 탭이 활성화되어 있는지 확인 (탭 0이 활성화되어 있어야 드롭다운이 보임)
                            tab_selector = self.config.get('tab_selector')
                            if tab_selector:
                                try:
                                    tabs = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)
                                    if tabs and len(tabs) > 0:
                                        # 탭 0이 활성화되어 있지 않으면 클릭
                                        try:
                                            parent_li = tabs[0].find_element(By.XPATH, "./..")
                                            if "on" not in (parent_li.get_attribute("class") or ""):
                                                self.logger.debug(f"[{self.internal_name}] 탭 0이 활성화되지 않았습니다. 탭 클릭합니다.")
                                                tabs[0].click()
                                                time.sleep(2)
                                        except:
                                            # 탭 클릭 시도
                                            try:
                                                tabs[0].click()
                                                time.sleep(2)
                                            except:
                                                pass
                                except:
                                    pass
                            
                            # 드롭다운이 다시 나타날 때까지 대기 (최대 15초)
                            dropdown_found = False
                            for retry in range(5):
                                try:
                                    wait = WebDriverWait(self.driver, 3)
                                    dropdown_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                                    if dropdown_elem:
                                        dropdown_found = True
                                        self.logger.debug(f"✅ [{self.internal_name}] 드롭다운 요소 복원 확인 (재시도 {retry + 1}/5)")
                                        break
                                except:
                                    if retry < 4:
                                        time.sleep(1)
                                    else:
                                        # 마지막 재시도: JavaScript로 확인
                                        try:
                                            element_exists = self.driver.execute_script(
                                                f"return document.querySelector('{selector}') !== null;"
                                            )
                                            if element_exists:
                                                dropdown_found = True
                                                self.logger.debug(f"✅ [{self.internal_name}] 드롭다운 요소 JavaScript로 확인됨")
                                        except:
                                            pass
                            
                            if not dropdown_found:
                                self.logger.warning(f"⚠️  [{self.internal_name}] 드롭다운 요소를 찾을 수 없지만 계속 진행합니다.")
                            
                            time.sleep(1.5)  # 안정화 대기
                            self.logger.debug(f"✅ [{self.internal_name}] 드롭다운 페이지 복원 완료. 다음 옵션 처리 준비됨")
                        except Exception as back_err:
                            self.logger.error(f"❌ [{self.internal_name}] 드롭다운 페이지로 돌아가기 실패: {type(back_err).__name__}: {back_err}")
                            # 페이지 복원 실패 시 다음 옵션은 건너뜀
                            break

                except NoSuchElementException:
                    self.logger.warning(f"⚠️  [{self.internal_name}] 드롭다운 요소를 찾을 수 없습니다. 종료합니다.")
                    break
                except Exception as e:
                    self.logger.error(f"❌ [{self.internal_name}] 드롭다운 옵션 {i} 처리 중 오류: {e}", exc_info=True)
                    # 오류 발생 시 다음 옵션으로 계속 진행
                    continue

        except Exception as e:
            self.logger.error(f"❌ [{self.internal_name}] 드롭다운 로직 실행 실패: {e}", exc_info=True)
        
        self.logger.info(f"✅ [{self.internal_name}] 드롭다운 크롤링 완료: 총 {len(all_data)}개 항목 수집")
        return all_data

    def _execute_sub_tab_logic(self, selector: str) -> List[Dict[str, Any]]:
        """서브 탭을 순회하며 데이터를 크롤링합니다. (강화된 에러 처리)"""
        all_data = []
        try:
            # 서브 탭 링크 찾기
            wait = WebDriverWait(self.driver, 15)
            try:
                element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                if element.tag_name == 'a':
                    sub_tab_links = self.driver.find_elements(By.CSS_SELECTOR, selector)
                else:
                    sub_tab_links = element.find_elements(By.TAG_NAME, 'a')
                    if not sub_tab_links:
                        sub_tab_links = self.driver.find_elements(By.CSS_SELECTOR, f"{selector} a")
            except TimeoutException:
                self.logger.error(f"❌ [{self.internal_name}] 서브 탭 컨테이너를 찾을 수 없습니다.")
                return []
            except Exception:
                # 폴백: 선택자 + a 태그로 찾기
                sub_tab_links = self.driver.find_elements(By.CSS_SELECTOR, f"{selector} a")
            
            num_tabs = len(sub_tab_links)
            self.logger.info(f"✅ [{self.internal_name}] 서브 탭 {num_tabs}개 발견")

            for i in range(num_tabs):
                try:
                    # Stale Element 방지를 위해 매번 다시 찾기
                    try:
                        element = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        if element.tag_name == 'a':
                            current_tab_link = self.driver.find_elements(By.CSS_SELECTOR, selector)[i]
                        else:
                            links = element.find_elements(By.TAG_NAME, 'a')
                            if i < len(links):
                                current_tab_link = links[i]
                            else:
                                current_tab_link = self.driver.find_elements(By.CSS_SELECTOR, f"{selector} a")[i]
                    except (TimeoutException, IndexError) as e:
                        self.logger.error(f"❌ [{self.internal_name}] 서브 탭 {i}를 찾을 수 없습니다: {e}")
                        break
                    
                    tab_name = current_tab_link.text.strip()
                    if not tab_name:
                        self.logger.debug(f"[{self.internal_name}] 서브 탭 [{i+1}/{num_tabs}] 비어있음. 스킵합니다.")
                        continue  # 빈 탭 스킵

                    self.logger.info(f"🔀 [{self.internal_name}] 서브 탭 [{i+1}/{num_tabs}] 클릭: '{tab_name}'")
                    
                    # 클릭 시도
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", current_tab_link)
                        time.sleep(0.3)
                        self.driver.execute_script("arguments[0].click();", current_tab_link)
                        self.logger.debug(f"✅ [{self.internal_name}] 서브 탭 '{tab_name}' 클릭 완료")
                    except Exception as click_err:
                        self.logger.error(f"❌ [{self.internal_name}] 서브 탭 클릭 실패: {type(click_err).__name__}: {click_err}")
                        continue

                    # 테이블이 나타날 때까지 대기
                    table_selector = self.config.get('table_selector')
                    if table_selector:
                        try:
                            WebDriverWait(self.driver, 15).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, table_selector))
                            )
                            self.logger.debug(f"✅ [{self.internal_name}] 테이블 로드 확인")
                        except TimeoutException:
                            self.logger.warning(f"⚠️  [{self.internal_name}] 서브 탭 '{tab_name}' 클릭 후 테이블이 나타나지 않았습니다.")
                            # 테이블이 없어도 계속 진행 (데이터가 없을 수 있음)
                    else:
                        time.sleep(3)  # 폴백 대기

                    # 페이지네이션 및 스크래핑
                    data_for_tab = self._paginate_and_scrape_all_pages(
                        '행위료', 
                        dropdown_text_for_injection=tab_name, 
                        dropdown_index=i
                    )
                    all_data.extend(data_for_tab)
                    self.logger.info(f"✅ [{self.internal_name}] 서브 탭 '{tab_name}' 크롤링 완료: {len(data_for_tab)}개 항목")

                except Exception as e:
                    self.logger.error(f"❌ [{self.internal_name}] 서브 탭 {i} 처리 중 오류: {e}", exc_info=True)
                    # 오류 발생 시 다음 탭으로 계속 진행
                    continue

        except Exception as e:
            self.logger.error(f"❌ [{self.internal_name}] 서브 탭 로직 실행 실패: {e}", exc_info=True)
        
        self.logger.info(f"✅ [{self.internal_name}] 서브 탭 크롤링 완료: 총 {len(all_data)}개 항목 수집")
        return all_data

    def _click_search_button(self, search_button_selector: str) -> bool:
        """검색 버튼을 클릭합니다. (필수, 실패 시 False 반환)"""
        try:
            # 검색 버튼이 나타날 때까지 대기 (최대 10초)
            wait = WebDriverWait(self.driver, 10)
            search_button = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, search_button_selector))
            )
            
            # 버튼이 보이고 클릭 가능한지 확인
            if not search_button.is_displayed():
                self.logger.warning(f"⚠️  [{self.internal_name}] 검색 버튼이 표시되지 않았습니다.")
                # 표시되지 않아도 클릭 시도
            if not search_button.is_enabled():
                self.logger.warning(f"⚠️  [{self.internal_name}] 검색 버튼이 비활성화되어 있습니다.")
                # 비활성화되어 있어도 클릭 시도
            
            # 스크롤하여 요소가 보이도록 함
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", search_button)
            time.sleep(0.5)
            
            # 클릭 가능할 때까지 대기
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, search_button_selector)))
            
            # 클릭 시도
            try:
                search_button.click()
                self.logger.info(f"✅ [{self.internal_name}] 검색 버튼 클릭 성공")
            except Exception as click_err:
                self.logger.warning(f"⚠️  [{self.internal_name}] 표준 클릭 실패: {type(click_err).__name__}. JavaScript 클릭으로 재시도합니다.")
                try:
                    self.driver.execute_script("arguments[0].click();", search_button)
                    self.logger.info(f"✅ [{self.internal_name}] 검색 버튼 JavaScript 클릭 성공")
                except Exception as js_err:
                    self.logger.error(f"❌ [{self.internal_name}] JavaScript 클릭도 실패: {type(js_err).__name__}: {js_err}")
                    return False
            
            # 검색 결과가 로드될 때까지 대기 (테이블이 나타나거나 변경되는지 확인)
            time.sleep(1)  # 초기 대기
            
            # 테이블이 나타났는지 확인 (검색 결과 확인)
            table_selector = self.config.get('table_selector')
            if table_selector:
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, table_selector))
                    )
                    self.logger.debug(f"✅ [{self.internal_name}] 검색 후 테이블 로드 확인")
                except TimeoutException:
                    self.logger.warning(f"⚠️  [{self.internal_name}] 검색 후 테이블이 나타나지 않았지만 계속 진행합니다.")
            
            return True
            
        except TimeoutException:
            self.logger.error(f"❌ [{self.internal_name}] 검색 버튼을 찾을 수 없습니다: {search_button_selector}")
            return False
        except Exception as e:
            self.logger.error(f"❌ [{self.internal_name}] 검색 버튼 클릭 중 오류: {type(e).__name__}: {e}")
            return False

    def _paginate_and_scrape_all_pages(
        self, 
        internal_name: str, 
        dropdown_text_for_injection: Optional[str] = None, 
        dropdown_index: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """모든 페이지를 순회하며 데이터를 수집합니다. (무한 루프 방지 로직 추가)"""
        all_rows_data = []
        column_mapping = self._get_column_mapping(internal_name)
        if not column_mapping:
            self.logger.error(f"컬럼 매핑이 없습니다: '{internal_name}'")
            return []

        # 마지막 페이지 설정 확인
        last_page = None
        if internal_name == '행위료' and dropdown_index is not None:
            # '행위료' 하위 카테고리의 경우 콤마로 구분된 페이지 번호
            last_page_config_str = str(self.config.get('행위료 마지막 페이지', '')).strip()
            if last_page_config_str:
                try:
                    last_pages_list = [int(p.strip()) for p in last_page_config_str.split(',') if p.strip().isdigit()]
                    if dropdown_index < len(last_pages_list):
                        last_page = last_pages_list[dropdown_index]
                        self.logger.info(f"[{self.internal_name}] 카테고리 인덱스 {dropdown_index}의 마지막 페이지: {last_page}")
                except (ValueError, IndexError):
                    self.logger.warning(f"[{self.internal_name}] 마지막 페이지 설정 파싱 실패: {last_page_config_str}")
        else:
            # 다른 탭의 경우 단일 페이지 번호
            tab_last_page_key = f'{internal_name} 마지막 페이지'
            last_page_str = str(self.config.get(tab_last_page_key, '')).strip()
            if last_page_str.isdigit():
                last_page = int(last_page_str)
                self.logger.info(f"[{self.internal_name}] 탭 '{internal_name}'의 마지막 페이지: {last_page}")

        page_count = 1
        consecutive_empty_pages = 0
        max_pages = 10000  # 무한 루프 방지
        previous_first_row = None  # 무한 루프 방지: 이전 페이지의 첫 번째 행 데이터
        previous_page_row_count = None  # 이전 페이지의 행 개수
        same_data_count = 0  # 동일한 데이터가 반복된 횟수

        while page_count <= max_pages:
            if last_page and page_count > last_page:
                self.logger.info(f"[{self.internal_name}] 설정된 마지막 페이지({last_page})에 도달했습니다. 중단합니다.")
                break

            self.logger.info(f"[{self.internal_name}] 📄 페이지 {page_count} 스크래핑 중 (탭: '{internal_name}')...")
            
            page_data = self._scrape_current_page_table(column_mapping, dropdown_text_for_injection)

            if page_data:
                # 무한 루프 방지: 첫 번째 행이 이전 페이지와 동일한지 확인
                if previous_first_row and len(page_data) > 0:
                    current_first_row = str(page_data[0])
                    if current_first_row == previous_first_row:
                        same_data_count += 1
                        self.logger.warning(f"⚠️  [{self.internal_name}] 이전 페이지와 동일한 첫 번째 행 데이터가 발견되었습니다. (반복 {same_data_count}회)")
                        if same_data_count >= 2:
                            self.logger.critical(f"❌ [{self.internal_name}] 동일한 데이터가 {same_data_count}회 반복되었습니다. 무한 루프 방지를 위해 중단합니다.")
                            break
                    else:
                        same_data_count = 0  # 다른 데이터가 나오면 리셋
                
                # 행 개수 확인 (페이지네이션 컨테이너가 없을 때 마지막 페이지 판단용)
                current_row_count = len(page_data)
                if previous_page_row_count is not None and current_row_count == previous_page_row_count:
                    # 행 개수가 동일하고, 첫 번째 행도 동일하면 마지막 페이지일 가능성
                    if previous_first_row and len(page_data) > 0:
                        if str(page_data[0]) == previous_first_row:
                            self.logger.warning(f"⚠️  [{self.internal_name}] 페이지 {page_count}: 행 개수와 첫 번째 행이 이전 페이지와 동일합니다. 마지막 페이지로 판단합니다.")
                            break
                
                all_rows_data.extend(page_data)
                self.logger.info(f"✅ [{self.internal_name}] 페이지 {page_count}에서 {len(page_data)}개 항목 수집. 총: {len(all_rows_data)}")
                consecutive_empty_pages = 0
                # 다음 페이지 비교를 위해 첫 번째 행과 행 개수 저장
                if len(page_data) > 0:
                    previous_first_row = str(page_data[0])
                previous_page_row_count = current_row_count
            else:
                self.logger.warning(f"⚠️  [{self.internal_name}] 페이지 {page_count}에서 데이터를 찾지 못했습니다.")
                consecutive_empty_pages += 1

            if consecutive_empty_pages >= MAX_CONSECUTIVE_EMPTY:
                self.logger.critical(f"❌ [{self.internal_name}] {MAX_CONSECUTIVE_EMPTY}회 연속 빈 페이지. 크롤링 중단합니다.")
                break

            # 다음 페이지로 이동 시도
            next_page_result = self._click_next_page()
            if next_page_result is False:
                self.logger.info(f"🏁 [{self.internal_name}] 마지막 페이지에 도달했습니다. 총 {len(all_rows_data)}개 항목 수집 완료.")
                break
            elif next_page_result is None:
                # None 반환 시 에러 발생, 한 번 더 시도
                self.logger.warning(f"⚠️  [{self.internal_name}] 페이지 이동 중 에러 발생. 다시 시도합니다.")
                time.sleep(2)
                if not self._click_next_page():
                    self.logger.info(f"🏁 [{self.internal_name}] 재시도 후에도 다음 페이지로 이동할 수 없습니다. 크롤링을 종료합니다.")
                    break

            page_count += 1
            time.sleep(1)

        if page_count > max_pages:
            self.logger.error(f"❌ [{self.internal_name}] 최대 페이지 수({max_pages})에 도달했습니다. 무한 루프 방지를 위해 중단합니다.")

        self.logger.info(f"✅ [{self.internal_name}] '{internal_name}' 크롤링 완료: 총 {len(all_rows_data)}개 항목 수집")
        return all_rows_data

    def _scrape_current_page_table(
        self, 
        column_mapping: Dict[int, str], 
        dropdown_text: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """현재 페이지의 테이블 데이터를 추출합니다."""
        row_selector = self.config.get('row_selector')
        page_rows_data = []
        
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, row_selector))
            )
            rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
            
            for row in rows:
                try:
                    all_cells = row.find_elements(By.CSS_SELECTOR, 'th, td')
                    if not all_cells:
                        continue
                    
                    row_data = {
                        col_name: all_cells[col_idx].get_attribute('textContent').strip() 
                        if col_idx < len(all_cells) else '' 
                        for col_idx, col_name in column_mapping.items()
                    }
                    
                    # 하위 카테고리 정보 추가
                    if dropdown_text:
                        row_data['중분류'] = dropdown_text
                    
                    if any(row_data.values()):
                        page_rows_data.append(row_data)
                        
                except StaleElementReferenceException:
                    self.logger.warning(f"[{self.internal_name}] Stale Element 발생. 행을 건너뜁니다.")
                    continue
                    
            return page_rows_data
        except TimeoutException:
            return []  # 행이 없으면 빈 리스트 반환
        except Exception as e:
            self.logger.error(f"[{self.internal_name}] 테이블 스크래핑 중 오류: {e}", exc_info=True)
            return []

    def _switch_to_tab_by_index(self, tab_index: int) -> bool:
        """탭 인덱스로 탭을 전환합니다. (강화된 버전)"""
        tab_selector = self.config.get('tab_selector')
        table_selector = self.config.get('table_selector')
        row_selector = self.config.get('row_selector')
        
        if not tab_selector:
            self.logger.error(f"❌ [{self.internal_name}] 'tab_selector'가 설정에 정의되지 않았습니다.")
            return False
        
        try:
            wait = WebDriverWait(self.driver, 15)
            
            # 탭들이 나타날 때까지 대기
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, tab_selector)))
            
            # 현재 탭 목록 가져오기
            tabs_for_check = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)
            if tab_index >= len(tabs_for_check):
                self.logger.error(f"❌ [{self.internal_name}] 탭 인덱스 {tab_index}가 범위를 벗어났습니다. (총 {len(tabs_for_check)}개 탭)")
                return False
            
            # 부모 li 태그에 'on' 클래스 확인 (서울성모병원 구조)
            try:
                parent_li = tabs_for_check[tab_index].find_element(By.XPATH, "./..")
                if "on" in (parent_li.get_attribute("class") or ""):
                    self.logger.info(f"✅ [{self.internal_name}] 탭 {tab_index}이 이미 활성화되어 있습니다.")
                    # 이미 활성화되어 있어도 테이블이 로드되었는지 확인
                    if self._verify_table_loaded(table_selector, row_selector):
                        return True
                    else:
                        self.logger.warning(f"⚠️  [{self.internal_name}] 탭이 활성화되어 있지만 테이블이 로드되지 않았습니다. 재시도합니다.")
            except Exception:
                pass  # 부모 요소 확인 실패 시 계속 진행

            # 테이블 선택자 확인
            if not table_selector:
                self.logger.warning(f"⚠️  [{self.internal_name}] 'table_selector'가 설정되지 않았습니다. 클릭만 수행합니다.")
                target_tab = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index]
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_tab)
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", target_tab)
                time.sleep(3)
                return True

            # 클릭 전 테이블 텍스트 또는 행 개수 저장
            initial_table_content = None
            if row_selector:
                try:
                    initial_rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                    if initial_rows:
                        initial_table_content = initial_rows[0].text.strip() if len(initial_rows) > 0 else None
                except Exception:
                    pass
            
            if not initial_table_content:
                try:
                    initial_table_content = self.driver.find_element(By.CSS_SELECTOR, table_selector).text[:100]  # 처음 100자만
                except NoSuchElementException:
                    initial_table_content = "no_initial_table_found"

            # 탭 클릭
            self.logger.info(f"🔀 [{self.internal_name}] 탭 {tab_index}로 전환 시도")
            target_tab = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)[tab_index]
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_tab)
            time.sleep(0.5)
            
            try:
                target_tab.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", target_tab)

            # 테이블 내용 변경 대기 (여러 방법으로 확인)
            self.logger.info(f"[{self.internal_name}] 탭 내용 로딩 대기 중...")
            try:
                # 방법 1: 테이블 텍스트 변경 확인
                if row_selector:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: self._is_table_changed(d, row_selector, initial_table_content)
                    )
                else:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: d.find_element(By.CSS_SELECTOR, table_selector).text[:100] != initial_table_content
                    )
                self.logger.info(f"✅ [{self.internal_name}] 탭 내용 로드 완료 (테이블 변경 확인)")
            except TimeoutException:
                # 방법 2: 테이블이 나타났는지 확인
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, table_selector))
                    )
                    self.logger.info(f"✅ [{self.internal_name}] 탭 내용 로드 완료 (테이블 요소 확인)")
                except TimeoutException:
                    self.logger.warning(f"⚠️  [{self.internal_name}] 테이블 로드 확인 실패했지만 계속 진행합니다.")
            
            time.sleep(2)  # 추가 대기 시간
            return True
        
        except Exception as e:
            self.logger.error(f"❌ [{self.internal_name}] 탭 전환 중 오류 발생: {e}", exc_info=True)
            # 폴백: 간단한 클릭 시도
            try:
                self.logger.warning(f"⚠️  [{self.internal_name}] 탭 전환 재시도 (간단한 클릭)")
                tabs = self.driver.find_elements(By.CSS_SELECTOR, tab_selector)
                if tab_index < len(tabs):
                    tabs[tab_index].click()
                    time.sleep(5)
                    return True
            except Exception as e2:
                self.logger.error(f"❌ [{self.internal_name}] 모든 탭 전환 시도 실패: {e2}")
                return False
            return False

    def _verify_table_loaded(self, table_selector: Optional[str] = None, row_selector: Optional[str] = None) -> bool:
        """테이블이 로드되었는지 확인"""
        if not table_selector:
            table_selector = self.config.get('table_selector')
        if not row_selector:
            row_selector = self.config.get('row_selector')
        
        try:
            if table_selector:
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, table_selector))
                    )
                except TimeoutException:
                    return False
            
            if row_selector:
                rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                if len(rows) > 0:
                    return True
            
            # 테이블 요소만 있어도 성공으로 간주
            if table_selector:
                try:
                    self.driver.find_element(By.CSS_SELECTOR, table_selector)
                    return True
                except:
                    pass
            
            return False
        except Exception:
            return False
    
    def _is_table_changed(self, driver, row_selector: str, previous_content: Optional[str]) -> bool:
        """테이블 내용이 변경되었는지 확인"""
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, row_selector)
            if rows and len(rows) > 0:
                current_content = rows[0].text.strip()
                return current_content != previous_content
        except:
            pass
        return False

    def _click_next_page(self) -> Optional[bool]:
        """강화된 페이지네이션 로직: 페이지 번호를 우선적으로 찾고 변경을 검증합니다. (페이지네이션 컨테이너 없을 때 처리 추가)"""
        page_num_selector = self.config.get('page_number_selector')
        next_block_selector = self.config.get('next_button_selector')
        row_selector = self.config.get('row_selector')

        # Helper: 현재 활성 페이지 번호 텍스트 찾기
        def get_active_page_text() -> Optional[str]:
            try:
                if not page_num_selector:
                    return None
                page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_num_selector)
                for element in page_elements:
                    # strong 태그는 활성 페이지를 나타냄
                    if element.tag_name == 'strong':
                        return element.text.strip()

                    el_class = element.get_attribute('class') or ''
                    is_active = 'active' in el_class or 'on' in el_class or 'ac' in el_class

                    if not is_active:
                        try:
                            link_tag = element.find_element(By.TAG_NAME, 'a')
                            a_class = link_tag.get_attribute('class') or ''
                            is_active = 'active' in a_class or 'on' in a_class or 'ac' in a_class
                        except NoSuchElementException:
                            pass

                    if is_active:
                        return element.text.strip()
            except Exception:
                return None
            return None

        try:
            # 페이지네이션 컨테이너 대기 (찾지 못해도 계속 진행)
            pagination_container_found = False
            wait = WebDriverWait(self.driver, 5)
            try:
                wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.pagination, div.paging, div.paging_D")
                ))
                pagination_container_found = True
                self.logger.debug(f"✅ [{self.internal_name}] 페이지네이션 컨테이너 발견")
            except TimeoutException:
                self.logger.warning(f"⚠️  [{self.internal_name}] 페이지네이션 컨테이너를 찾을 수 없습니다. nextPageBtn으로 직접 이동을 시도합니다.")
                # 페이지네이션 컨테이너가 없어도 nextPageBtn이 있으면 계속 진행
                if next_block_selector:
                    try:
                        next_button = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                        if next_button.is_displayed() and next_button.is_enabled():
                            self.logger.info(f"✅ [{self.internal_name}] nextPageBtn을 찾았습니다. 페이지네이션 컨테이너 없이도 진행합니다.")
                            # nextPageBtn 클릭 시도
                            try:
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                                time.sleep(0.3)
                                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(next_button))
                                next_button.click()
                                self.logger.info(f"✅ [{self.internal_name}] nextPageBtn 클릭 성공 (페이지네이션 컨테이너 없이)")
                                # 페이지 변경 확인
                                time.sleep(2)
                                # row count로 확인
                                if row_selector:
                                    try:
                                        rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                                        if len(rows) > 0:
                                            self.logger.info(f"✅ [{self.internal_name}] 페이지 이동 성공 (행 개수: {len(rows)}개)")
                                            return True
                                    except:
                                        pass
                                # 일단 성공으로 간주 (상위 로직에서 데이터 중복 확인)
                                return True
                            except Exception as click_err:
                                self.logger.error(f"❌ [{self.internal_name}] nextPageBtn 클릭 실패: {type(click_err).__name__}")
                                return None
                        else:
                            self.logger.info(f"🏁 [{self.internal_name}] nextPageBtn이 비활성화되어 있습니다. 마지막 페이지로 판단합니다.")
                            return False
                    except NoSuchElementException:
                        self.logger.info(f"🏁 [{self.internal_name}] nextPageBtn도 찾을 수 없습니다. 마지막 페이지로 판단합니다.")
                        return False
                else:
                    self.logger.info(f"🏁 [{self.internal_name}] next_block_selector가 설정되지 않았습니다. 마지막 페이지로 판단합니다.")
                    return False

            # 페이지네이션 컨테이너가 있는 경우 정상 처리
            if not page_num_selector:
                self.logger.warning(f"⚠️  [{self.internal_name}] 'page_number_selector'가 설정되지 않았습니다.")
                # nextPageBtn만 사용
                if next_block_selector:
                    try:
                        next_button = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                        if next_button.is_displayed() and next_button.is_enabled():
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                            time.sleep(0.3)
                            WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(next_button))
                            next_button.click()
                            time.sleep(2)
                            return True
                    except:
                        pass
                return False

            initial_active_text = get_active_page_text()
            self.logger.info(f"📄 [{self.internal_name}] 현재 활성 페이지: '{initial_active_text}'. 다음 페이지 요소 찾는 중...")

            page_elements = self.driver.find_elements(By.CSS_SELECTOR, page_num_selector)
            if not page_elements:
                # 페이지 번호 요소가 없으면 nextPageBtn 사용
                if next_block_selector:
                    try:
                        next_button = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                        if next_button.is_displayed() and next_button.is_enabled():
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                            time.sleep(0.3)
                            WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(next_button))
                            next_button.click()
                            time.sleep(2)
                            return True
                    except:
                        pass
                return False

            active_idx = -1
            if initial_active_text:
                for i, element in enumerate(page_elements):
                    if element.text.strip() == initial_active_text:
                        active_idx = i
                        break

            element_to_click = None

            # Case 1: 활성 페이지가 발견되었고 블록 내에 다음 페이지가 있는 경우
            if active_idx != -1 and active_idx < len(page_elements) - 1:
                element_to_click = page_elements[active_idx + 1]
                self.logger.info(f"✅ [{self.internal_name}] 다음 페이지 번호 발견: '{element_to_click.text}'")

            # Case 2: 활성 페이지가 블록의 끝이거나 찾지 못한 경우, '다음 블록' 버튼 사용
            elif next_block_selector:
                try:
                    element_to_click = self.driver.find_element(By.CSS_SELECTOR, next_block_selector)
                    if element_to_click.is_displayed() and element_to_click.is_enabled():
                        self.logger.info(f"✅ [{self.internal_name}] '다음 블록' 버튼 사용")
                    else:
                        self.logger.info(f"🏁 [{self.internal_name}] '다음 블록' 버튼이 비활성화되어 있습니다. 페이지네이션 종료.")
                        return False
                except NoSuchElementException:
                    self.logger.info(f"🏁 [{self.internal_name}] '다음 블록' 버튼을 찾을 수 없습니다. 페이지네이션 종료.")
                    return False
            else:
                self.logger.info(f"🏁 [{self.internal_name}] 추가 페이지 번호나 '다음 블록' 버튼이 없습니다. 페이지네이션 종료.")
                return False

            # li 태그인 경우 내부 a 태그 찾기
            actual_clickable_element = element_to_click
            if element_to_click.tag_name.lower() == 'li':
                try:
                    actual_clickable_element = element_to_click.find_element(By.TAG_NAME, 'a')
                    self.logger.debug(f"[{self.internal_name}] <li> 내부 <a> 태그 찾음")
                except NoSuchElementException:
                    self.logger.debug(f"[{self.internal_name}] <li> 내부 <a> 태그를 찾을 수 없습니다. <li> 직접 클릭합니다.")

            # 클릭 실행
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", actual_clickable_element)
                time.sleep(0.3)
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(actual_clickable_element))
                actual_clickable_element.click()
            except Exception as click_e:
                self.logger.warning(f"⚠️  [{self.internal_name}] 표준 클릭 실패: {type(click_e).__name__}. JS 클릭으로 재시도합니다.")
                try:
                    self.driver.execute_script("arguments[0].click();", actual_clickable_element)
                except Exception as js_err:
                    self.logger.error(f"❌ [{self.internal_name}] JS 클릭도 실패: {type(js_err).__name__}")
                    return None

            # 페이지 변경 확인
            time.sleep(1.5)  # 페이지 로딩 대기

            # 페이지네이션 컨테이너가 없었던 경우, row count로만 확인
            if not pagination_container_found:
                self.logger.debug(f"[{self.internal_name}] 페이지네이션 컨테이너가 없었으므로 row count로만 확인합니다.")
                try:
                    if row_selector:
                        rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                        row_count = len(rows)
                        if row_count > 0:
                            self.logger.info(f"✅ [{self.internal_name}] 페이지 이동 성공 (행 개수: {row_count}개, 페이지네이션 컨테이너 없음)")
                            return True
                except Exception as e:
                    self.logger.debug(f"[{self.internal_name}] row count 확인 중 오류: {e}")
                
                # row count 확인 실패해도 클릭은 성공했으므로 일단 성공으로 간주
                self.logger.info(f"✅ [{self.internal_name}] 페이지 이동 시도 완료 (페이지네이션 컨테이너 없음, 데이터 변경은 상위 로직에서 확인)")
                return True

            # 페이지네이션 컨테이너가 있는 경우, 정상적인 확인 진행
            try:
                # 페이지 변경 확인 (최대 10초 대기)
                page_changed = False
                for attempt in range(10):
                    time.sleep(1)
                    new_active_text = get_active_page_text()
                    if new_active_text and new_active_text != initial_active_text:
                        self.logger.info(f"✅ [{self.internal_name}] 페이지 이동 성공. 새 활성 페이지: '{new_active_text}'.")
                        page_changed = True
                        break
                    elif attempt < 9:
                        continue

                if not page_changed:
                    # 페이지 번호가 변경되지 않았지만, row count로 확인
                    try:
                        if row_selector:
                            rows = self.driver.find_elements(By.CSS_SELECTOR, row_selector)
                            if len(rows) > 0:
                                self.logger.info(f"✅ [{self.internal_name}] 페이지 이동 성공 (행 개수 확인: {len(rows)}개)")
                                return True
                    except:
                        pass

                    # 그래도 확인되지 않으면 경고하고 계속 진행 (페이지가 실제로 변경되었을 수 있음)
                    self.logger.warning(f"⚠️  [{self.internal_name}] 페이지 변경 확인 실패 (현재 페이지: '{initial_active_text}'), 하지만 계속 진행합니다.")
                    return True  # 일단 성공으로 간주하고 계속 진행

                return True
            except Exception as e:
                self.logger.error(f"❌ [{self.internal_name}] 페이지 변경 확인 중 오류: {e}")
                # 오류가 발생해도 한 번 더 시도
                try:
                    final_check = get_active_page_text()
                    if final_check and final_check != initial_active_text:
                        self.logger.info(f"✅ [{self.internal_name}] 오류 후 재확인: 페이지 이동 성공 '{final_check}'")
                        return True
                except:
                    pass
                return None  # 에러 발생 시 None 반환

        except Exception as e:
            self.logger.error(f"❌ [{self.internal_name}] 페이지네이션 중 치명적 오류 발생: {e}", exc_info=True)
            return None  # 에러 발생 시 None 반환

    def _get_column_mapping(self, internal_name: str) -> Dict[int, str]:
        """
        서울성모병원 테이블의 탭별 컬럼 매핑을 반환합니다.
        """
        # '행위료' 또는 '행위' 탭
        if '행위' in internal_name:
            return {
                0: "중분류", 1: "소분류", 2: "코드", 3: "명칭", 4: "구분", 5: "비용",
                6: "최저비용", 7: "최고비용", 8: "치료재료대 포함", 9: "약제비 포함", 10: "특이사항", 11: "최종 변경일"
            }
        # '치료재료' 탭
        elif '치료재료' in internal_name:
            return {
                0: "중분류", 1: "코드", 2: "명칭", 3: "구분", 4: "비용",
                5: "최저비용", 6: "최고비용", 7: "특이사항", 8: "최종 변경일"
            }
        # '약제' 탭
        elif '약제' in internal_name:
            return {
                0: "코드", 1: "명칭", 2: "비용", 3: "특이사항", 4: "최종 변경일"
            }
        # '제증명수수료' 탭
        elif '제증명' in internal_name:
            return {
                0: "코드", 1: "명칭", 2: "구분", 3: "비용", 4: "특이사항", 5: "최종 변경일"
            }
        else:
            self.logger.warning(f"알 수 없는 탭 이름: {internal_name}. 기본 매핑 사용.")
            return {0: "분류", 1: "코드", 2: "명칭", 3: "가격"}
