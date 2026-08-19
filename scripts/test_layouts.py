#!/usr/bin/env python3
"""Run the theme matrix and adaptive-layout fixture regression suite."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Sequence

try:
    from .fit_resume import (
        analyze_reference_image,
        read_pgm,
        read_png_grayscale,
    )
except ImportError:  # Direct script execution places scripts/ on sys.path.
    from fit_resume import (
        analyze_reference_image,
        read_pgm,
        read_png_grayscale,
    )


CONFIG_SCHEMA_VERSION = 1
FIT_MANIFEST_SCHEMA_VERSION = 2
REGRESSION_SCHEMA_VERSION = 1
_AUX_MARKER_PREFIX = "resume-page-marker:"
_MARKER_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_POSITIVE_PAGE = re.compile(r"^[1-9][0-9]*$")


class RegressionError(RuntimeError):
    """A configuration or fixture error."""


def _load_json(path: Path, *, schema_version: int) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegressionError(f"layout case file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RegressionError(
            f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise RegressionError(f"{path}: root must be an object")
    if payload.get("schema_version") != schema_version:
        raise RegressionError(
            f"{path}: schema_version must be {schema_version}"
        )
    return payload


def _jobs_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    matrix = config.get("theme_matrix")
    if not isinstance(matrix, dict):
        raise RegressionError("theme_matrix must be an object")
    themes = matrix.get("themes")
    if not isinstance(themes, list) or not themes:
        raise RegressionError("theme_matrix.themes must be a non-empty array")
    matrix_id = str(matrix.get("id", "default"))
    for theme in themes:
        job = dict(matrix)
        job.pop("themes", None)
        job["id"] = f"{matrix_id}-{theme}"
        job["theme"] = str(theme)
        job["kind"] = "theme_matrix"
        jobs.append(job)

    cases = config.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RegressionError("cases must be a non-empty array")
    for raw_case in cases:
        if not isinstance(raw_case, dict):
            raise RegressionError("every layout case must be an object")
        case = dict(raw_case)
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise RegressionError("every layout case needs a non-empty id")
        case.setdefault("theme", "ocean")
        case["kind"] = "fixture"
        jobs.append(case)

    ids = [str(job["id"]) for job in jobs]
    if len(set(ids)) != len(ids):
        raise RegressionError("layout job ids must be unique")
    return jobs


def _resolve_template_path(value: str, *, repo_root: Path, theme: str) -> Path:
    rendered = value.format(theme=theme)
    path = Path(rendered)
    if not path.is_absolute():
        path = repo_root / path
    return path


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _preflight_fixtures(jobs: Sequence[dict[str, Any]], repo_root: Path) -> None:
    missing: list[str] = []
    for job in jobs:
        content = job.get("content")
        if not isinstance(content, str) or not content:
            raise RegressionError(f"{job['id']}: content must be a path string")
        content_path = _resolve_template_path(
            content, repo_root=repo_root, theme=str(job["theme"])
        )
        if not content_path.is_file():
            missing.append(f"{job['id']}: {content}")
        reference = job.get("reference")
        if reference is not None:
            if not isinstance(reference, dict):
                raise RegressionError(f"{job['id']}: reference must be an object")
            image = reference.get("image")
            if not isinstance(image, str) or not image:
                raise RegressionError(
                    f"{job['id']}: reference.image must be a path string"
                )
            image_path = _resolve_template_path(
                image, repo_root=repo_root, theme=str(job["theme"])
            )
            if not image_path.is_file():
                missing.append(f"{job['id']} reference: {image}")
    if missing:
        details = "\n".join(f"  - {item}" for item in missing)
        raise RegressionError(
            "required layout fixture(s) are missing:\n"
            f"{details}\n"
            "Add the named content/reference files or remove the corresponding "
            "case from examples/layout-cases.json."
        )


def _merge_thresholds(
    defaults: dict[str, Any], job: dict[str, Any]
) -> dict[str, Any]:
    thresholds = dict(defaults.get("thresholds", {}))
    thresholds.update(job.get("thresholds", {}))
    required = (
        "dpi",
        "white_threshold",
        "max_bottom_whitespace_mm",
        "min_page_fill_ratio",
        "max_page_fill_spread",
        "max_bottom_whitespace_spread_mm",
        "max_underfull",
    )
    missing = [name for name in required if name not in thresholds]
    if missing:
        raise RegressionError(
            f"{job['id']}: missing threshold(s): {', '.join(missing)}"
        )
    return thresholds


def _range_failure(
    label: str, value: float, bounds: Sequence[float]
) -> str | None:
    if len(bounds) != 2:
        raise RegressionError(f"{label}: range must contain [minimum, maximum]")
    minimum = float(bounds[0])
    maximum = float(bounds[1])
    if not minimum <= value <= maximum:
        return f"{label}:{value:.6f} not in [{minimum:.6f},{maximum:.6f}]"
    return None


def _normalized_bbox(metrics: dict[str, Any]) -> list[float] | None:
    bbox = metrics.get("bbox_px")
    if bbox is None:
        return None
    width = float(metrics["width_px"])
    height = float(metrics["height_px"])
    left, top, right, bottom = [float(value) for value in bbox]
    return [left / width, top / height, right / width, bottom / height]


def _geometry_failures(
    *,
    job_id: str,
    pages: Sequence[dict[str, Any]],
    geometry: dict[str, Any] | None,
) -> list[str]:
    if geometry is None:
        return []
    if not isinstance(geometry, dict):
        raise RegressionError(f"{job_id}: geometry must be an object")
    failures: list[str] = []
    expected_width = geometry.get("page_width_px")
    expected_height = geometry.get("page_height_px")
    dimension_tolerance = int(geometry.get("page_dimension_tolerance_px", 0))
    fill_range = geometry.get("content_fill_ratio")
    bottom_range = geometry.get("bottom_whitespace_mm")
    max_side = geometry.get("max_side_whitespace_mm")
    reference_bbox = geometry.get("bbox_ratio")
    bbox_tolerance = float(geometry.get("bbox_edge_tolerance_ratio", 0.0))

    for page_number, metrics in enumerate(pages, start=1):
        prefix = f"{job_id}.page_{page_number}"
        if expected_width is not None:
            difference = abs(int(metrics["width_px"]) - int(expected_width))
            if difference > dimension_tolerance:
                failures.append(
                    f"{prefix}.width_px drift:{difference}>{dimension_tolerance}"
                )
        if expected_height is not None:
            difference = abs(int(metrics["height_px"]) - int(expected_height))
            if difference > dimension_tolerance:
                failures.append(
                    f"{prefix}.height_px drift:{difference}>{dimension_tolerance}"
                )
        if fill_range is not None:
            failure = _range_failure(
                f"{prefix}.content_fill_ratio",
                float(metrics["content_fill_ratio"]),
                fill_range,
            )
            if failure:
                failures.append(failure)
        if bottom_range is not None:
            failure = _range_failure(
                f"{prefix}.bottom_whitespace_mm",
                float(metrics["bottom_whitespace_mm"]),
                bottom_range,
            )
            if failure:
                failures.append(failure)
        if max_side is not None:
            for side in ("left", "right"):
                value = float(metrics[f"{side}_whitespace_mm"])
                if value > float(max_side):
                    failures.append(
                        f"{prefix}.{side}_whitespace_mm:"
                        f"{value:.3f}>{float(max_side):.3f}"
                    )
        if reference_bbox is not None and page_number == 1:
            normalized = _normalized_bbox(metrics)
            if normalized is None:
                failures.append(f"{prefix}.bbox:blank")
            else:
                if not isinstance(reference_bbox, list) or len(reference_bbox) != 4:
                    raise RegressionError(
                        f"{job_id}: geometry.bbox_ratio must contain four values"
                    )
                for edge, actual, expected in zip(
                    ("left", "top", "right", "bottom"),
                    normalized,
                    reference_bbox,
                ):
                    drift = abs(actual - float(expected))
                    if drift > bbox_tolerance:
                        failures.append(
                            f"{prefix}.bbox_{edge}_ratio drift:"
                            f"{drift:.6f}>{bbox_tolerance:.6f}"
                        )
    return failures


def _load_normalized_pixels(path: Path) -> tuple[int, int, tuple[int, ...]]:
    if path.suffix.lower() == ".pgm":
        width, height, maximum, pixels = read_pgm(path)
    elif path.suffix.lower() == ".png":
        width, height, maximum, pixels = read_png_grayscale(path)
    else:
        raise RegressionError(f"{path}: pixel comparison needs .pgm or .png")
    normalized = tuple(round(value * 255 / maximum) for value in pixels)
    return width, height, normalized


def _metric_snapshot(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "width_px": metrics.get("width_px"),
        "height_px": metrics.get("height_px"),
        "bbox_px": metrics.get("bbox_px"),
        "content_fill_ratio": metrics.get("content_fill_ratio"),
        "ink_fill_ratio": metrics.get("ink_fill_ratio"),
    }


def _reference_comparison(
    *,
    job: dict[str, Any],
    repo_root: Path,
    selected_pages: Sequence[dict[str, Any]],
    thresholds: dict[str, Any],
) -> dict[str, Any] | None:
    reference = job.get("reference")
    if reference is None:
        return None
    assert isinstance(reference, dict)
    page_number = int(reference.get("page", 1))
    reference_path = _resolve_template_path(
        str(reference["image"]),
        repo_root=repo_root,
        theme=str(job["theme"]),
    )
    changed_limit = reference.get("max_pixel_changed_ratio")
    mean_limit = reference.get("max_pixel_mean_absolute_difference")
    has_pixel_limits = changed_limit is not None or mean_limit is not None
    configured_mode = reference.get("comparison_mode")
    comparison_mode = (
        str(configured_mode)
        if configured_mode is not None
        else ("shape+pixel" if has_pixel_limits else "shape")
    )
    dimension_tolerance = int(
        reference.get("page_dimension_tolerance_px", 0)
    )
    bbox_tolerance = float(reference.get("bbox_edge_tolerance_ratio", 0.03))
    content_fill_tolerance = float(
        reference.get("content_fill_tolerance", 0.05)
    )
    ink_fill_tolerance = float(reference.get("ink_fill_tolerance", 0.04))
    report: dict[str, Any] = {
        "path": _display_path(reference_path, repo_root),
        "sha256": None,
        "page": page_number,
        "comparison_mode": comparison_mode,
        "result": "failed",
        "reference_metrics": None,
        "candidate_metrics": None,
        "measured_drifts": {},
        "tolerances": {
            "page_dimension_px": dimension_tolerance,
            "bbox_edge_ratio": bbox_tolerance,
            "content_fill_ratio": content_fill_tolerance,
            "ink_fill_ratio": ink_fill_tolerance,
        },
        "failures": [],
    }
    failures = report["failures"]
    assert isinstance(failures, list)

    if comparison_mode not in {"shape", "shape+pixel"}:
        failures.append(
            f"{job['id']}: unsupported reference comparison mode "
            f"{comparison_mode!r}"
        )
        return report
    if comparison_mode == "shape" and has_pixel_limits:
        failures.append(
            f"{job['id']}: shape comparison cannot configure pixel thresholds"
        )
        return report
    if not 1 <= page_number <= len(selected_pages):
        failures.append(
            f"{job['id']}: reference page {page_number} is unavailable"
        )
        return report

    candidate = selected_pages[page_number - 1]
    report["candidate_metrics"] = _metric_snapshot(candidate)
    try:
        reference_bytes = reference_path.read_bytes()
    except OSError as exc:
        failures.append(
            f"{job['id']}: reference image is unavailable: "
            f"{_display_path(reference_path, repo_root)} ({exc.strerror or exc})"
        )
        return report
    report["sha256"] = hashlib.sha256(reference_bytes).hexdigest()
    try:
        reference_metrics = analyze_reference_image(
            reference_path,
            dpi=int(reference.get("dpi", thresholds["dpi"])),
            white_threshold=int(
                reference.get("white_threshold", thresholds["white_threshold"])
            ),
        )
    except (OSError, ValueError) as exc:
        failures.append(
            f"{job['id']}: reference image is invalid: "
            f"{_display_path(reference_path, repo_root)} ({exc})"
        )
        return report
    report["reference_metrics"] = _metric_snapshot(reference_metrics)

    measured_drifts = report["measured_drifts"]
    assert isinstance(measured_drifts, dict)
    width_drift = abs(
        int(candidate["width_px"]) - int(reference_metrics["width_px"])
    )
    height_drift = abs(
        int(candidate["height_px"]) - int(reference_metrics["height_px"])
    )
    measured_drifts["page_dimensions_px"] = {
        "width": width_drift,
        "height": height_drift,
    }
    for dimension, drift in (
        ("width", width_drift),
        ("height", height_drift),
    ):
        if drift > dimension_tolerance:
            failures.append(
                f"{job['id']}.reference_{dimension}_px drift:"
                f"{drift}>{dimension_tolerance}"
            )

    actual_bbox = _normalized_bbox(candidate)
    expected_bbox = _normalized_bbox(reference_metrics)
    bbox_drifts: dict[str, float | None] = {}
    measured_drifts["bbox_edge_ratio"] = bbox_drifts
    if actual_bbox is None or expected_bbox is None:
        report["failures"].append(
            f"{job['id']}: candidate/reference bbox is blank"
        )
    else:
        for edge, actual, expected in zip(
            ("left", "top", "right", "bottom"), actual_bbox, expected_bbox
        ):
            drift = abs(actual - expected)
            bbox_drifts[edge] = round(drift, 9)
            if drift > bbox_tolerance:
                report["failures"].append(
                    f"{job['id']}.reference_bbox_{edge}_ratio drift:"
                    f"{drift:.6f}>{bbox_tolerance:.6f}"
                )

    for metric, tolerance in (
        ("content_fill_ratio", content_fill_tolerance),
        ("ink_fill_ratio", ink_fill_tolerance),
    ):
        drift = abs(float(candidate[metric]) - float(reference_metrics[metric]))
        measured_drifts[metric] = round(drift, 9)
        if drift > tolerance:
            report["failures"].append(
                f"{job['id']}.reference_{metric} drift:{drift:.6f}>{tolerance:.6f}"
            )

    if comparison_mode == "shape+pixel":
        report["tolerances"]["pixel_changed_ratio"] = changed_limit
        report["tolerances"][
            "pixel_mean_absolute_difference"
        ] = mean_limit
        render = candidate.get("render")
        if not isinstance(render, str):
            report["failures"].append(
                f"{job['id']}: selected PGM render was not retained"
            )
        else:
            render_path = repo_root / render
            actual_width, actual_height, actual_pixels = _load_normalized_pixels(
                render_path
            )
            ref_width, ref_height, ref_pixels = _load_normalized_pixels(reference_path)
            if (actual_width, actual_height) != (ref_width, ref_height):
                report["failures"].append(
                    f"{job['id']}: pixel reference dimensions "
                    f"{ref_width}x{ref_height} != {actual_width}x{actual_height}"
                )
            else:
                changed = sum(
                    actual != expected
                    for actual, expected in zip(actual_pixels, ref_pixels)
                )
                changed_ratio = changed / len(actual_pixels)
                mean_difference = sum(
                    abs(actual - expected)
                    for actual, expected in zip(actual_pixels, ref_pixels)
                ) / len(actual_pixels)
                measured_drifts["pixel_changed_ratio"] = round(
                    changed_ratio, 9
                )
                measured_drifts[
                    "pixel_mean_absolute_difference"
                ] = round(mean_difference, 9)
                if (
                    changed_limit is not None
                    and changed_ratio > float(changed_limit)
                ):
                    report["failures"].append(
                        f"{job['id']}.pixel_changed_ratio:"
                        f"{changed_ratio:.6f}>{float(changed_limit):.6f}"
                    )
                if mean_limit is not None and mean_difference > float(mean_limit):
                    report["failures"].append(
                        f"{job['id']}.pixel_mean_absolute_difference:"
                        f"{mean_difference:.6f}>{float(mean_limit):.6f}"
                    )
    report["result"] = "passed" if not report["failures"] else "failed"
    return report


def _reference_failures(
    *,
    job: dict[str, Any],
    repo_root: Path,
    selected_pages: Sequence[dict[str, Any]],
    thresholds: dict[str, Any],
) -> list[str]:
    comparison = _reference_comparison(
        job=job,
        repo_root=repo_root,
        selected_pages=selected_pages,
        thresholds=thresholds,
    )
    return list(comparison["failures"]) if comparison is not None else []


def _strip_tex_comments(value: str) -> str:
    """Remove unescaped TeX comments without disturbing command boundaries."""
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "%":
            output.append(character)
            index += 1
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and value[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            output.append(character)
            index += 1
            continue
        while index < len(value) and value[index] not in "\r\n":
            index += 1
    return "".join(output)


def _skip_tex_space(value: str, index: int) -> int:
    while index < len(value) and value[index].isspace():
        index += 1
    return index


def _parse_tex_group(value: str, index: int) -> tuple[str, int]:
    """Parse one balanced TeX group while respecting escaped braces."""
    index = _skip_tex_space(value, index)
    if index >= len(value) or value[index] != "{":
        raise RegressionError(f"expected TeX group at offset {index}")
    depth = 1
    cursor = index + 1
    content_start = cursor
    while cursor < len(value):
        character = value[cursor]
        if character == "\\" and cursor + 1 < len(value):
            cursor += 2
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return value[content_start:cursor], cursor + 1
        cursor += 1
    raise RegressionError(f"unterminated TeX group at offset {index}")


def _parse_aux_marker_pages(value: str) -> dict[str, list[int]]:
    """Return every namespaced marker and its deferred shipout page(s)."""
    source = _strip_tex_comments(value)
    command = r"\newlabel"
    marker_pages: dict[str, list[int]] = {}
    cursor = 0
    while True:
        command_start = source.find(command, cursor)
        if command_start < 0:
            break
        command_end = command_start + len(command)
        cursor = command_end
        if command_start > 0 and source[command_start - 1] == "\\":
            continue
        if command_end < len(source) and (
            source[command_end].isalpha() or source[command_end] == "@"
        ):
            continue
        label, payload_start = _parse_tex_group(source, command_end)
        payload, cursor = _parse_tex_group(source, payload_start)
        if not label.startswith(_AUX_MARKER_PREFIX):
            continue
        marker = label[len(_AUX_MARKER_PREFIX) :]
        if not _MARKER_KEY.fullmatch(marker):
            raise RegressionError(
                f"AUX marker label has an unsafe key: {marker!r}"
            )
        fields: list[str] = []
        field_cursor = 0
        while _skip_tex_space(payload, field_cursor) < len(payload):
            field, field_cursor = _parse_tex_group(payload, field_cursor)
            fields.append(field)
        if len(fields) < 2:
            raise RegressionError(
                f"AUX marker {marker!r} has no shipped-page field"
            )
        page = fields[1].strip()
        if not _POSITIVE_PAGE.fullmatch(page):
            raise RegressionError(
                f"AUX marker {marker!r} has a non-numeric shipped page: {page!r}"
            )
        marker_pages.setdefault(marker, []).append(int(page))
    return marker_pages


def _evaluate_same_page_marker_groups(
    *,
    job_id: str,
    marker_pages: dict[str, list[int]],
    groups: Any,
    page_count: int,
) -> dict[str, Any] | None:
    if groups is None:
        return None
    report: dict[str, Any] = {
        "result": "failed",
        "page_count": page_count,
        "groups": [],
        "failures": [],
    }
    failures = report["failures"]
    group_reports = report["groups"]
    assert isinstance(failures, list)
    assert isinstance(group_reports, list)
    if not isinstance(groups, list) or not groups:
        failures.append(
            f"{job_id}: same_page_markers must be a non-empty array"
        )
        return report

    seen_group_ids: set[str] = set()
    for index, group in enumerate(groups):
        location = f"{job_id}: same_page_markers[{index}]"
        if not isinstance(group, dict):
            failures.append(f"{location} must be an object")
            continue
        group_id = group.get("id")
        markers = group.get("markers")
        if not isinstance(group_id, str) or not group_id.strip():
            failures.append(f"{location}.id must be non-empty")
            continue
        if group_id in seen_group_ids:
            failures.append(f"{location}.id is duplicated: {group_id!r}")
            continue
        seen_group_ids.add(group_id)
        if (
            not isinstance(markers, list)
            or len(markers) < 2
            or any(
                not isinstance(marker, str)
                or not _MARKER_KEY.fullmatch(marker)
                for marker in markers
            )
        ):
            failures.append(
                f"{location}.markers must contain at least two safe marker keys"
            )
            continue
        if len(set(markers)) != len(markers):
            failures.append(f"{location}.markers must not contain duplicates")
            continue

        resolved = {marker: list(marker_pages.get(marker, [])) for marker in markers}
        group_failures: list[str] = []
        unique_pages: list[int] = []
        for marker, pages in resolved.items():
            if not pages:
                group_failures.append(
                    f"{job_id}.{group_id}: marker {marker!r} is missing"
                )
            elif len(pages) > 1:
                group_failures.append(
                    f"{job_id}.{group_id}: marker {marker!r} is duplicated "
                    f"on shipped pages {pages}"
                )
            elif not 1 <= pages[0] <= page_count:
                group_failures.append(
                    f"{job_id}.{group_id}: marker {marker!r} resolved to "
                    f"page {pages[0]} outside 1..{page_count}"
                )
            else:
                unique_pages.append(pages[0])

        common_page: int | None = None
        if not group_failures:
            if len(set(unique_pages)) != 1:
                placements = ", ".join(
                    f"{marker}={pages[0]}" for marker, pages in resolved.items()
                )
                group_failures.append(
                    f"{job_id}.{group_id}: markers shipped on different pages "
                    f"({placements})"
                )
            else:
                common_page = unique_pages[0]
        failures.extend(group_failures)
        group_reports.append(
            {
                "id": group_id,
                "marker_pages": resolved,
                "common_page": common_page,
                "result": "passed" if not group_failures else "failed",
                "failures": group_failures,
            }
        )

    report["result"] = "passed" if not failures else "failed"
    return report


def _same_page_marker_comparison(
    *,
    job: dict[str, Any],
    repo_root: Path,
    selected_candidate: Any,
) -> dict[str, Any] | None:
    groups = job.get("same_page_markers")
    if groups is None:
        return None
    empty_report: dict[str, Any] = {
        "result": "failed",
        "aux": None,
        "page_count": 0,
        "groups": [],
        "failures": [],
    }
    failures = empty_report["failures"]
    assert isinstance(failures, list)
    if not isinstance(selected_candidate, dict):
        failures.append(f"{job['id']}: selected candidate is unavailable")
        return empty_report
    page_count = selected_candidate.get("pages")
    if (
        not isinstance(page_count, int)
        or isinstance(page_count, bool)
        or page_count <= 0
    ):
        failures.append(f"{job['id']}: selected candidate page count is invalid")
        return empty_report
    candidate_pdf = selected_candidate.get("pdf")
    if not isinstance(candidate_pdf, str) or not candidate_pdf:
        failures.append(f"{job['id']}: selected candidate PDF is unavailable")
        return empty_report
    pdf_path = Path(candidate_pdf)
    if not pdf_path.is_absolute():
        pdf_path = repo_root / pdf_path
    if pdf_path.suffix.casefold() != ".pdf":
        failures.append(f"{job['id']}: selected candidate PDF path is invalid")
        return empty_report
    aux_path = pdf_path.with_suffix(".aux")
    empty_report["aux"] = _display_path(aux_path, repo_root)
    empty_report["page_count"] = page_count
    try:
        aux_text = aux_path.read_text(encoding="utf-8")
        marker_pages = _parse_aux_marker_pages(aux_text)
    except (OSError, UnicodeError, RegressionError) as exc:
        failures.append(
            f"{job['id']}: selected candidate AUX is unavailable or invalid "
            f"({_display_path(aux_path, repo_root)}: {exc})"
        )
        return empty_report

    report = _evaluate_same_page_marker_groups(
        job_id=str(job["id"]),
        marker_pages=marker_pages,
        groups=groups,
        page_count=page_count,
    )
    assert report is not None
    report["aux"] = _display_path(aux_path, repo_root)
    return report


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_fit_manifest(
    *,
    validator: Path,
    manifest: Path,
    target_pages: int,
    repo_root: Path,
) -> tuple[int, str]:
    completed = subprocess.run(
        [
            sys.executable,
            str(validator),
            str(manifest),
            "--expected-pages",
            str(target_pages),
        ],
        cwd=repo_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run all themes for the default resume and Ocean for every layout "
            "fixture declared in examples/layout-cases.json."
        )
    )
    parser.add_argument(
        "--config", default="examples/layout-cases.json", help="case matrix JSON"
    )
    parser.add_argument(
        "--output-dir", default="build/layout-regression", help="generated output"
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="run only a named expanded job id (repeatable)",
    )
    parser.add_argument(
        "--manifest-validator",
        help="override the Skill fit-manifest validator path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir

    try:
        config = _load_json(
            config_path,
            schema_version=CONFIG_SCHEMA_VERSION,
        )
        defaults = config.get("defaults")
        if not isinstance(defaults, dict):
            raise RegressionError("defaults must be an object")
        validator_value = args.manifest_validator or defaults.get(
            "manifest_validator"
        )
        if not isinstance(validator_value, str) or not validator_value:
            raise RegressionError(
                "defaults.manifest_validator must be a non-empty path"
            )
        manifest_validator = _resolve_template_path(
            validator_value, repo_root=repo_root, theme="ocean"
        )
        if not manifest_validator.is_file():
            raise RegressionError(
                f"fit manifest validator not found: {validator_value}"
            )
        jobs = _jobs_from_config(config)
        if args.case_ids:
            requested = set(args.case_ids)
            available = {str(job["id"]) for job in jobs}
            unknown = sorted(requested - available)
            if unknown:
                raise RegressionError(
                    "unknown expanded layout job(s): " + ", ".join(unknown)
                )
            jobs = [job for job in jobs if str(job["id"]) in requested]
        _preflight_fixtures(jobs, repo_root)
    except RegressionError as exc:
        print(f"layout-regression: {exc}", file=sys.stderr)
        return 2

    profiles = defaults.get("profiles", ["balanced", "airy", "compact", "dense"])
    if not isinstance(profiles, list) or not profiles:
        print(
            "layout-regression: defaults.profiles must be a non-empty array",
            file=sys.stderr,
        )
        return 2

    results: list[dict[str, Any]] = []
    failed = False
    for job in jobs:
        job_id = str(job["id"])
        theme = str(job["theme"])
        target_pages = int(job.get("target_pages", 1))
        thresholds = _merge_thresholds(defaults, job)
        job_dir = output_dir / job_id
        manifest_path = job_dir / "manifest.json"
        content_path = _resolve_template_path(
            str(job["content"]), repo_root=repo_root, theme=theme
        )
        keep_renders = bool(job.get("reference"))
        command = [
            sys.executable,
            str(repo_root / "scripts" / "fit_resume.py"),
            "--content",
            str(content_path),
            "--theme",
            theme,
            "--target-pages",
            str(target_pages),
            "--output-dir",
            str(job_dir),
            "--manifest",
            str(manifest_path),
            "--dpi",
            str(thresholds["dpi"]),
            "--white-threshold",
            str(thresholds["white_threshold"]),
            "--max-bottom-whitespace-mm",
            str(thresholds["max_bottom_whitespace_mm"]),
            "--min-page-fill-ratio",
            str(thresholds["min_page_fill_ratio"]),
            "--max-page-fill-spread",
            str(thresholds["max_page_fill_spread"]),
            "--max-bottom-whitespace-spread-mm",
            str(thresholds["max_bottom_whitespace_spread_mm"]),
            "--max-underfull",
            str(thresholds["max_underfull"]),
            "--profiles",
            *[str(profile) for profile in profiles],
        ]
        if keep_renders:
            command.append("--keep-renders")

        print(f"layout-regression: {job_id}", flush=True)
        completed = subprocess.run(
            command,
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        failures: list[str] = []
        reference_comparison: dict[str, Any] | None = None
        same_page_marker_comparison: dict[str, Any] | None = None
        manifest: dict[str, Any] | None = None
        if manifest_path.is_file():
            manifest = _load_json(
                manifest_path,
                schema_version=FIT_MANIFEST_SCHEMA_VERSION,
            )
        if completed.returncode != 0:
            failures.append(f"fit_exit_code:{completed.returncode}")
        if manifest is None:
            failures.append("fit_manifest_missing")
            selected_pages: list[dict[str, Any]] = []
        else:
            selected_profile = manifest.get("selected_profile")
            expected_profile = job.get("expected_profile")
            if expected_profile is not None and selected_profile != expected_profile:
                failures.append(
                    f"selected_profile:{selected_profile!s}!={expected_profile!s}"
                )
            selected_fill_mode = manifest.get("selected_page_fill_mode")
            expected_fill_mode = job.get("expected_page_fill_mode")
            if (
                expected_fill_mode is not None
                and selected_fill_mode != expected_fill_mode
            ):
                failures.append(
                    "selected_page_fill_mode:"
                    f"{selected_fill_mode!s}!={expected_fill_mode!s}"
                )
            validator_returncode, validator_output = _validate_fit_manifest(
                validator=manifest_validator,
                manifest=manifest_path,
                target_pages=target_pages,
                repo_root=repo_root,
            )
            if validator_returncode != 0:
                failures.append(
                    f"fit_manifest_validator_exit_code:{validator_returncode}"
                )
                if validator_output:
                    failures.append(
                        "fit_manifest_validator_output:"
                        + validator_output.replace("\n", " | ")
                    )
            selected_candidate = next(
                (
                    candidate
                    for candidate in manifest.get("candidates", [])
                    if candidate.get("profile") == selected_profile
                    and candidate.get("page_fill_mode") == selected_fill_mode
                ),
                None,
            )
            selected_pages = (
                list(selected_candidate.get("page_metrics", []))
                if isinstance(selected_candidate, dict)
                else []
            )
            failures.extend(
                _geometry_failures(
                    job_id=job_id,
                    pages=selected_pages,
                    geometry=job.get("geometry"),
                )
            )
            reference_comparison = _reference_comparison(
                job=job,
                repo_root=repo_root,
                selected_pages=selected_pages,
                thresholds=thresholds,
            )
            if reference_comparison is not None:
                failures.extend(reference_comparison["failures"])
            same_page_marker_comparison = _same_page_marker_comparison(
                job=job,
                repo_root=repo_root,
                selected_candidate=selected_candidate,
            )
            if same_page_marker_comparison is not None:
                failures.extend(same_page_marker_comparison["failures"])

        if failures:
            failed = True
            print(
                f"layout-regression: {job_id} failed: " + "; ".join(failures),
                file=sys.stderr,
            )
            if completed.stdout.strip():
                print(completed.stdout.rstrip(), file=sys.stderr)
            if completed.stderr.strip():
                print(completed.stderr.rstrip(), file=sys.stderr)
        results.append(
            {
                "id": job_id,
                "kind": job["kind"],
                "theme": theme,
                "content": str(job["content"]),
                "target_pages": target_pages,
                "returncode": completed.returncode,
                "selected_profile": (
                    manifest.get("selected_profile") if manifest else None
                ),
                "selected_page_fill_mode": (
                    manifest.get("selected_page_fill_mode") if manifest else None
                ),
                "selection_reason": (
                    manifest.get("selection_reason") if manifest else None
                ),
                "reference": reference_comparison,
                "same_page_markers": same_page_marker_comparison,
                "failures": failures,
                "manifest": _display_path(manifest_path, repo_root),
            }
        )

    summary = {
        "schema_version": REGRESSION_SCHEMA_VERSION,
        "success": not failed,
        "config": _display_path(config_path, repo_root),
        "jobs": results,
    }
    _write_json(output_dir / "regression-manifest.json", summary)
    if failed:
        print(
            "layout-regression: one or more jobs failed; see "
            f"{_display_path(output_dir / 'regression-manifest.json', repo_root)}",
            file=sys.stderr,
        )
        return 1
    print(f"layout-regression: {len(results)} job(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
