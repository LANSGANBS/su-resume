from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

from scripts.fit_resume import (
    FitError,
    _display_path,
    _a4_pixel_dimensions,
    _underfill_only,
    _parse_profiles,
    _poppler_raster_is_usable,
    analyze_pgm,
    analyze_reference_image,
    evaluate_candidate,
    evaluate_compiled_candidate,
    find_duplicate_pages,
    parse_log_counts,
    read_pgm,
    select_profile,
    sha256_file,
    main,
)


def _write_p5(path: Path, width: int, height: int, pixels: bytes) -> None:
    if len(pixels) != width * height:
        raise ValueError("pixel payload does not match image dimensions")
    path.write_bytes(
        b"P5\n# deterministic test fixture\n"
        + f"{width} {height}\n255\n".encode("ascii")
        + pixels
    )


def _png_chunk(name: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(name)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", checksum)


def _write_grayscale_png(
    path: Path, width: int, height: int, pixels: bytes
) -> None:
    if len(pixels) != width * height:
        raise ValueError("pixel payload does not match image dimensions")
    scanlines = b"".join(
        b"\x00" + pixels[row * width : (row + 1) * width]
        for row in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(scanlines))
        + _png_chunk(b"IEND", b"")
    )


class PgmAnalysisTests(unittest.TestCase):
    def test_poppler_font_failures_require_raster_fallback(self) -> None:
        self.assertTrue(_poppler_raster_is_usable(0, ""))
        self.assertFalse(_poppler_raster_is_usable(1, ""))
        for diagnostic in (
            "Syntax Error: Missing language pack for 'Adobe-GB1' mapping",
            "Syntax Error: Unknown font tag 'F1'",
            "Syntax Error: No font in show/space",
        ):
            with self.subTest(diagnostic=diagnostic):
                self.assertFalse(_poppler_raster_is_usable(0, diagnostic))

    def test_a4_fallback_dimensions_match_poppler_rounding(self) -> None:
        self.assertEqual((993, 1404), _a4_pixel_dimensions(120))

    def test_binary_pgm_bbox_and_bottom_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.pgm"
            pixels = bytearray([255] * (6 * 5))
            for y in range(1, 4):
                for x in range(1, 4):
                    pixels[y * 6 + x] = 0
            _write_p5(path, 6, 5, bytes(pixels))

            metrics = analyze_pgm(path, dpi=25, white_threshold=250)

            self.assertEqual(metrics["bbox_px"], [1, 1, 3, 3])
            self.assertEqual(metrics["nonwhite_pixels"], 9)
            self.assertEqual(metrics["bottom_whitespace_px"], 1)
            self.assertAlmostEqual(metrics["bottom_whitespace_mm"], 1.016)
            self.assertAlmostEqual(metrics["content_fill_ratio"], 0.6)
            self.assertFalse(metrics["blank"])

    def test_ascii_pgm_comments_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.pgm"
            path.write_text(
                "P2\n# before dimensions\n4 3\n# before maximum\n15\n"
                "15 15 15 15\n15 0 0 15\n15 15 15 15\n",
                encoding="ascii",
            )

            width, height, maximum, pixels = read_pgm(path)
            metrics = analyze_pgm(path, dpi=100, white_threshold=250)

            self.assertEqual((width, height, maximum), (4, 3, 15))
            self.assertEqual(len(pixels), 12)
            self.assertEqual(metrics["bbox_px"], [1, 1, 2, 1])

    def test_blank_and_duplicate_pages_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blank = root / "blank.pgm"
            ink_a = root / "ink-a.pgm"
            ink_b = root / "ink-b.pgm"
            _write_p5(blank, 3, 2, bytes([255] * 6))
            _write_p5(ink_a, 3, 2, bytes([255, 0, 255, 255, 255, 255]))
            _write_p5(ink_b, 3, 2, bytes([255, 0, 255, 255, 255, 255]))

            metrics = [
                analyze_pgm(path, dpi=100, white_threshold=250)
                for path in (ink_a, ink_b, blank)
            ]

            self.assertEqual(find_duplicate_pages(metrics), [[1, 2]])
            self.assertTrue(metrics[2]["blank"])
            self.assertIsNone(metrics[2]["bbox_px"])

    def test_png_reference_uses_the_same_bbox_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.png"
            _write_grayscale_png(
                path,
                4,
                3,
                bytes(
                    [
                        255,
                        255,
                        255,
                        255,
                        255,
                        0,
                        0,
                        255,
                        255,
                        255,
                        255,
                        255,
                    ]
                ),
            )

            metrics = analyze_reference_image(path, dpi=100, white_threshold=250)

            self.assertEqual(metrics["bbox_px"], [1, 1, 2, 1])
            self.assertEqual(metrics["nonwhite_pixels"], 2)


class CandidatePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = {
            "target_pages": 1,
            "max_underfull": 4,
            "max_bottom_whitespace_mm": 22.0,
            "min_page_fill_ratio": 0.62,
            "max_page_fill_spread": 0.22,
            "max_bottom_whitespace_spread_mm": 25.0,
        }

    @staticmethod
    def candidate(
        profile: str,
        *,
        pages: int = 1,
        bottom_mm: float = 10.0,
        fill: float = 0.8,
        blank: bool = False,
        overfull: int = 0,
    ) -> dict[str, object]:
        return {
            "profile": profile,
            "page_fill_mode": "natural",
            "returncode": 0,
            "pages": pages,
            "log_counts": {
                "errors": 0,
                "overfull": overfull,
                "underfull": 0,
                "missing_glyph": 0,
            },
            "page_metrics": [
                {
                    "blank": blank,
                    "bottom_whitespace_mm": bottom_mm,
                    "content_fill_ratio": fill,
                    "pixel_sha256": profile,
                }
                for _ in range(pages)
            ],
            "duplicate_page_pairs": [],
            "page_balance": {
                "page_fill_spread": 0.0,
                "bottom_whitespace_spread_mm": 0.0,
            },
            "eligible": False,
            "rejection_reasons": [],
        }

    def make_eligible(self, candidate: dict[str, object]) -> None:
        reasons = evaluate_candidate(candidate, self.thresholds)
        candidate["rejection_reasons"] = reasons
        candidate["eligible"] = not reasons

    def test_balanced_is_selected_when_reference_passes(self) -> None:
        candidates = [
            self.candidate("balanced"),
            self.candidate("airy"),
            self.candidate("compact"),
            self.candidate("dense"),
        ]
        for candidate in candidates:
            self.make_eligible(candidate)

        selected, order, reason = select_profile(candidates, target_pages=1)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["profile"], "balanced")
        self.assertEqual(order, ["balanced"])
        self.assertEqual(reason, "balanced_reference_passed")

    def test_underfilled_reference_falls_back_to_airy(self) -> None:
        candidates = [
            self.candidate("balanced", bottom_mm=45.0, fill=0.55),
            self.candidate("airy"),
            self.candidate("compact"),
            self.candidate("dense"),
        ]
        for candidate in candidates:
            self.make_eligible(candidate)

        selected, order, reason = select_profile(candidates, target_pages=1)

        self.assertEqual(selected["profile"], "airy")
        self.assertEqual(order, ["balanced", "airy", "compact", "dense"])
        self.assertEqual(reason, "reference_under_target_or_underfilled")

    def test_overflowing_reference_falls_back_to_compact(self) -> None:
        candidates = [
            self.candidate("balanced", pages=2),
            self.candidate("airy", pages=2),
            self.candidate("compact"),
            self.candidate("dense"),
        ]
        for candidate in candidates:
            self.make_eligible(candidate)

        selected, order, reason = select_profile(candidates, target_pages=1)

        self.assertEqual(selected["profile"], "compact")
        self.assertEqual(order, ["balanced", "compact", "dense", "airy"])
        self.assertEqual(reason, "reference_over_target_or_overflow")

    def test_abnormal_pagination_blank_and_duplicates_are_rejected(self) -> None:
        candidate = self.candidate("balanced", pages=2, blank=True)
        candidate["duplicate_page_pairs"] = [[1, 2]]

        reasons = evaluate_candidate(candidate, self.thresholds)

        self.assertIn("page_count:2!=1", reasons)
        self.assertIn("blank_pages:1,2", reasons)
        self.assertIn("duplicate_pages:1-2", reasons)

    def test_imbalanced_two_page_candidate_is_rejected_and_prefers_airy(self) -> None:
        self.thresholds["target_pages"] = 2
        balanced = self.candidate("balanced", pages=2)
        balanced["page_metrics"][0]["content_fill_ratio"] = 0.92
        balanced["page_metrics"][1]["content_fill_ratio"] = 0.63
        balanced["page_metrics"][0]["bottom_whitespace_mm"] = 12.0
        balanced["page_metrics"][1]["bottom_whitespace_mm"] = 48.0
        balanced["page_balance"] = {
            "page_fill_spread": 0.29,
            "bottom_whitespace_spread_mm": 36.0,
        }
        candidates = [
            balanced,
            self.candidate("airy", pages=2),
            self.candidate("compact", pages=2),
            self.candidate("dense", pages=2),
        ]
        for candidate in candidates:
            self.make_eligible(candidate)

        self.assertIn(
            "page_fill_spread:0.290000>0.220000",
            balanced["rejection_reasons"],
        )
        self.assertIn(
            "bottom_whitespace_spread_mm:36.000>25.000",
            balanced["rejection_reasons"],
        )
        selected, order, reason = select_profile(candidates, target_pages=2)
        self.assertEqual(selected["profile"], "airy")
        self.assertEqual(order, ["balanced", "airy", "compact", "dense"])
        self.assertEqual(reason, "reference_under_target_or_underfilled")

    def test_elastic_candidate_rejects_any_underfull_box(self) -> None:
        self.thresholds["target_pages"] = 2
        candidate = self.candidate("balanced", pages=2)
        candidate["page_fill_mode"] = "elastic"
        candidate["log_counts"]["underfull"] = 1

        reasons = evaluate_compiled_candidate(candidate, self.thresholds)

        self.assertIn("elastic_underfull_boxes:1>0", reasons)

    def test_log_event_parser_counts_layout_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resume.log"
            path.write_text(
                "Overfull \\hbox (2.0pt too wide)\n"
                "Underfull \\vbox (badness 10000)\n"
                "Missing character: There is no 字\n"
                "! Undefined control sequence.\n",
                encoding="utf-8",
            )

            counts = parse_log_counts([path])

            self.assertEqual(
                counts,
                {
                    "overfull": 1,
                    "underfull": 1,
                    "missing_glyph": 1,
                    "errors": 1,
                },
            )


class ManifestShapeTests(unittest.TestCase):
    def test_example_manifest_values_are_json_serializable(self) -> None:
        payload = {
            "schema_version": 1,
            "selection_policy": "balanced-reference-v1",
            "selection_reason": "balanced_reference_passed",
            "selection_order": ["balanced"],
        }
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_reference_policy_requires_all_four_profiles(self) -> None:
        with self.assertRaises(FitError):
            _parse_profiles(["balanced", "compact", "dense"])
        self.assertEqual(
            _parse_profiles(["dense", "balanced", "airy", "compact"]),
            ["dense", "balanced", "airy", "compact"],
        )

    def test_external_manifest_paths_remain_locatable(self) -> None:
        with tempfile.TemporaryDirectory() as repository:
            with tempfile.TemporaryDirectory() as outside:
                external = Path(outside) / "resume.pdf"
                rendered = _display_path(external, Path(repository))
        self.assertEqual(rendered, external.resolve().as_posix())

    def test_underfill_classifier_rejects_non_layout_failures(self) -> None:
        self.assertTrue(
            _underfill_only(
                [
                    "page_1_bottom_whitespace_mm:30.000>22.000",
                    "page_fill_spread:0.300000>0.220000",
                ]
            )
        )
        self.assertFalse(
            _underfill_only(
                [
                    "page_1_bottom_whitespace_mm:30.000>22.000",
                    "overfull_boxes:1",
                ]
            )
        )

    def test_failed_rerun_removes_stale_final_pdf_and_records_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "content.tex"
            content.write_text("immutable content\n", encoding="utf-8")
            output = root / "output"
            output.mkdir()
            stale = output / "resume-ocean-fit.pdf"
            stale.write_bytes(b"old successful PDF")
            unrelated = output / "keep.txt"
            unrelated.write_text("keep", encoding="utf-8")
            manifest_path = output / "manifest.json"

            def failed_candidate(**kwargs: object) -> dict[str, object]:
                return {
                    "profile": kwargs["profile"],
                    "page_fill_mode": kwargs["page_fill_mode"],
                    "returncode": 1,
                    "render_returncode": None,
                    "raster_error": None,
                    "pdf": None,
                    "_pdf_path": None,
                    "pages": None,
                    "log_counts": {
                        "errors": 1,
                        "overfull": 0,
                        "underfull": 0,
                        "missing_glyph": 0,
                    },
                    "page_metrics": [],
                    "page_balance": {
                        "page_fill_spread": 0.0,
                        "bottom_whitespace_spread_mm": 0.0,
                    },
                    "duplicate_page_pairs": [],
                    "eligible": False,
                    "rejection_reasons": [],
                }

            with mock.patch(
                "scripts.fit_resume._check_dependencies"
            ), mock.patch(
                "scripts.fit_resume.compile_candidate",
                side_effect=failed_candidate,
            ):
                returncode = main(
                    [
                        "--content",
                        str(content),
                        "--output-dir",
                        str(output),
                        "--manifest",
                        str(manifest_path),
                    ]
                )

            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(returncode, 1)
            self.assertFalse(stale.exists())
            self.assertTrue(unrelated.is_file())
            self.assertFalse(payload["success"])
            self.assertIsNone(payload["selected_pdf"])
            self.assertEqual(payload["selection_detail"], "no_eligible_candidate")
            self.assertEqual(
                payload["inputs"]["content_sha256"], sha256_file(content)
            )
            for key in (
                "content_sha256",
                "entrypoint_sha256",
                "layout_sha256",
                "theme_sha256",
            ):
                self.assertRegex(payload["inputs"][key], r"^[0-9a-f]{64}$")
            components = (
                Path(__file__).resolve().parent.parent / "resume-components.tex"
            )
            if components.is_file():
                self.assertRegex(
                    payload["inputs"]["components_sha256"],
                    r"^[0-9a-f]{64}$",
                )
            else:
                self.assertIsNone(payload["inputs"]["components_sha256"])

    def test_balanced_elastic_recovers_exact_two_page_underfill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "content.tex"
            content.write_text("immutable two-page content\n", encoding="utf-8")
            output = root / "output"
            manifest_path = output / "manifest.json"

            def candidate(
                *,
                profile: str,
                page_fill_mode: str,
                output_dir: Path,
                **_: object,
            ) -> dict[str, object]:
                name = (
                    profile
                    if page_fill_mode == "natural"
                    else f"{profile}-{page_fill_mode}"
                )
                candidate_dir = output_dir / name
                candidate_dir.mkdir(parents=True, exist_ok=True)
                pdf_path = candidate_dir / f"{name}.pdf"
                pdf_path.write_bytes(name.encode("ascii"))
                if profile == "balanced" and page_fill_mode == "natural":
                    page_values = [
                        (54.822, 0.758547),
                        (39.793, 0.821225),
                    ]
                    pages = 2
                elif profile == "balanced" and page_fill_mode == "elastic":
                    page_values = [
                        (18.415, 0.881054),
                        (15.028, 0.904558),
                    ]
                    pages = 2
                else:
                    page_values = [(10.0, 0.90)] * 3
                    pages = 3
                bottom_values = [value[0] for value in page_values]
                fill_values = [value[1] for value in page_values]
                return {
                    "profile": profile,
                    "page_fill_mode": page_fill_mode,
                    "returncode": 0,
                    "render_returncode": 0,
                    "raster_error": None,
                    "pdf": pdf_path.as_posix(),
                    "_pdf_path": pdf_path.as_posix(),
                    "pages": pages,
                    "log_counts": {
                        "errors": 0,
                        "overfull": 0,
                        "underfull": 0,
                        "missing_glyph": 0,
                    },
                    "page_metrics": [
                        {
                            "blank": False,
                            "bottom_whitespace_mm": bottom,
                            "content_fill_ratio": fill,
                            "pixel_sha256": f"{name}-{index}",
                        }
                        for index, (bottom, fill) in enumerate(page_values)
                    ],
                    "page_balance": {
                        "page_fill_spread": round(
                            max(fill_values) - min(fill_values), 6
                        ),
                        "bottom_whitespace_spread_mm": round(
                            max(bottom_values) - min(bottom_values), 3
                        ),
                    },
                    "duplicate_page_pairs": [],
                    "eligible": False,
                    "rejection_reasons": [],
                }

            with mock.patch(
                "scripts.fit_resume._check_dependencies"
            ), mock.patch(
                "scripts.fit_resume.compile_candidate",
                side_effect=candidate,
            ):
                returncode = main(
                    [
                        "--content",
                        str(content),
                        "--target-pages",
                        "2",
                        "--output-dir",
                        str(output),
                        "--manifest",
                        str(manifest_path),
                    ]
                )

            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(returncode, 0)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["selected_profile"], "balanced")
            self.assertEqual(payload["selected_page_fill_mode"], "elastic")
            self.assertEqual(
                payload["selection_reason"],
                "reference_under_target_or_underfilled",
            )
            self.assertEqual(
                payload["selection_order"],
                ["balanced", "airy", "compact", "dense"],
            )
            self.assertEqual(
                payload["selection_detail"],
                "balanced_elastic_underfill_recovery",
            )
            self.assertEqual(
                payload["attempted_page_fill_modes"], ["natural", "elastic"]
            )
            self.assertEqual(
                [
                    attempt["page_fill_mode"]
                    for attempt in payload["page_fill_attempts"]
                ],
                ["natural", "elastic"],
            )
            self.assertTrue(
                payload["page_fill_attempts"][0]["rejection_reasons"]
            )
            self.assertEqual(
                payload["page_fill_attempts"][1]["rejection_reasons"], []
            )
            selected = next(
                candidate
                for candidate in payload["candidates"]
                if candidate["profile"] == "balanced"
            )
            self.assertEqual(selected["page_fill_mode"], "elastic")
            self.assertEqual(
                (output / "resume-ocean-fit.pdf").read_bytes(),
                b"balanced-elastic",
            )

    def test_eligible_natural_profile_suppresses_elastic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "content.tex"
            content.write_text("immutable two-page content\n", encoding="utf-8")
            output = root / "output"
            manifest_path = output / "manifest.json"
            calls: list[tuple[str, str]] = []

            def candidate(
                *,
                profile: str,
                page_fill_mode: str,
                output_dir: Path,
                **_: object,
            ) -> dict[str, object]:
                calls.append((profile, page_fill_mode))
                name = (
                    profile
                    if page_fill_mode == "natural"
                    else f"{profile}-{page_fill_mode}"
                )
                candidate_dir = output_dir / name
                candidate_dir.mkdir(parents=True, exist_ok=True)
                pdf_path = candidate_dir / f"{name}.pdf"
                pdf_path.write_bytes(name.encode("ascii"))
                if profile == "balanced":
                    page_values = [
                        (54.822, 0.758547),
                        (39.793, 0.821225),
                    ]
                    pages = 2
                elif profile == "airy":
                    page_values = [
                        (18.0, 0.89),
                        (16.5, 0.90),
                    ]
                    pages = 2
                else:
                    page_values = [(10.0, 0.90)] * 3
                    pages = 3
                bottom_values = [value[0] for value in page_values]
                fill_values = [value[1] for value in page_values]
                return {
                    "profile": profile,
                    "page_fill_mode": page_fill_mode,
                    "returncode": 0,
                    "render_returncode": 0,
                    "raster_error": None,
                    "pdf": pdf_path.as_posix(),
                    "_pdf_path": pdf_path.as_posix(),
                    "pages": pages,
                    "log_counts": {
                        "errors": 0,
                        "overfull": 0,
                        "underfull": 0,
                        "missing_glyph": 0,
                    },
                    "page_metrics": [
                        {
                            "blank": False,
                            "bottom_whitespace_mm": bottom,
                            "content_fill_ratio": fill,
                            "pixel_sha256": f"{name}-{index}",
                        }
                        for index, (bottom, fill) in enumerate(page_values)
                    ],
                    "page_balance": {
                        "page_fill_spread": round(
                            max(fill_values) - min(fill_values), 6
                        ),
                        "bottom_whitespace_spread_mm": round(
                            max(bottom_values) - min(bottom_values), 3
                        ),
                    },
                    "duplicate_page_pairs": [],
                    "eligible": False,
                    "rejection_reasons": [],
                }

            with mock.patch(
                "scripts.fit_resume._check_dependencies"
            ), mock.patch(
                "scripts.fit_resume.compile_candidate",
                side_effect=candidate,
            ):
                returncode = main(
                    [
                        "--content",
                        str(content),
                        "--target-pages",
                        "2",
                        "--output-dir",
                        str(output),
                        "--manifest",
                        str(manifest_path),
                    ]
                )

            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(returncode, 0)
            self.assertEqual(payload["selected_profile"], "airy")
            self.assertEqual(payload["selected_page_fill_mode"], "natural")
            self.assertEqual(payload["attempted_page_fill_modes"], ["natural"])
            self.assertEqual(payload["page_fill_attempts"], [])
            self.assertNotIn(("balanced", "elastic"), calls)
            self.assertEqual(
                (output / "resume-ocean-fit.pdf").read_bytes(),
                b"airy",
            )

    def test_fatal_rerun_clears_stale_final_pdf_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "content.tex"
            content.write_text("immutable content\n", encoding="utf-8")
            output = root / "output"
            output.mkdir()
            fitted_pdf = output / "resume-ocean-fit.pdf"
            fitted_pdf.write_bytes(b"stale PDF")
            manifest_path = output / "manifest.json"
            manifest_path.write_text('{"success": true}\n', encoding="utf-8")

            with mock.patch(
                "scripts.fit_resume._check_dependencies"
            ), mock.patch(
                "scripts.fit_resume.compile_candidate",
                side_effect=FitError("simulated fatal compile setup failure"),
            ):
                returncode = main(
                    [
                        "--content",
                        str(content),
                        "--output-dir",
                        str(output),
                        "--manifest",
                        str(manifest_path),
                    ]
                )

            self.assertEqual(returncode, 2)
            self.assertFalse(fitted_pdf.exists())
            self.assertFalse(manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
