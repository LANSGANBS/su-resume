from __future__ import annotations

import copy
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import zlib


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
SKILL_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import privacy_audit  # noqa: E402
import validate_fact_ledger  # noqa: E402
import validate_fit_manifest  # noqa: E402
import validate_resume  # noqa: E402
import validate_text_parity  # noqa: E402


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", checksum)
    )


def minimal_png(extra_chunks=()) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    image_data = zlib.compress(b"\x00\x00\x00\x00\x00")
    return (
        privacy_audit.PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + b"".join(extra_chunks)
        + png_chunk(b"IDAT", image_data)
        + png_chunk(b"IEND", b"")
    )


class PrivacyAuditTests(unittest.TestCase):
    def test_reserved_placeholders_are_safe(self) -> None:
        text = "Contact: candidate" + "@example.com " + "https" + "://example.com"
        findings = privacy_audit.scan_text(
            text, "content.tex", {"github.com"}, []
        )
        self.assertEqual([], findings)

    def test_sensitive_values_are_redacted(self) -> None:
        private_email = "candidate" + "@" + "sample.test"
        private_address = "10" + ".0.0.1"
        private_phone = "139" + " 1111 " + "2222"
        international_phone = "+1 (" + "202) 555-0198"
        government_id = "123" + "-45-" + "6789"
        text = (
            f"{private_email}\n{private_address}\n{private_phone}\n"
            f"{international_phone}\n{government_id}\n"
            "private-codename"
        )
        findings = privacy_audit.scan_text(
            text,
            "content.tex",
            set(),
            [(1, "private-codename")],
        )
        categories = {finding.category for finding in findings}
        self.assertIn("personal_email", categories)
        self.assertIn("personal_phone", categories)
        self.assertIn("government_id", categories)
        self.assertIn("private_network_address", categories)
        self.assertIn("private_deny_term_line_1", categories)
        for finding in findings:
            self.assertIn("[REDACTED]", finding.snippet)
            self.assertNotIn(private_email, finding.snippet)
            self.assertNotIn(private_address, finding.snippet)
            self.assertNotIn(private_phone, finding.snippet)
            self.assertNotIn(international_phone, finding.snippet)
            self.assertNotIn(government_id, finding.snippet)

    def test_non_dialable_phone_placeholder_is_safe(self) -> None:
        placeholder = "(+86) 1XX XXXX XXXX"
        findings = privacy_audit.scan_text(
            placeholder, "content.tex", set(), []
        )
        self.assertEqual([], findings)

    def test_fully_numeric_example_phone_is_not_exempt(self) -> None:
        dialable = "138" + " 0000 " + "0000"
        findings = privacy_audit.scan_text(
            dialable, "content.tex", set(), []
        )
        self.assertIn(
            "personal_phone", {finding.category for finding in findings}
        )

    def test_version_number_is_not_mistaken_for_phone(self) -> None:
        version_banner = "XeTeX Version 3.14159" + "2653-2.6-0.999998"
        findings = privacy_audit.scan_text(
            version_banner,
            "build.log",
            set(),
            [],
        )
        self.assertNotIn(
            "personal_phone",
            {finding.category for finding in findings},
        )

    def test_github_private_email_is_allowed(self) -> None:
        findings = privacy_audit.scan_text(
            "noreply@github.com 123+user@users.noreply.github.com",
            "metadata.txt",
            set(),
            [],
        )
        self.assertNotIn(
            "personal_email",
            {finding.category for finding in findings},
        )

    def test_clean_png_is_inspected_and_text_metadata_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clean = root / "clean.png"
            clean.write_bytes(minimal_png())
            self.assertEqual(
                [],
                privacy_audit.scan_png(clean, "clean.png", 5_000_000),
            )

            metadata = root / "metadata.png"
            metadata.write_bytes(
                minimal_png((png_chunk(b"tEXt", b"Author\x00Private"),))
            )
            self.assertIn(
                "image_text_metadata",
                {
                    finding.category
                    for finding in privacy_audit.scan_png(
                        metadata,
                        "metadata.png",
                        5_000_000,
                    )
                },
            )

    def test_default_excludes_skip_generated_but_scan_public_tests(self) -> None:
        self.assertTrue(
            privacy_audit.should_exclude(Path("build/resume.log"), [])
        )
        self.assertFalse(
            privacy_audit.should_exclude(Path("tests/fixture.txt"), [])
        )
        self.assertTrue(
            privacy_audit.should_exclude(Path("resume.xdv"), [])
        )

    def test_pdf_tool_rejects_font_diagnostics(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["pdftotext"],
            returncode=0,
            stdout="visible fragment",
            stderr="Syntax Error: Missing language pack for Adobe-GB1",
        )
        with mock.patch.object(privacy_audit.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "font/CMap"):
                privacy_audit.run_text_tool(
                    ["pdftotext"],
                    reject_markers=privacy_audit.PDF_TEXT_FAILURE_MARKERS,
                )


class FactLedgerTests(unittest.TestCase):
    def valid_ledger(self) -> dict:
        return {
            "schema_version": 1,
            "source_index": [
                {
                    "id": "SRC-001",
                    "path": "sources/source.txt",
                    "description": "User-provided source",
                }
            ],
            "facts": [
                {
                    "id": "FACT-001",
                    "category": "experience",
                    "claim": "Implemented a documented feature",
                    "status": "usable",
                    "source_ids": ["SRC-001"],
                    "evidence": "Source states the implementation explicitly.",
                    "public_text": "Implemented the documented feature.",
                }
            ],
            "open_questions": [],
        }

    def test_valid_ledger_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sources").mkdir()
            (root / "sources/source.txt").write_text("source", encoding="utf-8")
            errors = validate_fact_ledger.validate_ledger(
                self.valid_ledger(),
                root,
                check_source_files=True,
                require_usable_facts=True,
            )
        self.assertEqual([], errors)

    def test_usable_fact_requires_evidence(self) -> None:
        ledger = self.valid_ledger()
        ledger["facts"][0]["evidence"] = "TODO"
        errors = validate_fact_ledger.validate_ledger(
            ledger,
            Path("."),
            check_source_files=False,
            require_usable_facts=True,
        )
        self.assertTrue(any("evidence" in error for error in errors))

    def test_normal_phrase_containing_pending_confirmation_is_not_a_todo(self) -> None:
        ledger = self.valid_ledger()
        sentence = "将联系人可用时段和待确认事项整理为同一份可追溯记录。"
        ledger["facts"][0]["evidence"] = sentence
        ledger["facts"][0]["public_text"] = sentence
        errors = validate_fact_ledger.validate_ledger(
            ledger,
            Path("."),
            check_source_files=False,
            require_usable_facts=True,
        )
        self.assertEqual([], errors)

    def test_leading_chinese_placeholder_is_still_rejected(self) -> None:
        ledger = self.valid_ledger()
        ledger["facts"][0]["public_text"] = "待确认：具体日期"
        errors = validate_fact_ledger.validate_ledger(
            ledger,
            Path("."),
            check_source_files=False,
            require_usable_facts=True,
        )
        self.assertTrue(any("public_text must be final" in error for error in errors))

    def test_resolved_question_requires_answer_source(self) -> None:
        ledger = self.valid_ledger()
        ledger["open_questions"] = [
            {
                "id": "Q-001",
                "fact_id": "FACT-001",
                "status": "resolved",
                "question": "Confirm the supported claim.",
            }
        ]
        errors = validate_fact_ledger.validate_ledger(
            ledger,
            Path("."),
            check_source_files=False,
            require_usable_facts=True,
        )
        self.assertTrue(any("answer_source_id" in error for error in errors))

    def test_question_requires_fact_reference(self) -> None:
        ledger = self.valid_ledger()
        ledger["open_questions"] = [
            {
                "id": "Q-001",
                "status": "open",
                "question": "Confirm the claim.",
                "answer_source_id": None,
            }
        ]
        errors = validate_fact_ledger.validate_ledger(
            ledger,
            Path("."),
            check_source_files=False,
            require_usable_facts=True,
        )
        self.assertTrue(any("fact_id" in error for error in errors))

    def test_category_is_open_vocabulary(self) -> None:
        ledger = self.valid_ledger()
        ledger["facts"][0]["category"] = "candidate-defined-culinary-achievement"
        errors = validate_fact_ledger.validate_ledger(
            ledger,
            Path("."),
            check_source_files=False,
            require_usable_facts=True,
        )
        self.assertEqual([], errors)


class TextParityTests(unittest.TestCase):
    def test_normalization_ignores_layout_whitespace_and_unicode_width(self) -> None:
        baseline = "项目 A\n指标：１２３ %\f下一页"
        candidate = "项目A 指标:123%\n下一页"

        result = validate_text_parity.compare_texts(
            baseline,
            candidate,
            baseline_label="baseline.pdf",
            candidate_label="candidate.pdf",
        )

        self.assertTrue(result["identical"])
        self.assertEqual(
            result["baseline"]["sha256"],
            result["candidate"]["sha256"],
        )
        self.assertIsNone(result["first_mismatch_index"])

    def test_rejects_empty_or_font_broken_extraction(self) -> None:
        source = Path("resume.pdf")
        with self.assertRaisesRegex(validate_text_parity.ParityError, "no visible text"):
            validate_text_parity.validate_extracted_text("  \n", "", source)
        with self.assertRaisesRegex(validate_text_parity.ParityError, "font/CMap"):
            validate_text_parity.validate_extracted_text(
                "partial text",
                "Unknown font tag F1; No font in show/space",
                source,
            )

    def test_detects_rewrite_deletion_or_reordering(self) -> None:
        result = validate_text_parity.compare_texts(
            "第一条 76% 第二条 75%",
            "第二条 75% 第一条 76%",
            baseline_label="baseline.pdf",
            candidate_label="candidate.pdf",
        )

        self.assertFalse(result["identical"])
        self.assertIsInstance(result["first_mismatch_index"], int)
        self.assertNotEqual(
            result["baseline"]["sha256"],
            result["candidate"]["sha256"],
        )


class FitManifestTests(unittest.TestCase):
    def valid_manifest(self) -> dict:
        return {
            "schema_version": 2,
            "success": True,
            "inputs": {
                "content": "examples/content-undergrad.tex",
                "theme": "ocean",
                "target_pages": 1,
                "content_preserved": True,
                "content_sha256": validate_fit_manifest.sha256_file(
                    validate_fit_manifest.REPO_ROOT
                    / "examples"
                    / "content-undergrad.tex"
                ),
                "entrypoint_sha256": validate_fit_manifest.sha256_file(
                    validate_fit_manifest.REPO_ROOT / "resume.tex"
                ),
                "layout_sha256": validate_fit_manifest.sha256_file(
                    validate_fit_manifest.REPO_ROOT / "resume-layout.tex"
                ),
                "components_sha256": validate_fit_manifest.sha256_file(
                    validate_fit_manifest.REPO_ROOT / "resume-components.tex"
                ),
                "theme_sha256": validate_fit_manifest.sha256_file(
                    validate_fit_manifest.REPO_ROOT / "theme.tex"
                ),
            },
            "thresholds": {
                "target_pages": 1,
                "max_bottom_whitespace_mm": 22,
                "min_page_fill_ratio": 0.62,
                "max_underfull": 20,
                "max_page_fill_spread": 0.22,
                "max_bottom_whitespace_spread_mm": 25,
            },
            "selection_policy": "balanced-reference-v1",
            "selection_reason": "balanced_reference_passed",
            "selection_order": ["balanced"],
            "attempted_profiles": ["balanced", "airy", "compact", "dense"],
            "attempted_page_fill_modes": ["natural"],
            "page_fill_attempts": [],
            "selection_detail": "natural_profile_selection",
            "selected_profile": "balanced",
            "selected_page_fill_mode": "natural",
            "selected_pdf": "output/resume-balanced.pdf",
            "candidates": [
                {
                    "profile": "airy",
                    "page_fill_mode": "natural",
                    "eligible": False,
                    "rejection_reasons": ["not selected by reference policy"],
                    "returncode": 0,
                    "render_returncode": 0,
                    "rasterizer": "pdftoppm",
                    "raster_error": None,
                    "pdf": "output/resume-airy.pdf",
                    "pages": 1,
                    "log_counts": {
                        "overfull": 0,
                        "underfull": 0,
                        "missing_glyph": 0,
                        "errors": 0,
                    },
                    "page_metrics": [],
                    "duplicate_page_pairs": [],
                },
                {
                    "profile": "balanced",
                    "page_fill_mode": "natural",
                    "eligible": True,
                    "rejection_reasons": [],
                    "returncode": 0,
                    "render_returncode": 0,
                    "rasterizer": "pdftoppm",
                    "raster_error": None,
                    "pdf": "output/resume-balanced.pdf",
                    "pages": 1,
                    "log_counts": {
                        "overfull": 0,
                        "underfull": 2,
                        "missing_glyph": 0,
                        "errors": 0,
                    },
                    "page_metrics": [
                        {
                            "blank": False,
                            "bbox_px": [10, 10, 990, 1390],
                            "nonwhite_pixels": 123456,
                            "ink_fill_ratio": 0.15,
                            "content_fill_ratio": 0.77,
                            "bottom_whitespace_px": 70,
                            "bottom_whitespace_mm": 14.8,
                        }
                    ],
                    "duplicate_page_pairs": [],
                },
                {
                    "profile": "compact",
                    "page_fill_mode": "natural",
                    "eligible": False,
                    "rejection_reasons": ["not selected by reference policy"],
                    "returncode": 0,
                    "render_returncode": 0,
                    "rasterizer": "pdftoppm",
                    "raster_error": None,
                    "pdf": "output/resume-compact.pdf",
                    "pages": 1,
                    "log_counts": {
                        "overfull": 0,
                        "underfull": 0,
                        "missing_glyph": 0,
                        "errors": 0,
                    },
                    "page_metrics": [],
                    "duplicate_page_pairs": [],
                },
                {
                    "profile": "dense",
                    "page_fill_mode": "natural",
                    "eligible": False,
                    "rejection_reasons": ["not selected by reference policy"],
                    "returncode": 0,
                    "render_returncode": 0,
                    "rasterizer": "pdftoppm",
                    "raster_error": None,
                    "pdf": "output/resume-dense.pdf",
                    "pages": 1,
                    "log_counts": {
                        "overfull": 0,
                        "underfull": 0,
                        "missing_glyph": 0,
                        "errors": 0,
                    },
                    "page_metrics": [],
                    "duplicate_page_pairs": [],
                },
            ],
        }

    def with_mock_artifacts(self, manifest: dict, directory: Path) -> dict:
        selected = next(
            candidate
            for candidate in manifest["candidates"]
            if candidate["profile"] == manifest["selected_profile"]
        )
        candidate_pdf = directory / "candidate.pdf"
        final_pdf = directory / "selected.pdf"
        payload = b"%PDF-1.4\n% mock artifact\n%%EOF\n"
        candidate_pdf.write_bytes(payload)
        final_pdf.write_bytes(payload)
        selected["pdf"] = str(candidate_pdf)
        manifest["selected_pdf"] = str(final_pdf)
        return manifest

    def elastic_manifest(self) -> dict:
        manifest = self.valid_manifest()
        manifest["inputs"]["target_pages"] = 2
        manifest["thresholds"]["target_pages"] = 2
        natural = copy.deepcopy(manifest["candidates"][1])
        natural.update(
            {
                "page_fill_mode": "natural",
                "eligible": False,
                "rejection_reasons": [
                    "page_1_bottom_whitespace_mm:54.822>22.000",
                    "page_2_bottom_whitespace_mm:39.793>22.000",
                ],
                "pdf": "output/resume-balanced.pdf",
                "pages": 2,
                "page_metrics": [
                    {
                        "blank": False,
                        "bbox_px": [10, 10, 990, 1200],
                        "nonwhite_pixels": 120000,
                        "ink_fill_ratio": 0.14,
                        "content_fill_ratio": 0.758547,
                        "bottom_whitespace_px": 259,
                        "bottom_whitespace_mm": 54.822,
                    },
                    {
                        "blank": False,
                        "bbox_px": [10, 10, 990, 1270],
                        "nonwhite_pixels": 130000,
                        "ink_fill_ratio": 0.15,
                        "content_fill_ratio": 0.821225,
                        "bottom_whitespace_px": 188,
                        "bottom_whitespace_mm": 39.793,
                    },
                ],
                "page_balance": {
                    "page_fill_spread": 0.062678,
                    "bottom_whitespace_spread_mm": 15.029,
                },
            }
        )
        elastic = copy.deepcopy(natural)
        elastic.update(
            {
                "page_fill_mode": "elastic",
                "eligible": True,
                "rejection_reasons": [],
                "pdf": "output/resume-balanced-elastic.pdf",
                "page_metrics": [
                    {
                        "blank": False,
                        "bbox_px": [10, 10, 990, 1316],
                        "nonwhite_pixels": 130000,
                        "ink_fill_ratio": 0.15,
                        "content_fill_ratio": 0.881054,
                        "bottom_whitespace_px": 87,
                        "bottom_whitespace_mm": 18.415,
                    },
                    {
                        "blank": False,
                        "bbox_px": [10, 10, 990, 1332],
                        "nonwhite_pixels": 135000,
                        "ink_fill_ratio": 0.16,
                        "content_fill_ratio": 0.904558,
                        "bottom_whitespace_px": 71,
                        "bottom_whitespace_mm": 15.028,
                    },
                ],
                "page_balance": {
                    "page_fill_spread": 0.023504,
                    "bottom_whitespace_spread_mm": 3.387,
                },
            }
        )
        elastic["log_counts"]["underfull"] = 0
        manifest["candidates"][1] = copy.deepcopy(elastic)
        manifest["attempted_page_fill_modes"] = ["natural", "elastic"]
        manifest["page_fill_attempts"] = [natural, elastic]
        manifest["selection_reason"] = "reference_under_target_or_underfilled"
        manifest["selection_order"] = ["balanced", "airy", "compact", "dense"]
        manifest["selection_detail"] = "balanced_elastic_underfill_recovery"
        manifest["selected_page_fill_mode"] = "elastic"
        manifest["selected_pdf"] = "output/resume-balanced-elastic.pdf"
        return manifest

    def test_valid_mock_fit_manifest_passes(self) -> None:
        errors = validate_fit_manifest.validate_manifest(
            self.valid_manifest(),
            expected_pages=1,
        )
        self.assertEqual([], errors)

    def test_rejects_unknown_manifest_schema(self) -> None:
        manifest = self.valid_manifest()
        manifest["schema_version"] = 3
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(
            any("schema_version must be exactly 2" in error for error in errors)
        )

    def test_valid_elastic_underfill_recovery_passes(self) -> None:
        errors = validate_fit_manifest.validate_manifest(
            self.elastic_manifest(),
            expected_pages=2,
        )
        self.assertEqual([], errors)

    def test_rejects_elastic_recovery_claimed_as_reference_pass(self) -> None:
        manifest = self.elastic_manifest()
        manifest["selection_reason"] = "balanced_reference_passed"
        manifest["selection_order"] = ["balanced"]
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(
            any(
                "selection_reason does not match the balanced candidate" in error
                for error in errors
            )
        )

    def test_rejects_elastic_underfull_box(self) -> None:
        manifest = self.elastic_manifest()
        manifest["candidates"][1]["log_counts"]["underfull"] = 1
        manifest["page_fill_attempts"][1]["log_counts"]["underfull"] = 1
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(
            any("zero underfull boxes" in error for error in errors)
        )

    def test_rejects_elastic_without_underfill_only_origin(self) -> None:
        manifest = self.elastic_manifest()
        manifest["page_fill_attempts"][0]["rejection_reasons"].append(
            "overfull_boxes:1"
        )
        manifest["page_fill_attempts"][0]["log_counts"]["overfull"] = 1
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(
            any("fail only whitespace/fill/balance" in error for error in errors)
        )

    def test_rejects_missing_provenance_hash_and_mode_mismatch(self) -> None:
        manifest = self.valid_manifest()
        manifest["inputs"]["components_sha256"] = "not-a-digest"
        manifest["selected_page_fill_mode"] = "elastic"
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(
            any("components_sha256" in error for error in errors)
        )
        self.assertTrue(
            any("must match the selected candidate" in error for error in errors)
        )

    def test_rejects_each_tampered_source_hash(self) -> None:
        for field in (
            "content_sha256",
            "entrypoint_sha256",
            "layout_sha256",
            "components_sha256",
            "theme_sha256",
        ):
            with self.subTest(field=field):
                manifest = self.valid_manifest()
                manifest["inputs"][field] = "0" * 64
                errors = validate_fit_manifest.validate_manifest(manifest)
                self.assertTrue(
                    any(
                        f"inputs.{field} does not match" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_absolute_external_content_hash_is_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = Path(directory) / "private-content.tex"
            content.write_text("external immutable content\n", encoding="utf-8")
            manifest = self.valid_manifest()
            manifest["inputs"]["content"] = str(content)
            manifest["inputs"]["content_sha256"] = (
                validate_fit_manifest.sha256_file(content)
            )
            errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertEqual([], errors)

    def test_rejects_natural_selection_after_elastic_attempt(self) -> None:
        manifest = self.elastic_manifest()
        natural, elastic = manifest["page_fill_attempts"]
        elastic["eligible"] = False
        elastic["rejection_reasons"] = ["elastic_underfull_boxes:1>0"]
        elastic["log_counts"]["underfull"] = 1
        manifest["candidates"][1] = copy.deepcopy(natural)
        airy = manifest["candidates"][0]
        airy.update(
            {
                "eligible": True,
                "rejection_reasons": [],
                "pages": 2,
                "page_metrics": [
                    {
                        "blank": False,
                        "bbox_px": [10, 10, 990, 1320],
                        "nonwhite_pixels": 130000,
                        "ink_fill_ratio": 0.15,
                        "content_fill_ratio": 0.89,
                        "bottom_whitespace_px": 80,
                        "bottom_whitespace_mm": 16.9,
                    },
                    {
                        "blank": False,
                        "bbox_px": [10, 10, 990, 1310],
                        "nonwhite_pixels": 128000,
                        "ink_fill_ratio": 0.15,
                        "content_fill_ratio": 0.88,
                        "bottom_whitespace_px": 85,
                        "bottom_whitespace_mm": 18.0,
                    },
                ],
                "page_balance": {
                    "page_fill_spread": 0.01,
                    "bottom_whitespace_spread_mm": 1.1,
                },
            }
        )
        manifest["selection_reason"] = "reference_under_target_or_underfilled"
        manifest["selection_order"] = ["balanced", "airy", "compact", "dense"]
        manifest["selection_detail"] = (
            "natural_profile_selection_after_elastic_rejection"
        )
        manifest["selected_profile"] = "airy"
        manifest["selected_page_fill_mode"] = "natural"
        manifest["selected_pdf"] = "output/resume-airy.pdf"
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(
            any(
                "must be selected before elastic page fill is attempted"
                in error
                for error in errors
            )
        )

    def test_rejects_elastic_when_a_natural_profile_is_eligible(self) -> None:
        manifest = self.elastic_manifest()
        airy = manifest["candidates"][0]
        airy["eligible"] = True
        airy["rejection_reasons"] = []
        airy["pages"] = 2
        airy["page_metrics"] = copy.deepcopy(
            manifest["page_fill_attempts"][1]["page_metrics"]
        )
        airy["page_balance"] = copy.deepcopy(
            manifest["page_fill_attempts"][1]["page_balance"]
        )

        errors = validate_fit_manifest.validate_manifest(manifest)

        self.assertTrue(
            any(
                "requires every natural profile to be ineligible" in error
                for error in errors
            )
        )

    def test_rejects_profile_outside_reason_directed_order(self) -> None:
        manifest = self.valid_manifest()
        balanced = manifest["candidates"][1]
        balanced["eligible"] = False
        balanced["rejection_reasons"] = ["bottom whitespace exceeds threshold"]
        balanced["page_metrics"][0]["bottom_whitespace_mm"] = 30
        airy = manifest["candidates"][0]
        airy["eligible"] = True
        airy["rejection_reasons"] = []
        airy["page_metrics"] = [
            {
                "blank": False,
                "bbox_px": [10, 10, 990, 1390],
                "nonwhite_pixels": 123456,
                "ink_fill_ratio": 0.15,
                "content_fill_ratio": 0.74,
                "bottom_whitespace_px": 80,
                "bottom_whitespace_mm": 16.0,
            }
        ]
        manifest["selection_reason"] = "reference_under_target_or_underfilled"
        manifest["selection_order"] = ["balanced", "airy", "compact", "dense"]
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(any("reason-directed" in error for error in errors))

    def test_underfilled_reference_selects_airy(self) -> None:
        manifest = self.valid_manifest()
        balanced = manifest["candidates"][1]
        balanced["eligible"] = False
        balanced["rejection_reasons"] = ["bottom whitespace exceeds threshold"]
        balanced["page_metrics"][0]["bottom_whitespace_mm"] = 30
        airy = manifest["candidates"][0]
        airy["eligible"] = True
        airy["rejection_reasons"] = []
        airy["page_metrics"] = [
            {
                "blank": False,
                "bbox_px": [10, 10, 990, 1390],
                "nonwhite_pixels": 123456,
                "ink_fill_ratio": 0.15,
                "content_fill_ratio": 0.74,
                "bottom_whitespace_px": 80,
                "bottom_whitespace_mm": 16.0,
            }
        ]
        manifest["selection_reason"] = "reference_under_target_or_underfilled"
        manifest["selection_order"] = ["balanced", "airy", "compact", "dense"]
        manifest["selected_profile"] = "airy"
        manifest["selected_pdf"] = "output/resume-airy.pdf"
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertEqual([], errors)

    def test_overflowing_reference_selects_compact(self) -> None:
        manifest = self.valid_manifest()
        balanced = manifest["candidates"][1]
        balanced["eligible"] = False
        balanced["rejection_reasons"] = ["expected 1 page, produced 2"]
        balanced["pages"] = 2
        compact = manifest["candidates"][2]
        compact["eligible"] = True
        compact["rejection_reasons"] = []
        compact["page_metrics"] = [
            {
                "blank": False,
                "bbox_px": [10, 10, 990, 1390],
                "nonwhite_pixels": 123456,
                "ink_fill_ratio": 0.15,
                "content_fill_ratio": 0.78,
                "bottom_whitespace_px": 70,
                "bottom_whitespace_mm": 14.8,
            }
        ]
        manifest["selection_reason"] = "reference_over_target_or_overflow"
        manifest["selection_order"] = ["balanced", "compact", "dense", "airy"]
        manifest["selected_profile"] = "compact"
        manifest["selected_pdf"] = "output/resume-compact.pdf"
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertEqual([], errors)

    def test_rejects_bottom_whitespace_and_duplicate_pages(self) -> None:
        manifest = self.valid_manifest()
        selected = manifest["candidates"][1]
        selected["page_metrics"][0]["bottom_whitespace_mm"] = 30
        selected["duplicate_page_pairs"] = [[1, 2]]
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(any("bottom_whitespace_mm exceeds" in error for error in errors))
        self.assertTrue(any("duplicate rendered pages" in error for error in errors))

    def test_rejects_unbalanced_multi_page_fill(self) -> None:
        manifest = self.valid_manifest()
        manifest["inputs"]["target_pages"] = 2
        manifest["thresholds"]["target_pages"] = 2
        manifest["thresholds"]["max_bottom_whitespace_mm"] = 60
        selected = manifest["candidates"][1]
        selected["pages"] = 2
        selected["page_metrics"] = [
            {
                "blank": False,
                "bbox_px": [10, 10, 990, 1390],
                "nonwhite_pixels": 140000,
                "ink_fill_ratio": 0.17,
                "content_fill_ratio": 0.85,
                "bottom_whitespace_px": 24,
                "bottom_whitespace_mm": 5.0,
            },
            {
                "blank": False,
                "bbox_px": [10, 10, 990, 1390],
                "nonwhite_pixels": 100000,
                "ink_fill_ratio": 0.12,
                "content_fill_ratio": 0.62,
                "bottom_whitespace_px": 168,
                "bottom_whitespace_mm": 35.0,
            },
        ]
        selected["page_balance"] = {
            "page_fill_spread": 0.23,
            "bottom_whitespace_spread_mm": 30.0,
        }
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(any("page_fill_spread exceeds" in error for error in errors))
        self.assertTrue(
            any("bottom_whitespace_spread_mm exceeds" in error for error in errors)
        )

    def test_artifact_gate_rejects_tampered_selected_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.with_mock_artifacts(self.valid_manifest(), root)
            Path(manifest["selected_pdf"]).write_bytes(
                b"%PDF-1.4\n% different artifact\n%%EOF\n"
            )
            errors = validate_fit_manifest.validate_manifest(
                manifest,
                repo_root=validate_fit_manifest.REPO_ROOT,
                check_artifacts=True,
            )
        self.assertTrue(any("byte-identical" in error for error in errors))

    def test_rejects_non_finite_or_out_of_range_thresholds(self) -> None:
        manifest = self.valid_manifest()
        manifest["thresholds"]["min_page_fill_ratio"] = float("nan")
        manifest["thresholds"]["max_page_fill_spread"] = 2
        errors = validate_fit_manifest.validate_manifest(manifest)
        self.assertTrue(any("finite number" in error for error in errors))
        self.assertTrue(any("max_page_fill_spread" in error for error in errors))

    def test_mock_manifest_cli_round_trip(self) -> None:
        script = SCRIPTS_DIR / "validate_fit_manifest.py"
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "fit-manifest.json"
            payload = self.with_mock_artifacts(
                self.valid_manifest(), Path(directory)
            )
            manifest.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(manifest),
                    "--repo-root",
                    str(validate_fit_manifest.REPO_ROOT),
                    "--expected-pages",
                    "1",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("profile=balanced", completed.stdout)

    def test_installed_skill_copy_accepts_explicit_repo_root(self) -> None:
        source_script = SCRIPTS_DIR / "validate_fit_manifest.py"
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "installed-skill" / "scripts"
            installed.mkdir(parents=True)
            copied_script = installed / "validate_fit_manifest.py"
            copied_script.write_text(
                source_script.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            manifest = Path(directory) / "outside-repo-manifest.json"
            payload = self.with_mock_artifacts(
                self.valid_manifest(), Path(directory)
            )
            manifest.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(copied_script),
                    str(manifest),
                    "--repo-root",
                    str(validate_fit_manifest.REPO_ROOT),
                    "--expected-pages",
                    "1",
                ],
                cwd=directory,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("fit manifest validation passed", completed.stdout)


class SkillDocumentationContractTests(unittest.TestCase):
    def test_adaptive_contract_is_documented(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        adaptive = (SKILL_ROOT / "references/adaptive-layout.md").read_text(
            encoding="utf-8"
        )
        mapping = (SKILL_ROOT / "references/latex-mapping.md").read_text(
            encoding="utf-8"
        )
        rubric = (SKILL_ROOT / "references/content-rubric.md").read_text(
            encoding="utf-8"
        )

        for token in (
            r"\ResumeContentFile",
            r"\ResumeDensity",
            "fit_resume.py",
            "validate_text_parity.py",
            "target page count",
            "read-only",
            "visual truth",
            "balanced-reference-v1",
            "make privacy-history",
        ):
            self.assertIn(token, skill + adaptive)

        for token in (
            "arbitrary sections",
            "one, two, or three columns",
            "one, two, three, or more",
            "resume-components.tex",
        ):
            self.assertIn(token, (mapping + skill).lower())

        self.assertIn("open vocabulary", rubric)
        self.assertIn("must not require a schema or validator change", rubric)
        self.assertIn("non-dialable", skill + adaptive)
        self.assertIn("byte-identical", skill + adaptive)

    def test_hard_gates_are_documented(self) -> None:
        adaptive = (SKILL_ROOT / "references/adaptive-layout.md").read_text(
            encoding="utf-8"
        )
        checklist = (
            SKILL_ROOT / "references/acceptance-checklist.md"
        ).read_text(encoding="utf-8")
        combined = adaptive + checklist
        for token in (
            "bottom whitespace",
            "section heading",
            "Long-field gates",
            "Repetition gates",
            "Content-integrity gate",
            "duplicate rendered page",
            "multilevel bullets",
            "max_page_fill_spread",
            "max_bottom_whitespace_spread_mm",
            "visible-text parity",
            "repository history gate",
        ):
            self.assertIn(token, combined)


class ResumeValidatorTests(unittest.TestCase):
    def test_discovers_template_themes(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        themes = validate_resume.discover_themes(repo_root / "theme.tex")
        self.assertEqual(["ocean", "forest", "plum", "graphite"], themes)

    def test_discovers_expanding_theme_selector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            theme_file = Path(directory) / "theme.tex"
            theme_file.write_text(
                "\\providecommand{\\ResumeTheme}{ocean}\n"
                "\\ifdefstring{\\ResumeTheme}{forest}{}{}\n",
                encoding="utf-8",
            )
            themes = validate_resume.discover_themes(theme_file)
        self.assertEqual(["ocean", "forest"], themes)

    def test_rejects_full_document_in_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "resume.tex"
            content = root / "content.tex"
            main.write_text(
                "\\providecommand{\\ResumeTheme}{ocean}\n"
                "\\input{content.tex}\n",
                encoding="utf-8",
            )
            content.write_text("\\begin{document}\n", encoding="utf-8")
            errors = validate_resume.validate_source_layout(main, content)
        self.assertTrue(any("\\begin{document}" in error for error in errors))

    def test_flags_byte_identical_theme_renders(self) -> None:
        results = [
            {
                "theme": "first",
                "status": "passed",
                "errors": [],
                "rendered_pages": [{"sha256": "same-digest"}],
            },
            {
                "theme": "second",
                "status": "passed",
                "errors": [],
                "rendered_pages": [{"sha256": "same-digest"}],
            },
            {
                "theme": "third",
                "status": "passed",
                "errors": [],
                "rendered_pages": [{"sha256": "different-digest"}],
            },
        ]
        groups = validate_resume.flag_duplicate_theme_renders(results)
        self.assertEqual([["first", "second"]], groups)
        self.assertEqual("failed", results[0]["status"])
        self.assertEqual("failed", results[1]["status"])
        self.assertEqual("passed", results[2]["status"])

    def test_inspects_tex_box_and_glyph_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "resume.log"
            slash = "\\"
            log.write_text(
                f"Overfull {slash}hbox (1.25pt too wide) in paragraph\n"
                f"Underfull {slash}vbox (badness 10000)\n"
                "Missing character: There is no glyph\n",
                encoding="utf-8",
            )
            summary = validate_resume.inspect_log(log, max_overfull_pt=0.5)
        self.assertEqual(1, summary["overfull_boxes"])
        self.assertEqual(1.25, summary["largest_overfull_pt"])
        self.assertEqual(1, summary["underfull_boxes"])
        self.assertEqual(1, summary["missing_characters"])
        self.assertTrue(summary["overfull_limit_exceeded"])

    def test_quotes_tex_input_paths_with_spaces(self) -> None:
        content = Path("/private/tmp/private workspace/content.tex")
        expression = validate_resume.tex_entry_expression(
            "folder with spaces/resume.tex", "forest", content
        )
        self.assertIn('\\input{"folder with spaces/resume.tex"}', expression)
        self.assertIn(
            rf"\def\ResumeContentFile{{\detokenize{{{content}}}}}",
            expression,
        )

    def test_rejects_broken_poppler_and_falls_back_to_ghostscript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "resume.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")

            def fake_which(name: str):
                return f"/fake/{name}" if name in {"pdftoppm", "gs"} else None

            def fake_run(command, **kwargs):
                if command[0] == "/fake/pdftoppm":
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        "",
                        "Missing language pack for Adobe-GB1",
                    )
                output_option = next(
                    value for value in command if value.startswith("-sOutputFile=")
                )
                output = Path(output_option.split("=", 1)[1].replace("%d", "1"))
                output.write_bytes(minimal_png())
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(validate_resume.shutil, "which", side_effect=fake_which), mock.patch.object(
                validate_resume.subprocess, "run", side_effect=fake_run
            ):
                images, renderer, attempts = validate_resume.render_pdf(
                    pdf, root, 120
                )

        self.assertEqual("ghostscript", renderer)
        self.assertEqual(1, len(images))
        self.assertTrue(attempts[0]["font_diagnostics_rejected"])
        self.assertFalse(attempts[1]["font_diagnostics_rejected"])


class PrivateWorkspaceCliTests(unittest.TestCase):
    def test_initializes_outside_repository_without_overwriting(self) -> None:
        script = SCRIPTS_DIR / "init_private_workspace.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "public"
            private = root / "private"
            repo.mkdir()
            for name in ("resume.tex", "content.tex", "theme.tex"):
                (repo / name).write_text("% test\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--repo-root",
                    str(repo),
                    "--private-root",
                    str(private),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            ledger = Path(payload["ledger_path"])
            self.assertTrue(ledger.is_file())
            ledger.write_text('{"preserve": true}\n', encoding="utf-8")
            repeated = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--repo-root",
                    str(repo),
                    "--private-root",
                    str(private),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertEqual('{"preserve": true}\n', ledger.read_text(encoding="utf-8"))

    def test_rejects_private_workspace_inside_any_git_tree(self) -> None:
        script = SCRIPTS_DIR / "init_private_workspace.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "public"
            enclosing_repo = root / "enclosing"
            repo.mkdir()
            enclosing_repo.mkdir()
            for name in ("resume.tex", "content.tex", "theme.tex"):
                (repo / name).write_text("% test\n", encoding="utf-8")
            initialized = subprocess.run(
                ["git", "-C", str(enclosing_repo), "init", "--quiet"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--repo-root",
                    str(repo),
                    "--private-root",
                    str(enclosing_repo / "private"),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(2, completed.returncode)
            self.assertIn("inside any Git worktree", completed.stderr)


if __name__ == "__main__":
    unittest.main()
