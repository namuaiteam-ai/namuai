"""
Gemini(나노바나나) 이미지 자동 생성 스크립트

공식 Gemini API(gemini-2.5-flash-image)를 이용해 prompts.txt에 적어둔
프롬프트를 순서대로 호출해서 이미지를 폴더에 저장합니다.
(Chrome/Selenium으로 gemini.google.com 챗 화면을 직접 조작하는 방식은
구글 이용약관상 문제가 있어 사용하지 않습니다.)

사용법:
  1. pip install -r requirements.txt
  2. API 키 발급: https://aistudio.google.com/apikey
  3. 환경변수로 설정 (Windows cmd):
       set GEMINI_API_KEY=여기에_발급받은_키
     또는 실행할 때마다 --api-key 옵션으로 넘겨도 됩니다.
  4. prompts.txt에 프롬프트를 한 줄에 하나씩 적기 (빈 줄은 무시됨)
  5. 실행:
       python gemini_image_gen.py
     기본적으로 prompts.txt를 읽어서 output/gemini_images 폴더에 저장합니다.
"""

import argparse
import os
import sys
from pathlib import Path

from google import genai

MODEL_NAME = "gemini-2.5-flash-image"


def load_prompts(prompts_path: Path) -> list[str]:
    if not prompts_path.exists():
        sys.exit(f"프롬프트 파일을 찾을 수 없습니다: {prompts_path}")
    lines = prompts_path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def generate_images(prompts: list[str], out_dir: Path, api_key: str) -> None:
    client = genai.Client(api_key=api_key)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, prompt in enumerate(prompts, start=1):
        print(f"[{i}/{len(prompts)}] 생성 중: {prompt[:60]}...")
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[prompt],
            )
        except Exception as e:
            print(f"  실패: {e}")
            continue

        saved = False
        for part in response.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                out_path = out_dir / f"gemini_image_{i:02d}.png"
                out_path.write_bytes(part.inline_data.data)
                print(f"  저장 완료: {out_path}")
                saved = True
                break

        if not saved:
            print("  이미지 데이터를 응답에서 찾지 못했습니다 (텍스트만 반환됐을 수 있음)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini API로 프롬프트별 이미지 자동 생성")
    parser.add_argument("--prompts", default="prompts.txt", help="프롬프트 목록 파일 (한 줄에 하나씩)")
    parser.add_argument("--out", default="output/gemini_images", help="이미지 저장 폴더")
    parser.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY"), help="Gemini API 키 (기본: GEMINI_API_KEY 환경변수)")
    args = parser.parse_args()

    if not args.api_key:
        sys.exit(
            "API 키가 없습니다. GEMINI_API_KEY 환경변수를 설정하거나 --api-key 옵션을 사용하세요.\n"
            "발급: https://aistudio.google.com/apikey"
        )

    prompts = load_prompts(Path(args.prompts))
    if not prompts:
        sys.exit(f"{args.prompts}에 프롬프트가 없습니다.")

    generate_images(prompts, Path(args.out), args.api_key)


if __name__ == "__main__":
    main()
