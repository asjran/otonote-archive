# Symbol fallback

`NotoSansSymbols2-Regular.ttf` is the unmodified Google Fonts distribution, downloaded 2026-09-26:

https://github.com/google/fonts/tree/main/ofl/notosanssymbols2

Distributed under the SIL Open Font License in `OFL.txt`.

`NotoSansSymbols.ttf` is the unmodified `NotoSansSymbols[wght].ttf` from https://github.com/google/fonts/tree/main/ofl/notosanssymbols, downloaded 2026-09-26; its license is `OFL-Symbols.txt`.

Both are used only for glyphs unavailable in the configured CJK font, including music, heart and alchemical symbols. System CJK fonts are not redistributed in this repository. The Docker image installs the Debian `fonts-noto-cjk` package.
