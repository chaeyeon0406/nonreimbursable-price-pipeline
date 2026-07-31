import logging
from selenium.webdriver.remote.webdriver import WebDriver

class BaseCrawler:
    """
    모든 크롤러 클래스의 기반이 되는 부모 클래스입니다.
    WebDriver, 설정(config), 로거(logger) 등 공통적인 속성을 초기화합니다.
    """
    def __init__(self, driver: WebDriver, config: dict, logger: logging.Logger, internal_name: str):
        """
        BaseCrawler를 초기화합니다.

        Args:
            driver (WebDriver): Selenium WebDriver 인스턴스.
            config (dict): 크롤링에 필요한 설정이 담긴 딕셔너리.
            logger (logging.Logger): 로깅을 위한 로거 인스턴스.
            internal_name (str): 크롤링 대상의 내부 이름 (예: 'snu_hospital').
        """
        self.driver = driver
        self.config = config
        self.logger = logger
        self.internal_name = internal_name