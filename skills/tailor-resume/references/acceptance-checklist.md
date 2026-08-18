# Acceptance checklist

## Evidence

- [ ] Validate `fact-ledger.json` with source-file checks enabled.
- [ ] Trace every company, school, role, date, metric, result, and award in
      `content.tex` to a `usable` fact.
- [ ] Preserve scope, attribution, units, baselines, and uncertainty.
- [ ] Report every unresolved fact ID; keep it as a non-sensitive `TODO` or
      omit it.
- [ ] Remove claims that are merely inferred from technology names or context.

## Content

- [ ] Match the target role with the strongest relevant, recent evidence.
- [ ] Keep one main contribution per bullet with precise ownership.
- [ ] Remove filler, repetition, unsupported superlatives, and keyword stuffing.
- [ ] Check spelling, terminology, tense, punctuation, date format, and link
      labels.
- [ ] Escape every TeX-special character in visible text.

## Privacy and public release

- [ ] Keep raw documents, extracts, the fact ledger, denylist, private
      screenshots, and QA output outside the repository.
- [ ] Inspect `git status --short --untracked-files=all` before staging.
- [ ] Confirm no raw material or private-mode output is tracked by
      `git ls-files`.
- [ ] Run `privacy_audit.py` with the private denylist and `--fail-on medium`.
- [ ] Explicitly approve every allowed public domain; remove private,
      authenticated, expiring, or access-controlled links.
- [ ] Manually check names, contact details, handles, organizations, internal
      project names, hostnames, file paths, business data, source comments, and
      PDF metadata.
- [ ] Confirm anonymization does not combine facts into a misleading fictional
      identity.

## Build and pagination

- [ ] Run `git diff --check`.
- [ ] Compile with XeLaTeX for the selected theme.
- [ ] Compile every theme after changing theme or shared layout logic.
- [ ] Confirm differently named themes produce different rendered first pages.
- [ ] Match the requested page count.
- [ ] Resolve compilation errors, missing glyphs, and overfull boxes above the
      configured threshold.
- [ ] Render every PDF page to PNG and confirm the rendered-page count matches
      the PDF page count.

## Visual QA

- [ ] Open every rendered page image at readable scale.
- [ ] Check top, bottom, left, and right edges for clipping or accidental
      overflow.
- [ ] Check section rhythm, alignment, indentation, line wrapping, and column
      balance.
- [ ] Check font consistency, Chinese/Latin weight, punctuation, and glyph
      rendering.
- [ ] Check chip and link contrast in the chosen palette.
- [ ] Check that dense sections remain scannable and that no heading or bullet
      is stranded across pages.
- [ ] Rebuild and reinspect after the final edit.

## Handoff

- [ ] Report output mode, theme, page count, PDF path, and rendered image paths.
- [ ] Report unresolved fact IDs and approved public domains.
- [ ] Report the privacy-audit result.
- [ ] Confirm that private artifacts remain outside Git.
