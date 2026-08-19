from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import zlib

from scripts import render_pdf_page


def _png_chunk(name: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(name)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + name
        + payload
        + struct.pack(">I", checksum)
    )


def _write_png(path: Path, width: int = 993, height: int = 1404) -> None:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixel = b"\xff\xff\xff" * width
    scanlines = b"".join(b"\x00" + pixel for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(scanlines))
        + _png_chunk(b"IEND", b"")
    )


class PageRendererTests(unittest.TestCase):
    def test_known_poppler_font_diagnostics_are_rejected_at_zero_exit(self) -> None:
        for diagnostic in (
            "Missing language pack for Adobe-GB1",
            "Unknown font tag F1",
            "No font in show/space",
        ):
            with self.subTest(diagnostic=diagnostic):
                self.assertFalse(
                    render_pdf_page._poppler_log_is_usable(0, diagnostic)
                )

    def test_truncated_png_with_expected_header_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.png"
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + struct.pack(">I", 13)
                + b"IHDR"
                + struct.pack(">II", 993, 1404)
            )
            self.assertFalse(render_pdf_page._png_has_expected_geometry(path))

    def _paths(self, directory: str) -> tuple[Path, Path]:
        root = Path(directory)
        source = root / "source.pdf"
        destination = root / "page.png"
        source.write_bytes(b"%PDF-1.7\n%%EOF\n")
        return source, destination

    def test_accepts_valid_poppler_output_without_running_ghostscript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, destination = self._paths(directory)
            commands: list[list[str]] = []

            def fake_run(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                _write_png(Path(f"{command[-1]}.png"))
                return subprocess.CompletedProcess(command, 0, stdout="")

            with (
                mock.patch.object(
                    render_pdf_page.shutil,
                    "which",
                    side_effect=lambda name: f"/tools/{name}",
                ),
                mock.patch.object(
                    render_pdf_page.subprocess, "run", side_effect=fake_run
                ),
            ):
                renderer = render_pdf_page.render_page_one(source, destination)

            self.assertEqual(renderer, "poppler")
            self.assertTrue(render_pdf_page._png_has_expected_geometry(destination))
            self.assertEqual(len(commands), 1)
            self.assertTrue(commands[0][0].endswith("pdftoppm"))

    def test_font_diagnostic_at_zero_exit_cleans_partial_then_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, destination = self._paths(directory)
            commands: list[list[str]] = []

            def fake_run(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                if command[0].endswith("pdftoppm"):
                    _write_png(Path(f"{command[-1]}.png"))
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=(
                            "Syntax Error: Missing language pack for Adobe-GB1\n"
                            "private document text must not be reported"
                        ),
                    )

                output = next(
                    value.removeprefix("-sOutputFile=")
                    for value in command
                    if value.startswith("-sOutputFile=")
                )
                temporary_root = Path(output).parent
                self.assertEqual(list(temporary_root.glob("poppler-page*")), [])
                _write_png(Path(output))
                return subprocess.CompletedProcess(command, 0, stdout="")

            with (
                mock.patch.object(
                    render_pdf_page.shutil,
                    "which",
                    side_effect=lambda name: f"/tools/{name}",
                ),
                mock.patch.object(
                    render_pdf_page.subprocess, "run", side_effect=fake_run
                ),
            ):
                renderer = render_pdf_page.render_page_one(source, destination)

            self.assertEqual(renderer, "ghostscript")
            self.assertTrue(render_pdf_page._png_has_expected_geometry(destination))
            self.assertEqual(len(commands), 2)

    def test_wrong_poppler_geometry_uses_fixed_geometry_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, destination = self._paths(directory)

            def fake_run(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                if command[0].endswith("pdftoppm"):
                    _write_png(Path(f"{command[-1]}.png"), width=992)
                else:
                    output = next(
                        value.removeprefix("-sOutputFile=")
                        for value in command
                        if value.startswith("-sOutputFile=")
                    )
                    _write_png(Path(output))
                return subprocess.CompletedProcess(command, 0, stdout="")

            with (
                mock.patch.object(
                    render_pdf_page.shutil,
                    "which",
                    side_effect=lambda name: f"/tools/{name}",
                ),
                mock.patch.object(
                    render_pdf_page.subprocess, "run", side_effect=fake_run
                ),
            ):
                renderer = render_pdf_page.render_page_one(source, destination)

            self.assertEqual(renderer, "ghostscript")
            self.assertTrue(render_pdf_page._png_has_expected_geometry(destination))

    def test_no_renderer_available_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, destination = self._paths(directory)
            destination.write_bytes(b"stale")
            with (
                mock.patch.object(
                    render_pdf_page.shutil, "which", return_value=None
                ),
                mock.patch.object(render_pdf_page.subprocess, "run") as run,
            ):
                with self.assertRaises(render_pdf_page.RenderError):
                    render_pdf_page.render_page_one(source, destination)

            self.assertFalse(destination.exists())
            run.assert_not_called()

    def test_both_fail_removes_stale_output_and_hides_renderer_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, destination = self._paths(directory)
            destination.write_bytes(b"stale")

            def fake_run(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                if command[0].endswith("pdftoppm"):
                    Path(f"{command[-1]}.png").write_bytes(b"partial")
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="No font in show/space: private document text",
                    )
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="private document text",
                )

            with (
                mock.patch.object(
                    render_pdf_page.shutil,
                    "which",
                    side_effect=lambda name: f"/tools/{name}",
                ),
                mock.patch.object(
                    render_pdf_page.subprocess, "run", side_effect=fake_run
                ),
            ):
                with self.assertRaises(render_pdf_page.RenderError) as raised:
                    render_pdf_page.render_page_one(source, destination)

            self.assertFalse(destination.exists())
            self.assertNotIn("private document text", str(raised.exception))

    def test_cli_reports_renderer_without_echoing_input_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, destination = self._paths(directory)
            output = io.StringIO()
            with (
                mock.patch.object(
                    render_pdf_page,
                    "render_page_one",
                    return_value="ghostscript",
                ),
                redirect_stdout(output),
            ):
                returncode = render_pdf_page.main([str(source), str(destination)])

            self.assertEqual(returncode, 0)
            self.assertEqual(
                output.getvalue(),
                "render-pdf-page: renderer=ghostscript "
                "page=1 pixels=993x1404\n",
            )
            self.assertNotIn(str(source), output.getvalue())


if __name__ == "__main__":
    unittest.main()
