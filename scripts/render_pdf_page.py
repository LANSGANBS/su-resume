#!/usr/bin/env python3
"""Render page one of an A4 PDF to a validated, deterministic PNG."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Sequence
import zlib


DPI = 120
PAGE_WIDTH_PX = 993
PAGE_HEIGHT_PX = 1404
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_POPPLER_FONT_FAILURES = (
    "missing language pack",
    "unknown font tag",
    "no font in show/space",
)


class RenderError(RuntimeError):
    """A safe, user-facing PDF rendering failure."""


def _png_has_expected_geometry(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if not data.startswith(PNG_SIGNATURE):
        return False

    offset = len(PNG_SIGNATURE)
    saw_header = False
    saw_image_data = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            return False
        chunk_type = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        stored_checksum = struct.unpack(">I", data[chunk_end - 4 : chunk_end])[0]
        checksum = zlib.crc32(chunk_type)
        checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
        if checksum != stored_checksum:
            return False

        if not saw_header:
            if chunk_type != b"IHDR" or length != 13:
                return False
            width, height = struct.unpack(">II", payload[:8])
            if (width, height) != (PAGE_WIDTH_PX, PAGE_HEIGHT_PX):
                return False
            saw_header = True
        elif chunk_type == b"IHDR":
            return False

        if chunk_type == b"IDAT":
            saw_image_data = True
        if chunk_type == b"IEND":
            return length == 0 and saw_image_data and chunk_end == len(data)
        offset = chunk_end

    return False


def _run(command: Sequence[str]) -> tuple[int | None, str]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None, ""
    return completed.returncode, completed.stdout or ""


def _poppler_log_is_usable(returncode: int | None, log_text: str) -> bool:
    normalized = log_text.casefold()
    return returncode == 0 and not any(
        marker in normalized for marker in _POPPLER_FONT_FAILURES
    )


def _clean_prefix(directory: Path, prefix: str) -> None:
    for path in directory.glob(f"{prefix}*"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)


def render_page_one(pdf_path: Path | str, output_path: Path | str) -> str:
    """Render page one and return the selected renderer name.

    The destination is removed before rendering so a failed attempt cannot leave
    a stale PNG that a later build might mistake for fresh output.
    """

    source = Path(pdf_path)
    destination = Path(output_path)
    if not source.is_file():
        raise RenderError("input PDF does not exist")
    if source.resolve() == destination.resolve():
        raise RenderError("input PDF and output PNG must be different files")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.unlink(missing_ok=True)
    except IsADirectoryError as exc:
        raise RenderError("output PNG path is a directory") from exc

    poppler_status = "unavailable"
    ghostscript_status = "unavailable"
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.render-",
        dir=destination.parent,
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)

        pdftoppm = shutil.which("pdftoppm")
        if pdftoppm is not None:
            poppler_prefix = temporary_root / "poppler-page"
            poppler_png = poppler_prefix.with_suffix(".png")
            returncode, log_text = _run(
                [
                    pdftoppm,
                    "-f",
                    "1",
                    "-l",
                    "1",
                    "-singlefile",
                    "-png",
                    "-r",
                    str(DPI),
                    "-scale-to-x",
                    str(PAGE_WIDTH_PX),
                    "-scale-to-y",
                    str(PAGE_HEIGHT_PX),
                    str(source),
                    str(poppler_prefix),
                ]
            )
            if _poppler_log_is_usable(
                returncode, log_text
            ) and _png_has_expected_geometry(poppler_png):
                os.replace(poppler_png, destination)
                return "poppler"
            poppler_status = "rejected"
            _clean_prefix(temporary_root, "poppler-page")

        ghostscript = shutil.which("gs")
        if ghostscript is not None:
            ghostscript_png = temporary_root / "ghostscript-page.png"
            returncode, _ = _run(
                [
                    ghostscript,
                    "-q",
                    "-dSAFER",
                    "-dBATCH",
                    "-dNOPAUSE",
                    "-dFirstPage=1",
                    "-dLastPage=1",
                    "-sDEVICE=png16m",
                    f"-r{DPI}",
                    f"-g{PAGE_WIDTH_PX}x{PAGE_HEIGHT_PX}",
                    "-dFIXEDMEDIA",
                    "-dPDFFitPage",
                    "-dTextAlphaBits=4",
                    "-dGraphicsAlphaBits=4",
                    f"-sOutputFile={ghostscript_png}",
                    str(source),
                ]
            )
            if returncode == 0 and _png_has_expected_geometry(ghostscript_png):
                os.replace(ghostscript_png, destination)
                return "ghostscript"
            ghostscript_status = "rejected"
            _clean_prefix(temporary_root, "ghostscript-page")

    raise RenderError(
        "no usable page renderer "
        f"(Poppler: {poppler_status}; Ghostscript: {ghostscript_status})"
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render PDF page 1 to a validated 993x1404 PNG using Poppler "
            "with a Ghostscript fallback."
        )
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        renderer = render_page_one(args.pdf, args.output)
    except (OSError, RenderError) as exc:
        print(f"render-pdf-page: error: {exc}", file=sys.stderr)
        return 1

    print(
        "render-pdf-page: "
        f"renderer={renderer} page=1 pixels={PAGE_WIDTH_PX}x{PAGE_HEIGHT_PX}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
