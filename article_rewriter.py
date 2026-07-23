#!/usr/bin/env python3
"""
Claude API로 일반 뉴스 기사를 후킹력 있는 나레이션 대본으로 재작성한다.
- Anthropic API 키가 필요합니다 (유료). https://console.anthropic.com 에서 발급 후
  환경변수 ANTHROPIC_API_KEY로 설정하세요.
- 사실관계는 원문 그대로 유지하고, 문체/구성만 더 매력적으로 다듬습니다 (자극적 왜곡 금지).
"""

from __future__ import annotations

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = (
    "당신은 짧은 영상(유튜브 쇼츠) 나레이션 대본을 쓰는 작가입니다. "
    "입력된 뉴스 기사를 바탕으로, 시청자의 관심을 끄는 후킹력 있는 나레이션 대본으로 다시 씁니다.\n\n"
    "규칙:\n"
    "- 기사에 없는 사실을 지어내거나 과장하지 마세요. 사실관계는 원문 그대로 유지합니다.\n"
    "- 자극적인 어그로성 표현이 아니라, 궁금증을 유발하는 도입부와 리듬감 있는 문장으로 매력을 만드세요.\n"
    "- 구어체로, 소리 내어 읽었을 때 자연스럽게 쓰세요.\n"
    "- 한 줄에 한 문장씩, 짧고 리듬감 있게 줄바꿈하세요 (자막 한 줄 = 문장 하나).\n"
    "- 대본 텍스트만 출력하고, 다른 설명이나 따옴표는 붙이지 마세요."
)


def is_available() -> bool:
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def rewrite_article(article: str, model: str = MODEL) -> str:
    """뉴스 기사를 후킹력 있는 나레이션 대본으로 재작성해 반환한다."""
    if not article or not article.strip():
        raise ValueError("기사 내용이 비어 있습니다.")

    import anthropic
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": article.strip()}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()
