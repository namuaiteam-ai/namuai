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

필요 패키지:
    pip install selenium

Chrome/Chromedriver:
    Selenium 4.6+ 는 Selenium Manager 가 내장되어 있어 별도 chromedriver 설치 없이
    시스템에 설치된 Chrome 버전에 맞는 드라이버를 자동으로 내려받는다.
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
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
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


def build_driver(profile_dir: str, headless: bool) -> webdriver.Chrome:
    """영구 프로필을 사용하는 Chrome 드라이버 생성 (로그인 세션 유지)."""
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

    driver = webdriver.Chrome(options=options)
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
        "--download-dir",
        help="생성된 이미지를 저장할 디렉터리 (지정하지 않으면 다운로드하지 않음)",
    )
    parser.add_argument(
        "--delay", type=float, default=5.0, help="프롬프트 간 대기 시간(초), 기본 5초"
    )
    parser.add_argument(
        "--response-timeout", type=float, default=180.0, help="응답 생성 최대 대기 시간(초)"
    )
    args = parser.parse_args()

    prompts = load_prompts(args)
    driver = build_driver(args.profile_dir, args.headless)

    try:
        driver.get(GEMINI_URL)
        wait_for_chat_ready(driver)

        for idx, prompt in enumerate(prompts, start=1):
            print(f"[{idx}/{len(prompts)}] 프롬프트 전송: {prompt}")
            send_prompt(driver, prompt)
            wait_for_response(driver, timeout=args.response_timeout)

            if args.download_dir:
                download_latest_images(
                    driver, Path(args.download_dir), prefix=f"prompt_{idx:03d}"
                )

            if idx < len(prompts):
                time.sleep(args.delay)

        print("모든 프롬프트 처리 완료.")
    finally:
        if not args.headless:
            input("종료하려면 Enter 를 누르세요 (브라우저를 닫습니다)...")
        driver.quit()


if __name__ == "__main__":
    main()
