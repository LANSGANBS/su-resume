from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import privacy_check  # noqa: E402


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", checksum)
    )


def minimal_png(extra_chunks=()):
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    image_data = zlib.compress(b"\x00\x00\x00\x00\x00")
    return (
        privacy_check.PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + b"".join(extra_chunks)
        + png_chunk(b"IDAT", image_data)
        + png_chunk(b"IEND", b"")
    )


def rules_for(text: str):
    return {finding.rule for finding in privacy_check.scan_text("fixture", text)}


class TextScannerTests(unittest.TestCase):
    def test_repository_placeholders_are_allowed(self):
        sample = "\n".join(
            (
                "you@example.com",
                r"(+86) 138\,0000\,0000",
                "https://github.com/yourname",
                "pdfauthor={Resume Template}",
            )
        )
        self.assertEqual(rules_for(sample), set())

    def test_non_example_email_is_detected_without_storing_fixture(self):
        address = "person" + "@" + "company" + ".com"
        findings = privacy_check.scan_text("fixture", address)
        self.assertIn("non-example-email", {item.rule for item in findings})
        self.assertNotIn(address, "\n".join(item.render() for item in findings))

    def test_realistic_phone_is_detected(self):
        phone = "139" + "2468" + "1357"
        self.assertIn("phone-number", rules_for(phone))

    def test_private_and_internal_urls_are_detected(self):
        private_url = "http://" + "10.20.30.40" + "/admin"
        internal_url = "https://" + "service.internal" + ".company.com/api"
        self.assertIn("private-url", rules_for(private_url))
        self.assertIn("private-url", rules_for(internal_url))

    def test_url_credentials_are_detected(self):
        value = "S8fK3mP7qR2vN9xL"
        url = "https://example.dev/download?access_" + "token=" + value
        self.assertIn("private-url", rules_for(url))

    def test_public_and_reserved_urls_are_allowed(self):
        sample = "\n".join(
            (
                "https://github.com/example/project",
                "https://docs.example.org/path",
            )
        )
        self.assertEqual(rules_for(sample), set())

    def test_common_token_and_private_key_are_detected(self):
        token = "gh" + "p_" + ("A" * 40)
        private_key_header = "-----BEGIN " + "PRIVATE KEY-----"
        rules = rules_for(token + "\n" + private_key_header)
        self.assertIn("github-token", rules)
        self.assertIn("private-key", rules)

    def test_high_entropy_secret_assignment_is_detected(self):
        value = "N7zQ2mV9pL4xK8cR6sT1"
        self.assertIn("assigned-secret", rules_for("api_key=" + value))

    def test_symbolic_secret_assignment_is_allowed(self):
        self.assertEqual(rules_for("api_key=${API_KEY}"), set())

    def test_personal_home_path_is_detected(self):
        path = "/Users/" + "developer" + "/resume"
        self.assertIn("local-home-path", rules_for(path))


class HistoryScannerTests(unittest.TestCase):
    def run_git(self, repository: Path, *arguments: str, env=None):
        completed = subprocess.run(
            ("git",) + arguments,
            cwd=repository,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", "replace"),
        )

    def commit_environment(self, email: str):
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_NAME": "Template Maintainer",
                "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": "Template Maintainer",
                "GIT_COMMITTER_EMAIL": email,
            }
        )
        return environment

    def test_history_flags_non_private_commit_email(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self.run_git(repository, "init", "-q")
            (repository / "safe.txt").write_text("safe\n", encoding="utf-8")
            self.run_git(repository, "add", "safe.txt")
            self.run_git(
                repository,
                "commit",
                "-q",
                "-m",
                "safe root",
                env=self.commit_environment("maintainers@example.com"),
            )
            self.assertEqual(privacy_check.scan_history(repository), [])

            (repository / "safe.txt").write_text("still safe\n", encoding="utf-8")
            self.run_git(repository, "add", "safe.txt")
            private_email = "author" + "@" + "company" + ".com"
            self.run_git(
                repository,
                "commit",
                "-q",
                "-m",
                "unsafe metadata",
                env=self.commit_environment(private_email),
            )
            rules = {
                finding.rule
                for finding in privacy_check.scan_history(repository)
            }
            self.assertIn("commit-author-email", rules)
            self.assertIn("commit-committer-email", rules)

    def test_history_scans_a_secret_deleted_from_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self.run_git(repository, "init", "-q")
            environment = self.commit_environment("maintainers@example.com")
            secret_path = repository / "temporary.txt"
            token = "gh" + "p_" + ("B" * 40)
            secret_path.write_text(token + "\n", encoding="utf-8")
            self.run_git(repository, "add", "temporary.txt")
            self.run_git(
                repository,
                "commit",
                "-q",
                "-m",
                "temporary fixture",
                env=environment,
            )

            secret_path.unlink()
            self.run_git(repository, "add", "-u")
            self.run_git(
                repository,
                "commit",
                "-q",
                "-m",
                "remove fixture",
                env=environment,
            )

            rules = {
                finding.rule
                for finding in privacy_check.scan_history(repository)
            }
            self.assertIn("github-token", rules)

    def test_history_allows_only_valid_reviewed_png(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self.run_git(repository, "init", "-q")
            environment = self.commit_environment("maintainers@example.com")
            preview = repository / "preview.png"
            preview.write_bytes(minimal_png())
            self.run_git(repository, "add", "preview.png")
            self.run_git(
                repository,
                "commit",
                "-q",
                "-m",
                "add reviewed preview",
                env=environment,
            )

            without_allow = {
                finding.rule
                for finding in privacy_check.scan_history(repository)
            }
            self.assertIn("binary-history-blob", without_allow)
            self.assertEqual(
                [],
                privacy_check.scan_history(
                    repository,
                    allowed_binary_extensions={".png"},
                ),
            )


class FileScannerTests(unittest.TestCase):
    def test_binary_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(bytes((0, 1, 2, 3)))
            rules = {
                finding.rule
                for finding in privacy_check.scan_file(
                    path,
                    "payload.bin",
                    tracked=False,
                    allowed_binary_extensions=set(),
                )
            }
            self.assertIn("unexpected-binary", rules)

    def test_tracked_pdf_requires_metadata_tool_and_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resume.pdf"
            path.write_bytes(b"%PDF-invalid fixture")
            with mock.patch.object(privacy_check.shutil, "which", return_value=None):
                rules = {
                    finding.rule
                    for finding in privacy_check.scan_file(
                        path,
                        "resume.pdf",
                        tracked=True,
                        allowed_binary_extensions=set(),
                    )
                }
            self.assertIn("tracked-pdf", rules)
            self.assertIn("pdf-metadata-unchecked", rules)

    def test_reviewed_png_is_structurally_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            path.write_bytes(minimal_png())
            findings = privacy_check.scan_file(
                path,
                "preview.png",
                tracked=True,
                allowed_binary_extensions={".png"},
            )
            self.assertEqual(findings, [])

    def test_png_text_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            path.write_bytes(
                minimal_png((png_chunk(b"tEXt", b"Author\x00Private"),))
            )
            rules = {
                finding.rule
                for finding in privacy_check.scan_file(
                    path,
                    "preview.png",
                    tracked=True,
                    allowed_binary_extensions={".png"},
                )
            }
            self.assertIn("image-text-metadata", rules)

    def test_fake_png_is_rejected_even_when_extension_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            path.write_bytes(b"\x00not a png")
            rules = {
                finding.rule
                for finding in privacy_check.scan_file(
                    path,
                    "preview.png",
                    tracked=True,
                    allowed_binary_extensions={".png"},
                )
            }
            self.assertIn("invalid-allowed-binary", rules)


if __name__ == "__main__":
    unittest.main()
