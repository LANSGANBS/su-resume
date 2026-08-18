#!/usr/bin/env python3
"""Audit a public resume tree for likely personal or private information."""

from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import json
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlsplit
import zlib


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
DEFAULT_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "node_modules",
    "output",
    "tests",
    "tmp",
}
DEFAULT_EXCLUDED_GLOBS = {
    "*.aux",
    "*.fdb_latexmk",
    "*.fls",
    "*.log",
    "*.out",
    "*.synctex.gz",
    "*.xdv",
}
RESERVED_DOMAINS = {"example.com", "example.org", "example.net", "localhost"}
RESERVED_EMAILS = {"noreply@github.com"}
RESERVED_EMAIL_DOMAINS = {"users.noreply.github.com"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_METADATA_CHUNKS = {b"eXIf", b"iTXt", b"tEXt", b"zTXt"}
URL_RE = re.compile(r"https?://[^\s<>{}\\]+", re.IGNORECASE)
EMAIL_RE = re.compile(
    r"(?<![\w.+-])"
    r"([\w.+-]+@([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+))"
)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
CN_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
CN_MOBILE_RE = re.compile(
    r"(?<![\d.])(?:\+?\s*86(?:[\s()~.-]|\\,)*)?"
    r"(1[3-9](?:(?:[\s()~.-]|\\,)*\d){9})(?![\d.])"
)
INTERNATIONAL_PHONE_RE = re.compile(
    r"(?<![\w+])\+\s*\d{1,3}(?:(?:[\s()~.-]|\\,)*\d){7,14}(?!\d)"
)
RESERVED_PHONE_DIGITS = {"13800000000"}
US_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
LABELLED_PHONE_RE = re.compile(
    r"(?:phone|mobile|tel(?:ephone)?|电话|手机)"
    r"\s*[:：]?\s*([+()\d][\d ()-]{6,}\d)",
    re.IGNORECASE,
)
POSIX_USER_ROOTS = ("/" + "Users" + "/", "/" + "home" + "/")
WINDOWS_USER_ROOT = "Users" + "\\"
HOME_PATH_RE = re.compile(
    r"(?:"
    + "|".join(re.escape(root) for root in POSIX_USER_ROOTS)
    + r"|[A-Za-z]:\\"
    + re.escape(WINDOWS_USER_ROOT)
    + r")"
    + r"[^/\s\"'<>\\]+"
)
PEM_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE
)
KNOWN_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})"
)
ASSIGNED_SECRET_RE = re.compile(
    r"\b(?:api[_-]?key|access[_-]?token|secret|password|passwd|authorization)"
    r"\b\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{8,})",
    re.IGNORECASE,
)
PRIVATE_HOST_SUFFIXES = (
    ".corp",
    ".internal",
    ".intranet",
    ".local",
)
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "key",
    "password",
    "secret",
    "signature",
    "token",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    path: str
    line: int
    column: int
    snippet: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan public files and PDF text/metadata for personal contacts, "
            "credentials, private hosts, private paths, and user-supplied deny terms."
        )
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Files or directories to scan.")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Exclude a relative path glob; repeat as needed.",
    )
    parser.add_argument(
        "--deny-file",
        type=Path,
        help="Private file containing one literal sensitive term per line.",
    )
    parser.add_argument(
        "--allow-domain",
        action="append",
        default=[],
        metavar="DOMAIN",
        help="Treat this confirmed-public URL domain and its subdomains as allowed.",
    )
    parser.add_argument(
        "--fail-on",
        choices=("low", "medium", "high", "none"),
        default="high",
        help="Return exit code 1 at or above this severity (default: high).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=5_000_000,
        help="Maximum non-PDF file size to inspect (default: 5000000).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Write the redacted machine-readable report to this path.",
    )
    return parser.parse_args()


def allowed_domain(host: str, allowed: set[str]) -> bool:
    normalized = host.rstrip(".").lower()
    return any(normalized == domain or normalized.endswith("." + domain) for domain in allowed)


def redact_snippet(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    prefix = text[line_start:start][-40:]
    suffix = text[end:line_end][:40]
    return (prefix + "[REDACTED]" + suffix).strip()


def location(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    previous_newline = text.rfind("\n", 0, offset)
    column = offset - previous_newline
    return line, column


def make_finding(
    severity: str,
    category: str,
    display_path: str,
    text: str,
    start: int,
    end: int,
) -> Finding:
    line, column = location(text, start)
    return Finding(
        severity=severity,
        category=category,
        path=display_path,
        line=line,
        column=column,
        snippet=redact_snippet(text, start, end),
    )


def private_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not isinstance(address, ipaddress.IPv4Address):
        return False
    octets = tuple(int(part) for part in value.split("."))
    return (
        octets[0] == 10
        or octets[0] == 127
        or (octets[0] == 172 and 16 <= octets[1] <= 31)
        or (octets[0] == 192 and octets[1] == 168)
        or (octets[0] == 169 and octets[1] == 254)
    )


def load_deny_terms(path: Path | None) -> list[tuple[int, str]]:
    if path is None:
        return []
    try:
        lines = path.expanduser().read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read deny file: {exc}") from exc
    terms: list[tuple[int, str]] = []
    for line_number, raw in enumerate(lines, start=1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if len(value) < 2:
            raise ValueError(f"deny term on line {line_number} is too short")
        terms.append((line_number, value))
    return terms


def scan_text(
    text: str,
    display_path: str,
    allowed_domains: set[str],
    deny_terms: list[tuple[int, str]],
) -> list[Finding]:
    findings: list[Finding] = []

    for match in EMAIL_RE.finditer(text):
        address = match.group(1).lower()
        domain = match.group(2).lower()
        if (
            address not in RESERVED_EMAILS
            and domain not in RESERVED_EMAIL_DOMAINS
            and not allowed_domain(domain, RESERVED_DOMAINS)
        ):
            findings.append(
                make_finding(
                    "high", "personal_email", display_path, text, match.start(), match.end()
                )
            )

    for pattern, category in (
        (CN_ID_RE, "government_id"),
        (US_SSN_RE, "government_id"),
        (HOME_PATH_RE, "private_home_path"),
        (PEM_KEY_RE, "private_key"),
        (KNOWN_TOKEN_RE, "credential"),
    ):
        for match in pattern.finditer(text):
            findings.append(
                make_finding(
                    "high", category, display_path, text, match.start(), match.end()
                )
            )

    phone_spans: set[tuple[int, int]] = set()
    for pattern in (CN_MOBILE_RE, INTERNATIONAL_PHONE_RE):
        for match in pattern.finditer(text):
            digits = re.sub(r"\D", "", match.group(0))
            if any(digits.endswith(value) for value in RESERVED_PHONE_DIGITS):
                continue
            phone_spans.add(match.span())

    for match in LABELLED_PHONE_RE.finditer(text):
        start, end = match.span(1)
        digits = re.sub(r"\D", "", text[start:end])
        if not any(digits.endswith(value) for value in RESERVED_PHONE_DIGITS):
            phone_spans.add((start, end))

    for start, end in sorted(phone_spans):
        findings.append(
            make_finding(
                "high",
                "personal_phone",
                display_path,
                text,
                start,
                end,
            )
        )

    for match in ASSIGNED_SECRET_RE.finditer(text):
        start, end = match.span(1)
        findings.append(
            make_finding("high", "assigned_secret", display_path, text, start, end)
        )

    for match in IPV4_RE.finditer(text):
        if private_ip(match.group(0)):
            findings.append(
                make_finding(
                    "high",
                    "private_network_address",
                    display_path,
                    text,
                    match.start(),
                    match.end(),
                )
            )

    for match in URL_RE.finditer(text):
        raw_url = match.group(0).rstrip(".,;:!?)\\]}\"'")
        end = match.start() + len(raw_url)
        parsed = urlsplit(raw_url)
        host = (parsed.hostname or "").lower()
        query_keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
        if query_keys & SENSITIVE_QUERY_KEYS:
            findings.append(
                make_finding(
                    "high",
                    "credential_in_url",
                    display_path,
                    text,
                    match.start(),
                    end,
                )
            )
        if (
            host == "localhost"
            or host.endswith(PRIVATE_HOST_SUFFIXES)
            or private_ip(host)
        ):
            findings.append(
                make_finding(
                    "high", "private_url", display_path, text, match.start(), end
                )
            )
        elif host and not allowed_domain(host, allowed_domains | RESERVED_DOMAINS):
            findings.append(
                make_finding(
                    "medium", "url_requires_review", display_path, text, match.start(), end
                )
            )

    folded = text.casefold()
    for deny_line, term in deny_terms:
        folded_term = term.casefold()
        offset = 0
        while True:
            start = folded.find(folded_term, offset)
            if start < 0:
                break
            end = start + len(term)
            findings.append(
                make_finding(
                    "high",
                    f"private_deny_term_line_{deny_line}",
                    display_path,
                    text,
                    start,
                    end,
                )
            )
            offset = end

    return findings


def should_exclude(relative: Path, patterns: list[str]) -> bool:
    if any(part in DEFAULT_EXCLUDED_PARTS for part in relative.parts):
        return True
    value = relative.as_posix()
    active_patterns = [*DEFAULT_EXCLUDED_GLOBS, *patterns]
    return any(
        fnmatch.fnmatch(value, pattern)
        or any(fnmatch.fnmatch(part, pattern) for part in relative.parts)
        for pattern in active_patterns
    )


def iter_files(root: Path, patterns: list[str]) -> Iterable[tuple[Path, str]]:
    if root.is_symlink():
        yield root, root.name
        return
    if root.is_file():
        yield root, root.name
        return
    for candidate in sorted(root.rglob("*")):
        relative = candidate.relative_to(root)
        if should_exclude(relative, patterns):
            continue
        if candidate.is_file() or candidate.is_symlink():
            yield candidate, relative.as_posix()


def run_text_tool(command: list[str]) -> str:
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
        message = detail[-1] if detail else "unknown error"
        raise RuntimeError(message)
    return completed.stdout


def extract_pdf_text(path: Path) -> str:
    pdftotext = shutil.which("pdftotext")
    pdfinfo = shutil.which("pdfinfo")
    if not pdftotext or not pdfinfo:
        raise RuntimeError("pdftotext and pdfinfo are required to inspect PDF files")
    body = run_text_tool([pdftotext, "-layout", str(path), "-"])
    metadata = run_text_tool([pdfinfo, str(path)])
    return body + "\n--- PDF METADATA ---\n" + metadata


def read_text_file(path: Path, max_bytes: int) -> tuple[str | None, str | None]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"cannot stat file: {exc}"
    if size > max_bytes:
        return None, "file exceeds inspection size limit"
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, f"cannot read file: {exc}"
    if b"\x00" in data:
        return None, "uninspected binary file"
    return data.decode("utf-8", errors="replace"), None


def scan_png(path: Path, display_path: str, max_bytes: int) -> list[Finding]:
    try:
        data = path.read_bytes()
    except OSError:
        return [
            Finding(
                severity="high",
                category="image_not_inspected",
                path=display_path,
                line=1,
                column=1,
                snippet="[PNG COULD NOT BE READ]",
            )
        ]
    if len(data) > max_bytes:
        return [
            Finding(
                severity="medium",
                category="image_not_inspected",
                path=display_path,
                line=1,
                column=1,
                snippet="[PNG EXCEEDS INSPECTION SIZE LIMIT]",
            )
        ]
    if not data.startswith(PNG_SIGNATURE):
        return [
            Finding(
                severity="high",
                category="malformed_png",
                path=display_path,
                line=1,
                column=1,
                snippet="[INVALID PNG SIGNATURE]",
            )
        ]

    findings: list[Finding] = []
    offset = len(PNG_SIGNATURE)
    seen_ihdr = False
    seen_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            findings.append(
                Finding(
                    severity="high",
                    category="malformed_png",
                    path=display_path,
                    line=1,
                    column=1,
                    snippet="[TRUNCATED PNG CHUNK]",
                )
            )
            break
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        chunk_end = payload_end + 4
        if chunk_end > len(data):
            findings.append(
                Finding(
                    severity="high",
                    category="malformed_png",
                    path=display_path,
                    line=1,
                    column=1,
                    snippet="[PNG CHUNK EXCEEDS FILE BOUNDS]",
                )
            )
            break

        payload = data[payload_start:payload_end]
        expected_crc = struct.unpack(">I", data[payload_end:chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            findings.append(
                Finding(
                    severity="high",
                    category="malformed_png",
                    path=display_path,
                    line=1,
                    column=1,
                    snippet="[PNG CRC CHECK FAILED]",
                )
            )

        if not seen_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                findings.append(
                    Finding(
                        severity="high",
                        category="malformed_png",
                        path=display_path,
                        line=1,
                        column=1,
                        snippet="[PNG DOES NOT START WITH A VALID IHDR]",
                    )
                )
            seen_ihdr = True

        if chunk_type in PNG_METADATA_CHUNKS:
            findings.append(
                Finding(
                    severity="high",
                    category="image_text_metadata",
                    path=display_path,
                    line=1,
                    column=1,
                    snippet="[PNG CONTAINS TEXT OR EXIF METADATA]",
                )
            )

        offset = chunk_end
        if chunk_type == b"IEND":
            seen_iend = True
            if length != 0 or offset != len(data):
                findings.append(
                    Finding(
                        severity="high",
                        category="malformed_png",
                        path=display_path,
                        line=1,
                        column=1,
                        snippet="[INVALID PNG IEND OR TRAILING DATA]",
                    )
                )
            break

    if not seen_ihdr or not seen_iend:
        findings.append(
            Finding(
                severity="high",
                category="malformed_png",
                path=display_path,
                line=1,
                column=1,
                snippet="[PNG IS MISSING IHDR OR IEND]",
            )
        )
    return findings


def scan_path(
    path: Path,
    display_path: str,
    max_bytes: int,
    allowed_domains: set[str],
    deny_terms: list[tuple[int, str]],
) -> list[Finding]:
    if path.is_symlink():
        placeholder = path.name
        return [
            Finding(
                severity="medium",
                category="symlink_requires_review",
                path=display_path,
                line=1,
                column=1,
                snippet=f"{placeholder}: [REDACTED TARGET]",
            )
        ]

    if path.suffix.lower() == ".pdf":
        try:
            text = extract_pdf_text(path)
        except RuntimeError:
            return [
                Finding(
                    severity="high",
                    category="pdf_not_inspected",
                    path=display_path,
                    line=1,
                    column=1,
                    snippet="[PDF COULD NOT BE INSPECTED]",
                )
            ]
        return scan_text(text, display_path, allowed_domains, deny_terms)

    if path.suffix.lower() == ".png":
        return scan_png(path, display_path, max_bytes)

    text, error = read_text_file(path, max_bytes)
    if error:
        severity = "medium" if "binary" in error or "size" in error else "high"
        return [
            Finding(
                severity=severity,
                category="file_not_inspected",
                path=display_path,
                line=1,
                column=1,
                snippet=f"[{error.upper()}]",
            )
        ]
    assert text is not None
    return scan_text(text, display_path, allowed_domains, deny_terms)


def write_json_report(
    path: Path, scanned_files: int, findings: list[Finding]
) -> None:
    payload = {
        "scanned_files": scanned_files,
        "finding_count": len(findings),
        "counts": {
            severity: sum(item.severity == severity for item in findings)
            for severity in ("high", "medium", "low")
        },
        "findings": [asdict(item) for item in findings],
    }
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.max_bytes <= 0:
        print("error: --max-bytes must be positive", file=sys.stderr)
        return 2
    try:
        deny_terms = load_deny_terms(args.deny_file)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    allowed_domains = {
        value.strip().lower().rstrip(".")
        for value in args.allow_domain
        if value.strip()
    }
    findings: list[Finding] = []
    scanned_files = 0
    for raw_root in args.paths:
        root = raw_root.expanduser().resolve()
        if not root.exists() and not root.is_symlink():
            print(f"error: scan path does not exist: {root}", file=sys.stderr)
            return 2
        for path, display_path in iter_files(root, args.exclude):
            scanned_files += 1
            findings.extend(
                scan_path(
                    path,
                    display_path,
                    args.max_bytes,
                    allowed_domains,
                    deny_terms,
                )
            )

    findings.sort(
        key=lambda item: (
            -SEVERITY_RANK[item.severity],
            item.path,
            item.line,
            item.column,
            item.category,
        )
    )
    if args.json_out:
        try:
            write_json_report(args.json_out, scanned_files, findings)
        except OSError as exc:
            print(f"error: cannot write JSON report: {exc}", file=sys.stderr)
            return 2

    print(f"privacy audit scanned {scanned_files} file(s)")
    if findings:
        for finding in findings:
            print(
                f"{finding.severity.upper():6} "
                f"{finding.path}:{finding.line}:{finding.column} "
                f"{finding.category}: {finding.snippet}"
            )
    else:
        print("no findings")

    counts = {
        severity: sum(item.severity == severity for item in findings)
        for severity in ("high", "medium", "low")
    }
    print(
        "summary: "
        + ", ".join(f"{severity}={counts[severity]}" for severity in counts)
    )

    if args.fail_on == "none":
        return 0
    threshold = SEVERITY_RANK[args.fail_on]
    return int(any(SEVERITY_RANK[item.severity] >= threshold for item in findings))


if __name__ == "__main__":
    raise SystemExit(main())
