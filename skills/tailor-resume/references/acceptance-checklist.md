# Acceptance checklist

## Contents

1. [Authority and source integrity](#authority-and-source-integrity)
2. [Evidence](#evidence)
3. [Adaptive content model](#adaptive-content-model)
4. [Visual-reference fidelity](#visual-reference-fidelity)
5. [Content quality](#content-quality)
6. [Privacy and public release](#privacy-and-public-release)
7. [Fit and pagination](#fit-and-pagination)
8. [Breaks and long fields](#breaks-and-long-fields)
9. [Visual QA and regression](#visual-qa-and-regression)
10. [Handoff](#handoff)

## Authority and source integrity

- [ ] Record public/private mode, target pages, theme, visual reference, and
      content authority before editing.
- [ ] Treat formatting, fitting, theming, and anonymization as read-only content
      operations unless the user explicitly authorizes editing.
- [ ] Preserve the original facts, sentences, metrics, sections, entries, and
      order in read-only adaptation mode.
- [ ] When a baseline PDF exists, run `validate_text_parity.py` against the
      selected candidate and require exact normalized visible-text equality.
- [ ] When no baseline PDF exists, compare an explicit ordered fact/text ledger
      and do not claim deterministic zero-change parity from visual review.
- [ ] Record the explicit scope of every authorized deletion, rewrite, or
      reorder and report the final diff.
- [ ] Never change a source fact, metric, unit, baseline, attribution, or
      uncertainty.

## Evidence

- [ ] Validate `fact-ledger.json` with source-file checks enabled.
- [ ] Accept every non-empty, user-derived `category`; do not apply a hidden
      category enum.
- [ ] Trace every rendered company, school, role, date, metric, result, award,
      publication, and unconventional achievement to a `usable` fact.
- [ ] Preserve scope, attribution, units, baselines, and uncertainty.
- [ ] Report every unresolved fact ID; keep it as a non-sensitive `TODO` or
      omit it only when the user authorized content selection.
- [ ] Remove no claim merely because it lacks a predefined template field.

## Adaptive content model

- [ ] Derive sections and entries from evidence rather than filling a fixed
      education/experience/project schema.
- [ ] Support any number of sections, entries, contacts, cards, metadata rows,
      and bullets.
- [ ] Render one, two, three, and more education entries without empty
      placeholders or a schema change.
- [ ] Use domain-neutral components for unfamiliar section types.
- [ ] Choose one, two, or three columns from content length and homogeneity.
- [ ] Use full-width flow for long, irregular, or bullet-heavy entries.
- [ ] Confirm optional fields disappear without empty separators, chips, or
      columns.

## Visual-reference fidelity

- [ ] Treat the user reference or initial template as visual truth, not a README
      preview or a convenient alternative variant.
- [ ] Preserve the high-density accent-rule hierarchy, pale organization bands,
      multilevel bullets, typography, spacing rhythm, and alignment.
- [ ] Keep blue as the baseline accent unless the user requests another
      semantic theme.
- [ ] Do not switch templates or redesign the hierarchy without explicit user
      authorization.
- [ ] Compare the final render with the reference at the same scale.

## Content quality

- [ ] Keep one main contribution per bullet when content editing is authorized.
- [ ] In read-only mode, report repetition or weak material without deleting or
      merging it.
- [ ] In authorized edit mode, remove filler and repetition only within the
      agreed scope.
- [ ] Check spelling, terminology, tense, punctuation, date format, and link
      labels without silently rewriting source wording.
- [ ] Escape every TeX-special character in visible text.

## Privacy and public release

- [ ] Keep raw documents, extracts, fact ledgers, denylists, private
      screenshots, personalized content, and QA output outside the public
      repository.
- [ ] Use only fictional or reserved-domain data in public templates and
      examples; use visibly non-dialable phone placeholders, never a fully
      numeric example number.
- [ ] Inspect `git status --short --untracked-files=all` before staging.
- [ ] Confirm no raw material or private-mode output is tracked by
      `git ls-files`.
- [ ] Run `privacy_audit.py` with the private denylist and `--fail-on medium`.
- [ ] Run the repository history gate (`make privacy-history` or the equivalent
      `privacy_check.py --history`) before publication.
- [ ] Inspect reachable author and committer names/emails after any history
      rewrite and confirm they are intentionally public.
- [ ] Explicitly approve every allowed public domain; remove private,
      authenticated, expiring, or access-controlled links.
- [ ] Manually check names, contact details, handles, organizations, internal
      project names, hostnames, file paths, business data, source comments, and
      PDF metadata.
- [ ] Confirm anonymization does not combine facts into a misleading fictional
      identity.

## Fit and pagination

- [ ] Choose and record the target page count before drafting layout-specific
      TeX.
- [ ] Run `fit_resume.py` with the `balanced-reference-v1` policy.
- [ ] Select `balanced` when it passes; use `airy` only for an underfilled
      reference and `compact`/`dense` for an over-target or overflowing
      reference.
- [ ] Confirm the selected density is the first eligible profile in the
      reason-directed order, not merely a profile that compiles.
- [ ] Run `validate_fit_manifest.py --expected-pages`.
- [ ] Confirm the manifest records unchanged content plus content, entrypoint,
      layout, component, and theme SHA-256 provenance.
- [ ] Confirm the selected candidate and final PDF still exist and are
      byte-identical when the manifest validator runs.
- [ ] If elastic was attempted, confirm natural balanced already met the target
      page count, failed only whitespace/fill/balance gates, and every natural
      profile was ineligible.
- [ ] Reject selected elastic output with any underfull box.
- [ ] Match the exact target page count.
- [ ] Resolve compilation errors, missing glyphs, overfull content, blank
      pages, and duplicate pages.
- [ ] Keep every page above the configured fill ratio and below the configured
      bottom-whitespace threshold.
- [ ] Keep the multi-page fill-ratio spread and bottom-whitespace spread below
      their configured thresholds; reject a full first page followed by a
      sparse later page.
- [ ] Preserve content with compatible components, columns, bounded density,
      and page breaks before proposing editorial changes.
- [ ] Do not use arbitrary font shrinking, page scaling, negative spacing,
      hidden content, or silent deletion.

## Breaks and long fields

- [ ] Keep every section heading with its first entry.
- [ ] Keep every entry heading with its first meaningful line or bullet.
- [ ] Do not strand a bullet marker, date, role chip, or metadata row.
- [ ] Test long names, organizations, degrees, dates, links, labels, project
      titles, publication titles, and identifiers.
- [ ] Keep unbounded text in flexible-width or naturally wrapping structures.
- [ ] Confirm no long field clips, overlaps, becomes illegible, or creates an
      overfull warning.

## Visual QA and regression

- [ ] Render every PDF page to PNG and confirm the image count matches the PDF
      page count.
- [ ] Open every rendered page at readable scale.
- [ ] Check all page edges for clipping or accidental overflow.
- [ ] Check section rhythm, alignment, indentation, line wrapping, column
      balance, contrast, and link labels.
- [ ] Check Chinese/Latin glyph consistency and font weight.
- [ ] Inspect every repeated topic and distinguish its scope or report it for
      user-authorized removal.
- [ ] Run `examples/layout-cases.json` through the current layout regression
      workflow after changing shared components or layout behavior.
- [ ] Cover single-degree, three-plus-degree, academic, unconventional-section,
      and long-content cases.
- [ ] Rebuild and reinspect after the final edit.

## Handoff

- [ ] Report output mode, target pages, selected density, theme, content file,
      PDF path, rendered images, and fit manifest.
- [ ] Report unresolved fact IDs, approved public domains, and privacy result.
- [ ] Report regression and visual-QA results.
- [ ] Confirm visual-reference fidelity or identify an explicitly authorized
      redesign.
- [ ] Confirm source content and order were preserved or list every authorized
      content edit.
- [ ] Report the visible-text parity hash/result for read-only adaptation.
- [ ] Confirm private artifacts remain outside Git.
