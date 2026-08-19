#!/usr/bin/env python3
"""Verify that two PDFs expose the same normalized visible-text sequence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
NORMALIZATION = "unicode-nfkc-remove-all-whitespace-v1"
PDF_TEXT_FAILURE_MARKERS = (
    "missing language pack",
    "unknown font tag",
    "no font in show/space",
)


class ParityError(RuntimeError):
    """A deterministic user-facing parity validation failure."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract visible text with pdftotext, normalize Unicode and "
            "whitespace, then require the baseline and candidate sequences "
            "to be exactly identical."
        )
    )
    parser.add_argument("baseline_pdf", type=Path)
    parser.add_argument("candidate_pdf", type=Path)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def normalize_visible_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(character for character in normalized if not character.isspace())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def first_mismatch(left: str, right: str) -> int | None:
    for index, (left_character, right_character) in enumerate(zip(left, right)):
        if left_character != right_character:
            return index
    if len(left) != len(right):
        return min(len(left), len(right))
    return None


def validate_extracted_text(text: str, diagnostics: str, source: Path) -> None:
    normalized_diagnostics = diagnostics.casefold()
    failures = [
        marker
        for marker in PDF_TEXT_FAILURE_MARKERS
        if marker in normalized_diagnostics
    ]
    if failures:
        raise ParityError(
            "pdftotext reported unusable font/CMap output for "
            f"{source}: {', '.join(failures)}"
        )
    if not normalize_visible_text(text):
        raise ParityError(f"pdftotext extracted no visible text from {source}")


def extract_pdf_text(path: Path) -> str:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ParityError(f"PDF does not exist: {source}")
    executable = shutil.which("pdftotext")
    if executable is None:
        raise ParityError("required command not found: pdftotext")

    with tempfile.TemporaryDirectory(prefix="resume-text-parity-") as directory:
        output = Path(directory) / "visible.txt"
        completed = subprocess.run(
            [executable, "-layout", str(source), str(output)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown extraction error"
            raise ParityError(f"pdftotext failed for {source}: {detail}")
        try:
            text = output.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ParityError(f"cannot read extracted text for {source}: {exc}") from exc
        validate_extracted_text(text, completed.stderr, source)
        return text


def compare_texts(
    baseline_text: str,
    candidate_text: str,
    *,
    baseline_label: str,
    candidate_label: str,
) -> dict[str, Any]:
    baseline_normalized = normalize_visible_text(baseline_text)
    candidate_normalized = normalize_visible_text(candidate_text)
    mismatch = first_mismatch(baseline_normalized, candidate_normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "normalization": NORMALIZATION,
        "identical": mismatch is None,
        "baseline": {
            "path": baseline_label,
            "normalized_characters": len(baseline_normalized),
            "sha256": sha256_text(baseline_normalized),
        },
        "candidate": {
            "path": candidate_label,
            "normalized_characters": len(candidate_normalized),
            "sha256": sha256_text(candidate_normalized),
        },
        "first_mismatch_index": mismatch,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def main() -> int:
    args = parse_args()
    try:
        baseline = args.baseline_pdf.expanduser().resolve()
        candidate = args.candidate_pdf.expanduser().resolve()
        result = compare_texts(
            extract_pdf_text(baseline),
            extract_pdf_text(candidate),
            baseline_label=str(baseline),
            candidate_label=str(candidate),
        )
        if args.json_out is not None:
            write_json(args.json_out, result)
    except (OSError, ParityError) as exc:
        print(f"text parity error: {exc}", file=sys.stderr)
        return 2

    if result["identical"]:
        print(
            "visible-text parity passed: "
            f"characters={result['baseline']['normalized_characters']}, "
            f"sha256={result['baseline']['sha256']}"
        )
        return 0

    print(
        "visible-text parity failed: "
        f"baseline_chars={result['baseline']['normalized_characters']}, "
        f"candidate_chars={result['candidate']['normalized_characters']}, "
        f"first_mismatch_index={result['first_mismatch_index']}",
        file=sys.stderr,
    )
    print(
        "The candidate changed, removed, added, or reordered visible text. "
        "Do not deliver it in read-only adaptation mode.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
