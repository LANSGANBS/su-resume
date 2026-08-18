---
name: tailor-resume
description: Convert raw resume files, career notes, project evidence, or interview material into this repository's polished `content.tex` and a verified XeLaTeX PDF. Use when Codex must tailor or anonymize the Chinese technical resume template, establish an evidence-backed fact ledger, choose or test theme colors, keep private source material out of Git, enforce one-page or explicit multi-page output, render the PDF for visual QA, or audit a resume repository before publishing it.
---

# Tailor Resume

Build from evidence, keep raw material private, and treat the rendered PDF—not
the TeX source—as the final artifact.

## Set up the private workspace

1. Resolve the repository root and this skill directory as absolute paths.
2. Decide the output mode from the request:
   - Use **public mode** for a template or public repository. Write only
     anonymized, public-approved text to tracked files.
   - Use **private mode** for an application resume. Work in a private copy or
     worktree and never commit personal content to the public repository.
3. Create the isolated workspace outside the repository:

```bash
python3 "$SKILL_DIR/scripts/init_private_workspace.py" \
  --repo-root "$REPO_ROOT"
```

4. Read the returned JSON paths. Store raw files only under `sources_dir`,
   intermediate notes only under `working_dir`, and builds only under `qa_dir`.
   Never place original documents, screenshots, exports, or copied images in
   the repository.
5. If raw material already sits inside the repository, stop before staging it.
   Copy it to the private workspace, add a local ignore rule if needed, and
   remove the public-tree copy only with the user's authorization.

## Establish the fact ledger first

Read [content-rubric.md](references/content-rubric.md). Inventory every source
in `fact-ledger.json`, then record each candidate claim with its exact evidence
and public-safe wording.

- Mark a claim `usable` only when a cited source directly supports it.
- Mark incomplete or ambiguous claims `needs-confirmation`.
- Never invent or infer a company, school, team, title, date, metric, scale,
  ownership level, result, award, publication, or causal impact.
- Save user confirmations as a private source and cite them like any other
  evidence.
- Ask focused questions for missing facts. If the user cannot answer, retain a
  non-sensitive `TODO` tied to the fact ID or omit the claim; never guess.

Validate the ledger before drafting:

```bash
python3 "$SKILL_DIR/scripts/validate_fact_ledger.py" \
  "$PRIVATE_ROOT/fact-ledger.json" \
  --check-source-files \
  --require-usable-facts
```

## Draft `content.tex`

1. Read [latex-mapping.md](references/latex-mapping.md).
2. Rank usable facts by target-role relevance, evidence strength, impact, and
   recency. Prefer removing weak material over shrinking typography.
3. Preserve the sample document structure and replace its text with concise,
   source-backed wording. Keep one contribution per bullet and make ownership
   precise.
4. Use only the macros supported by the repository. Escape LaTeX-sensitive
   characters and keep colors out of `content.tex`.
5. In public mode, use only `public_text` from the ledger. Replace private
   contact details with reserved placeholders, remove private URLs and internal
   codenames, and generalize organizations only when the user requests it.
6. Keep unresolved items as non-sensitive TeX comments such as
   `% TODO(FACT-004): confirm end month`; report them to the user.
7. Select an existing theme in `resume.tex`. Add a custom theme only in
   `theme.tex`, using semantic color tokens and sufficient contrast.

## Build, paginate, and render

Build into the private QA directory. Enforce the requested page count; default
to one page when the user does not explicitly request multiple pages.

```bash
python3 "$SKILL_DIR/scripts/validate_resume.py" "$REPO_ROOT" \
  --theme ocean \
  --expected-pages 1 \
  --out-dir "$PRIVATE_ROOT/qa"
```

Use `--all-themes` after editing palette logic or when the user wants theme
choices. Treat compilation failures, unexpected pages, missing glyphs,
overfull boxes above the threshold, or missing rendered pages as defects.

Open every generated `page-*.png` with the available image-viewing tool.
Inspect hierarchy, alignment, clipping, density, contrast, whitespace, link
labels, and page boundaries. Iterate on `content.tex` or semantic theme tokens,
rebuild, and inspect again. Do not claim visual QA from a successful compiler
run alone.

## Run the publication gate

Populate `privacy-denylist.txt` in the private workspace with every real name,
private handle, internal project name, private hostname, and other term that
must not appear publicly. Run:

```bash
python3 "$SKILL_DIR/scripts/privacy_audit.py" "$REPO_ROOT" \
  --deny-file "$PRIVATE_ROOT/privacy-denylist.txt" \
  --fail-on medium \
  --json-out "$PRIVATE_ROOT/qa/privacy-report.json"
```

Review every URL finding. Repeat `--allow-domain` only for domains the user has
confirmed are intentionally public. Rerun until the audit passes. Then perform
the manual privacy checks in
[acceptance-checklist.md](references/acceptance-checklist.md); automated
patterns cannot reliably recognize names, confidential business context, or
misleading anonymization.

## Finish

Complete every applicable item in
[acceptance-checklist.md](references/acceptance-checklist.md). Report:

- the output mode, selected theme, and page count;
- the PDF and rendered-page paths;
- evidence or privacy items still marked `TODO`;
- the privacy-audit result and any explicitly allowed public domains;
- confirmation that raw sources and private QA artifacts remain outside Git.

Do not stage, commit, upload, or publish raw material, the fact ledger,
denylist, private build outputs, or any personalized `content.tex` from private
mode.
