"""Deterministic image templates; every user-facing response is a PNG."""
from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .query import Reply
from .theme import stage, masthead, floating_panel, mix

FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)
WIDTH, MARGIN, MAX_HEIGHT = 900, 48, 2500
BG, INK, MUTED, PANEL = "#F2F6FA", "#1B2C43", "#64758A", "#FFFFFF"


def find_font(path: str | None = None) -> str:
    if path:
        if Path(path).is_file():
            return path
        raise ValueError("configured CJK font does not exist")
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise ValueError("install fonts-noto-cjk or set OURNOTES_QQ_FONT")


class Renderer:
    def __init__(self, snapshot: str, font: str | None = None):
        self.snapshot = snapshot
        path = find_font(font)
        self.font_path = path
        bold = path.replace("Regular", "Bold")
        self.fonts = {size: ImageFont.truetype(bold if size in (28, 32, 38, 44) and Path(bold).is_file() else path, size)
                      for size in (18, 20, 22, 24, 26, 28, 30, 32, 38, 44)}
        fallbacks = [Path(__file__).parent / "fonts/NotoSansSymbols.ttf",
                     Path(__file__).parent / "fonts/NotoSansSymbols2-Regular.ttf",
                     Path("/System/Library/Fonts/Hiragino Sans GB.ttc")]
        self.fallbacks = {size: [ImageFont.truetype(str(p), size) for p in fallbacks if p.is_file()]
                          for size in self.fonts}
        self.glyphs = {}
        self.missing = {id(f): bytes(f.getmask(chr(0x10FFFF)))
                        for size in self.fonts for f in [self.fonts[size], *self.fallbacks[size]]}
        self.measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def glyph_font(self, char: str, size: int):
        key = (char, size)
        if key not in self.glyphs:
            for font in [self.fonts[size], *self.fallbacks[size]]:
                if char.isspace() or bytes(font.getmask(char)) != self.missing[id(font)]:
                    self.glyphs[key] = font
                    break
            else:
                raise ValueError(f"font lacks character U+{ord(char):04X}")
        return self.glyphs[key]

    def runs(self, text: str, size: int):
        runs = []
        for char in text:
            font = self.glyph_font(char, size)
            if runs and runs[-1][0] is font:
                runs[-1] = (font, runs[-1][1] + char)
            else:
                runs.append((font, char))
        return runs

    def length(self, text: str, size: int) -> float:
        return sum(self.measure.textlength(run, font=font) for font, run in self.runs(text, size))

    def text(self, draw, xy, text, size, fill):
        x, y = xy
        for font, run in self.runs(text, size):
            draw.text((x, y + size), run, font=font, fill=fill, anchor="ls")
            x += draw.textlength(run, font=font)

    def wrap(self, text: str, width: int, size: int) -> list[str]:
        result = []
        for paragraph in str(text).split("\n"):
            line = ""
            for char in paragraph:
                if self.length(line + char, size) > width and line:
                    result.append(line)
                    line = char
                else:
                    line += char
            result.append(line)
        return result

    def render(self, reply: Reply) -> list[bytes]:
        if reply.layout:
            from .templates import Templates
            return Templates(self, reply).render()
        accent = reply.accent if re.fullmatch(r"#[0-9a-fA-F]{6}", reply.accent) else "#5364D9"
        title_lines = self.wrap(reply.title, WIDTH - 2 * MARGIN, 38)
        subtitle_lines = self.wrap(reply.subtitle, WIDTH - 2 * MARGIN, 24) if reply.subtitle else []
        header = 124 + len(title_lines) * 52 + len(subtitle_lines) * 36
        # Convert large sections into bounded panels without dropping any text.
        panels = []
        for section in reply.sections:
            heading = self.wrap(section.title, 748, 26)
            body = [line for text in section.lines for line in self.wrap(text, 748, 26)]
            for start in range(0, max(1, len(body)), 22):
                lines = body[start:start + 22]
                h = 40 + len(heading) * 38 + len(lines) * 39
                panels.append((heading, lines, h))
        if reply.notice:
            body = self.wrap(reply.notice, 748, 24)
            panels.append((["资料说明"], body, 78 + len(body) * 39))
        if any(panel[2] + header + 116 > MAX_HEIGHT for panel in panels):
            raise ValueError("section heading exceeds image pagination budget")
        visual = None
        if reply.image and reply.image.is_file():
            try:
                with Image.open(reply.image) as source:
                    visual = source.convert("RGBA")
            except (OSError, ValueError, Image.DecompressionBombError):
                pass
        hero_height = 390 if visual else 0
        pages, page, used = [], [], header + hero_height + 116
        for panel in panels:
            if used + panel[2] + 16 > MAX_HEIGHT:
                pages.append(page)
                page, used = [], header + 116
            page.append(panel)
            used += panel[2] + 16
        pages.append(page)
        if len(pages) > 4 or header > 700:
            raise ValueError("reply exceeds image pagination budget")
        output = []
        for index, page in enumerate(pages):
            hero = hero_height if index == 0 else 0
            height = max(620, header + hero + sum(x[2] + 16 for x in page) + 116)
            canvas = stage((WIDTH, height), accent)
            draw = ImageDraw.Draw(canvas)
            masthead(canvas, accent)
            self.text(draw, (48, 20), "OUR NOTES", 32, "white")
            self.text(draw, (48, 66), reply.kind, 20, "#CFDDF0")
            y = 120
            for line in title_lines:
                self.text(draw, (48, y), line, 38, INK)
                y += 52
            for line in subtitle_lines:
                self.text(draw, (48, y + 5), line, 24, MUTED)
                y += 36
            y = header
            if hero:
                draw.rounded_rectangle((48, y, 852, y + 366), radius=18, fill=PANEL)
                contained = ImageOps.contain(visual, (780, 344), Image.Resampling.LANCZOS)
                canvas.paste(contained, (48 + (804 - contained.width) // 2,
                                        y + (366 - contained.height) // 2), contained)
                y += hero
            for heading, lines, h in page:
                panel = Image.new("RGB", (804, h), PANEL)
                ImageDraw.Draw(panel).rectangle((0, 0, 804, 28 + len(heading)*38), fill=mix(accent, "#FFFFFF", .92))
                floating_panel(canvas, panel, (48, y))
                draw.rounded_rectangle((48, y + 23, 53, y + 49), radius=2, fill=accent)
                line_y = y + 18
                for line in heading:
                    self.text(draw, (76, line_y), line, 26, accent)
                    line_y += 38
                for line in lines:
                    self.text(draw, (76, line_y), line, 26, INK)
                    line_y += 39
                y += h + 16
            draw.line((48, height - 88, 852, height - 88), fill="#D9DEEF", width=2)
            self.text(draw, (48, height - 73), f"国际服 · 资料快照 {self.snapshot}", 20, MUTED)
            self.text(draw, (48, height - 41), "游戏内信息为准 · Our Notes", 20, MUTED)
            self.text(draw, (754, height - 58), f"{index + 1} / {len(pages)}", 20, MUTED)
            buffer = io.BytesIO()
            canvas.save(buffer, format="PNG", optimize=True)
            output.append(buffer.getvalue())
        return output
