#!/usr/bin/env python3
"""
Gemini 챗 화면에 이미지 프롬프트를 자동 입력하는 스크립트 (Selenium)

- Chrome 프로필을 그대로 사용하므로 최초 1회 수동 로그인 후에는 재로그인 불필요
- 프롬프트 1개 또는 파일(줄 단위)로 여러 개를 순차 입력 가능
- 응답 생성이 끝날 때까지 대기 후, 생성된 이미지를 다운로드하는 옵션 제공

사용 예:
    python gemini_image_prompt_automation.py --prompt "노을 지는 해변, 유화 스타일"
    python gemini_image_prompt_automation.py --prompts-file prompts.txt --download-dir output/gemini_images
    python gemini_image_prompt_automation.py --prompts-file prompts.txt --headless

    # chromedriver 를 가져오는 방식 비교 테스트
    python gemini_image_prompt_automation.py --prompt "테스트" --driver-manager auto
    python gemini_image_prompt_automation.py --prompt "테스트" --driver-manager webdriver-manager

    # 평소 쓰는 Chrome(이미 로그인된 구글 계정)에 그대로 연결
    #   1) launch_chrome_debug.bat 실행 (기존 Chrome 창을 모두 닫고 디버깅 모드로 재실행)
    #   2) 아래처럼 --attach 로 그 창에 붙어서 제어
    python gemini_image_prompt_automation.py --prompt "테스트" --attach

필요 패키지:
    pip install selenium                    # --driver-manager auto (기본값)
    pip install selenium webdriver-manager  # --driver-manager webdriver-manager

Chrome/Chromedriver:
    - auto: Selenium 4.6+ 내장 Selenium Manager 가 Chrome 버전에 맞는 드라이버를
      자동으로 찾아 내려받는다. 별도 패키지 불필요.
    - webdriver-manager: 서드파티 webdriver-manager 패키지가 드라이버 다운로드/캐싱을
      명시적으로 관리한다. 사내망/프록시 등 Selenium Manager 가 실패하는 환경에서 대안으로 사용.
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

GEMINI_URL = "https://gemini.google.com/app"

# Gemini 웹 UI 는 자주 바뀌므로 여러 셀렉터를 순서대로 시도한다.
PROMPT_BOX_SELECTORS = [
    (By.CSS_SELECTOR, "div.ql-editor[contenteditable='true']"),
    (By.CSS_SELECTOR, "rich-textarea div[contenteditable='true']"),
    (By.CSS_SELECTOR, "div[aria-label='Enter a prompt here']"),
    (By.CSS_SELECTOR, "div[contenteditable='true']"),
]

SEND_BUTTON_SELECTORS = [
    (By.CSS_SELECTOR, "button.send-button:not([disabled])"),
    (By.CSS_SELECTOR, "button[aria-label='Send message']:not([disabled])"),
    (By.CSS_SELECTOR, "button[aria-label='메시지 보내기']:not([disabled])"),
]

STOP_BUTTON_SELECTORS = [
    (By.CSS_SELECTOR, "button[aria-label='Stop response']"),
    (By.CSS_SELECTOR, "button[aria-label='응답 중지']"),
]

RESPONSE_IMAGE_SELECTORS = [
    (By.CSS_SELECTOR, "message-content img"),
    (By.CSS_SELECTOR, "single-image img"),
]


def _build_chromedriver_service(driver_manager: str) -> Service | None:
    if driver_manager != "webdriver-manager":
        return None
    try:
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as exc:
        raise SystemExit(
            "webdriver-manager 가 설치되어 있지 않습니다. "
            "pip install webdriver-manager 로 설치하세요."
        ) from exc
    return Service(ChromeDriverManager().install())


def build_driver(
    profile_dir: str,
    headless: bool,
    driver_manager: str = "auto",
    attach_debugger_port: int | None = None,
) -> webdriver.Chrome:
    """Chrome 드라이버를 생성한다.

    driver_manager:
        "auto"             - Selenium 4.6+ 내장 Selenium Manager 가 chromedriver 를 자동 해결.
        "webdriver-manager" - webdriver-manager 패키지로 chromedriver 를 명시적으로 다운로드/캐싱.

    attach_debugger_port:
        지정하면 새 프로필을 만들지 않고, 이미 --remote-debugging-port 로 실행 중인
        Chrome(평소 로그인해서 쓰는 그 브라우저)에 그대로 연결한다.
        (launch_chrome_debug.bat 로 미리 그 포트를 열어둔 Chrome 을 켜둬야 함)
    """
    if attach_debugger_port:
        options = Options()
        options.add_experimental_option(
            "debuggerAddress", f"127.0.0.1:{attach_debugger_port}"
        )
        service = _build_chromedriver_service(driver_manager)
        driver = webdriver.Chrome(service=service, options=options) if service else webdriver.Chrome(options=options)
        return driver

    options = Options()
    options.add_argument(f"--user-data-dir={Path(profile_dir).resolve()}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--start-maximized")
    options.add_argument("--lang=ko-KR")
    if headless:
        # 구글 로그인은 headless 를 차단하는 경우가 많으므로
        # 최초 로그인은 반드시 headless=False 로 진행할 것을 권장.
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = _build_chromedriver_service(driver_manager)
    driver = webdriver.Chrome(service=service, options=options) if service else webdriver.Chrome(options=options)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def _find_first(driver, selectors, timeout=20):
    last_exc = None
    end_time = time.time() + timeout
    while time.time() < end_time:
        for by, value in selectors:
            try:
                el = driver.find_element(by, value)
                if el.is_displayed():
                    return el
            except (NoSuchElementException, StaleElementReferenceException) as exc:
                last_exc = exc
        time.sleep(0.5)
    raise TimeoutException(f"요소를 찾지 못함: {selectors}") from last_exc


def wait_for_chat_ready(driver, timeout=120):
    """프롬프트 입력창이 나타날 때까지 대기 (로그인 완료 대기 포함)."""
    print("Gemini 채팅창 로딩 대기 중... (최초 실행 시 수동 로그인 필요)")
    WebDriverWait(driver, timeout).until(
        lambda d: any(
            d.find_elements(by, value) for by, value in PROMPT_BOX_SELECTORS
        )
    )


def send_prompt(driver, prompt: str, timeout=20):
    """프롬프트 입력창에 텍스트를 입력하고 전송한다."""
    box = _find_first(driver, PROMPT_BOX_SELECTORS, timeout=timeout)
    box.click()
    box.send_keys(prompt)
    time.sleep(0.3)  # 전송 버튼 활성화 대기

    try:
        send_btn = _find_first(driver, SEND_BUTTON_SELECTORS, timeout=5)
        send_btn.click()
    except TimeoutException:
        box.send_keys(Keys.ENTER)


def wait_for_response(driver, timeout=180):
    """응답(이미지 생성 포함) 완료까지 대기: 중지 버튼이 사라질 때까지."""
    time.sleep(1.5)
    try:
        WebDriverWait(driver, timeout).until_not(
            lambda d: any(
                d.find_elements(by, value) for by, value in STOP_BUTTON_SELECTORS
            )
        )
    except TimeoutException:
        print("경고: 응답 완료 대기 시간 초과, 다음 단계로 진행합니다.", file=sys.stderr)


def download_latest_images(driver, download_dir: Path, prefix: str) -> list[Path]:
    """가장 최근 응답에 포함된 이미지들을 다운로드한다."""
    download_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    imgs = []
    for by, value in RESPONSE_IMAGE_SELECTORS:
        imgs = driver.find_elements(by, value)
        if imgs:
            break

    for i, img in enumerate(imgs):
        src = img.get_attribute("src")
        if not src or not src.startswith("http"):
            continue
        ext = ".png" if ".png" in src.lower() else ".jpg"
        out_path = download_dir / f"{prefix}_{i}{ext}"
        try:
            urllib.request.urlretrieve(src, out_path)
            saved.append(out_path)
            print(f"이미지 저장: {out_path}")
        except Exception as exc:
            print(f"이미지 다운로드 실패 ({src}): {exc}", file=sys.stderr)
    return saved


def load_prompts(args) -> list[str]:
    if args.prompt:
        return [args.prompt]
    if args.prompts_file:
        text = Path(args.prompts_file).read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]
    raise SystemExit("--prompt 또는 --prompts-file 중 하나는 반드시 지정해야 합니다.")


def run_prompts(
    prompts: list[str],
    profile_dir: str,
    headless: bool = False,
    driver_manager: str = "auto",
    download_dir: str | None = None,
    delay: float = 5.0,
    response_timeout: float = 180.0,
    progress_cb=None,
    should_stop=None,
    keep_open: bool = False,
    attach_debugger_port: int | None = None,
) -> list[dict]:
    """프롬프트 목록을 순서대로 Gemini 에 전송하고 결과를 반환한다.

    UI(웹/데스크톱)나 다른 스크립트에서 재사용할 수 있도록 CLI 로직을 함수로 분리.

    progress_cb(step, total, message) - 진행 상황 콜백 (선택)
    should_stop() -> bool             - True 를 반환하면 다음 프롬프트 전에 중단 (선택)
    keep_open                         - True 면 처리 후 브라우저를 닫지 않고 대기 (CLI 수동 확인용)
    attach_debugger_port              - 지정하면 새 프로필 대신 이미 열려 있는(로그인된) Chrome 에 연결.
                                         이 경우 사용자의 실제 브라우저이므로 작업 종료 후 닫지 않는다.

    반환: [{"prompt": str, "images": [str, ...]}, ...]
    """

    def report(step, total, message):
        print(message)
        if progress_cb:
            progress_cb(step, total, message)

    results = []
    driver = build_driver(
        profile_dir, headless, driver_manager=driver_manager,
        attach_debugger_port=attach_debugger_port,
    )
    try:
        report(0, len(prompts), "Gemini 접속 중...")
        if attach_debugger_port:
            # 기존 탭을 건드리지 않도록 새 탭을 열어서 사용한다.
            driver.switch_to.new_window("tab")
        driver.get(GEMINI_URL)
        wait_for_chat_ready(driver)

        for idx, prompt in enumerate(prompts, start=1):
            if should_stop and should_stop():
                report(idx - 1, len(prompts), "사용자 요청으로 중단됨.")
                break

            report(idx - 1, len(prompts), f"[{idx}/{len(prompts)}] 프롬프트 전송: {prompt}")
            send_prompt(driver, prompt)
            wait_for_response(driver, timeout=response_timeout)

            images: list[str] = []
            if download_dir:
                saved = download_latest_images(
                    driver, Path(download_dir), prefix=f"prompt_{idx:03d}"
                )
                images = [str(p) for p in saved]

            results.append({"prompt": prompt, "images": images})
            report(idx, len(prompts), f"[{idx}/{len(prompts)}] 완료")

            if idx < len(prompts):
                time.sleep(delay)

        report(len(prompts), len(prompts), "모든 프롬프트 처리 완료.")
    finally:
        if attach_debugger_port:
            # 연결만 한 것이므로 quit() 을 호출하지 않는다.
            # (attach 세션에서 quit() 을 부르면 사용자의 실제 Chrome 자체가 종료됨)
            pass
        else:
            if keep_open:
                input("종료하려면 Enter 를 누르세요 (브라우저를 닫습니다)...")
            driver.quit()

    return results


def main():
    parser = argparse.ArgumentParser(description="Gemini 챗창에 이미지 프롬프트 자동 입력")
    parser.add_argument("--prompt", help="단일 프롬프트 텍스트")
    parser.add_argument("--prompts-file", help="줄 단위로 프롬프트가 담긴 텍스트 파일")
    parser.add_argument(
        "--profile-dir",
        default="gemini_chrome_profile",
        help="Chrome 사용자 프로필 저장 경로 (로그인 세션 유지용, 기본: ./gemini_chrome_profile)",
    )
    parser.add_argument("--headless", action="store_true", help="헤드리스 모드로 실행")
    parser.add_argument(
        "--driver-manager",
        choices=["auto", "webdriver-manager"],
        default="auto",
        help="chromedriver 확보 방식: auto=Selenium Manager(기본), webdriver-manager=webdriver-manager 패키지",
    )
    parser.add_argument(
        "--download-dir",
        help="생성된 이미지를 저장할 디렉터리 (지정하지 않으면 다운로드하지 않음)",
    )
    parser.add_argument(
        "--delay", type=float, default=5.0, help="프롬프트 간 대기 시간(초), 기본 5초"
    )
    parser.add_argument(
        "--response-timeout", type=float, default=180.0, help="응답 생성 최대 대기 시간(초)"
    )
    parser.add_argument(
        "--attach",
        action="store_true",
        help="새 프로필 대신, launch_chrome_debug.bat 로 미리 띄워둔 기존 로그인 Chrome 에 연결",
    )
    parser.add_argument(
        "--debugger-port", type=int, default=9222,
        help="--attach 사용 시 연결할 Chrome 원격 디버깅 포트 (기본 9222)",
    )
    args = parser.parse_args()

    prompts = load_prompts(args)
    run_prompts(
        prompts,
        profile_dir=args.profile_dir,
        headless=args.headless,
        driver_manager=args.driver_manager,
        download_dir=args.download_dir,
        delay=args.delay,
        response_timeout=args.response_timeout,
        keep_open=not args.headless,
        attach_debugger_port=args.debugger_port if args.attach else None,
    )


if __name__ == "__main__":
    main()
