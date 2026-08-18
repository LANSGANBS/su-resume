#!/usr/bin/env python3
"""Fail closed on common privacy leaks without echoing matched values."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import ipaddress
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qsl, urlsplit


MAX_FILE_BYTES = 8 * 1024 * 1024
EXAMPLE_DOMAINS = {"example.com", "example.net", "example.org"}
PRIVATE_HOST_LABELS = {
    "corp",
    "int",
    "internal",
    "intra",
    "intranet",
    "lan",
    "local",
    "private",
}
GENERIC_USERS = {
    "example",
    "runner",
    "user",
    "username",
}
GENERIC_PDF_AUTHORS = {
    "anonymous",
    "example",
    "maintainer",
    "resume template",
    "template",
}

EMAIL_RE = re.compile(
    r"(?<![\w.+-])"
    r"([A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Z0-9-]+\.)+[A-Z]{2,63})"
    r"(?![\w.-])",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?86[\s()\\,.\-]*)?"
    r"(1[3-9]\d(?:[\s()\\,.\-]*\d){8})(?!\d)"
)
URL_RE = re.compile(r"\b(?:https?|ftp)://[^\s<>{}\[\]\"'`]+", re.IGNORECASE)
SSH_URL_RE = re.compile(
    r"(?<![\w.-])(?:ssh://)?[A-Z0-9._-]+@([A-Z0-9.-]+)(?=[:/])",
    re.IGNORECASE,
)
HOME_PATH_RE = re.compile(
    r"(?<![A-Z0-9])/(Users|home)/([A-Z0-9._-]+)(?=/|\b)",
    re.IGNORECASE,
)
WINDOWS_HOME_RE = re.compile(
    r"(?<![A-Z0-9])[A-Z]:\\Users\\([A-Z0-9._-]+)(?=\\|\b)",
    re.IGNORECASE,
)
TEX_PDF_AUTHOR_RE = re.compile(
    r"pdfauthor\s*=\s*\{([^}]*)\}",
    re.IGNORECASE,
)
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.IGNORECASE,
)
GENERIC_SECRET_RE = re.compile(
    r"""(?ix)
    \b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|
        password|passwd|secret)\b
    \s*[:=]\s*["']?([A-Z0-9_./+=-]{16,})
    """
)

TOKEN_PATTERNS: Sequence[Tuple[str, re.Pattern[str]]] = (
    ("github-token", re.compile(r"\bgh[pousr]_[A-Z0-9]{30,}\b", re.IGNORECASE)),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "google-api-key",
        re.compile(r"\bAIza[A-Z0-9_-]{30,}\b", re.IGNORECASE),
    ),
    (
        "slack-token",
        re.compile(r"\bxox[baprs]-[A-Z0-9-]{20,}\b", re.IGNORECASE),
    ),
    (
        "openai-token",
        re.compile(r"\bsk-(?:proj-)?[A-Z0-9_-]{20,}\b", re.IGNORECASE),
    ),
    (
        "stripe-secret",
        re.compile(r"\bsk_(?:live|test)_[A-Z0-9]{20,}\b", re.IGNORECASE),
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Z0-9_-]{8,}\.[A-Z0-9_-]{8,}\.[A-Z0-9_-]{8,}\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclasses.dataclass(frozen=True)
class Finding:
    location: str
    line: Optional[int]
    rule: str
    message: str

    def render(self) -> str:
        safe_location = redact_location(self.location)
        line_suffix = ":{0}".format(self.line) if self.line else ""
        return "{0}{1}: [{2}] {3}".format(
            safe_location,
            line_suffix,
            self.rule,
            self.message,
        )


def redact_location(value: str) -> str:
    """Redact sensitive-shaped substrings if a filename itself is unsafe."""
    redacted = EMAIL_RE.sub("<redacted-email>", value)
    redacted = PHONE_RE.sub("<redacted-phone>", redacted)
    redacted = HOME_PATH_RE.sub(r"/\1/<redacted-user>", redacted)
    redacted = WINDOWS_HOME_RE.sub(r"C:\\Users\\<redacted-user>", redacted)
    for _, pattern in TOKEN_PATTERNS:
        redacted = pattern.sub("<redacted-token>", redacted)
    return redacted


def is_example_email(address: str) -> bool:
    domain = address.rsplit("@", 1)[-1].casefold().rstrip(".")
    return (
        domain in EXAMPLE_DOMAINS
        or address.casefold() == "noreply@github.com"
        or domain == "users.noreply.github.com"
        or domain.endswith(".test")
        or domain.endswith(".invalid")
    )


def is_placeholder_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return len(digits) == 11 and len(set(digits[-8:])) == 1


def is_placeholder_secret(value: str) -> bool:
    lowered = value.casefold()
    markers = (
        "changeme",
        "dummy",
        "example",
        "placeholder",
        "redacted",
        "sample",
        "xxxx",
    )
    return (
        any(marker in lowered for marker in markers)
        or value.startswith("$")
        or "{{" in value
        or "<" in value
    )


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {character: value.count(character) for character in set(value)}
    length = float(len(value))
    return -sum(
        (count / length) * math.log(count / length, 2)
        for count in counts.values()
    )


def url_privacy_issue(raw_url: str) -> Optional[str]:
    candidate = raw_url.rstrip(".,;:!?)]}>\\")
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return "URL 无法安全解析"

    if not host:
        return "URL 缺少可验证的主机名"
    if parsed.username is not None or parsed.password is not None:
        return "URL 中包含嵌入式凭据"
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.casefold().replace("-", "_")
        if (
            value
            and any(
                marker in normalized_key
                for marker in ("auth", "key", "secret", "signature", "token")
            )
            and not is_placeholder_secret(value)
        ):
            return "URL 查询参数中包含疑似访问凭据"
    if host in EXAMPLE_DOMAINS or any(
        host.endswith("." + domain) for domain in EXAMPLE_DOMAINS
    ):
        return None
    if host == "localhost" or host.endswith(".localhost"):
        return "URL 指向本机地址"

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        return "URL 指向非公网 IP"

    labels = host.split(".")
    if len(labels) == 1:
        return "URL 使用无法公开解析的单标签主机名"
    if any(label in PRIVATE_HOST_LABELS for label in labels[:-2]):
        return "URL 主机名包含常见内部网络标签"
    if any(
        host.endswith(suffix)
        for suffix in (".corp", ".internal", ".intranet", ".lan", ".local")
    ):
        return "URL 使用常见内部网络后缀"
    return None


def ssh_host_privacy_issue(host: str) -> Optional[str]:
    probe = "ssh://user@{0}/repository".format(host)
    return url_privacy_issue(probe)


def scan_text(location: str, text: str) -> List[Finding]:
    findings: List[Finding] = []
    seen: Set[Tuple[int, str]] = set()

    def add(line_number: int, rule: str, message: str) -> None:
        key = (line_number, rule)
        if key not in seen:
            findings.append(Finding(location, line_number, rule, message))
            seen.add(key)

    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in EMAIL_RE.finditer(line):
            if not is_example_email(match.group(1)):
                add(
                    line_number,
                    "non-example-email",
                    "发现非保留示例域邮箱；请改为示例值或确认公开意图",
                )

        for match in PHONE_RE.finditer(line):
            if not is_placeholder_phone(match.group(0)):
                add(
                    line_number,
                    "phone-number",
                    "发现疑似真实中国大陆手机号",
                )

        for match in URL_RE.finditer(line):
            issue = url_privacy_issue(match.group(0))
            if issue:
                add(line_number, "private-url", issue)

        for match in SSH_URL_RE.finditer(line):
            issue = ssh_host_privacy_issue(match.group(1))
            if issue:
                add(line_number, "private-git-url", issue)

        for match in HOME_PATH_RE.finditer(line):
            if match.group(2).casefold() not in GENERIC_USERS:
                add(
                    line_number,
                    "local-home-path",
                    "发现带本机用户名的 POSIX 绝对路径",
                )

        for match in WINDOWS_HOME_RE.finditer(line):
            if match.group(1).casefold() not in GENERIC_USERS:
                add(
                    line_number,
                    "local-home-path",
                    "发现带本机用户名的 Windows 绝对路径",
                )

        if PRIVATE_KEY_RE.search(line):
            add(line_number, "private-key", "发现私钥头")

        for rule, pattern in TOKEN_PATTERNS:
            if pattern.search(line):
                add(line_number, rule, "发现符合常见凭据格式的高风险字符串")

        for match in GENERIC_SECRET_RE.finditer(line):
            candidate = match.group(1)
            if (
                not is_placeholder_secret(candidate)
                and len(set(candidate)) >= 8
                and shannon_entropy(candidate) >= 3.0
            ):
                add(
                    line_number,
                    "assigned-secret",
                    "发现疑似直接赋值的高熵凭据",
                )

        for match in TEX_PDF_AUTHOR_RE.finditer(line):
            author = " ".join(match.group(1).casefold().split())
            if author and not any(
                marker in author for marker in GENERIC_PDF_AUTHORS
            ):
                add(
                    line_number,
                    "tex-pdf-author",
                    "LaTeX PDF 作者字段不像通用示例身份",
                )

    return findings


def run(
    command: Sequence[str],
    cwd: Optional[Path] = None,
    input_bytes: Optional[bytes] = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(
            list(command),
            124,
            stdout=b"",
            stderr=error.__class__.__name__.encode("ascii", "replace"),
        )


def find_git_root(start: Path) -> Optional[Path]:
    probe = run(("git", "rev-parse", "--show-toplevel"), cwd=start)
    if probe.returncode != 0:
        return None
    return Path(probe.stdout.decode("utf-8", "replace").strip()).resolve()


def repo_path(path: Path, root: Optional[Path]) -> str:
    resolved = path.resolve()
    if root is not None:
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            pass
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:10]
    return "<external:{0}>/{1}".format(digest, resolved.name)


def git_paths(root: Path) -> Tuple[List[Path], Set[Path]]:
    tracked_probe = run(("git", "ls-files", "-z"), cwd=root)
    candidate_probe = run(
        ("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"),
        cwd=root,
    )
    if tracked_probe.returncode != 0 or candidate_probe.returncode != 0:
        raise RuntimeError("无法读取 Git 文件列表")

    def decode_paths(data: bytes) -> List[Path]:
        return [
            (root / value.decode("utf-8", "surrogateescape")).resolve()
            for value in data.split(b"\0")
            if value
        ]

    tracked = set(decode_paths(tracked_probe.stdout))
    return decode_paths(candidate_probe.stdout), tracked


def is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def collect_files(
    requested: Sequence[Path],
    root: Optional[Path],
) -> Tuple[List[Path], Set[Path]]:
    candidates: Set[Path] = set()
    tracked: Set[Path] = set()
    git_candidates: List[Path] = []
    if root is not None:
        git_candidates, tracked = git_paths(root)

    for requested_path in requested:
        path = requested_path.resolve()
        if path.is_file() or path.is_symlink():
            candidates.add(path)
            continue
        if not path.exists():
            raise FileNotFoundError(str(requested_path))

        if root is not None and is_inside(path, root):
            candidates.update(
                candidate for candidate in git_candidates if is_inside(candidate, path)
            )
            continue

        for directory, directory_names, file_names in os.walk(path):
            directory_names[:] = [
                name
                for name in directory_names
                if name not in {".git", ".hg", ".svn", "__pycache__"}
            ]
            candidates.update(Path(directory, name).resolve() for name in file_names)

    return sorted(candidates), tracked


def looks_binary(data: bytes) -> bool:
    if b"\0" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def safe_pdf_author(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return not normalized or any(
        marker in normalized for marker in GENERIC_PDF_AUTHORS
    )


def scan_pdf(path: Path, location: str, tracked: bool) -> List[Finding]:
    findings: List[Finding] = []
    if tracked:
        findings.append(
            Finding(
                location,
                None,
                "tracked-pdf",
                "生成 PDF 被 Git 跟踪；请发布源码并单独分发审核后的产物",
            )
        )

    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        findings.append(
            Finding(
                location,
                None,
                "pdf-metadata-unchecked",
                "缺少 pdfinfo，无法验证 PDF 元数据",
            )
        )
        return findings

    standard = run((pdfinfo, str(path)))
    if standard.returncode != 0:
        findings.append(
            Finding(
                location,
                None,
                "invalid-pdf",
                "pdfinfo 无法解析该 PDF",
            )
        )
        return findings

    standard_text = standard.stdout.decode("utf-8", "replace")
    findings.extend(scan_text(location + ":metadata", standard_text))
    for line in standard_text.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        normalized_key = key.strip().casefold()
        if normalized_key == "author":
            author = value
            if not safe_pdf_author(author):
                findings.append(
                    Finding(
                        location,
                        None,
                        "pdf-author",
                        "PDF Author 元数据不像通用示例身份",
                    )
                )
        if (
            normalized_key in {"creationdate", "moddate"}
            and value.strip()
            and not re.search(r"\b(?:1970|2000)\b", value)
        ):
            findings.append(
                Finding(
                    location,
                    None,
                    "pdf-timestamp",
                    "PDF 含非固定的创建或修改时间元数据",
                )
            )

    xmp = run((pdfinfo, "-meta", str(path)))
    if xmp.returncode == 0 and xmp.stdout.strip():
        findings.extend(
            scan_text(
                location + ":xmp",
                xmp.stdout.decode("utf-8", "replace"),
            )
        )
    return findings


def scan_file(
    path: Path,
    location: str,
    tracked: bool,
    allowed_binary_extensions: Set[str],
    max_bytes: int = MAX_FILE_BYTES,
) -> List[Finding]:
    if path.is_symlink():
        return [
            Finding(
                location,
                None,
                "symlink",
                "仓库包含符号链接；请确认目标不会泄露本机或仓库外文件",
            )
        ]

    try:
        size = path.stat().st_size
    except OSError:
        return [
            Finding(location, None, "unreadable-file", "文件无法读取或已消失")
        ]
    if size > max_bytes:
        return [
            Finding(
                location,
                None,
                "oversized-file",
                "文件超过扫描上限，未进行内容检查",
            )
        ]

    try:
        data = path.read_bytes()
    except OSError:
        return [Finding(location, None, "unreadable-file", "文件读取失败")]

    if path.suffix.casefold() == ".pdf" or data.startswith(b"%PDF-"):
        return scan_pdf(path, location, tracked)

    if looks_binary(data):
        if path.suffix.casefold() in allowed_binary_extensions:
            return []
        return [
            Finding(
                location,
                None,
                "unexpected-binary",
                "发现未批准的二进制文件；请检查内容、许可证与元数据",
            )
        ]

    text = data.decode("utf-8-sig")
    return scan_text(location, text)


def public_commit_email(address: str) -> bool:
    return bool(address) and is_example_email(address)


def scan_history(root: Path, max_bytes: int = MAX_FILE_BYTES) -> List[Finding]:
    findings: List[Finding] = []
    commits_probe = run(("git", "rev-list", "HEAD"), cwd=root)
    if commits_probe.returncode != 0:
        return [
            Finding(
                "git-history",
                None,
                "history-unavailable",
                "无法枚举从 HEAD 可达的提交",
            )
        ]

    commits = commits_probe.stdout.decode("ascii", "replace").splitlines()
    for commit in commits:
        metadata = run(
            (
                "git",
                "show",
                "-s",
                "--format=%an%n%ae%n%cn%n%ce%n%B",
                commit,
            ),
            cwd=root,
        )
        lines = metadata.stdout.decode("utf-8", "replace").splitlines()
        if metadata.returncode != 0 or len(lines) < 4:
            findings.append(
                Finding(
                    "commit:{0}".format(commit[:12]),
                    None,
                    "commit-metadata-unavailable",
                    "无法读取提交元数据",
                )
            )
            continue

        author_name, author_email, committer_name, committer_email = lines[:4]
        label = "commit:{0}".format(commit[:12])
        if not public_commit_email(author_email):
            findings.append(
                Finding(
                    label,
                    None,
                    "commit-author-email",
                    "提交作者邮箱不是保留示例域或 GitHub 隐私邮箱",
                )
            )
        if not public_commit_email(committer_email):
            findings.append(
                Finding(
                    label,
                    None,
                    "commit-committer-email",
                    "提交者邮箱不是保留示例域或 GitHub 隐私邮箱",
                )
            )
        message = "\n".join(lines[4:])
        findings.extend(
            scan_text(
                label + ":metadata",
                "\n".join((author_name, committer_name, message)),
            )
        )

    objects_probe = run(("git", "rev-list", "--objects", "HEAD"), cwd=root)
    if objects_probe.returncode != 0:
        findings.append(
            Finding(
                "git-history",
                None,
                "history-objects-unavailable",
                "无法枚举历史对象",
            )
        )
        return findings

    seen_blobs: Set[str] = set()
    for line in objects_probe.stdout.decode("utf-8", "surrogateescape").splitlines():
        object_id = line.split(" ", 1)[0]
        object_type = run(("git", "cat-file", "-t", object_id), cwd=root)
        if object_type.stdout.strip() != b"blob" or object_id in seen_blobs:
            continue
        seen_blobs.add(object_id)

        size_probe = run(("git", "cat-file", "-s", object_id), cwd=root)
        try:
            size = int(size_probe.stdout.strip())
        except ValueError:
            continue
        label = "history-blob:{0}".format(object_id[:12])
        if size > max_bytes:
            findings.append(
                Finding(
                    label,
                    None,
                    "oversized-history-blob",
                    "历史 blob 超过扫描上限",
                )
            )
            continue

        blob = run(("git", "cat-file", "blob", object_id), cwd=root)
        data = blob.stdout
        if data.startswith(b"%PDF-") or looks_binary(data):
            findings.append(
                Finding(
                    label,
                    None,
                    "binary-history-blob",
                    "可达历史包含二进制 blob，需人工审计",
                )
            )
            continue
        findings.extend(scan_text(label, data.decode("utf-8-sig")))
    return findings


def unique_findings(findings: Iterable[Finding]) -> List[Finding]:
    return sorted(
        set(findings),
        key=lambda item: (
            item.location,
            item.line or 0,
            item.rule,
            item.message,
        ),
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan repository files and optional reachable Git history for "
            "common privacy leaks. Matched values are never printed."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to scan (default: current repository)",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Also scan commits and blobs reachable from HEAD",
    )
    parser.add_argument(
        "--allow-binary",
        action="append",
        default=[],
        metavar=".EXT",
        help="Allow a reviewed binary extension; repeat as needed",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=MAX_FILE_BYTES,
        help="Maximum bytes scanned per file or blob",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.max_bytes <= 0:
        print("privacy-check: --max-bytes must be positive", file=sys.stderr)
        return 2

    requested = [Path(value).expanduser() for value in args.paths]
    search_start = Path.cwd()
    root = find_git_root(search_start)
    allowed_binary_extensions = {
        value.casefold() if value.startswith(".") else "." + value.casefold()
        for value in args.allow_binary
    }

    try:
        files, tracked = collect_files(requested, root)
    except (FileNotFoundError, RuntimeError) as error:
        print(
            "privacy-check: unable to collect requested files ({0})".format(
                error.__class__.__name__
            ),
            file=sys.stderr,
        )
        return 2

    findings: List[Finding] = []
    for path in files:
        location = repo_path(path, root)
        findings.extend(scan_text(location + ":path", location))
        findings.extend(
            scan_file(
                path,
                location,
                path.resolve() in tracked,
                allowed_binary_extensions,
                args.max_bytes,
            )
        )

    if args.history:
        if root is None:
            findings.append(
                Finding(
                    "git-history",
                    None,
                    "not-a-git-repository",
                    "--history 需要在 Git 仓库内运行",
                )
            )
        else:
            findings.extend(scan_history(root, args.max_bytes))

    results = unique_findings(findings)
    if results:
        print(
            "Privacy check failed: {0} finding(s) in {1} file(s).".format(
                len(results),
                len(files),
            ),
            file=sys.stderr,
        )
        for finding in results:
            print("  " + finding.render(), file=sys.stderr)
        return 1

    suffix = " plus reachable Git history" if args.history else ""
    print(
        "Privacy check passed: {0} file(s){1}.".format(len(files), suffix)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
