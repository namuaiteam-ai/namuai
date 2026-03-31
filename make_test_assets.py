"""테스트용 이미지 3장 + SRT 자막 생성"""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 720, 1280
os.makedirs("test_assets", exist_ok=True)

CARDS = [
    {"bg": (30, 60, 120),   "title": "이지뉴스", "sub": "오늘의 헤드라인"},
    {"bg": (120, 40, 40),   "title": "최신 뉴스", "sub": "신속하게 전달합니다"},
    {"bg": (30, 100, 60),   "title": "YouTube Shorts", "sub": "짧고 강렬하게"},
]

for i, card in enumerate(CARDS):
    img = Image.new("RGB", (W, H), card["bg"])
    draw = ImageDraw.Draw(img)

    # 그라디언트 오버레이 효과 (단순 사각형)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 80))
    img.paste(Image.new("RGB", (W, 200), (0, 0, 0)), (0, H - 200))

    draw = ImageDraw.Draw(img)

    # 제목 (중앙)
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 72)
        font_sub   = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 36)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub   = font_title

    # 제목 텍스트
    bbox = draw.textbbox((0, 0), card["title"], font=font_title)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2, H / 2 - 80), card["title"], font=font_title, fill="white")

    # 부제목
    bbox2 = draw.textbbox((0, 0), card["sub"], font=font_sub)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((W - tw2) / 2, H / 2 + 20), card["sub"], font=font_sub, fill=(220, 220, 220))

    # 이미지 번호
    draw.text((30, 50), f"{i + 1} / {len(CARDS)}", font=font_sub, fill=(180, 180, 180))

    path = f"test_assets/image{i+1}.jpg"
    img.save(path, quality=95)
    print(f"생성: {path}")

# SRT 자막
srt = """1
00:00:00,000 --> 00:00:04,000
이지뉴스에 오신 것을 환영합니다

2
00:00:04,000 --> 00:00:08,000
오늘의 최신 뉴스를 전해드립니다

3
00:00:08,000 --> 00:00:12,000
YouTube Shorts로 빠르게 확인하세요
"""
with open("test_assets/subtitle.srt", "w", encoding="utf-8") as f:
    f.write(srt)
print("생성: test_assets/subtitle.srt")

# 오디오 (ffmpeg로 1kHz 사인파 12초)
import subprocess
subprocess.run([
    "ffmpeg", "-y",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
    "-af", "volume=0.3",
    "test_assets/narration.mp3"
], capture_output=True)
print("생성: test_assets/narration.mp3")
print("\n✅ 테스트 에셋 생성 완료!")
