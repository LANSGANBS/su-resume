from __future__ import annotations

from pathlib import Path
import re
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_PATH = REPOSITORY_ROOT / "theme.tex"

PALETTE_START = re.compile(
    r"^\s*\\newcommand\{\\Use(?P<name>[A-Za-z]+)Theme\}\{%\s*$"
)
TOKEN_DEFINITION = re.compile(
    r"^\s*\\renewcommand\{\\Theme(?P<token>[A-Za-z]+)\}"
    r"\{(?P<value>[0-9A-Fa-f]{6})\}%\s*$"
)

EXPECTED_THEMES = {"ocean", "forest", "plum", "graphite"}
REQUIRED_TOKENS = {
    "Accent",
    "AccentStrong",
    "AccentSoft",
    "AccentSurface",
    "Secondary",
    "SecondarySoft",
    "Ink",
    "Muted",
    "Subtle",
    "Rule",
    "Surface",
    "SurfaceStrong",
    "Paper",
    "Link",
    "Gold",
    "Silver",
    "Bronze",
}

# WCAG AA requires 4.50:1 for normal-sized text. Medal chips use a slightly
# stricter project guard because their bold text is only 7.45pt.
NORMAL_TEXT_MIN_CONTRAST = 4.50
MEDAL_TEXT_MIN_CONTRAST = 4.65
MEDAL_BACKGROUND_FOREGROUND_SHARE = 0.11

# These pairs are explicit component contracts in resume-components.tex.
# Decorative rules and borders are intentionally excluded from text contrast.
CORE_SEMANTIC_PAIRS = (
    ("body", "Ink", "Paper"),
    ("muted text", "Muted", "Paper"),
    ("small secondary heading", "Subtle", "Paper"),
    ("entry title", "AccentStrong", "Paper"),
    ("plain link", "Link", "Paper"),
    ("tag chip", "AccentStrong", "AccentSoft"),
    ("role chip", "Secondary", "SecondarySoft"),
    ("link chip", "Link", "AccentSoft"),
    ("organization title", "AccentStrong", "AccentSurface"),
    ("organization detail", "Muted", "AccentSurface"),
)


Rgb = tuple[float, float, float]


def parse_palettes(path: Path) -> dict[str, dict[str, str]]:
    palettes: dict[str, dict[str, str]] = {}
    current_name: str | None = None

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        start = PALETTE_START.fullmatch(line)
        if start:
            if current_name is not None:
                raise ValueError(
                    f"nested theme at {path}:{line_number}: {current_name}"
                )
            current_name = start.group("name").lower()
            if current_name in palettes:
                raise ValueError(
                    f"duplicate theme at {path}:{line_number}: {current_name}"
                )
            palettes[current_name] = {}
            continue

        if current_name is None:
            continue

        token = TOKEN_DEFINITION.fullmatch(line)
        if token:
            token_name = token.group("token")
            if token_name in palettes[current_name]:
                raise ValueError(
                    f"duplicate token at {path}:{line_number}: "
                    f"{current_name}.{token_name}"
                )
            palettes[current_name][token_name] = token.group("value").upper()
        elif line.strip() == "}":
            current_name = None

    if current_name is not None:
        raise ValueError(f"unterminated theme in {path}: {current_name}")
    return palettes


def html_rgb(value: str) -> Rgb:
    red, green, blue = (
        int(value[offset : offset + 2], 16) / 255.0
        for offset in (0, 2, 4)
    )
    return red, green, blue


def xcolor_mix(foreground: Rgb, share: float, background: Rgb) -> Rgb:
    """Model xcolor's `foreground!percent!background` sRGB interpolation."""
    red, green, blue = (
        share * foreground_channel + (1.0 - share) * background_channel
        for foreground_channel, background_channel in zip(foreground, background)
    )
    return red, green, blue


def linear_srgb(channel: float) -> float:
    # WCAG 2.x sRGB transfer function (the current 0.04045 breakpoint).
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: Rgb) -> float:
    red, green, blue = (linear_srgb(channel) for channel in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: Rgb, second: Rgb) -> float:
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


class ThemeContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.palettes = parse_palettes(THEME_PATH)

    def test_parser_finds_every_complete_palette(self) -> None:
        self.assertEqual(EXPECTED_THEMES, set(self.palettes))
        for theme, palette in self.palettes.items():
            with self.subTest(theme=theme):
                self.assertEqual(REQUIRED_TOKENS, set(palette))

    def test_wcag_reference_values(self) -> None:
        self.assertAlmostEqual(
            21.0,
            contrast_ratio(html_rgb("000000"), html_rgb("FFFFFF")),
            places=12,
        )
        mixed = xcolor_mix(
            html_rgb("000000"),
            MEDAL_BACKGROUND_FOREGROUND_SHARE,
            html_rgb("FFFFFF"),
        )
        for channel in mixed:
            self.assertAlmostEqual(0.89, channel, places=12)

    def test_core_semantic_text_pairs_meet_wcag_aa(self) -> None:
        for theme, palette in self.palettes.items():
            for label, foreground_token, background_token in CORE_SEMANTIC_PAIRS:
                ratio = contrast_ratio(
                    html_rgb(palette[foreground_token]),
                    html_rgb(palette[background_token]),
                )
                with self.subTest(theme=theme, pairing=label):
                    self.assertGreaterEqual(
                        ratio,
                        NORMAL_TEXT_MIN_CONTRAST,
                        (
                            f"{theme} {label}: {foreground_token} on "
                            f"{background_token} is {ratio:.4f}:1; expected "
                            f">= {NORMAL_TEXT_MIN_CONTRAST:.2f}:1"
                        ),
                    )

    def test_small_accent_mark_text_meets_wcag_aa(self) -> None:
        for theme, palette in self.palettes.items():
            accent = html_rgb(palette["Accent"])
            background = xcolor_mix(
                accent,
                0.09,
                html_rgb(palette["Paper"]),
            )
            ratio = contrast_ratio(accent, background)
            with self.subTest(theme=theme):
                self.assertGreaterEqual(
                    ratio,
                    NORMAL_TEXT_MIN_CONTRAST,
                    (
                        f"{theme} Accent on Accent!9!Paper is "
                        f"{ratio:.4f}:1; expected "
                        f">= {NORMAL_TEXT_MIN_CONTRAST:.2f}:1"
                    ),
                )

    def test_medal_chips_clear_conservative_small_text_guard(self) -> None:
        for theme, palette in self.palettes.items():
            paper = html_rgb(palette["Paper"])
            for medal in ("Gold", "Silver", "Bronze"):
                foreground = html_rgb(palette[medal])
                background = xcolor_mix(
                    foreground,
                    MEDAL_BACKGROUND_FOREGROUND_SHARE,
                    paper,
                )
                ratio = contrast_ratio(foreground, background)
                with self.subTest(theme=theme, medal=medal):
                    self.assertGreaterEqual(
                        ratio,
                        MEDAL_TEXT_MIN_CONTRAST,
                        (
                            f"{theme} {medal} on {medal}!11!Paper is "
                            f"{ratio:.4f}:1; expected "
                            f">= {MEDAL_TEXT_MIN_CONTRAST:.2f}:1"
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
