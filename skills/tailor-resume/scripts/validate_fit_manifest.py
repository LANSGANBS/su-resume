#!/usr/bin/env python3
"""Validate the selected layout candidate in a fit_resume.py manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_TEMPLATE_FILES = (
    "resume.tex",
    "resume-layout.tex",
    "resume-components.tex",
    "theme.tex",
)
MANIFEST_SCHEMA_VERSION = 2
DEFAULT_MAX_BOTTOM_WHITESPACE_MM = 22.0
DEFAULT_MIN_PAGE_FILL_RATIO = 0.62
DEFAULT_MAX_UNDERFULL = 20
DEFAULT_MAX_PAGE_FILL_SPREAD = 0.22
DEFAULT_MAX_BOTTOM_WHITESPACE_SPREAD_MM = 25.0
SELECTION_POLICY = "balanced-reference-v1"
PAGE_FILL_MODES = ("natural", "elastic")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UNDERFILL_REASON_MARKERS = (
    "_bottom_whitespace_mm:",
    "_content_fill_ratio:",
    "page_fill_spread:",
    "bottom_whitespace_spread_mm:",
)
POLICY_ORDERS = {
    "balanced_reference_passed": ["balanced"],
    "reference_over_target_or_overflow": [
        "balanced",
        "compact",
        "dense",
        "airy",
    ],
    "reference_under_target_or_underfilled": [
        "balanced",
        "airy",
        "compact",
        "dense",
    ],
    "reference_quality_failure": [
        "balanced",
        "compact",
        "airy",
        "dense",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that fit_resume.py preserved the balanced reference profile "
            "when possible, followed the reason-directed fallback policy, and "
            "satisfied the release gates."
        )
    )
    parser.add_argument("manifest", type=Path, help="Path to the fit manifest.")
    parser.add_argument(
        "--expected-pages",
        type=int,
        help="Override/check the target page count recorded in the manifest.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help=(
            "Resume repository root. Required when the Skill is installed "
            "outside the repository and the current directory is elsewhere."
        ),
    )
    return parser.parse_args()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"manifest does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("manifest root must be a JSON object")
    return value


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def sha256_digest(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_template_root(path: Path) -> bool:
    return path.is_dir() and all(
        (path / name).is_file() for name in REQUIRED_TEMPLATE_FILES
    )


def resolve_repo_root(
    explicit: Path | None = None,
    *,
    cwd: Path | None = None,
    vendored_root: Path | None = None,
) -> Path:
    if explicit is not None:
        resolved = explicit.expanduser().resolve()
        if not is_template_root(resolved):
            raise ValueError(
                f"--repo-root is not a resume template repository: {resolved}"
            )
        return resolved

    working = (cwd or Path.cwd()).resolve()
    candidates = [working, *working.parents]
    bundled = (vendored_root or REPO_ROOT).resolve()
    if bundled not in candidates:
        candidates.append(bundled)
    for candidate in candidates:
        if is_template_root(candidate):
            return candidate
    raise ValueError(
        "cannot locate the resume repository; pass --repo-root explicitly"
    )


def validate_source_hashes(
    inputs: dict[str, Any],
    repo_root: Path,
) -> list[str]:
    errors: list[str] = []
    content_value = inputs.get("content")
    content_path: Path | None = None
    if not nonempty_string(content_value):
        errors.append("inputs.content must be a non-empty path")
    else:
        content_path = Path(str(content_value))
        if not content_path.is_absolute():
            content_path = repo_root / content_path

    sources = {
        "content_sha256": content_path,
        "entrypoint_sha256": repo_root / "resume.tex",
        "layout_sha256": repo_root / "resume-layout.tex",
        "components_sha256": repo_root / "resume-components.tex",
        "theme_sha256": repo_root / "theme.tex",
    }
    for field, source in sources.items():
        recorded = inputs.get(field)
        if not sha256_digest(recorded):
            continue
        if source is None or not source.is_file():
            rendered = str(source) if source is not None else "<missing content path>"
            errors.append(f"{field} source does not exist: {rendered}")
            continue
        try:
            actual = sha256_file(source)
        except OSError as exc:
            errors.append(f"cannot hash {field} source: {exc}")
            continue
        if actual != recorded:
            errors.append(f"inputs.{field} does not match {source}")
    return errors


def resolve_artifact_path(value: Any, repo_root: Path) -> Path | None:
    if not nonempty_string(value):
        return None
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def validate_selected_artifacts(
    manifest: dict[str, Any], repo_root: Path
) -> list[str]:
    errors: list[str] = []
    selected_profile = manifest.get("selected_profile")
    candidates = manifest.get("candidates")
    selected = None
    if isinstance(candidates, list):
        selected = next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, dict)
                and candidate.get("profile") == selected_profile
            ),
            None,
        )
    candidate_path = resolve_artifact_path(
        selected.get("pdf") if isinstance(selected, dict) else None,
        repo_root,
    )
    final_path = resolve_artifact_path(manifest.get("selected_pdf"), repo_root)
    artifacts = (
        ("selected candidate PDF", candidate_path),
        ("selected_pdf", final_path),
    )
    for label, artifact in artifacts:
        if artifact is None or not artifact.is_file():
            errors.append(f"{label} does not exist: {artifact or '<missing path>'}")
            continue
        try:
            with artifact.open("rb") as stream:
                header = stream.read(5)
            if header != b"%PDF-":
                errors.append(f"{label} is not a PDF file: {artifact}")
        except OSError as exc:
            errors.append(f"cannot read {label}: {exc}")
    if (
        candidate_path is not None
        and final_path is not None
        and candidate_path.is_file()
        and final_path.is_file()
    ):
        try:
            if sha256_file(candidate_path) != sha256_file(final_path):
                errors.append(
                    "selected_pdf is not byte-identical to the selected candidate PDF"
                )
        except OSError as exc:
            errors.append(f"cannot hash selected PDF artifacts: {exc}")
    return errors


def underfill_only(reasons: Any) -> bool:
    return (
        isinstance(reasons, list)
        and bool(reasons)
        and all(
            isinstance(reason, str)
            and any(marker in reason for marker in UNDERFILL_REASON_MARKERS)
            for reason in reasons
        )
    )


def threshold(
    thresholds: dict[str, Any],
    *keys: str,
    default: float | int,
) -> float | int:
    for key in keys:
        value = thresholds.get(key)
        if finite_number(value):
            return value
    return default


def validate_threshold_contract(thresholds: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    numeric_ranges = {
        "max_bottom_whitespace_mm": (0.0, None),
        "min_page_fill_ratio": (0.0, 1.0),
        "max_page_fill_spread": (0.0, 1.0),
        "max_bottom_whitespace_spread_mm": (0.0, None),
    }
    for key, (minimum, maximum) in numeric_ranges.items():
        value = thresholds.get(key)
        if not finite_number(value):
            errors.append(f"thresholds.{key} must be a finite number")
            continue
        numeric = float(value)
        if numeric < minimum or (maximum is not None and numeric > maximum):
            upper = f" and <= {maximum}" if maximum is not None else ""
            errors.append(f"thresholds.{key} must be >= {minimum}{upper}")
    max_underfull = thresholds.get("max_underfull")
    if (
        not isinstance(max_underfull, int)
        or isinstance(max_underfull, bool)
        or max_underfull < 0
    ):
        errors.append("thresholds.max_underfull must be a non-negative integer")
    return errors


def infer_selection_reason(
    balanced: dict[str, Any],
    target_pages: int | None,
    max_bottom_whitespace_mm: float,
    min_page_fill_ratio: float,
    max_page_fill_spread: float,
    max_bottom_whitespace_spread_mm: float,
) -> str:
    if balanced.get("eligible") is True:
        return "balanced_reference_passed"

    pages = balanced.get("pages")
    if (
        target_pages is not None
        and isinstance(pages, int)
        and not isinstance(pages, bool)
    ):
        if pages > target_pages:
            return "reference_over_target_or_overflow"
        if pages < target_pages:
            return "reference_under_target_or_underfilled"

    log_counts = balanced.get("log_counts")
    if isinstance(log_counts, dict):
        overfull = log_counts.get("overfull")
        if isinstance(overfull, int) and not isinstance(overfull, bool) and overfull > 0:
            return "reference_over_target_or_overflow"

    page_metrics = balanced.get("page_metrics")
    if isinstance(page_metrics, list):
        fill_values: list[float] = []
        bottom_values: list[float] = []
        for metrics in page_metrics:
            if not isinstance(metrics, dict):
                continue
            bottom_whitespace_mm = metrics.get("bottom_whitespace_mm")
            if finite_number(bottom_whitespace_mm) and (
                float(bottom_whitespace_mm) > max_bottom_whitespace_mm
            ):
                return "reference_under_target_or_underfilled"
            if finite_number(bottom_whitespace_mm):
                bottom_values.append(float(bottom_whitespace_mm))
            content_fill_ratio = metrics.get("content_fill_ratio")
            if finite_number(content_fill_ratio) and (
                float(content_fill_ratio) < min_page_fill_ratio
            ):
                return "reference_under_target_or_underfilled"
            if finite_number(content_fill_ratio):
                fill_values.append(float(content_fill_ratio))
        if (
            len(fill_values) > 1
            and max(fill_values) - min(fill_values) > max_page_fill_spread
        ):
            return "reference_under_target_or_underfilled"
        if (
            len(bottom_values) > 1
            and max(bottom_values) - min(bottom_values)
            > max_bottom_whitespace_spread_mm
        ):
            return "reference_under_target_or_underfilled"

    page_balance = balanced.get("page_balance")
    if not isinstance(page_balance, dict):
        page_balance = {}
    recorded_fill_spread = page_balance.get("page_fill_spread")
    if finite_number(recorded_fill_spread) and (
        float(recorded_fill_spread) > max_page_fill_spread
    ):
        return "reference_under_target_or_underfilled"
    recorded_bottom_spread = page_balance.get("bottom_whitespace_spread_mm")
    if finite_number(recorded_bottom_spread) and (
        float(recorded_bottom_spread) > max_bottom_whitespace_spread_mm
    ):
        return "reference_under_target_or_underfilled"

    return "reference_quality_failure"


def validate_page_fill_contract(
    *,
    attempted_modes: list[str],
    attempts: list[Any],
    selection_detail: Any,
    selected_profile: str | None,
    selected_mode: str | None,
    selected: dict[str, Any] | None,
    by_profile: dict[str, dict[str, Any]],
    target_pages: int | None,
    max_bottom_whitespace_mm: float,
    min_page_fill_ratio: float,
    max_page_fill_spread: float,
    max_bottom_whitespace_spread_mm: float,
) -> list[str]:
    errors: list[str] = []
    if selected is not None and selected_mode is not None:
        if selected.get("page_fill_mode") != selected_mode:
            errors.append(
                "selected_page_fill_mode must match the selected candidate"
            )

    if attempted_modes == ["natural"]:
        if attempts:
            errors.append(
                "page_fill_attempts must be empty when elastic was not attempted"
            )
        if selection_detail != "natural_profile_selection":
            errors.append(
                "natural-only selection must use "
                "'natural_profile_selection'"
            )
        if selected_mode is not None and selected_mode != "natural":
            errors.append("natural-only selection cannot select elastic page fill")
        if any(
            candidate.get("page_fill_mode") == "elastic"
            for candidate in by_profile.values()
        ):
            errors.append(
                "candidates cannot contain elastic page fill when it was not "
                "attempted"
            )
        return errors

    if attempted_modes != ["natural", "elastic"]:
        return errors

    if target_pages is not None and target_pages <= 1:
        errors.append("elastic page fill requires a multi-page target")
    if len(attempts) != 2:
        errors.append(
            "elastic fallback must record natural and elastic balanced attempts"
        )
        return errors
    if any(not isinstance(attempt, dict) for attempt in attempts):
        errors.append("every page_fill_attempts entry must be an object")
        return errors

    natural_attempt = attempts[0]
    elastic_attempt = attempts[1]
    assert isinstance(natural_attempt, dict)
    assert isinstance(elastic_attempt, dict)
    if natural_attempt.get("profile") != "balanced":
        errors.append("the natural page-fill attempt must use balanced")
    if natural_attempt.get("page_fill_mode") != "natural":
        errors.append("the first page-fill attempt must be natural")
    if natural_attempt.get("eligible") is not False:
        errors.append("the natural page-fill attempt must be ineligible")
    if target_pages is not None and natural_attempt.get("pages") != target_pages:
        errors.append(
            "elastic fallback requires natural balanced to already meet the "
            "target page count"
        )
    if not underfill_only(natural_attempt.get("rejection_reasons")):
        errors.append(
            "elastic fallback requires natural balanced to fail only "
            "whitespace/fill/balance gates"
        )
    inferred_reason = infer_selection_reason(
        natural_attempt,
        target_pages,
        max_bottom_whitespace_mm,
        min_page_fill_ratio,
        max_page_fill_spread,
        max_bottom_whitespace_spread_mm,
    )
    if inferred_reason != "reference_under_target_or_underfilled":
        errors.append(
            "the natural page-fill attempt does not prove underfill"
        )

    if elastic_attempt.get("profile") != "balanced":
        errors.append("the elastic page-fill attempt must use balanced")
    if elastic_attempt.get("page_fill_mode") != "elastic":
        errors.append("the second page-fill attempt must be elastic")

    if selected_mode == "elastic":
        if selection_detail != "balanced_elastic_underfill_recovery":
            errors.append(
                "selected elastic fill must use "
                "'balanced_elastic_underfill_recovery'"
            )
        if selected_profile != "balanced":
            errors.append("elastic page fill can only select balanced")
        eligible_natural_profiles = sorted(
            profile
            for profile, candidate in by_profile.items()
            if profile != "balanced"
            and candidate.get("page_fill_mode") == "natural"
            and candidate.get("eligible") is True
        )
        if eligible_natural_profiles:
            errors.append(
                "elastic page fill requires every natural profile to be "
                "ineligible; eligible: "
                + ", ".join(eligible_natural_profiles)
            )
        if elastic_attempt.get("eligible") is not True:
            errors.append("selected elastic page-fill attempt must be eligible")
        elastic_reasons = elastic_attempt.get("rejection_reasons")
        if not isinstance(elastic_reasons, list) or elastic_reasons:
            errors.append(
                "selected elastic page-fill attempt must have no rejection reasons"
            )
        elastic_counts = elastic_attempt.get("log_counts")
        elastic_underfull = (
            elastic_counts.get("underfull")
            if isinstance(elastic_counts, dict)
            else None
        )
        if elastic_underfull != 0:
            errors.append(
                "selected elastic page-fill attempt must have zero underfull boxes"
            )
        if selected is not None:
            for key in (
                "pdf",
                "pages",
                "eligible",
                "rejection_reasons",
                "log_counts",
                "page_metrics",
                "page_balance",
                "duplicate_page_pairs",
            ):
                if selected.get(key) != elastic_attempt.get(key):
                    errors.append(
                        "selected elastic candidate does not match "
                        f"page_fill_attempts[1].{key}"
                    )
    elif selected_mode == "natural":
        errors.append(
            "a successful natural profile must be selected before elastic "
            "page fill is attempted"
        )
    return errors


def validate_manifest(
    manifest: dict[str, Any],
    expected_pages: int | None = None,
    repo_root: Path | None = None,
    *,
    check_artifacts: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        resolved_repo_root = resolve_repo_root(repo_root)
    except ValueError as exc:
        return [str(exc)]

    schema_version = manifest.get("schema_version")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be exactly {MANIFEST_SCHEMA_VERSION}"
        )
    if manifest.get("success") is not True:
        errors.append("manifest.success must be true")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        errors.append("inputs must be an object")
        inputs = {}
    if inputs.get("content_preserved") is not True:
        errors.append("inputs.content_preserved must be true")
    for key in (
        "content_sha256",
        "entrypoint_sha256",
        "layout_sha256",
        "components_sha256",
        "theme_sha256",
    ):
        if not sha256_digest(inputs.get(key)):
            errors.append(f"inputs.{key} must be a lowercase SHA-256 digest")
    errors.extend(validate_source_hashes(inputs, resolved_repo_root))
    target_pages = inputs.get("target_pages")
    if not isinstance(target_pages, int) or isinstance(target_pages, bool) or target_pages <= 0:
        errors.append("inputs.target_pages must be a positive integer")
        target_pages = None
    if expected_pages is not None:
        if expected_pages <= 0:
            errors.append("expected_pages must be positive")
        elif target_pages is not None and target_pages != expected_pages:
            errors.append(
                "inputs.target_pages does not match --expected-pages "
                f"({target_pages} != {expected_pages})"
            )
        target_pages = expected_pages

    thresholds = manifest.get("thresholds")
    if not isinstance(thresholds, dict):
        errors.append("thresholds must be an object")
        thresholds = {}
    errors.extend(validate_threshold_contract(thresholds))
    threshold_target_pages = thresholds.get("target_pages")
    if (
        not isinstance(threshold_target_pages, int)
        or isinstance(threshold_target_pages, bool)
        or threshold_target_pages <= 0
    ):
        errors.append("thresholds.target_pages must be a positive integer")
    elif (
        target_pages is not None
        and threshold_target_pages != target_pages
    ):
        errors.append(
            "thresholds.target_pages does not match inputs.target_pages "
            f"({threshold_target_pages} != {target_pages})"
        )
    max_bottom_whitespace_mm = float(
        threshold(
            thresholds,
            "max_bottom_whitespace_mm",
            default=DEFAULT_MAX_BOTTOM_WHITESPACE_MM,
        )
    )
    min_page_fill_ratio = float(
        threshold(
            thresholds,
            "min_page_fill_ratio",
            default=DEFAULT_MIN_PAGE_FILL_RATIO,
        )
    )
    max_page_fill_spread = float(
        threshold(
            thresholds,
            "max_page_fill_spread",
            default=DEFAULT_MAX_PAGE_FILL_SPREAD,
        )
    )
    max_bottom_whitespace_spread_mm = float(
        threshold(
            thresholds,
            "max_bottom_whitespace_spread_mm",
            default=DEFAULT_MAX_BOTTOM_WHITESPACE_SPREAD_MM,
        )
    )

    if manifest.get("selection_policy") != SELECTION_POLICY:
        errors.append(f"selection_policy must be {SELECTION_POLICY!r}")
    selection_reason = manifest.get("selection_reason")
    if selection_reason not in POLICY_ORDERS:
        errors.append(
            "selection_reason must be one of "
            f"{sorted(POLICY_ORDERS)}"
        )
        selection_reason = None

    selection_order = manifest.get("selection_order")
    if (
        not isinstance(selection_order, list)
        or not selection_order
        or any(not nonempty_string(profile) for profile in selection_order)
    ):
        errors.append("selection_order must be a non-empty array of profile names")
        selection_order = []
    elif len(set(selection_order)) != len(selection_order):
        errors.append("selection_order contains duplicate profile names")
    elif selection_reason is not None and selection_order != POLICY_ORDERS[selection_reason]:
        errors.append(
            "selection_order does not match selection_reason "
            f"(expected {POLICY_ORDERS[selection_reason]!r})"
        )
    elif selection_order[0] != "balanced":
        errors.append("selection_order must start from the balanced reference")

    attempted_profiles = manifest.get("attempted_profiles")
    if (
        not isinstance(attempted_profiles, list)
        or not attempted_profiles
        or any(not nonempty_string(profile) for profile in attempted_profiles)
    ):
        errors.append("attempted_profiles must be a non-empty array")
        attempted_profiles = []
    elif len(set(attempted_profiles)) != len(attempted_profiles):
        errors.append("attempted_profiles contains duplicate profile names")

    attempted_page_fill_modes = manifest.get("attempted_page_fill_modes")
    if attempted_page_fill_modes not in (
        ["natural"],
        ["natural", "elastic"],
    ):
        errors.append(
            "attempted_page_fill_modes must be ['natural'] or "
            "['natural', 'elastic']"
        )
        attempted_page_fill_modes = []

    page_fill_attempts = manifest.get("page_fill_attempts")
    if not isinstance(page_fill_attempts, list):
        errors.append("page_fill_attempts must be an array")
        page_fill_attempts = []

    selection_detail = manifest.get("selection_detail")
    allowed_selection_details = {
        "natural_profile_selection",
        "balanced_elastic_underfill_recovery",
    }
    if selection_detail not in allowed_selection_details:
        errors.append(
            "selection_detail must describe natural selection or bounded "
            "elastic recovery"
        )

    selected_profile = manifest.get("selected_profile")
    if not nonempty_string(selected_profile):
        errors.append("selected_profile must be a non-empty string")
        selected_profile = None
    elif selection_order and selected_profile not in selection_order:
        errors.append("selected_profile is absent from selection_order")

    selected_pdf = manifest.get("selected_pdf")
    if not nonempty_string(selected_pdf):
        errors.append("selected_pdf must be a non-empty string")

    selected_page_fill_mode = manifest.get("selected_page_fill_mode")
    if selected_page_fill_mode not in PAGE_FILL_MODES:
        errors.append("selected_page_fill_mode must be 'natural' or 'elastic'")
        selected_page_fill_mode = None

    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        errors.append("candidates must be a non-empty array")
        candidates = []

    by_profile: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"candidates[{index}] must be an object")
            continue
        profile = candidate.get("profile")
        if not nonempty_string(profile):
            errors.append(f"candidates[{index}].profile must be a non-empty string")
            continue
        if profile in by_profile:
            errors.append(f"candidate profile is duplicated: {profile}")
            continue
        page_fill_mode = candidate.get("page_fill_mode")
        if page_fill_mode not in PAGE_FILL_MODES:
            errors.append(
                f"candidates[{index}].page_fill_mode must be 'natural' or "
                "'elastic'"
            )
        elif page_fill_mode == "elastic" and profile != "balanced":
            errors.append("elastic page fill is only valid for balanced")
        by_profile[profile] = candidate

    if attempted_profiles and set(attempted_profiles) != set(by_profile):
        errors.append("attempted_profiles must match the candidate profiles")

    balanced = by_profile.get("balanced")
    if balanced is None:
        errors.append("candidates must include the balanced reference profile")
    elif selection_reason is not None:
        reason_source = balanced
        if (
            selected_page_fill_mode == "elastic"
            and len(page_fill_attempts) == 2
            and isinstance(page_fill_attempts[0], dict)
        ):
            reason_source = page_fill_attempts[0]
        inferred_reason = infer_selection_reason(
            reason_source,
            target_pages,
            max_bottom_whitespace_mm,
            min_page_fill_ratio,
            max_page_fill_spread,
            max_bottom_whitespace_spread_mm,
        )
        if selection_reason != inferred_reason:
            errors.append(
                "selection_reason does not match the balanced candidate "
                f"(expected {inferred_reason!r})"
            )

    first_eligible = next(
        (
            profile
            for profile in selection_order
            if isinstance(by_profile.get(profile), dict)
            and by_profile[profile].get("eligible") is True
        ),
        None,
    )
    if selected_profile is not None and first_eligible != selected_profile:
        errors.append(
            "selected_profile must be the first eligible profile in the "
            "reason-directed "
            f"selection_order (expected {first_eligible!r})"
        )

    selected = by_profile.get(selected_profile) if selected_profile else None
    if selected is None:
        if selected_profile is not None:
            errors.append("selected_profile has no matching candidate")
        return errors
    errors.extend(
        validate_page_fill_contract(
            attempted_modes=attempted_page_fill_modes,
            attempts=page_fill_attempts,
            selection_detail=selection_detail,
            selected_profile=selected_profile,
            selected_mode=selected_page_fill_mode,
            selected=selected,
            by_profile=by_profile,
            target_pages=target_pages,
            max_bottom_whitespace_mm=max_bottom_whitespace_mm,
            min_page_fill_ratio=min_page_fill_ratio,
            max_page_fill_spread=max_page_fill_spread,
            max_bottom_whitespace_spread_mm=(
                max_bottom_whitespace_spread_mm
            ),
        )
    )
    if selected.get("eligible") is not True:
        errors.append("selected candidate must be eligible")
    if selected.get("returncode") != 0:
        errors.append("selected candidate returncode must be zero")
    if selected.get("render_returncode") != 0:
        errors.append("selected candidate render_returncode must be zero")
    if not nonempty_string(selected.get("rasterizer")):
        errors.append("selected candidate rasterizer must be recorded")
    if selected.get("raster_error") is not None:
        errors.append("selected candidate raster_error must be null")
    if not nonempty_string(selected.get("pdf")):
        errors.append("selected candidate pdf must be a non-empty path")

    rejection_reasons = selected.get("rejection_reasons")
    if not isinstance(rejection_reasons, list):
        errors.append("selected candidate rejection_reasons must be an array")
    elif rejection_reasons:
        errors.append("selected candidate must have no rejection_reasons")

    pages = selected.get("pages")
    if not isinstance(pages, int) or isinstance(pages, bool) or pages <= 0:
        errors.append("selected candidate pages must be a positive integer")
        pages = None
    elif target_pages is not None and pages != target_pages:
        errors.append(
            f"selected candidate produced {pages} page(s), expected {target_pages}"
        )

    log_counts = selected.get("log_counts")
    if not isinstance(log_counts, dict):
        errors.append("selected candidate log_counts must be an object")
        log_counts = {}
    for key in ("overfull", "missing_glyph", "errors"):
        value = log_counts.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"selected candidate log_counts.{key} must be non-negative")
        elif value:
            errors.append(f"selected candidate log_counts.{key} must be zero")

    max_underfull = int(
        threshold(
            thresholds,
            "max_underfull",
            "max_underfull_boxes",
            default=DEFAULT_MAX_UNDERFULL,
        )
    )
    underfull = log_counts.get("underfull")
    if not isinstance(underfull, int) or isinstance(underfull, bool) or underfull < 0:
        errors.append("selected candidate log_counts.underfull must be non-negative")
    elif underfull > max_underfull:
        errors.append(
            "selected candidate underfull count exceeds threshold "
            f"({underfull} > {max_underfull})"
        )

    duplicate_pairs = selected.get("duplicate_page_pairs")
    if not isinstance(duplicate_pairs, list):
        errors.append("selected candidate duplicate_page_pairs must be an array")
    elif duplicate_pairs:
        errors.append("selected candidate contains duplicate rendered pages")

    page_metrics = selected.get("page_metrics")
    if not isinstance(page_metrics, list):
        errors.append("selected candidate page_metrics must be an array")
        page_metrics = []
    elif pages is not None and len(page_metrics) != pages:
        errors.append(
            "selected candidate page_metrics count does not match pages "
            f"({len(page_metrics)} != {pages})"
        )

    selected_fill_values: list[float] = []
    selected_bottom_values: list[float] = []
    for index, metrics in enumerate(page_metrics):
        label = f"selected candidate page_metrics[{index}]"
        if not isinstance(metrics, dict):
            errors.append(f"{label} must be an object")
            continue
        if metrics.get("blank") is not False:
            errors.append(f"{label}.blank must be false")
        nonwhite_pixels = metrics.get("nonwhite_pixels")
        if (
            not isinstance(nonwhite_pixels, int)
            or isinstance(nonwhite_pixels, bool)
            or nonwhite_pixels <= 0
        ):
            errors.append(f"{label}.nonwhite_pixels must be positive")
        content_fill_ratio = metrics.get("content_fill_ratio")
        if not finite_number(content_fill_ratio):
            errors.append(f"{label}.content_fill_ratio must be numeric")
        elif not 0 <= float(content_fill_ratio) <= 1:
            errors.append(f"{label}.content_fill_ratio must be between 0 and 1")
        else:
            selected_fill_values.append(float(content_fill_ratio))
            if float(content_fill_ratio) < min_page_fill_ratio:
                errors.append(
                    f"{label}.content_fill_ratio is below threshold "
                    f"({float(content_fill_ratio):.3f} < "
                    f"{min_page_fill_ratio:.3f})"
                )
        bottom_whitespace_mm = metrics.get("bottom_whitespace_mm")
        if not finite_number(bottom_whitespace_mm):
            errors.append(f"{label}.bottom_whitespace_mm must be numeric")
        elif float(bottom_whitespace_mm) < 0:
            errors.append(f"{label}.bottom_whitespace_mm cannot be negative")
        else:
            selected_bottom_values.append(float(bottom_whitespace_mm))
            if float(bottom_whitespace_mm) > max_bottom_whitespace_mm:
                errors.append(
                    f"{label}.bottom_whitespace_mm exceeds threshold "
                    f"({float(bottom_whitespace_mm):.2f} > "
                    f"{max_bottom_whitespace_mm:.2f})"
                )

    if pages is not None and pages > 1:
        page_balance = selected.get("page_balance")
        if not isinstance(page_balance, dict):
            errors.append("selected candidate page_balance must be an object")
            page_balance = {}
        computed_fill_spread = (
            max(selected_fill_values) - min(selected_fill_values)
            if len(selected_fill_values) == pages
            else None
        )
        recorded_fill_spread = page_balance.get("page_fill_spread")
        if not finite_number(recorded_fill_spread):
            errors.append("selected candidate page_fill_spread must be numeric")
        elif computed_fill_spread is not None and abs(
            float(recorded_fill_spread) - computed_fill_spread
        ) > 0.005:
            errors.append(
                "selected candidate page_fill_spread does not match page_metrics"
            )
        elif float(recorded_fill_spread) > max_page_fill_spread:
            errors.append(
                "selected candidate page_fill_spread exceeds threshold "
                f"({float(recorded_fill_spread):.3f} > "
                f"{max_page_fill_spread:.3f})"
            )

        computed_bottom_spread = (
            max(selected_bottom_values) - min(selected_bottom_values)
            if len(selected_bottom_values) == pages
            else None
        )
        recorded_bottom_spread = page_balance.get("bottom_whitespace_spread_mm")
        if not finite_number(recorded_bottom_spread):
            errors.append(
                "selected candidate bottom_whitespace_spread_mm must be numeric"
            )
        elif computed_bottom_spread is not None and abs(
            float(recorded_bottom_spread) - computed_bottom_spread
        ) > 0.05:
            errors.append(
                "selected candidate bottom_whitespace_spread_mm does not match "
                "page_metrics"
            )
        elif float(recorded_bottom_spread) > max_bottom_whitespace_spread_mm:
            errors.append(
                "selected candidate bottom_whitespace_spread_mm exceeds "
                "threshold "
                f"({float(recorded_bottom_spread):.2f} > "
                f"{max_bottom_whitespace_spread_mm:.2f})"
            )

    if check_artifacts:
        errors.extend(validate_selected_artifacts(manifest, resolved_repo_root))
    return errors


def main() -> int:
    args = parse_args()
    path = args.manifest.expanduser().resolve()
    try:
        manifest = load_manifest(path)
        repo_root = resolve_repo_root(args.repo_root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    errors = validate_manifest(
        manifest, args.expected_pages, repo_root, check_artifacts=True
    )
    if errors:
        print(f"fit manifest validation failed ({len(errors)} issue(s)):")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "fit manifest validation passed: "
        f"profile={manifest['selected_profile']}, "
        f"pages={manifest['inputs']['target_pages']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
