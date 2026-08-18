#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
cd "${repo_root}"

for command_name in python3 xelatex pdfinfo pdftoppm; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "build-themes: required command not found: ${command_name}" >&2
    exit 2
  fi
done

theme_list="${THEMES:-ocean forest plum graphite}"
if (($# > 0)); then
  themes=("$@")
else
  read -r -a themes <<<"${theme_list}"
fi

if ((${#themes[@]} == 0)); then
  echo "build-themes: no themes requested" >&2
  exit 2
fi

export FORCE_SOURCE_DATE=1
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-946684800}"
export TZ=UTC

hash_index="${repo_root}/build/.theme-render-hashes.tsv"
mkdir -p "${repo_root}/build"
: >"${hash_index}"

for theme in "${themes[@]}"; do
  if [[ ! "${theme}" =~ ^[a-z][a-z0-9_-]*$ ]]; then
    echo "build-themes: invalid theme name" >&2
    exit 2
  fi

  output_dir="${repo_root}/build/${theme}"
  job_name="resume-${theme}"
  pdf_path="${output_dir}/${job_name}.pdf"
  mkdir -p "${output_dir}"

  echo "==> Building theme: ${theme}"
  for pass_number in 1 2; do
    command_log="${output_dir}/${job_name}.pass-${pass_number}.stdout.log"
    if ! xelatex \
      -no-shell-escape \
      -interaction=nonstopmode \
      -halt-on-error \
      -file-line-error \
      -output-directory="${output_dir}" \
      -jobname="${job_name}" \
      "\\def\\ResumeTheme{${theme}}\\input{resume.tex}" \
      >"${command_log}" 2>&1; then
      echo "build-themes: XeLaTeX failed for theme ${theme}" >&2
      tail -n 80 "${command_log}" >&2
      exit 1
    fi
  done

  if [[ ! -s "${pdf_path}" ]]; then
    echo "build-themes: expected PDF was not created" >&2
    exit 1
  fi

  pages="$(
    pdfinfo "${pdf_path}" |
      awk -F: '$1 == "Pages" {gsub(/[[:space:]]/, "", $2); print $2}'
  )"
  if [[ "${pages}" != "1" ]]; then
    echo "build-themes: theme ${theme} produced ${pages:-unknown} pages" >&2
    exit 1
  fi

  python3 "${script_dir}/privacy_check.py" "${pdf_path}"

  preview_prefix="${output_dir}/${job_name}.preview"
  preview_path="${preview_prefix}.png"
  pdftoppm \
    -f 1 \
    -singlefile \
    -png \
    -r 96 \
    "${pdf_path}" \
    "${preview_prefix}" \
    >/dev/null 2>&1
  preview_hash="$(
    python3 - "${preview_path}" <<'PY'
import hashlib
from pathlib import Path
import sys

print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
  )"
  if duplicate_theme="$(
    awk -F '\t' -v digest="${preview_hash}" \
      '$1 == digest { print $2; exit }' "${hash_index}"
  )" && [[ -n "${duplicate_theme}" ]]; then
    echo \
      "build-themes: ${theme} renders identically to ${duplicate_theme}; theme selection may be broken" \
      >&2
    exit 1
  fi
  printf '%s\t%s\n' "${preview_hash}" "${theme}" >>"${hash_index}"
done

echo "Built and verified ${#themes[@]} theme(s)."
