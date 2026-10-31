# -*- coding: utf-8 -*-
"""生成 addon 的 icon.png / fanart.jpg，视觉沿用 skin.mistuary 那套紫→青渐变。

为什么要脚本而不是直接画：
- 底图**不复制**皮肤那张 fanart（左下角已经烧了 "Mistuary / 雾 汐" 字样），
  而是把它降采样成 12×7 再双三次放大 —— 得到同一套配色、但没有任何文字的平滑渐变。
- 字体用皮肤自带的 Inter-Unicode-Regular.ttf，字形和皮肤完全一致。

用法（在 script.mistuary.helper 仓库根目录）：
    python tools/gen_assets.py
    python tools/gen_assets.py --skin-fanart ../skin.mistuary/resources/fanart.jpg

依赖：Pillow。
"""

from __future__ import annotations

import argparse
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULT_FANART = os.path.join(ROOT, "..", "skin.mistuary", "resources", "fanart.jpg")
DEFAULT_FONT = os.path.join(ROOT, "..", "skin.mistuary", "fonts", "Inter-Unicode-Regular.ttf")

ICON_SIZE = 256
FANART_W, FANART_H = 1920, 1080
ACCENT = (127, 209, 192)  # 青色识别点，和渐变右侧同色系但更亮


def _strip_text(src: Image.Image) -> Image.Image:
    """皮肤 fanart 左下角烧了 "Mistuary / 雾 汐" 字样。用正上方一块干净区域盖掉它，
    再整块模糊 —— 后面还要降采样到 12×7，接缝看不出来。"""
    w, h = src.size
    patch = src.crop((int(w * 0.02), int(h * 0.33), int(w * 0.30), int(h * 0.55)))
    patch = patch.filter(ImageFilter.GaussianBlur(6))
    src.paste(patch, (int(w * 0.02), int(h * 0.55)))
    return src


def gradient_from(base_path: str, size: tuple) -> Image.Image:
    """把皮肤 fanart 压成低分辨率再放大 → 同色系的纯渐变，没有文字残留。"""
    src = _strip_text(Image.open(base_path).convert("RGB"))
    tiny = src.resize((12, 7), Image.LANCZOS)
    return tiny.resize(size, Image.BICUBIC).filter(ImageFilter.GaussianBlur(1))


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size * 4 - 1, size * 4 - 1), radius=radius * 4, fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def draw_text(draw, xy, text, font, fill, shadow=True):
    if shadow:
        draw.text((xy[0], xy[1] + 2), text, font=font, fill=(0, 0, 0, 70))
    draw.text(xy, text, font=font, fill=fill)


def build_icon(base_path: str, font_path: str) -> Image.Image:
    # 整张 fanart 压成 12×7 再放大：文字会被平均掉，只留同一套配色
    bg = gradient_from(base_path, (ICON_SIZE, ICON_SIZE))

    canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    canvas.paste(bg, (0, 0))
    draw = ImageDraw.Draw(canvas)

    title_font = ImageFont.truetype(font_path, 40)
    sub_font = ImageFont.truetype(font_path, 22)

    draw.text((ICON_SIZE / 2, 110), "Mistuary", font=title_font, fill=(255, 255, 255, 255),
              anchor="mm")
    draw.text((ICON_SIZE / 2, 154), "Helper 助手", font=sub_font, fill=(255, 255, 255, 215),
              anchor="mm")

    # 右上角识别点（和皮肤图标区分）
    r = 5
    cx, cy = ICON_SIZE - 38, 38
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT + (255,))

    # 1px 内描边，和皮肤图标同款"玻璃边"
    draw.rounded_rectangle((0, 0, ICON_SIZE - 1, ICON_SIZE - 1), radius=22,
                           outline=(255, 255, 255, 26), width=1)

    canvas.putalpha(rounded_mask(ICON_SIZE, 22))
    return canvas


def build_fanart(base_path: str, font_path: str) -> Image.Image:
    canvas = gradient_from(base_path, (FANART_W, FANART_H)).convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    title_font = ImageFont.truetype(font_path, 66)
    sub_font = ImageFont.truetype(font_path, 38)
    note_font = ImageFont.truetype(font_path, 26)

    left = 120
    draw_text(draw, (left, 588), "Mistuary Helper", title_font, (255, 255, 255, 255))
    draw_text(draw, (left + 4, 682), "雾 汐 · 助手", sub_font, (255, 255, 255, 220))
    draw_text(draw, (left + 4, 744), "豆瓣评分 · 服务端搜索", note_font, (255, 255, 255, 150))
    return canvas


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 addon icon / fanart")
    ap.add_argument("--skin-fanart", default=DEFAULT_FANART, help="皮肤 fanart.jpg 路径（取配色用）")
    ap.add_argument("--font", default=DEFAULT_FONT, help="字体路径")
    ap.add_argument("--out", default=os.path.join(ROOT, "resources"), help="输出目录")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    icon = build_icon(args.skin_fanart, args.font)
    icon_path = os.path.join(args.out, "icon.png")
    icon.save(icon_path, "PNG")
    print("icon   ->", icon_path, icon.size)

    fanart = build_fanart(args.skin_fanart, args.font)
    fanart_path = os.path.join(args.out, "fanart.jpg")
    fanart.convert("RGB").save(fanart_path, "JPEG", quality=92, optimize=True)
    print("fanart ->", fanart_path, fanart.size)


if __name__ == "__main__":
    main()
