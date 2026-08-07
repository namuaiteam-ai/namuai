#!/usr/bin/env python3
"""
압축파일(zip) 업로드 → 이미지 생성 프롬프트 자동 생성

지원하는 zip 구성:
1) prompts.json / manifest.json  — [{"name","description","style"}, ...] 또는 문자열 배열
2) prompts.csv  / manifest.csv   — name,description,style 컬럼
3) prompts.txt                   — 한 줄에 하나씩 설명 텍스트
4) 이미지 파일들 (참고용) — 파일명과 동일한 이름의 .txt가 있으면 설명으로 사용,
   없으면 파일명을 정리해 프롬프트 기초로 사용
"""

import csv
import io
import json
import re
import zipfile
from pathlib import Path

STYLE_PRESETS = {
    "photo":        "photorealistic, DSLR photography, natural lighting, high detail, 8k",
    "illustration": "digital illustration, clean line art, vibrant colors, trending on artstation",
    "3d":           "3D render, octane render, studio lighting, high detail, physically based rendering",
    "watercolor":   "watercolor painting, soft brush strokes, paper texture, pastel palette",
    "anime":        "anime style, cel shading, sharp line art, vivid colors",
    "product":      "studio product photography, white background, soft shadow, high resolution, commercial",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
MANIFEST_NAMES = {"prompts.json", "manifest.json", "prompts.csv", "manifest.csv", "prompts.txt"}


def _clean_name(stem: str) -> str:
    text = re.sub(r"[_\-]+", " ", stem)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _read_json_manifest(zf: zipfile.ZipFile, arcname: str) -> list[dict]:
    data = json.loads(zf.read(arcname).decode("utf-8"))
    items = data if isinstance(data, list) else data.get("items", [])
    out = []
    for it in items:
        if isinstance(it, str):
            out.append({"name": "", "description": it})
        else:
            out.append({
                "name": it.get("name") or it.get("title") or "",
                "description": it.get("description") or it.get("prompt") or "",
                "style": it.get("style"),
            })
    return out


def _read_csv_manifest(zf: zipfile.ZipFile, arcname: str) -> list[dict]:
    raw = zf.read(arcname).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    out = []
    for row in reader:
        out.append({
            "name": (row.get("name") or row.get("title") or "").strip(),
            "description": (row.get("description") or row.get("prompt") or "").strip(),
            "style": (row.get("style") or "").strip() or None,
        })
    return out


def _read_txt_manifest(zf: zipfile.ZipFile, arcname: str) -> list[dict]:
    raw = zf.read(arcname).decode("utf-8-sig")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return [{"name": "", "description": ln} for ln in lines]


def _read_manifest(zf: zipfile.ZipFile) -> list[dict] | None:
    names = {Path(n).name.lower(): n for n in zf.namelist() if not n.endswith("/")}
    for target, reader in (
        ("prompts.json", _read_json_manifest),
        ("manifest.json", _read_json_manifest),
        ("prompts.csv", _read_csv_manifest),
        ("manifest.csv", _read_csv_manifest),
        ("prompts.txt", _read_txt_manifest),
    ):
        if target in names:
            return reader(zf, names[target])
    return None


def _read_images_with_sidecar(zf: zipfile.ZipFile) -> list[dict]:
    names = [n for n in zf.namelist() if not n.endswith("/")]
    text_lookup = {}
    for n in names:
        p = Path(n)
        if p.suffix.lower() == ".txt" and p.name.lower() not in MANIFEST_NAMES:
            text_lookup[p.with_suffix("").as_posix().lower()] = n

    items = []
    for n in names:
        p = Path(n)
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        key = p.with_suffix("").as_posix().lower()
        description = ""
        if key in text_lookup:
            description = zf.read(text_lookup[key]).decode("utf-8", errors="ignore").strip()
        items.append({
            "name": _clean_name(p.stem),
            "description": description,
            "source_filename": p.name,
        })
    return items


def build_prompt(item: dict, style: str, extra_keywords: str, aspect_ratio: str) -> str:
    base = (item.get("description") or item.get("name") or "제품").strip()
    style_kw = STYLE_PRESETS.get(item.get("style") or style, STYLE_PRESETS["photo"])
    parts = [base, style_kw]
    if extra_keywords:
        parts.append(extra_keywords.strip())
    if aspect_ratio and aspect_ratio != "auto":
        parts.append(f"aspect ratio {aspect_ratio}")
    parts.append("highly detailed, sharp focus, professional quality")
    return ", ".join(p for p in parts if p)


def generate_prompts_from_zip(zip_path: str, style: str = "photo",
                               extra_keywords: str = "", aspect_ratio: str = "1:1") -> list[dict]:
    with zipfile.ZipFile(zip_path) as zf:
        items = _read_manifest(zf)
        if items is None:
            items = _read_images_with_sidecar(zf)

    if not items:
        raise ValueError(
            "압축파일에서 이미지 또는 prompts.json/csv/txt 매니페스트를 찾을 수 없습니다."
        )

    results = []
    for i, item in enumerate(items):
        results.append({
            "id": i,
            "name": item.get("name") or f"item_{i + 1}",
            "prompt": build_prompt(item, style, extra_keywords, aspect_ratio),
            "source_filename": item.get("source_filename", ""),
            "status": "pending",
            "message": "",
        })
    return results
