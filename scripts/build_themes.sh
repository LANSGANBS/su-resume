#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
cd "${repo_root}"

for command_name in python3 xelatex pdfinfo; do
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
done

echo "Built and verified ${#themes[@]} theme(s)."
