#!/usr/bin/env python3
"""
「기억의 탑」 Seedance 2.0 클립 파이프라인

Magnific(Seedance 2.0)은 이 저장소 안에서 별도 API 키로 호출할 수 있는 공개 REST
엔드포인트가 아니라, Claude Code 세션에 연결된 MCP 서버(mcp__Magnific__*)를 통해서만
호출된다. 따라서 이 스크립트는 두 단계로 나뉜다.

  1) parse   : seedance_prompts_memory_tower.txt 를 파싱해 클립별 프롬프트를
               JSON(seedance_clips.json)으로 뽑아낸다. 에이전트(Claude)가 이 JSON을
               읽어 mcp__Magnific__video_generate 를 순서대로 호출한다.
  2) download: 에이전트가 생성을 마친 뒤 클립 번호 -> 다운로드 URL 매핑을 담은
               manifest(JSON)를 넘기면, 그걸 내려받아 ./output/clip_01.mp4 ~
               clip_20.mp4 형식으로 저장한다.

사용 예:
    python scripts/generate_seedance_clips.py parse \\
        --prompts-file seedance_prompts_memory_tower.txt \\
        --out seedance_clips.json

    python scripts/generate_seedance_clips.py download \\
        --manifest seedance_manifest.json \\
        --output-dir output
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

CLIP_RE = re.compile(
    r"CLIP\s+(?P<num>\d+)\s*\|\s*(?P<time>[\d:~]+)\s*─+\s*\n"
    r"\[장면\]\s*(?P<scene>.+?)\s*\n"
    r"\[프롬프트\]\s*\n"
    r"(?P<prompt>.+?)(?=\n\n─{3,}|\n\n【|\Z)",
    re.DOTALL,
)


def parse_clips(prompts_file: Path) -> list[dict]:
    text = prompts_file.read_text(encoding="utf-8")
    clips = []
    for m in CLIP_RE.finditer(text):
        clips.append({
            "number": int(m.group("num")),
            "time_range": m.group("time").strip(),
            "scene": m.group("scene").strip(),
            "prompt": " ".join(m.group("prompt").split()),
        })
    clips.sort(key=lambda c: c["number"])
    return clips


def cmd_parse(args: argparse.Namespace) -> None:
    prompts_file = Path(args.prompts_file)
    if not prompts_file.exists():
        sys.exit(f"[오류] 프롬프트 파일을 찾을 수 없습니다: {prompts_file}")

    clips = parse_clips(prompts_file)
    if not clips:
        sys.exit("[오류] 클립을 하나도 파싱하지 못했습니다. 파일 형식을 확인하세요.")

    start, end = args.start, args.end or clips[-1]["number"]
    selected = [c for c in clips if start <= c["number"] <= end]

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[완료] {len(selected)}개 클립(#{start}~#{end}) 파싱 -> {out_path}")
    for c in selected:
        print(f"  - clip_{c['number']:02d} ({c['time_range']}): {c['scene']}")


def cmd_download(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.exit(f"[오류] manifest 파일을 찾을 수 없습니다: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for entry in manifest:
        number = int(entry["number"])
        url = entry["url"]
        dest = output_dir / f"clip_{number:02d}.mp4"
        print(f"[다운로드] clip_{number:02d}.mp4 <- {url}")
        urllib.request.urlretrieve(url, dest)
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  -> 저장 완료: {dest} ({size_mb:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_parse = sub.add_parser("parse", help="프롬프트 txt -> 클립 JSON 파싱")
    p_parse.add_argument("--prompts-file", default="seedance_prompts_memory_tower.txt")
    p_parse.add_argument("--out", default="seedance_clips.json")
    p_parse.add_argument("--start", type=int, default=1)
    p_parse.add_argument("--end", type=int, default=None)
    p_parse.set_defaults(func=cmd_parse)

    p_dl = sub.add_parser("download", help="생성된 영상 URL manifest -> ./output/clip_NN.mp4 저장")
    p_dl.add_argument("--manifest", required=True)
    p_dl.add_argument("--output-dir", default="output")
    p_dl.set_defaults(func=cmd_download)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
