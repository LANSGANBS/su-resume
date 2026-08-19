#!/usr/bin/env python3
"""Compile and select the closest reference-compatible density that passes QA.

The fitter is deliberately content-preserving.  It never rewrites, truncates,
or conditionally hides content; it only compiles the same content file with
different semantic density profiles.  If no profile satisfies the exact page
target and quality thresholds, the command fails and leaves the content/page
count decision to the user.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from typing import Any, Iterable, Sequence
import zlib


PROFILE_ORDER = ("airy", "balanced", "compact", "dense")
DEFAULT_ATTEMPTS = ("balanced", "airy", "compact", "dense")
SCHEMA_VERSION = 2
MM_PER_INCH = 25.4

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_PAGE_SUFFIX = re.compile(r"-(\d+)\.pgm$")
_OVERFULL = re.compile(r"^Overfull \\[hv]box", re.MULTILINE)
_UNDERFULL = re.compile(r"^Underfull \\[hv]box", re.MULTILINE)
_MISSING_GLYPH = re.compile(
    r"^(?:Missing character: There is no|Missing character:)", re.MULTILINE
)
_TEX_ERROR = re.compile(r"^! ", re.MULTILINE)
_POPPLER_FONT_FAILURES = (
    "missing language pack",
    "unknown font tag",
    "no font in show/space",
)


class FitError(RuntimeError):
    """A deterministic user-facing fit failure."""


def _read_ascii_token(data: bytes, offset: int) -> tuple[bytes, int]:
    whitespace = b" \t\r\n\f\v"
    size = len(data)
    while offset < size:
        byte = data[offset]
        if byte in whitespace:
            offset += 1
            continue
        if byte == ord("#"):
            newline = data.find(b"\n", offset + 1)
            if newline < 0:
                raise ValueError("unterminated PGM comment")
            offset = newline + 1
            continue
        break
    if offset >= size:
        raise ValueError("unexpected end of PGM header")

    start = offset
    while offset < size and data[offset] not in whitespace:
        if data[offset] == ord("#"):
            break
        offset += 1
    if start == offset:
        raise ValueError("empty PGM token")
    return data[start:offset], offset


def read_pgm(path: Path | str) -> tuple[int, int, int, tuple[int, ...]]:
    """Read an ASCII (P2) or binary (P5) PGM using only the standard library."""

    source = Path(path)
    data = source.read_bytes()
    magic, offset = _read_ascii_token(data, 0)
    width_token, offset = _read_ascii_token(data, offset)
    height_token, offset = _read_ascii_token(data, offset)
    max_token, offset = _read_ascii_token(data, offset)

    if magic not in {b"P2", b"P5"}:
        raise ValueError(f"{source}: unsupported PGM magic {magic!r}")
    try:
        width = int(width_token)
        height = int(height_token)
        max_value = int(max_token)
    except ValueError as exc:
        raise ValueError(f"{source}: invalid numeric PGM header") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"{source}: PGM dimensions must be positive")
    if not 1 <= max_value <= 65535:
        raise ValueError(f"{source}: PGM max value must be in 1..65535")
    sample_count = width * height

    if magic == b"P2":
        pixels: list[int] = []
        while len(pixels) < sample_count:
            token, offset = _read_ascii_token(data, offset)
            try:
                value = int(token)
            except ValueError as exc:
                raise ValueError(f"{source}: invalid PGM sample") from exc
            if not 0 <= value <= max_value:
                raise ValueError(f"{source}: PGM sample outside declared range")
            pixels.append(value)
        return width, height, max_value, tuple(pixels)

    if offset >= len(data) or data[offset] not in b" \t\r\n\f\v":
        raise ValueError(f"{source}: binary PGM header lacks sample separator")
    if data[offset : offset + 2] == b"\r\n":
        offset += 2
    else:
        offset += 1

    if max_value < 256:
        expected = sample_count
        payload = data[offset : offset + expected]
        if len(payload) != expected:
            raise ValueError(
                f"{source}: expected {expected} PGM bytes, found {len(payload)}"
            )
        return width, height, max_value, tuple(payload)

    expected = sample_count * 2
    payload = data[offset : offset + expected]
    if len(payload) != expected:
        raise ValueError(
            f"{source}: expected {expected} PGM bytes, found {len(payload)}"
        )
    pixels_16 = tuple(
        (payload[index] << 8) | payload[index + 1]
        for index in range(0, expected, 2)
    )
    if any(value > max_value for value in pixels_16):
        raise ValueError(f"{source}: PGM sample outside declared range")
    return width, height, max_value, pixels_16


def read_png_grayscale(path: Path | str) -> tuple[int, int, int, tuple[int, ...]]:
    """Read a non-interlaced 8-bit PNG and composite it onto white."""

    source = Path(path)
    data = source.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"{source}: invalid PNG signature")

    offset = 8
    width = height = bit_depth = color_type = interlace = None
    palette: list[tuple[int, int, int]] | None = None
    transparency: bytes | None = None
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        crc_end = chunk_end + 4
        if crc_end > len(data):
            raise ValueError(f"{source}: truncated PNG chunk")
        chunk_data = data[chunk_start:chunk_end]
        expected_crc = struct.unpack(">I", data[chunk_end:crc_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"{source}: PNG CRC mismatch in {chunk_type!r}")

        if chunk_type == b"IHDR":
            if length != 13:
                raise ValueError(f"{source}: invalid IHDR length")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)
            if width <= 0 or height <= 0:
                raise ValueError(f"{source}: PNG dimensions must be positive")
            if compression != 0 or filter_method != 0:
                raise ValueError(f"{source}: unsupported PNG compression/filter")
        elif chunk_type == b"PLTE":
            if length % 3:
                raise ValueError(f"{source}: invalid PNG palette")
            palette = [
                tuple(chunk_data[index : index + 3])  # type: ignore[arg-type]
                for index in range(0, length, 3)
            ]
        elif chunk_type == b"tRNS":
            transparency = chunk_data
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
        offset = crc_end

    if None in {width, height, bit_depth, color_type, interlace}:
        raise ValueError(f"{source}: PNG lacks IHDR")
    assert width is not None
    assert height is not None
    assert bit_depth is not None
    assert color_type is not None
    assert interlace is not None
    if bit_depth != 8:
        raise ValueError(f"{source}: only 8-bit PNG references are supported")
    if interlace != 0:
        raise ValueError(f"{source}: interlaced PNG references are unsupported")

    channels_by_type = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    channels = channels_by_type.get(color_type)
    if channels is None:
        raise ValueError(f"{source}: unsupported PNG color type {color_type}")
    if color_type == 3 and palette is None:
        raise ValueError(f"{source}: indexed PNG lacks a palette")

    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise ValueError(f"{source}: invalid PNG compressed data") from exc
    stride = width * channels
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError(
            f"{source}: expected {expected} decoded PNG bytes, found {len(raw)}"
        )

    rows: list[bytes] = []
    previous = bytearray(stride)
    cursor = 0

    def paeth(left: int, above: int, upper_left: int) -> int:
        estimate = left + above - upper_left
        left_distance = abs(estimate - left)
        above_distance = abs(estimate - above)
        upper_left_distance = abs(estimate - upper_left)
        if left_distance <= above_distance and left_distance <= upper_left_distance:
            return left
        if above_distance <= upper_left_distance:
            return above
        return upper_left

    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor : cursor + stride]
        cursor += stride
        decoded = bytearray(stride)
        for index, byte in enumerate(encoded):
            left = decoded[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                predictor = paeth(left, above, upper_left)
            else:
                raise ValueError(f"{source}: invalid PNG filter {filter_type}")
            decoded[index] = (byte + predictor) & 0xFF
        rows.append(bytes(decoded))
        previous = decoded

    grayscale: list[int] = []
    for row in rows:
        for index in range(0, len(row), channels):
            if color_type == 0:
                red = green = blue = row[index]
                alpha = 255
                if transparency and len(transparency) >= 2:
                    transparent_gray = struct.unpack(">H", transparency[:2])[0] & 0xFF
                    if red == transparent_gray:
                        alpha = 0
            elif color_type == 2:
                red, green, blue = row[index : index + 3]
                alpha = 255
            elif color_type == 3:
                palette_index = row[index]
                assert palette is not None
                if palette_index >= len(palette):
                    raise ValueError(f"{source}: PNG palette index out of range")
                red, green, blue = palette[palette_index]
                alpha = (
                    transparency[palette_index]
                    if transparency and palette_index < len(transparency)
                    else 255
                )
            elif color_type == 4:
                red = green = blue = row[index]
                alpha = row[index + 1]
            else:
                red, green, blue, alpha = row[index : index + 4]
            gray = (299 * red + 587 * green + 114 * blue + 500) // 1000
            composited = (gray * alpha + 255 * (255 - alpha) + 127) // 255
            grayscale.append(composited)
    return width, height, 255, tuple(grayscale)


def _analyze_grayscale(
    *,
    width: int,
    height: int,
    max_value: int,
    pixels: Sequence[int],
    dpi: int,
    white_threshold: int,
) -> dict[str, Any]:
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    if not 0 <= white_threshold <= 255:
        raise ValueError("white_threshold must be in 0..255")
    threshold = round(white_threshold * max_value / 255)
    left = width
    top = height
    right = -1
    bottom = -1
    nonwhite = 0
    normalized = bytearray(len(pixels))

    for index, value in enumerate(pixels):
        normalized[index] = round(value * 255 / max_value)
        if value >= threshold:
            continue
        y, x = divmod(index, width)
        nonwhite += 1
        if x < left:
            left = x
        if x > right:
            right = x
        if y < top:
            top = y
        if y > bottom:
            bottom = y

    digest = hashlib.sha256()
    digest.update(f"{width}x{height}:".encode("ascii"))
    digest.update(normalized)
    page_area = width * height
    blank = nonwhite == 0
    if blank:
        bbox = None
        content_fill = 0.0
        bottom_whitespace_px = height
        top_whitespace_px = height
        left_whitespace_px = width
        right_whitespace_px = width
    else:
        bbox = [left, top, right, bottom]
        content_fill = (bottom - top + 1) / height
        bottom_whitespace_px = height - 1 - bottom
        top_whitespace_px = top
        left_whitespace_px = left
        right_whitespace_px = width - 1 - right

    px_to_mm = MM_PER_INCH / dpi
    return {
        "width_px": width,
        "height_px": height,
        "blank": blank,
        "bbox_px": bbox,
        "nonwhite_pixels": nonwhite,
        "ink_fill_ratio": round(nonwhite / page_area, 6),
        "content_fill_ratio": round(content_fill, 6),
        "top_whitespace_px": top_whitespace_px,
        "bottom_whitespace_px": bottom_whitespace_px,
        "left_whitespace_px": left_whitespace_px,
        "right_whitespace_px": right_whitespace_px,
        "top_whitespace_mm": round(top_whitespace_px * px_to_mm, 3),
        "bottom_whitespace_mm": round(bottom_whitespace_px * px_to_mm, 3),
        "left_whitespace_mm": round(left_whitespace_px * px_to_mm, 3),
        "right_whitespace_mm": round(right_whitespace_px * px_to_mm, 3),
        "pixel_sha256": digest.hexdigest(),
    }


def analyze_pgm(
    path: Path | str, *, dpi: int, white_threshold: int
) -> dict[str, Any]:
    """Return geometry and ink metrics for a rendered PGM page."""

    width, height, max_value, pixels = read_pgm(path)
    return _analyze_grayscale(
        width=width,
        height=height,
        max_value=max_value,
        pixels=pixels,
        dpi=dpi,
        white_threshold=white_threshold,
    )


def analyze_reference_image(
    path: Path | str, *, dpi: int, white_threshold: int
) -> dict[str, Any]:
    """Analyze a PGM or common 8-bit PNG reference image."""

    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".pgm":
        return analyze_pgm(source, dpi=dpi, white_threshold=white_threshold)
    if suffix == ".png":
        width, height, max_value, pixels = read_png_grayscale(source)
        return _analyze_grayscale(
            width=width,
            height=height,
            max_value=max_value,
            pixels=pixels,
            dpi=dpi,
            white_threshold=white_threshold,
        )
    raise ValueError(f"{source}: reference image must be .pgm or .png")


def find_duplicate_pages(page_metrics: Sequence[dict[str, Any]]) -> list[list[int]]:
    """Return one-based pairs of byte-identical rendered pages."""

    first_by_digest: dict[str, int] = {}
    duplicates: list[list[int]] = []
    for page_number, metrics in enumerate(page_metrics, start=1):
        digest = str(metrics["pixel_sha256"])
        first = first_by_digest.get(digest)
        if first is None:
            first_by_digest[digest] = page_number
        else:
            duplicates.append([first, page_number])
    return duplicates


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_log_counts(paths: Iterable[Path]) -> dict[str, int]:
    text_parts: list[str] = []
    for path in paths:
        if path.is_file():
            text_parts.append(path.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(text_parts)
    return {
        "overfull": len(_OVERFULL.findall(text)),
        "underfull": len(_UNDERFULL.findall(text)),
        "missing_glyph": len(_MISSING_GLYPH.findall(text)),
        "errors": len(_TEX_ERROR.findall(text)),
    }


def evaluate_candidate(
    candidate: dict[str, Any], thresholds: dict[str, Any]
) -> list[str]:
    """Return stable rejection reasons; an empty list means eligible."""

    reasons: list[str] = []
    if candidate.get("returncode") != 0:
        reasons.append("compile_failed")

    pages = candidate.get("pages")
    target_pages = int(thresholds["target_pages"])
    if pages != target_pages:
        reasons.append(f"page_count:{pages!s}!={target_pages}")

    counts = candidate.get("log_counts", {})
    if int(counts.get("errors", 0)) > 0:
        reasons.append(f"tex_errors:{counts['errors']}")
    if int(counts.get("overfull", 0)) > 0:
        reasons.append(f"overfull_boxes:{counts['overfull']}")
    if int(counts.get("missing_glyph", 0)) > 0:
        reasons.append(f"missing_glyphs:{counts['missing_glyph']}")
    underfull = int(counts.get("underfull", 0))
    max_underfull = int(thresholds["max_underfull"])
    if underfull > max_underfull:
        reasons.append(f"underfull_boxes:{underfull}>{max_underfull}")

    page_metrics = candidate.get("page_metrics", [])
    if pages is not None and len(page_metrics) != pages:
        reasons.append(f"raster_page_count:{len(page_metrics)}!={pages}")
    blank_pages = [
        str(index)
        for index, metrics in enumerate(page_metrics, start=1)
        if metrics.get("blank")
    ]
    if blank_pages:
        reasons.append(f"blank_pages:{','.join(blank_pages)}")

    duplicate_pairs = candidate.get("duplicate_page_pairs", [])
    if duplicate_pairs:
        rendered = ",".join(f"{left}-{right}" for left, right in duplicate_pairs)
        reasons.append(f"duplicate_pages:{rendered}")

    max_bottom = float(thresholds["max_bottom_whitespace_mm"])
    min_fill = float(thresholds["min_page_fill_ratio"])
    for page_number, metrics in enumerate(page_metrics, start=1):
        bottom = float(metrics["bottom_whitespace_mm"])
        fill = float(metrics["content_fill_ratio"])
        if bottom > max_bottom:
            reasons.append(
                f"page_{page_number}_bottom_whitespace_mm:{bottom:.3f}>{max_bottom:.3f}"
            )
        if fill < min_fill:
            reasons.append(
                f"page_{page_number}_content_fill_ratio:{fill:.6f}<{min_fill:.6f}"
            )
    page_balance = candidate.get("page_balance", {})
    fill_spread = float(page_balance.get("page_fill_spread", 0.0))
    max_fill_spread = float(thresholds["max_page_fill_spread"])
    if fill_spread > max_fill_spread:
        reasons.append(
            f"page_fill_spread:{fill_spread:.6f}>{max_fill_spread:.6f}"
        )
    bottom_spread = float(
        page_balance.get("bottom_whitespace_spread_mm", 0.0)
    )
    max_bottom_spread = float(thresholds["max_bottom_whitespace_spread_mm"])
    if bottom_spread > max_bottom_spread:
        reasons.append(
            "bottom_whitespace_spread_mm:"
            f"{bottom_spread:.3f}>{max_bottom_spread:.3f}"
        )
    return reasons


def evaluate_compiled_candidate(
    candidate: dict[str, Any],
    thresholds: dict[str, Any],
) -> list[str]:
    """Apply shared QA plus stricter gates for bounded elastic page fill."""

    reasons = evaluate_candidate(candidate, thresholds)
    if candidate.get("raster_error"):
        reasons.append(f"raster_error:{candidate['raster_error']}")
    if candidate.get("page_fill_mode") == "elastic":
        underfull = int(candidate.get("log_counts", {}).get("underfull", 0))
        if underfull > 0:
            reasons.append(f"elastic_underfull_boxes:{underfull}>0")
    return reasons


def selection_policy(
    candidates: Sequence[dict[str, Any]], *, target_pages: int
) -> tuple[list[str], str]:
    """Return a reference-first fallback order and an auditable reason."""

    attempted = [str(candidate["profile"]) for candidate in candidates]
    by_profile = {str(candidate["profile"]): candidate for candidate in candidates}
    balanced = by_profile.get("balanced")
    if balanced is None:
        ordered = sorted(
            attempted,
            key=lambda profile: (
                abs(PROFILE_ORDER.index(profile) - PROFILE_ORDER.index("balanced")),
                PROFILE_ORDER.index(profile),
            ),
        )
        return ordered, "balanced_reference_not_attempted"
    if balanced.get("eligible") is True:
        return ["balanced"], "balanced_reference_passed"

    pages = balanced.get("pages")
    counts = balanced.get("log_counts", {})
    reasons = [str(reason) for reason in balanced.get("rejection_reasons", [])]
    overflow = int(counts.get("overfull", 0)) > 0
    if (isinstance(pages, int) and pages > target_pages) or overflow:
        preferred = ["balanced", "compact", "dense", "airy"]
        reason = "reference_over_target_or_overflow"
    elif (
        (isinstance(pages, int) and pages < target_pages)
        or any("bottom_whitespace" in item for item in reasons)
        or any("content_fill_ratio" in item for item in reasons)
        or any("page_fill_spread" in item for item in reasons)
    ):
        preferred = ["balanced", "airy", "compact", "dense"]
        reason = "reference_under_target_or_underfilled"
    else:
        preferred = ["balanced", "compact", "airy", "dense"]
        reason = "reference_quality_failure"
    return [profile for profile in preferred if profile in attempted], reason


def select_profile(
    candidates: Sequence[dict[str, Any]], *, target_pages: int
) -> tuple[dict[str, Any] | None, list[str], str]:
    """Select the closest eligible fallback to the balanced visual reference."""

    by_profile = {str(candidate["profile"]): candidate for candidate in candidates}
    order, reason = selection_policy(candidates, target_pages=target_pages)
    for profile in order:
        candidate = by_profile[profile]
        if candidate.get("eligible") is True:
            return candidate, order, reason
    return None, order, reason


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
) -> int:
    with stdout_path.open("wb") as stream:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return completed.returncode


def _pdf_page_count(pdf_path: Path, *, cwd: Path, env: dict[str, str]) -> int:
    completed = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise FitError(
            f"pdfinfo failed for {pdf_path}: {completed.stderr.strip() or 'unknown error'}"
        )
    match = re.search(r"^Pages:\s*(\d+)\s*$", completed.stdout, re.MULTILINE)
    if match is None:
        raise FitError(f"pdfinfo did not report a page count for {pdf_path}")
    return int(match.group(1))


def _pgm_sort_key(path: Path) -> int:
    match = _PAGE_SUFFIX.search(path.name)
    if match is None:
        return sys.maxsize
    return int(match.group(1))


def _poppler_raster_is_usable(returncode: int, log_text: str) -> bool:
    normalized = log_text.casefold()
    return returncode == 0 and not any(
        marker in normalized for marker in _POPPLER_FONT_FAILURES
    )


def _a4_pixel_dimensions(dpi: int) -> tuple[int, int]:
    return (
        math.ceil(210 / MM_PER_INCH * dpi),
        math.ceil(297 / MM_PER_INCH * dpi),
    )


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _clean_generated_files(directory: Path, job_name: str) -> None:
    generated_names = {
        f"{job_name}.aux",
        f"{job_name}.log",
        f"{job_name}.out",
        f"{job_name}.pdf",
        f"{job_name}.xdv",
    }
    for name in generated_names:
        path = directory / name
        if path.is_file():
            path.unlink()
    for path in directory.glob(f"{job_name}.pass-*.stdout.log"):
        if path.is_file():
            path.unlink()
    for path in directory.glob(f"{job_name}.page-*.pgm"):
        if path.is_file():
            path.unlink()


def compile_candidate(
    *,
    repo_root: Path,
    content_path: Path,
    theme: str,
    profile: str,
    page_fill_mode: str,
    output_dir: Path,
    dpi: int,
    white_threshold: int,
    keep_renders: bool,
    env: dict[str, str],
) -> dict[str, Any]:
    candidate_name = (
        profile if page_fill_mode == "natural" else f"{profile}-{page_fill_mode}"
    )
    candidate_dir = output_dir / candidate_name
    candidate_dir.mkdir(parents=True, exist_ok=True)
    job_name = f"resume-{theme}-{candidate_name}"
    _clean_generated_files(candidate_dir, job_name)
    pdf_path = candidate_dir / f"{job_name}.pdf"

    content_text = content_path.resolve().as_posix()
    if any(character in content_text for character in "{}\n\r"):
        raise FitError("content path contains a character that TeX cannot safely quote")
    driver = (
        f"\\def\\ResumeTheme{{{theme}}}"
        f"\\def\\ResumeDensity{{{profile}}}"
        f"\\def\\ResumePageFill{{{page_fill_mode}}}"
        f"\\def\\ResumeContentFile{{\\detokenize{{{content_text}}}}}"
        "\\input{resume.tex}"
    )
    command = [
        "xelatex",
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-output-directory={candidate_dir}",
        f"-jobname={job_name}",
        driver,
    ]

    returncode = 0
    stdout_logs: list[Path] = []
    for pass_number in (1, 2):
        stdout_path = candidate_dir / f"{job_name}.pass-{pass_number}.stdout.log"
        stdout_logs.append(stdout_path)
        returncode = _run(command, cwd=repo_root, env=env, stdout_path=stdout_path)
        if returncode != 0:
            break

    tex_log = candidate_dir / f"{job_name}.log"
    counts = parse_log_counts(
        [tex_log] if tex_log.is_file() else stdout_logs[-1:]
    )
    pages: int | None = None
    page_metrics: list[dict[str, Any]] = []
    render_returncode: int | None = None
    rasterizer: str | None = None
    raster_error: str | None = None

    if returncode == 0 and pdf_path.is_file():
        try:
            pages = _pdf_page_count(pdf_path, cwd=repo_root, env=env)
            render_prefix = candidate_dir / f"{job_name}.page"
            render_stdout = candidate_dir / f"{job_name}.render.stdout.log"
            render_returncode = _run(
                [
                    "pdftoppm",
                    "-gray",
                    "-r",
                    str(dpi),
                    str(pdf_path),
                    str(render_prefix),
                ],
                cwd=repo_root,
                env=env,
                stdout_path=render_stdout,
            )
            poppler_log = render_stdout.read_text(
                encoding="utf-8",
                errors="replace",
            )
            if _poppler_raster_is_usable(render_returncode, poppler_log):
                rasterizer = "pdftoppm"
            else:
                for partial_render in candidate_dir.glob(
                    f"{job_name}.page-*.pgm"
                ):
                    partial_render.unlink(missing_ok=True)
                ghostscript = shutil.which("gs")
                if ghostscript is None:
                    raster_error = (
                        "pdftoppm produced unusable font/CMap output and "
                        "Ghostscript is unavailable"
                    )
                else:
                    width_px, height_px = _a4_pixel_dimensions(dpi)
                    ghostscript_stdout = (
                        candidate_dir
                        / f"{job_name}.ghostscript-render.stdout.log"
                    )
                    render_returncode = _run(
                        [
                            ghostscript,
                            "-q",
                            "-dSAFER",
                            "-dBATCH",
                            "-dNOPAUSE",
                            "-sDEVICE=pgmraw",
                            f"-r{dpi}",
                            f"-g{width_px}x{height_px}",
                            "-dFIXEDMEDIA",
                            "-dPDFFitPage",
                            "-dTextAlphaBits=4",
                            "-dGraphicsAlphaBits=4",
                            (
                                "-sOutputFile="
                                f"{render_prefix.as_posix()}-%d.pgm"
                            ),
                            str(pdf_path),
                        ],
                        cwd=repo_root,
                        env=env,
                        stdout_path=ghostscript_stdout,
                    )
                    if render_returncode == 0:
                        rasterizer = "ghostscript"
                    else:
                        raster_error = (
                            "pdftoppm output was unusable and Ghostscript "
                            "fallback failed"
                        )
            pgm_paths = sorted(
                candidate_dir.glob(f"{job_name}.page-*.pgm"), key=_pgm_sort_key
            )
            if raster_error is None:
                for pgm_path in pgm_paths:
                    metrics = analyze_pgm(
                        pgm_path,
                        dpi=dpi,
                        white_threshold=white_threshold,
                    )
                    if keep_renders:
                        metrics["render"] = _display_path(pgm_path, repo_root)
                    page_metrics.append(metrics)
            if not keep_renders:
                for pgm_path in pgm_paths:
                    pgm_path.unlink(missing_ok=True)
                render_stdout.unlink(missing_ok=True)
                for ghostscript_log in candidate_dir.glob(
                    f"{job_name}.ghostscript-render.stdout.log"
                ):
                    ghostscript_log.unlink(missing_ok=True)
        except (FitError, OSError, ValueError) as exc:
            raster_error = str(exc)

    candidate: dict[str, Any] = {
        "profile": profile,
        "page_fill_mode": page_fill_mode,
        "returncode": returncode,
        "render_returncode": render_returncode,
        "rasterizer": rasterizer,
        "raster_error": raster_error,
        "pdf": _display_path(pdf_path, repo_root) if pdf_path.is_file() else None,
        "_pdf_path": pdf_path.resolve().as_posix() if pdf_path.is_file() else None,
        "pages": pages,
        "log_counts": counts,
        "page_metrics": page_metrics,
        "page_balance": {
            "page_fill_spread": round(
                (
                    max(
                        float(metrics["content_fill_ratio"])
                        for metrics in page_metrics
                    )
                    - min(
                        float(metrics["content_fill_ratio"])
                        for metrics in page_metrics
                    )
                )
                if page_metrics
                else 0.0,
                6,
            ),
            "bottom_whitespace_spread_mm": round(
                (
                    max(
                        float(metrics["bottom_whitespace_mm"])
                        for metrics in page_metrics
                    )
                    - min(
                        float(metrics["bottom_whitespace_mm"])
                        for metrics in page_metrics
                    )
                )
                if page_metrics
                else 0.0,
                3,
            ),
        },
        "duplicate_page_pairs": find_duplicate_pages(page_metrics),
        "eligible": False,
        "rejection_reasons": [],
    }
    return candidate


def _underfill_only(reasons: Sequence[str]) -> bool:
    if not reasons:
        return False
    allowed_fragments = (
        "_bottom_whitespace_mm:",
        "_content_fill_ratio:",
        "page_fill_spread:",
        "bottom_whitespace_spread_mm:",
    )
    return all(any(fragment in reason for fragment in allowed_fragments) for reason in reasons)


def _selection_detail(
    selected: dict[str, Any] | None,
    attempted_page_fill_modes: Sequence[str],
) -> str:
    if selected is None:
        return "no_eligible_candidate"
    if selected.get("page_fill_mode") == "elastic":
        return "balanced_elastic_underfill_recovery"
    if "elastic" in attempted_page_fill_modes:
        return "natural_profile_selection_after_elastic_rejection"
    return "natural_profile_selection"


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parse_profiles(raw_profiles: Sequence[str]) -> list[str]:
    profiles: list[str] = []
    for value in raw_profiles:
        profiles.extend(part for part in value.split(",") if part)
    if not profiles:
        raise FitError("at least one density profile is required")
    unknown = [profile for profile in profiles if profile not in PROFILE_ORDER]
    if unknown:
        raise FitError(
            "unknown density profile(s): "
            + ", ".join(unknown)
            + "; use airy, balanced, compact, or dense"
        )
    if len(set(profiles)) != len(profiles):
        raise FitError("density profiles must not be repeated")
    missing = [profile for profile in PROFILE_ORDER if profile not in profiles]
    if missing:
        raise FitError(
            "--profiles must include all four reference-policy candidates exactly "
            f"once; missing: {', '.join(missing)}"
        )
    return profiles


def _check_dependencies() -> None:
    missing = [
        command
        for command in ("xelatex", "pdfinfo", "pdftoppm")
        if shutil.which(command) is None
    ]
    if missing:
        raise FitError("required command(s) not found: " + ", ".join(missing))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile every requested density and select the closest eligible "
            "fallback to balanced that preserves content and exact pagination."
        )
    )
    parser.add_argument("--content", required=True, help="TeX content fragment")
    parser.add_argument("--theme", default="ocean", help="semantic color theme")
    parser.add_argument(
        "--target-pages",
        type=int,
        default=1,
        help=(
            "required exact positive page count; built-in regression fixtures "
            "cover one and two pages"
        ),
    )
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=list(DEFAULT_ATTEMPTS),
        help=(
            "compile order; must contain balanced, airy, compact, and dense "
            "exactly once"
        ),
    )
    parser.add_argument("--output-dir", help="generated candidate directory")
    parser.add_argument("--manifest", help="JSON manifest path")
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--white-threshold", type=int, default=250)
    parser.add_argument("--max-bottom-whitespace-mm", type=float, default=22.0)
    parser.add_argument("--min-page-fill-ratio", type=float, default=0.62)
    parser.add_argument("--max-page-fill-spread", type=float, default=0.22)
    parser.add_argument(
        "--max-bottom-whitespace-spread-mm", type=float, default=25.0
    )
    parser.add_argument("--max-underfull", type=int, default=20)
    parser.add_argument(
        "--keep-renders",
        action="store_true",
        help="retain intermediate PGM page renders for debugging",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _check_dependencies()
        repo_root = Path(__file__).resolve().parent.parent
        content_path = Path(args.content)
        if not content_path.is_absolute():
            content_path = repo_root / content_path
        if not content_path.is_file():
            raise FitError(f"content fixture not found: {args.content}")
        if args.target_pages <= 0:
            raise FitError("--target-pages must be positive")
        if not _SAFE_NAME.fullmatch(args.theme):
            raise FitError("--theme must match [a-z][a-z0-9_-]*")
        profiles = _parse_profiles(args.profiles)
        if args.dpi <= 0:
            raise FitError("--dpi must be positive")
        if not 0 <= args.white_threshold <= 255:
            raise FitError("--white-threshold must be in 0..255")
        if args.max_bottom_whitespace_mm < 0:
            raise FitError("--max-bottom-whitespace-mm must not be negative")
        if not 0 <= args.min_page_fill_ratio <= 1:
            raise FitError("--min-page-fill-ratio must be in 0..1")
        if not 0 <= args.max_page_fill_spread <= 1:
            raise FitError("--max-page-fill-spread must be in 0..1")
        if args.max_bottom_whitespace_spread_mm < 0:
            raise FitError(
                "--max-bottom-whitespace-spread-mm must not be negative"
            )
        if args.max_underfull < 0:
            raise FitError("--max-underfull must not be negative")

        content_label = _display_path(content_path, repo_root)
        default_output = (
            repo_root / "build" / "fit" / f"{content_path.stem}-{args.theme}"
        )
        output_dir = Path(args.output_dir) if args.output_dir else default_output
        if not output_dir.is_absolute():
            output_dir = repo_root / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = (
            Path(args.manifest)
            if args.manifest
            else output_dir / "manifest.json"
        )
        if not manifest_path.is_absolute():
            manifest_path = repo_root / manifest_path
        temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
        fitted_pdf = output_dir / f"resume-{args.theme}-fit.pdf"
        temporary_fitted_pdf = output_dir / f".resume-{args.theme}-fit.pdf.tmp"
        # A failed rerun must never leave a previously successful final PDF or
        # manifest that could be mistaken for the result of this invocation.
        fitted_pdf.unlink(missing_ok=True)
        temporary_fitted_pdf.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)

        content_sha256 = sha256_file(content_path)
        entrypoint_sha256 = sha256_file(repo_root / "resume.tex")
        layout_sha256 = sha256_file(repo_root / "resume-layout.tex")
        components_path = repo_root / "resume-components.tex"
        theme_path = repo_root / "theme.tex"
        components_sha256 = (
            sha256_file(components_path) if components_path.is_file() else None
        )
        theme_sha256 = sha256_file(theme_path) if theme_path.is_file() else None

        thresholds: dict[str, Any] = {
            "target_pages": args.target_pages,
            "dpi": args.dpi,
            "white_threshold": args.white_threshold,
            "max_bottom_whitespace_mm": args.max_bottom_whitespace_mm,
            "min_page_fill_ratio": args.min_page_fill_ratio,
            "max_page_fill_spread": args.max_page_fill_spread,
            "max_bottom_whitespace_spread_mm": (
                args.max_bottom_whitespace_spread_mm
            ),
            "max_underfull": args.max_underfull,
        }
        env = os.environ.copy()
        env.update(
            {
                "FORCE_SOURCE_DATE": "1",
                "SOURCE_DATE_EPOCH": env.get("SOURCE_DATE_EPOCH", "946684800"),
                "TZ": "UTC",
            }
        )

        candidates: list[dict[str, Any]] = []
        for profile in profiles:
            print(f"fit-resume: compiling {profile}", flush=True)
            candidate = compile_candidate(
                repo_root=repo_root,
                content_path=content_path,
                theme=args.theme,
                profile=profile,
                page_fill_mode="natural",
                output_dir=output_dir,
                dpi=args.dpi,
                white_threshold=args.white_threshold,
                keep_renders=args.keep_renders,
                env=env,
            )
            reasons = evaluate_compiled_candidate(candidate, thresholds)
            candidate["rejection_reasons"] = reasons
            candidate["eligible"] = not reasons
            candidates.append(candidate)

        page_fill_attempts: list[dict[str, Any]] = []
        attempted_page_fill_modes = ["natural"]
        selected, selection_order, selection_reason = select_profile(
            candidates, target_pages=args.target_pages
        )
        if selected is None and args.target_pages > 1:
            balanced_index = next(
                (
                    index
                    for index, candidate in enumerate(candidates)
                    if candidate["profile"] == "balanced"
                ),
                None,
            )
            if balanced_index is not None:
                natural_balanced = candidates[balanced_index]
                natural_reasons = natural_balanced["rejection_reasons"]
                if _underfill_only(natural_reasons):
                    page_fill_attempts.append(copy.deepcopy(natural_balanced))
                    print(
                        "fit-resume: no natural profile passed and balanced "
                        "is underfilled; "
                        "compiling bounded elastic fill",
                        flush=True,
                    )
                    elastic_balanced = compile_candidate(
                        repo_root=repo_root,
                        content_path=content_path,
                        theme=args.theme,
                        profile="balanced",
                        page_fill_mode="elastic",
                        output_dir=output_dir,
                        dpi=args.dpi,
                        white_threshold=args.white_threshold,
                        keep_renders=args.keep_renders,
                        env=env,
                    )
                    elastic_reasons = evaluate_compiled_candidate(
                        elastic_balanced, thresholds
                    )
                    elastic_balanced["rejection_reasons"] = elastic_reasons
                    elastic_balanced["eligible"] = not elastic_reasons
                    page_fill_attempts.append(copy.deepcopy(elastic_balanced))
                    attempted_page_fill_modes.append("elastic")
                    if elastic_balanced["eligible"]:
                        candidates[balanced_index] = elastic_balanced
                        selected = elastic_balanced

        content_sha256_after = sha256_file(content_path)
        if content_sha256_after != content_sha256:
            raise FitError("content changed during fitting; refusing all output")

        selected_pdf: str | None = None
        if selected is not None:
            source_pdf = Path(str(selected["_pdf_path"]))
            shutil.copy2(source_pdf, temporary_fitted_pdf)
            temporary_fitted_pdf.replace(fitted_pdf)
            selected_pdf = _display_path(fitted_pdf, repo_root)

        for collection in (candidates, page_fill_attempts):
            for candidate in collection:
                candidate.pop("_pdf_path", None)

        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "success": selected is not None,
            "inputs": {
                "content": content_label,
                "theme": args.theme,
                "target_pages": args.target_pages,
                "content_preserved": content_sha256_after == content_sha256,
                "content_sha256": content_sha256,
                "entrypoint_sha256": entrypoint_sha256,
                "layout_sha256": layout_sha256,
                "components_sha256": components_sha256,
                "theme_sha256": theme_sha256,
            },
            "thresholds": thresholds,
            "selection_policy": "balanced-reference-v1",
            "attempted_profiles": profiles,
            "attempted_page_fill_modes": attempted_page_fill_modes,
            "page_fill_attempts": page_fill_attempts,
            "selection_order": selection_order,
            "selection_reason": selection_reason,
            "selection_detail": _selection_detail(
                selected, attempted_page_fill_modes
            ),
            "selected_profile": selected["profile"] if selected else None,
            "selected_page_fill_mode": (
                selected.get("page_fill_mode") if selected else None
            ),
            "selected_pdf": selected_pdf,
            "candidates": candidates,
        }
        _write_manifest(manifest_path, manifest)

        if selected is None:
            print(
                "fit-resume: no density profile satisfied the exact "
                f"{args.target_pages}-page target and layout thresholds.",
                file=sys.stderr,
            )
            print(
                "fit-resume: content was not modified. Decide whether to revise "
                "content or explicitly allow a different target page count.",
                file=sys.stderr,
            )
            print(
                f"fit-resume: diagnostics: {_display_path(manifest_path, repo_root)}",
                file=sys.stderr,
            )
            return 1

        print(
            "fit-resume: selected "
            f"{selected['profile']}+{selected['page_fill_mode']} -> {selected_pdf}",
            flush=True,
        )
        print(
            f"fit-resume: manifest -> {_display_path(manifest_path, repo_root)}",
            flush=True,
        )
        return 0
    except FitError as exc:
        print(f"fit-resume: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
