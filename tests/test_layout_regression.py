from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.fit_resume import analyze_reference_image
from scripts.test_layouts import (
    RegressionError,
    _display_path,
    _evaluate_same_page_marker_groups,
    _geometry_failures,
    _jobs_from_config,
    _load_json,
    _parse_aux_marker_pages,
    _preflight_fixtures,
    _reference_comparison,
    _reference_failures,
    _same_page_marker_comparison,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class LayoutRegressionConfigTests(unittest.TestCase):
    def test_config_and_fit_manifests_use_independent_schema_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fit_manifest = root / "fit-manifest.json"
            config.write_text('{"schema_version": 1}', encoding="utf-8")
            fit_manifest.write_text('{"schema_version": 2}', encoding="utf-8")

            self.assertEqual(
                1,
                _load_json(config, schema_version=1)["schema_version"],
            )
            self.assertEqual(
                2,
                _load_json(fit_manifest, schema_version=2)["schema_version"],
            )
            with self.assertRaises(RegressionError):
                _load_json(fit_manifest, schema_version=1)

    def test_theme_matrix_expands_while_fixtures_keep_ocean(self) -> None:
        jobs = _jobs_from_config(
            {
                "theme_matrix": {
                    "id": "default",
                    "content": "content.tex",
                    "themes": ["ocean", "forest"],
                },
                "cases": [
                    {
                        "id": "long",
                        "content": "examples/content-long.tex",
                        "target_pages": 2,
                    }
                ],
            }
        )

        self.assertEqual(
            [(job["id"], job["theme"]) for job in jobs],
            [
                ("default-ocean", "ocean"),
                ("default-forest", "forest"),
                ("long", "ocean"),
            ],
        )

    def test_missing_fixtures_are_reported_together(self) -> None:
        jobs = [
            {
                "id": "undergrad",
                "content": "examples/content-undergrad.tex",
                "theme": "ocean",
            },
            {
                "id": "long",
                "content": "examples/content-long.tex",
                "theme": "ocean",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RegressionError) as context:
                _preflight_fixtures(jobs, Path(directory))

        message = str(context.exception)
        self.assertIn("undergrad: examples/content-undergrad.tex", message)
        self.assertIn("long: examples/content-long.tex", message)

    def test_public_theme_matrix_requires_shape_references_for_all_themes(
        self,
    ) -> None:
        config = json.loads(
            (REPO_ROOT / "examples" / "layout-cases.json").read_text(
                encoding="utf-8"
            )
        )
        default_jobs = [
            job
            for job in _jobs_from_config(config)
            if job["kind"] == "theme_matrix"
        ]

        self.assertEqual(
            ["ocean", "forest", "plum", "graphite"],
            [job["theme"] for job in default_jobs],
        )
        for job in default_jobs:
            with self.subTest(theme=job["theme"]):
                reference = job.get("reference")
                self.assertIsInstance(reference, dict)
                self.assertEqual(
                    "assets/previews/theme-{theme}.png",
                    reference["image"],
                )
                self.assertEqual("shape", reference["comparison_mode"])
                self.assertNotIn("max_pixel_changed_ratio", reference)
                self.assertNotIn(
                    "max_pixel_mean_absolute_difference", reference
                )

    def test_output_paths_outside_repository_do_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as repository:
            with tempfile.TemporaryDirectory() as outside:
                rendered = _display_path(
                    Path(outside) / "manifest.json", Path(repository)
                )
        self.assertTrue(rendered.endswith("/manifest.json"))


class LayoutReferenceGateTests(unittest.TestCase):
    thresholds = {"dpi": 120, "white_threshold": 250}

    @staticmethod
    def _write_reference(path: Path, *, width: int = 10, height: int = 12) -> None:
        pixels = bytearray([255] * (width * height))
        for y in range(2, height - 2):
            for x in range(2, width - 2):
                pixels[y * width + x] = 0
        path.write_bytes(
            f"P5\n{width} {height}\n255\n".encode("ascii") + bytes(pixels)
        )

    @staticmethod
    def _job(reference: Path) -> dict[str, object]:
        return {
            "id": "default-ocean",
            "theme": "ocean",
            "reference": {
                "image": str(reference),
                "page": 1,
                "comparison_mode": "shape",
                "page_dimension_tolerance_px": 0,
                "bbox_edge_tolerance_ratio": 0.01,
                "content_fill_tolerance": 0.01,
                "ink_fill_tolerance": 0.01,
            },
        }

    def test_reference_shape_comparison_passes_and_records_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.pgm"
            self._write_reference(reference)
            metrics = analyze_reference_image(
                reference, dpi=120, white_threshold=250
            )

            failures = _reference_failures(
                job=self._job(reference),
                repo_root=root,
                selected_pages=[metrics],
                thresholds=self.thresholds,
            )
            comparison = _reference_comparison(
                job=self._job(reference),
                repo_root=root,
                selected_pages=[metrics],
                thresholds=self.thresholds,
            )

        self.assertEqual([], failures)
        assert comparison is not None
        self.assertEqual("passed", comparison["result"])
        self.assertEqual("shape", comparison["comparison_mode"])
        self.assertEqual(1, comparison["page"])
        self.assertEqual("reference.pgm", comparison["path"])
        self.assertRegex(comparison["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            {"width": 0, "height": 0},
            comparison["measured_drifts"]["page_dimensions_px"],
        )
        self.assertEqual(
            0.0, comparison["measured_drifts"]["content_fill_ratio"]
        )
        self.assertEqual(
            0.0, comparison["measured_drifts"]["ink_fill_ratio"]
        )

    def test_reference_shape_comparison_fails_on_geometry_and_ink_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.pgm"
            self._write_reference(reference)
            metrics = analyze_reference_image(
                reference, dpi=120, white_threshold=250
            )
            candidate = dict(metrics)
            candidate["bbox_px"] = [0, 0, 9, 11]
            candidate["content_fill_ratio"] = 1.0
            candidate["ink_fill_ratio"] = 1.0

            failures = _reference_failures(
                job=self._job(reference),
                repo_root=root,
                selected_pages=[candidate],
                thresholds=self.thresholds,
            )

        self.assertTrue(
            any("reference_bbox_left_ratio" in failure for failure in failures)
        )
        self.assertTrue(
            any("reference_content_fill_ratio" in failure for failure in failures)
        )
        self.assertTrue(
            any("reference_ink_fill_ratio" in failure for failure in failures)
        )

    def test_missing_reference_image_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.png"
            failures = _reference_failures(
                job=self._job(missing),
                repo_root=root,
                selected_pages=[
                    {
                        "width_px": 10,
                        "height_px": 12,
                        "bbox_px": [2, 2, 7, 9],
                        "content_fill_ratio": 0.666667,
                        "ink_fill_ratio": 0.4,
                    }
                ],
                thresholds=self.thresholds,
            )

        self.assertTrue(
            any("reference image is unavailable" in failure for failure in failures)
        )

    def test_corrupt_reference_image_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / "corrupt.png"
            corrupt.write_bytes(b"not a png")
            failures = _reference_failures(
                job=self._job(corrupt),
                repo_root=root,
                selected_pages=[
                    {
                        "width_px": 10,
                        "height_px": 12,
                        "bbox_px": [2, 2, 7, 9],
                        "content_fill_ratio": 0.666667,
                        "ink_fill_ratio": 0.4,
                    }
                ],
                thresholds=self.thresholds,
            )

        self.assertTrue(
            any("reference image is invalid" in failure for failure in failures)
        )

    def test_reference_dimension_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.pgm"
            self._write_reference(reference)
            candidate = analyze_reference_image(
                reference, dpi=120, white_threshold=250
            )
            candidate["width_px"] = 20

            failures = _reference_failures(
                job=self._job(reference),
                repo_root=root,
                selected_pages=[candidate],
                thresholds=self.thresholds,
            )

        self.assertTrue(
            any("reference_width_px drift:10>0" in failure for failure in failures)
        )


class SamePageMarkerGateTests(unittest.TestCase):
    groups = [
        {
            "id": "organization-band",
            "markers": ["fixture-organization-band", "fixture-first-item"],
        }
    ]

    def test_realistic_hyperref_aux_with_nested_and_escaped_braces_parses(
        self,
    ) -> None:
        marker_pages = _parse_aux_marker_pages(
            r"""
            \relax
            % \newlabel{resume-page-marker:commented}{{}{9}}
            \newlabel{ordinary-label}{{Nested {title} with \{braces\}}{7}}
            \newlabel{resume-page-marker:fixture-organization-band}%
              {{Nested {title} with \{literal braces\}}{2}{}{section*.4}{}}
            \newlabel{resume-page-marker:fixture-first-item}{{}{2}{}{Item.8}{}}
            """
        )

        self.assertEqual(
            {
                "fixture-organization-band": [2],
                "fixture-first-item": [2],
            },
            marker_pages,
        )

    def test_selected_candidate_aux_markers_on_same_shipped_page_pass(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_dir = root / "balanced-elastic"
            candidate_dir.mkdir()
            aux = candidate_dir / "resume-ocean-balanced-elastic.aux"
            aux.write_text(
                "\n".join(
                    [
                        r"\relax",
                        (
                            r"\newlabel{resume-page-marker:"
                            r"fixture-organization-band}{{}{2}{}{Doc-Start}{}}"
                        ),
                        (
                            r"\newlabel{resume-page-marker:"
                            r"fixture-first-item}{{}{2}{}{Item.1}{}}"
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            report = _same_page_marker_comparison(
                job={
                    "id": "fixture",
                    "same_page_markers": self.groups,
                },
                repo_root=root,
                selected_candidate={
                    "pdf": (
                        "balanced-elastic/"
                        "resume-ocean-balanced-elastic.pdf"
                    ),
                    "pages": 2,
                },
            )

        assert report is not None
        self.assertEqual("passed", report["result"])
        self.assertEqual(
            "balanced-elastic/resume-ocean-balanced-elastic.aux",
            report["aux"],
        )
        self.assertEqual(2, report["groups"][0]["common_page"])
        self.assertEqual([], report["failures"])

    def test_markers_on_different_shipped_pages_fail(self) -> None:
        report = _evaluate_same_page_marker_groups(
            job_id="fixture",
            marker_pages={
                "fixture-organization-band": [1],
                "fixture-first-item": [2],
            },
            groups=self.groups,
            page_count=2,
        )

        assert report is not None
        self.assertEqual("failed", report["result"])
        self.assertTrue(
            any(
                "different pages" in failure
                for failure in report["failures"]
            )
        )

    def test_missing_marker_fails(self) -> None:
        report = _evaluate_same_page_marker_groups(
            job_id="fixture",
            marker_pages={"fixture-organization-band": [1]},
            groups=self.groups,
            page_count=2,
        )

        assert report is not None
        self.assertEqual("failed", report["result"])
        self.assertTrue(
            any("is missing" in failure for failure in report["failures"])
        )

    def test_duplicate_aux_marker_fails_even_when_both_copies_share_page(
        self,
    ) -> None:
        report = _evaluate_same_page_marker_groups(
            job_id="fixture",
            marker_pages={
                "fixture-organization-band": [1, 1],
                "fixture-first-item": [1],
            },
            groups=self.groups,
            page_count=2,
        )

        assert report is not None
        self.assertEqual("failed", report["result"])
        self.assertTrue(
            any("is duplicated" in failure for failure in report["failures"])
        )

    def test_duplicate_or_unsafe_config_marker_is_rejected(self) -> None:
        duplicate = _evaluate_same_page_marker_groups(
            job_id="fixture",
            marker_pages={"same": [1]},
            groups=[{"id": "bad", "markers": ["same", "same"]}],
            page_count=1,
        )
        unsafe = _evaluate_same_page_marker_groups(
            job_id="fixture",
            marker_pages={},
            groups=[
                {
                    "id": "bad",
                    "markers": ["safe-marker", r"unsafe{marker}"],
                }
            ],
            page_count=1,
        )

        assert duplicate is not None
        assert unsafe is not None
        self.assertTrue(
            any(
                "must not contain duplicates" in failure
                for failure in duplicate["failures"]
            )
        )
        self.assertTrue(
            any(
                "safe marker keys" in failure
                for failure in unsafe["failures"]
            )
        )

    def test_marker_page_must_exist_in_selected_pdf(self) -> None:
        report = _evaluate_same_page_marker_groups(
            job_id="fixture",
            marker_pages={
                "fixture-organization-band": [3],
                "fixture-first-item": [3],
            },
            groups=self.groups,
            page_count=2,
        )

        assert report is not None
        self.assertTrue(
            any("outside 1..2" in failure for failure in report["failures"])
        )

    def test_non_numeric_aux_page_is_rejected(self) -> None:
        with self.assertRaisesRegex(RegressionError, "non-numeric shipped page"):
            _parse_aux_marker_pages(
                r"\newlabel{resume-page-marker:bad}{{}{ii}{}{Doc-Start}{}}"
            )


class LayoutGeometryGateTests(unittest.TestCase):
    @staticmethod
    def page_metrics() -> dict[str, object]:
        return {
            "width_px": 993,
            "height_px": 1404,
            "bbox_px": [56, 48, 935, 1328],
            "content_fill_ratio": 0.912,
            "bottom_whitespace_mm": 15.8,
            "left_whitespace_mm": 11.9,
            "right_whitespace_mm": 12.1,
        }

    def test_reference_bbox_and_a4_geometry_pass_within_tolerance(self) -> None:
        failures = _geometry_failures(
            job_id="default-ocean",
            pages=[self.page_metrics()],
            geometry={
                "page_width_px": 993,
                "page_height_px": 1404,
                "page_dimension_tolerance_px": 2,
                "bbox_ratio": [0.0564, 0.0342, 0.9416, 0.946],
                "bbox_edge_tolerance_ratio": 0.01,
                "content_fill_ratio": [0.8, 0.98],
                "bottom_whitespace_mm": [5, 25],
                "max_side_whitespace_mm": 20,
            },
        )

        self.assertEqual(failures, [])

    def test_geometry_drift_is_actionable(self) -> None:
        metrics = self.page_metrics()
        metrics["width_px"] = 1040
        metrics["content_fill_ratio"] = 0.5

        failures = _geometry_failures(
            job_id="default-ocean",
            pages=[metrics],
            geometry={
                "page_width_px": 993,
                "page_dimension_tolerance_px": 2,
                "content_fill_ratio": [0.8, 0.98],
            },
        )

        self.assertTrue(any("width_px drift" in failure for failure in failures))
        self.assertTrue(
            any("content_fill_ratio" in failure for failure in failures)
        )


if __name__ == "__main__":
    unittest.main()
