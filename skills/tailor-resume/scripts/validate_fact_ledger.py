#!/usr/bin/env python3
"""Validate the private JSON fact ledger used to author resume claims."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


FACT_ID_RE = re.compile(r"^FACT-\d{3,}$")
SOURCE_ID_RE = re.compile(r"^SRC-\d{3,}$")
QUESTION_ID_RE = re.compile(r"^Q-\d{3,}$")
VALID_FACT_STATUSES = {"usable", "needs-confirmation", "excluded"}
VALID_QUESTION_STATUSES = {"open", "resolved"}
TODO_RE = re.compile(r"\bTODO\b|待确认|待补充", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate source references, evidence, statuses, and TODO handling."
    )
    parser.add_argument("ledger", type=Path, help="Path to fact-ledger.json.")
    parser.add_argument(
        "--check-source-files",
        action="store_true",
        help="Require every source path to exist relative to the ledger directory.",
    )
    parser.add_argument(
        "--require-usable-facts",
        action="store_true",
        help="Fail when the ledger contains no usable facts.",
    )
    return parser.parse_args()


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def unique_id(
    item: Any,
    index: int,
    kind: str,
    pattern: re.Pattern[str],
    seen: set[str],
    errors: list[str],
) -> str | None:
    if not isinstance(item, dict):
        errors.append(f"{kind}[{index}] must be an object")
        return None
    item_id = item.get("id")
    if not nonempty_string(item_id) or not pattern.fullmatch(item_id):
        errors.append(f"{kind}[{index}].id has an invalid format")
        return None
    if item_id in seen:
        errors.append(f"{kind} id is duplicated: {item_id}")
        return None
    seen.add(item_id)
    return item_id


def load_ledger(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"ledger does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read ledger: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("ledger root must be a JSON object")
    return value


def validate_ledger(
    ledger: dict[str, Any],
    ledger_dir: Path,
    check_source_files: bool,
    require_usable_facts: bool,
) -> list[str]:
    errors: list[str] = []
    if ledger.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    sources = ledger.get("source_index")
    facts = ledger.get("facts")
    questions = ledger.get("open_questions")
    if not isinstance(sources, list):
        errors.append("source_index must be an array")
        sources = []
    if not isinstance(facts, list):
        errors.append("facts must be an array")
        facts = []
    if not isinstance(questions, list):
        errors.append("open_questions must be an array")
        questions = []

    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        source_id = unique_id(
            source, index, "source_index", SOURCE_ID_RE, source_ids, errors
        )
        if source_id is None or not isinstance(source, dict):
            continue
        source_path = source.get("path")
        if not nonempty_string(source_path):
            errors.append(f"{source_id}.path must be a non-empty string")
        else:
            candidate = Path(source_path)
            if candidate.is_absolute() or ".." in candidate.parts:
                errors.append(f"{source_id}.path must stay relative to the private root")
            elif not candidate.parts or candidate.parts[0] != "sources":
                errors.append(f"{source_id}.path must be under the sources directory")
            elif check_source_files and not (ledger_dir / candidate).is_file():
                errors.append(f"{source_id}.path does not exist")
        if not nonempty_string(source.get("description")):
            errors.append(f"{source_id}.description must be a non-empty string")

    fact_ids: set[str] = set()
    usable_count = 0
    facts_by_id: dict[str, dict[str, Any]] = {}
    for index, fact in enumerate(facts):
        fact_id = unique_id(fact, index, "facts", FACT_ID_RE, fact_ids, errors)
        if fact_id is None or not isinstance(fact, dict):
            continue
        facts_by_id[fact_id] = fact
        status = fact.get("status")
        if status not in VALID_FACT_STATUSES:
            errors.append(f"{fact_id}.status must be one of {sorted(VALID_FACT_STATUSES)}")
            continue
        if not nonempty_string(fact.get("category")):
            errors.append(f"{fact_id}.category must be a non-empty string")
        if not nonempty_string(fact.get("claim")):
            errors.append(f"{fact_id}.claim must be a non-empty string")

        refs = fact.get("source_ids")
        if not isinstance(refs, list) or any(not nonempty_string(ref) for ref in refs):
            errors.append(f"{fact_id}.source_ids must be an array of source ids")
            refs = []
        for ref in refs:
            if ref not in source_ids:
                errors.append(f"{fact_id} references unknown source id {ref}")

        public_text = fact.get("public_text")
        evidence = fact.get("evidence")
        if status == "usable":
            usable_count += 1
            if not refs:
                errors.append(f"{fact_id} is usable but has no source_ids")
            if not nonempty_string(evidence) or TODO_RE.search(evidence):
                errors.append(f"{fact_id}.evidence must be concrete and contain no TODO")
            if not nonempty_string(public_text) or TODO_RE.search(public_text):
                errors.append(f"{fact_id}.public_text must be final and contain no TODO")
        elif status == "needs-confirmation":
            if nonempty_string(public_text) and not TODO_RE.search(public_text):
                errors.append(
                    f"{fact_id}.public_text must be empty or explicitly marked TODO"
                )

    question_ids: set[str] = set()
    for index, question in enumerate(questions):
        question_id = unique_id(
            question, index, "open_questions", QUESTION_ID_RE, question_ids, errors
        )
        if question_id is None or not isinstance(question, dict):
            continue
        status = question.get("status")
        if status not in VALID_QUESTION_STATUSES:
            errors.append(
                f"{question_id}.status must be one of "
                f"{sorted(VALID_QUESTION_STATUSES)}"
            )
        if not nonempty_string(question.get("question")):
            errors.append(f"{question_id}.question must be a non-empty string")
        fact_id = question.get("fact_id")
        if fact_id is not None and fact_id not in facts_by_id:
            errors.append(f"{question_id} references unknown fact id {fact_id}")
        answer_source_id = question.get("answer_source_id")
        if status == "resolved":
            if not nonempty_string(answer_source_id):
                errors.append(
                    f"{question_id}.answer_source_id is required when resolved"
                )
            elif answer_source_id not in source_ids:
                errors.append(
                    f"{question_id} references unknown answer source id "
                    f"{answer_source_id}"
                )

    if require_usable_facts and usable_count == 0:
        errors.append("ledger must contain at least one usable fact")
    return errors


def main() -> int:
    args = parse_args()
    path = args.ledger.expanduser().resolve()
    try:
        ledger = load_ledger(path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    errors = validate_ledger(
        ledger,
        path.parent,
        check_source_files=args.check_source_files,
        require_usable_facts=args.require_usable_facts,
    )
    if errors:
        print(f"fact ledger validation failed ({len(errors)} issue(s)):")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "fact ledger validation passed: "
        f"{len(ledger.get('source_index', []))} source(s), "
        f"{len(ledger.get('facts', []))} fact(s), "
        f"{len(ledger.get('open_questions', []))} question(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
