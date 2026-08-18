#!/usr/bin/env python3
"""Build, page-check, render, and summarize the resume PDF."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any


THEME_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
OVERFULL_RE = re.compile(
    r"Overfull \\(?:hbox|vbox) \(([\d.]+)pt too (?:wide|high)\)"
)
MISSING_CHARACTER_RE = re.compile(r"^Missing character:", re.MULTILINE)
UNDERFULL_RE = re.compile(r"^Underfull \\(?:hbox|vbox)", re.MULTILINE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compile the template with XeLaTeX, enforce a page count, inspect "
            "layout warnings, render every PDF page, and write a QA manifest."
        )
    )
    parser.add_argument("repo_root", type=Path, help="Resume repository root.")
    parser.add_argument(
        "--main", default="resume.tex", help="Main TeX file relative to the repository."
    )
    parser.add_argument(
        "--content",
        default="content.tex",
        help="Content TeX file relative to the repository.",
    )
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        help="Theme to validate; repeat to validate multiple themes.",
    )
    parser.add_argument(
        "--all-themes",
        action="store_true",
        help="Validate every theme discovered in theme.tex.",
    )
    parser.add_argument(
        "--allow-identical-themes",
        action="store_true",
        help="Permit byte-identical first-page renders for differently named themes.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="QA output directory, preferably inside the private workspace.",
    )
    parser.add_argument(
        "--expected-pages",
        type=int,
        default=1,
        help="Required PDF page count (default: 1).",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=2,
        help="Number of XeLaTeX passes (default: 2).",
    )
    parser.add_argument(
        "--render-dpi",
        type=int,
        default=170,
        help="PNG rendering resolution (default: 170 DPI).",
    )
    parser.add_argument(
        "--max-overfull-pt",
        type=float,
        default=0.5,
        help="Largest permitted overfull box in points (default: 0.5).",
    )
    parser.add_argument(
        "--xelatex",
        help="XeLaTeX executable name or path (default: discover xelatex).",
    )
    parser.add_argument(
        "--theme-file",
        default="theme.tex",
        help="Theme definition file relative to the repository.",
    )
    return parser.parse_args()


def resolve_repo_file(repo_root: Path, relative: str, label: str) -> Path:
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside the repository") from exc
    if not candidate.is_file():
        raise ValueError(f"{label} does not exist: {candidate}")
    return candidate


def discover_themes(theme_file: Path) -> list[str]:
    text = theme_file.read_text(encoding="utf-8")
    discovered: list[str] = []
    default_match = re.search(
        r"\\providecommand\s*\{\\ResumeTheme\}\s*\{([^{}]+)\}", text
    )
    if default_match:
        discovered.append(default_match.group(1).strip())
    for match in re.finditer(
        r"\\(?:ifstrequal|ifdefstring)\s*\{\\ResumeTheme\}\s*\{([^{}]+)\}",
        text,
    ):
        discovered.append(match.group(1).strip())
    result: list[str] = []
    for theme in discovered:
        if THEME_NAME_RE.fullmatch(theme) and theme not in result:
            result.append(theme)
    if not result:
        raise ValueError(f"could not discover any themes in {theme_file}")
    return result


def validate_source_layout(main_file: Path, content_file: Path) -> list[str]:
    errors: list[str] = []
    main_text = main_file.read_text(encoding="utf-8")
    content_text = content_file.read_text(encoding="utf-8")
    if "\\ResumeTheme" not in main_text:
        errors.append("main file does not expose \\ResumeTheme")
    content_stem = re.escape(content_file.stem)
    if not re.search(
        rf"\\input\s*\{{[^}}]*{content_stem}(?:\.tex)?\s*\}}", main_text
    ):
        errors.append(f"main file does not input {content_file.name}")
    for forbidden in ("\\documentclass", "\\begin{document}", "\\end{document}"):
        if forbidden in content_text:
            errors.append(f"{content_file.name} must not contain {forbidden}")
    if not content_text.strip():
        errors.append(f"{content_file.name} is empty")
    return errors


def locate_executable(value: str | None, default: str) -> str:
    if value:
        candidate = Path(value).expanduser()
        if candidate.parent != Path("."):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
            raise ValueError(f"executable is not runnable: {candidate}")
        resolved = shutil.which(value)
    else:
        resolved = shutil.which(default)
    if not resolved:
        raise ValueError(f"required executable was not found: {value or default}")
    return resolved


def clean_previous_outputs(output_dir: Path, jobname: str) -> None:
    prefixes = (jobname, "page-", "console-pass")
    for candidate in output_dir.iterdir():
        if candidate.is_file() and candidate.name.startswith(prefixes):
            candidate.unlink()


def tex_entry_expression(main_relative: str, theme: str) -> str:
    if any(character in main_relative for character in ('"', "{", "}", "%", "#", "\n", "\r")):
        raise ValueError("main TeX path contains a character unsupported by XeLaTeX")
    normalized = main_relative.replace("\\", "/")
    return rf'\def\ResumeTheme{{{theme}}}\input{{"{normalized}"}}'


def run_xelatex(
    xelatex: str,
    repo_root: Path,
    main_relative: str,
    theme: str,
    output_dir: Path,
    jobname: str,
    passes: int,
) -> tuple[bool, list[str]]:
    console_logs: list[str] = []
    expression = tex_entry_expression(main_relative, theme)
    command = [
        xelatex,
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-jobname={jobname}",
        f"-output-directory={output_dir}",
        expression,
    ]
    for pass_number in range(1, passes + 1):
        completed = subprocess.run(
            command,
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        console_path = output_dir / f"console-pass{pass_number}.log"
        console_path.write_text(completed.stdout, encoding="utf-8")
        console_logs.append(str(console_path))
        if completed.returncode != 0:
            return False, console_logs
    return True, console_logs


def read_page_count(pdf_path: Path) -> tuple[int, str]:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        completed = subprocess.run(
            [pdfinfo, str(pdf_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        match = re.search(r"^Pages:\s*(\d+)\s*$", completed.stdout, re.MULTILINE)
        if completed.returncode == 0 and match:
            return int(match.group(1)), "pdfinfo"

    qpdf = shutil.which("qpdf")
    if qpdf:
        completed = subprocess.run(
            [qpdf, "--show-npages", str(pdf_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode == 0 and completed.stdout.strip().isdigit():
            return int(completed.stdout.strip()), "qpdf"

    try:
        from pypdf import PdfReader  # type: ignore

        return len(PdfReader(str(pdf_path)).pages), "pypdf"
    except (ImportError, OSError, ValueError):
        pass
    raise RuntimeError("could not count PDF pages; install pdfinfo, qpdf, or pypdf")


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"renderer did not create a valid PNG: {path}")
    return struct.unpack(">II", header[16:24])


def render_pdf(pdf_path: Path, output_dir: Path, dpi: int) -> tuple[list[Path], str]:
    prefix = output_dir / "page"
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        command = [pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(prefix)]
        renderer = "pdftoppm"
    else:
        pdftocairo = shutil.which("pdftocairo")
        if pdftocairo:
            command = [
                pdftocairo,
                "-png",
                "-r",
                str(dpi),
                str(pdf_path),
                str(prefix),
            ]
            renderer = "pdftocairo"
        else:
            mutool = shutil.which("mutool")
            if not mutool:
                raise RuntimeError(
                    "could not render PDF; install pdftoppm, pdftocairo, or mutool"
                )
            command = [
                mutool,
                "draw",
                "-r",
                str(dpi),
                "-o",
                str(output_dir / "page-%d.png"),
                str(pdf_path),
            ]
            renderer = "mutool"

    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "PDF renderer failed")

    images = sorted(
        output_dir.glob("page-*.png"),
        key=lambda path: int(re.search(r"(\d+)$", path.stem).group(1))
        if re.search(r"(\d+)$", path.stem)
        else 0,
    )
    if not images:
        raise RuntimeError("PDF renderer produced no page images")
    return images, renderer


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_log(log_path: Path, max_overfull_pt: float) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    overfull_values = [float(match.group(1)) for match in OVERFULL_RE.finditer(text)]
    return {
        "overfull_boxes": len(overfull_values),
        "largest_overfull_pt": max(overfull_values, default=0.0),
        "underfull_boxes": len(UNDERFULL_RE.findall(text)),
        "missing_characters": len(MISSING_CHARACTER_RE.findall(text)),
        "overfull_limit_exceeded": any(
            value > max_overfull_pt for value in overfull_values
        ),
    }


def flag_duplicate_theme_renders(results: list[dict[str, Any]]) -> list[list[str]]:
    """Fail differently named themes whose first rendered pages are identical."""
    by_digest: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        rendered_pages = result.get("rendered_pages")
        if not isinstance(rendered_pages, list) or not rendered_pages:
            continue
        first_page = rendered_pages[0]
        if not isinstance(first_page, dict):
            continue
        digest = first_page.get("sha256")
        if isinstance(digest, str) and digest:
            by_digest.setdefault(digest, []).append(result)

    duplicate_groups: list[list[str]] = []
    for matching_results in by_digest.values():
        if len(matching_results) < 2:
            continue
        themes = sorted(str(result["theme"]) for result in matching_results)
        duplicate_groups.append(themes)
        message = (
            "first rendered page is byte-identical across themes: "
            + ", ".join(themes)
        )
        for result in matching_results:
            result.setdefault("errors", []).append(message)
            result["status"] = "failed"
    return sorted(duplicate_groups)


def tail(path: Path, lines: int = 30) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def validate_theme(
    *,
    xelatex: str,
    repo_root: Path,
    main_relative: str,
    theme: str,
    output_root: Path,
    expected_pages: int,
    passes: int,
    render_dpi: int,
    max_overfull_pt: float,
) -> dict[str, Any]:
    output_dir = output_root / theme
    output_dir.mkdir(parents=True, exist_ok=True)
    jobname = f"resume-{theme}"
    clean_previous_outputs(output_dir, jobname)
    result: dict[str, Any] = {
        "theme": theme,
        "status": "failed",
        "errors": [],
        "visual_qa_required": True,
    }
    compiled, console_logs = run_xelatex(
        xelatex,
        repo_root,
        main_relative,
        theme,
        output_dir,
        jobname,
        passes,
    )
    result["console_logs"] = console_logs
    if not compiled:
        result["errors"].append("XeLaTeX compilation failed")
        result["compiler_tail"] = tail(Path(console_logs[-1]))
        return result

    pdf_path = output_dir / f"{jobname}.pdf"
    tex_log_path = output_dir / f"{jobname}.log"
    if not pdf_path.is_file() or not tex_log_path.is_file():
        result["errors"].append("compiler did not produce the expected PDF and log")
        return result

    result["pdf"] = str(pdf_path)
    result["pdf_sha256"] = file_digest(pdf_path)
    try:
        pages, page_counter = read_page_count(pdf_path)
        result["pages"] = pages
        result["page_counter"] = page_counter
        if pages != expected_pages:
            result["errors"].append(
                f"expected {expected_pages} page(s), produced {pages}"
            )
    except RuntimeError as exc:
        pages = 0
        result["errors"].append(str(exc))

    log_summary = inspect_log(tex_log_path, max_overfull_pt)
    result["log_summary"] = log_summary
    if log_summary["overfull_limit_exceeded"]:
        result["errors"].append(
            "overfull box exceeds "
            f"{max_overfull_pt:.2f}pt "
            f"(largest: {log_summary['largest_overfull_pt']:.2f}pt)"
        )
    if log_summary["missing_characters"]:
        result["errors"].append(
            f"log reports {log_summary['missing_characters']} missing character(s)"
        )

    try:
        images, renderer = render_pdf(pdf_path, output_dir, render_dpi)
        rendered = []
        for image in images:
            width, height = png_dimensions(image)
            rendered.append(
                {
                    "path": str(image),
                    "width": width,
                    "height": height,
                    "sha256": file_digest(image),
                }
            )
        result["renderer"] = renderer
        result["rendered_pages"] = rendered
        if pages and len(images) != pages:
            result["errors"].append(
                f"rendered {len(images)} page image(s) for a {pages}-page PDF"
            )
    except RuntimeError as exc:
        result["errors"].append(str(exc))

    if not result["errors"]:
        result["status"] = "passed"
    return result


def main() -> int:
    args = parse_args()
    if args.expected_pages <= 0:
        print("error: --expected-pages must be positive", file=sys.stderr)
        return 2
    if args.passes <= 0:
        print("error: --passes must be positive", file=sys.stderr)
        return 2
    if args.render_dpi < 72:
        print("error: --render-dpi must be at least 72", file=sys.stderr)
        return 2
    if args.max_overfull_pt < 0:
        print("error: --max-overfull-pt cannot be negative", file=sys.stderr)
        return 2

    repo_root = args.repo_root.expanduser().resolve()
    if not repo_root.is_dir():
        print(f"error: repository root does not exist: {repo_root}", file=sys.stderr)
        return 2
    try:
        main_file = resolve_repo_file(repo_root, args.main, "main file")
        content_file = resolve_repo_file(repo_root, args.content, "content file")
        theme_file = resolve_repo_file(repo_root, args.theme_file, "theme file")
        known_themes = discover_themes(theme_file)
        xelatex = locate_executable(args.xelatex, "xelatex")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    layout_errors = validate_source_layout(main_file, content_file)
    if layout_errors:
        print("source validation failed:")
        for error in layout_errors:
            print(f"- {error}")
        return 1

    requested = known_themes if args.all_themes else (args.theme or [known_themes[0]])
    themes: list[str] = []
    for theme in requested:
        if not THEME_NAME_RE.fullmatch(theme):
            print(f"error: invalid theme name: {theme}", file=sys.stderr)
            return 2
        if theme not in known_themes:
            print(
                f"error: unknown theme {theme!r}; available: {', '.join(known_themes)}",
                file=sys.stderr,
            )
            return 2
        if theme not in themes:
            themes.append(theme)

    output_root = args.out_dir.expanduser().resolve()
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create output directory: {exc}", file=sys.stderr)
        return 2

    main_relative = main_file.relative_to(repo_root).as_posix()
    try:
        tex_entry_expression(main_relative, themes[0])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    results = [
        validate_theme(
            xelatex=xelatex,
            repo_root=repo_root,
            main_relative=main_relative,
            theme=theme,
            output_root=output_root,
            expected_pages=args.expected_pages,
            passes=args.passes,
            render_dpi=args.render_dpi,
            max_overfull_pt=args.max_overfull_pt,
        )
        for theme in themes
    ]
    duplicate_theme_groups: list[list[str]] = []
    if len(results) > 1 and not args.allow_identical_themes:
        duplicate_theme_groups = flag_duplicate_theme_renders(results)
    manifest = {
        "repo_root": str(repo_root),
        "main": str(main_file),
        "content": str(content_file),
        "expected_pages": args.expected_pages,
        "render_dpi": args.render_dpi,
        "max_overfull_pt": args.max_overfull_pt,
        "duplicate_theme_groups": duplicate_theme_groups,
        "themes": results,
    }
    manifest_path = output_root / "validation-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for result in results:
        pages = result.get("pages", "?")
        rendered_count = len(result.get("rendered_pages", []))
        print(
            f"{result['theme']}: {result['status']} "
            f"(pages={pages}, rendered={rendered_count})"
        )
        for error in result["errors"]:
            print(f"  - {error}")
    print(f"QA manifest: {manifest_path}")

    return int(any(result["status"] != "passed" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
