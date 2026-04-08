#!/usr/bin/env python3
"""
뉴스 기사 → 노래/랩 가사 생성기 (Claude API 사용)

사용법:
    from lyrics_generator import generate_lyrics
    result = generate_lyrics(article_text="...", style="kpop", duration=60)
"""

import json
import os
import re

# 음악 스타일별 설정
STYLE_CONFIGS = {
    "kpop": {
        "name": "K-팝",
        "suno_style": "K-pop, Korean pop, upbeat, catchy, electronic, synth, energetic, bright",
        "bpm": 120,
        "lyric_glow": "&H00B469FF",   # ASS BGR: 핑크 (#FF69B4)
        "structure": "[버스1]\n...\n\n[코러스]\n...\n\n[버스2]\n...\n\n[코러스]",
    },
    "hiphop": {
        "name": "힙합/랩",
        "suno_style": "Korean hip-hop, rap, trap, 808 bass, hard-hitting, urban, drill",
        "bpm": 95,
        "lyric_glow": "&H0000D7FF",   # ASS BGR: 골드 (#FFD700)
        "structure": "[버스1]\n...\n\n[훅]\n...\n\n[버스2]\n...\n\n[훅]",
    },
    "ballad": {
        "name": "발라드",
        "suno_style": "Korean ballad, emotional, piano, strings, heartfelt, slow, acoustic",
        "bpm": 72,
        "lyric_glow": "&H00E16941",   # ASS BGR: 블루 (#4169E1)
        "structure": "[인트로]\n...\n\n[버스]\n...\n\n[코러스]\n...\n\n[브릿지]\n...\n\n[코러스]",
    },
    "trot": {
        "name": "트로트",
        "suno_style": "Korean trot, 트로트, traditional Korean pop, accordion, upbeat, retro",
        "bpm": 130,
        "lyric_glow": "&H000000FF",   # ASS BGR: 레드 (#FF0000)
        "structure": "[버스]\n...\n\n[코러스]\n...\n\n[버스2]\n...\n\n[코러스]",
    },
    "pop": {
        "name": "팝",
        "suno_style": "Korean pop, catchy chorus, modern production, radio-friendly, upbeat, hook",
        "bpm": 115,
        "lyric_glow": "&H00008CFF",   # ASS BGR: 오렌지 (#FF8C00)
        "structure": "[버스1]\n...\n\n[프리코러스]\n...\n\n[코러스]\n...\n\n[버스2]\n...\n\n[코러스]",
    },
}


def generate_lyrics(article_text: str, style: str = "kpop",
                    duration: int = 60) -> dict:
    """
    뉴스 기사를 노래/랩 가사로 변환 (Claude API 사용)

    Args:
        article_text: 한국어 뉴스 기사 본문
        style: 음악 스타일 (kpop|hiphop|ballad|trot|pop)
        duration: 목표 음악 길이 (초)

    Returns:
        {
            "title": str,          # 노래 제목
            "lyrics": str,         # 구조화된 가사 ([버스], [코러스] 태그 포함)
            "lrc": str,            # LRC 형식 가사 (자동 타이밍)
            "lines": list[str],    # 가사 줄 목록 (빈 줄/태그 제외)
            "suno_lyrics": str,    # Suno 커스텀 모드 가사
            "suno_style": str,     # Suno 스타일 프롬프트
            "style_config": dict,  # 스타일 설정값
            "style": str,          # 스타일 키
        }
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic 패키지가 필요합니다: pip install anthropic"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.\n"
            "설정 방법: set ANTHROPIC_API_KEY=your-key (Windows) 또는\n"
            "          export ANTHROPIC_API_KEY=your-key (Linux/Mac)"
        )

    style_conf = STYLE_CONFIGS.get(style, STYLE_CONFIGS["kpop"])
    style_name = style_conf["name"]
    suno_style_tags = style_conf["suno_style"]

    # 목표 라인 수 계산 (평균 3-4초/라인 기준)
    target_lines = max(10, min(32, duration // 3))

    prompt = f"""당신은 한국 뉴스를 감동적이고 중독성 있는 노래 가사로 만드는 전문 작사가입니다.

아래 뉴스 기사를 **{style_name}** 스타일의 노래 가사로 변환해주세요.

## 요구사항
- 뉴스의 핵심 내용(사실, 인물, 사건)을 가사에 녹여내세요
- 순수 한국어로 작성 (영어 단어는 꼭 필요한 경우만)
- 총 가사 줄 수: 약 {target_lines}줄 (섹션 태그·빈 줄 제외)
- 구조: [버스1] [코러스] [버스2] [코러스] (스타일에 맞게 조정)
- {style_name} 특유의 운율, 리듬감, 감성을 살려주세요
- 코러스는 반복·기억하기 쉽게 만들어 주세요
- 뉴스 내용이 명확히 전달되어야 합니다

## 뉴스 기사
{article_text[:2500]}

## 반환 형식 (반드시 순수 JSON만, 다른 텍스트 없이)
{{
  "title": "짧고 기억에 남는 노래 제목 (20자 이내)",
  "lyrics": "[버스1]\\n가사줄1\\n가사줄2\\n\\n[코러스]\\n후렴1\\n후렴2\\n\\n[버스2]\\n가사줄3\\n가사줄4\\n\\n[코러스]\\n후렴1\\n후렴2",
  "lines": ["가사줄1", "가사줄2", "후렴1", "후렴2", "가사줄3", "가사줄4", "후렴1", "후렴2"]
}}"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    # JSON 파싱 (코드블록 제거 후)
    raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if not json_match:
        raise ValueError(f"JSON 파싱 실패:\n{raw[:300]}")

    data = json.loads(json_match.group())
    title = data.get("title", "뉴스 쇼츠")
    lyrics = data.get("lyrics", "")
    lines = data.get("lines", [])

    # 빈 줄 / 섹션 태그 제거
    clean_lines = [
        l.strip() for l in lines
        if l.strip() and not (l.strip().startswith("[") and l.strip().endswith("]"))
    ]

    # LRC 자동 생성 (등간격 타이밍)
    lrc = _auto_lrc(clean_lines, duration, title)

    # Suno 스타일 프롬프트
    suno_style = f"{suno_style_tags}, {style_conf['bpm']}bpm, Korean news music"

    return {
        "title": title,
        "lyrics": lyrics,
        "lines": clean_lines,
        "lrc": lrc,
        "suno_lyrics": lyrics,
        "suno_style": suno_style,
        "style_config": style_conf,
        "style": style,
    }


def _auto_lrc(lines: list, duration: int, title: str) -> str:
    """가사 줄 목록 + 총 길이 → LRC 형식 자동 생성 (등간격)"""
    if not lines:
        return ""

    sec_per_line = duration / len(lines)
    current_ms = 0

    lrc_parts = [
        f"[ti:{title}]",
        "[ar:AI 뉴스 쇼츠]",
        f"[length:{duration // 60:02d}:{duration % 60:02d}]",
        "",
    ]

    for line in lines:
        mm = int(current_ms // 60000)
        ss = int((current_ms % 60000) // 1000)
        cc = int((current_ms % 1000) // 10)
        lrc_parts.append(f"[{mm:02d}:{ss:02d}.{cc:02d}]{line}")
        current_ms += int(sec_per_line * 1000)

    return "\n".join(lrc_parts)
