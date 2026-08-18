from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import privacy_audit  # noqa: E402
import validate_fact_ledger  # noqa: E402
import validate_resume  # noqa: E402


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

    def test_reserved_phone_placeholder_is_safe(self) -> None:
        placeholder = "(+86) " + r"138\,0000\,0000"
        findings = privacy_audit.scan_text(
            placeholder, "content.tex", set(), []
        )
        self.assertEqual([], findings)


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
        expression = validate_resume.tex_entry_expression(
            "folder with spaces/resume.tex", "forest"
        )
        self.assertIn('\\input{"folder with spaces/resume.tex"}', expression)


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
