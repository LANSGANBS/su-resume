# Adaptive layout and fitting

## Contents

1. [Preserve the visual contract](#preserve-the-visual-contract)
2. [Choose the page target first](#choose-the-page-target-first)
3. [Use the stable entry points](#use-the-stable-entry-points)
4. [Fit from the reference profile](#fit-from-the-reference-profile)
5. [Read and validate the manifest](#read-and-validate-the-manifest)
6. [Recover from a failed fit](#recover-from-a-failed-fit)
7. [Enforce hard gates](#enforce-hard-gates)
8. [Run layout regression](#run-layout-regression)
9. [Run a fresh-agent forward test](#run-a-fresh-agent-forward-test)

## Preserve the visual contract

Treat the user-supplied reference image or initial template as visual truth.
Do not replace it with a README preview or a newer card-heavy variant merely
because that variant is convenient to implement. Preserve the reference's
typography, spacing rhythm, hierarchy, alignment, and overall identity,
including the high-density accent-rule section treatment, pale organization
bands, and multilevel bullets. Blue is the baseline accent; use another
semantic accent only when the user requests a theme. Adapt content by composing
compatible components, changing bounded density, or selecting that approved
theme color.

Do not choose another template merely because a candidate has different
sections or more content. Do not redesign the resume, introduce a new visual
style, or change the hierarchy without explicit user authorization. When no
reference image exists, use the repository's rendered default as the reference.

Treat an existing resume's facts, sentences, metrics, section order, and entry
order as a content contract too. Formatting or fitting permission does not
authorize editorial changes. Record explicit user authorization before
shortening, deleting, rewriting, or reordering any original content.

## Choose the page target first

Set `TARGET_PAGES` before drafting layout-specific TeX.

- Honor a user-specified page count.
- Choose one page when the strongest evidence fits without deleting essential
  context or using the tightest density.
- Choose two or more pages when the candidate has enough relevant,
  non-repetitive evidence to justify them.
- Do not force an academic, senior, or publication-heavy resume into one page
  merely because the sample is one page.
- Do not expand thin evidence with filler to reach a target.

Record the decision and its rationale in private working notes. Treat a changed
page target as a deliberate content decision, not an invisible workaround.

## Use the stable entry points

Expect the main document to expose:

- `\ResumeContentFile`: the included content fragment;
- `\ResumeDensity`: the bounded density profile;
- `\ResumeTheme`: the semantic theme.

Inspect the implementation before use:

```bash
rg -n 'Resume(ContentFile|Density|Theme)' \
  "$REPO_ROOT/resume.tex" \
  "$REPO_ROOT/resume-components.tex"

python3 "$REPO_ROOT/scripts/fit_resume.py" --help
```

Do not rewrite `resume.tex` for each candidate. Keep candidate content in a
fragment and let the command-line definitions select it. A direct compile uses
the same conceptual entry points:

```tex
\def\ResumeContentFile{examples/content-undergrad.tex}
\def\ResumeDensity{balanced}
\def\ResumeTheme{ocean}
\input{resume.tex}
```

Treat the current implementation as the source of truth for path quoting and
supported profile names. Never interpolate untrusted TeX or shell text into a
command string.

## Fit from the reference profile

Run the fitter only after the content plan is structurally sound:

```bash
python3 "$REPO_ROOT/scripts/fit_resume.py" \
  --content "$CONTENT_FILE" \
  --theme "$THEME" \
  --target-pages "$TARGET_PAGES" \
  --output-dir "$PRIVATE_ROOT/qa/fit" \
  --manifest "$PRIVATE_ROOT/qa/fit-manifest.json" \
  --keep-renders
```

Use `balanced` as the visual reference profile:

1. Select `balanced` immediately when it passes.
2. If balanced produces too few pages or a render is underfilled, try
   `airy`.
3. If balanced produces too many pages or overfull content, try `compact` and
   then `dense`.
4. If balanced fails another quality gate, follow the fitter's
   reference-quality branch.
5. Only if every natural profile is ineligible, natural balanced already meets
   a multi-page target, and it fails only whitespace, fill, or page-balance
   gates, let the fitter try bounded `balanced + elastic`.

The fitter may compile all requested profiles for diagnostics, but selection
must follow `balanced-reference-v1`. Do not select `airy` merely because it is
more spacious; that can drift from the reference. Do not add an ad hoc profile
below the established density floor, and keep the dense body-text floor at or
above the template's supported minimum. Treat `elastic` as a tool-controlled
page-fill mode, not another density: it may only use finite vertical stretch,
must preserve the target page count, and must produce zero underfull boxes.

Use explicit thresholds only when the repository defaults are inappropriate
for a verified reason:

```bash
python3 "$REPO_ROOT/scripts/fit_resume.py" \
  --content "$CONTENT_FILE" \
  --theme "$THEME" \
  --target-pages "$TARGET_PAGES" \
  --output-dir "$PRIVATE_ROOT/qa/fit" \
  --manifest "$PRIVATE_ROOT/qa/fit-manifest.json" \
  --profiles balanced airy compact dense \
  --dpi 120 \
  --white-threshold 250 \
  --max-bottom-whitespace-mm 22 \
  --min-page-fill-ratio 0.62 \
  --max-page-fill-spread 0.22 \
  --max-bottom-whitespace-spread-mm 25 \
  --max-underfull 20 \
  --keep-renders
```

Changing a threshold requires visual inspection and a recorded rationale. Do
not loosen thresholds only to turn a failed candidate green.

## Read and validate the manifest

Expect the fit manifest to contain:

- `schema_version`, `success`, `inputs`, and `thresholds`;
- `content_preserved` plus SHA-256 values for the content, entrypoint, layout,
  component, and theme sources;
- `selection_policy`, `selection_reason`, and `selection_order`;
- `attempted_profiles`, `attempted_page_fill_modes`, and `page_fill_attempts`;
- `selected_profile`, `selected_page_fill_mode`, `selection_detail`, and
  `selected_pdf`;
- selected-candidate compile/render return codes, rasterizer, raster error,
  and candidate PDF path;
- `candidates`, including profile eligibility and rejection reasons;
- compiler/log counts;
- rendered page metrics;
- blank-page and duplicate-page signals.

Each candidate may include:

- `profile`, `eligible`, `rejection_reasons`, `returncode`, `pdf`, and `pages`;
- `log_counts` with overfull, underfull, missing-glyph, and error counts;
- `page_metrics` with blank status, content bounds, non-white pixels, fill
  ratios, and bottom whitespace;
- `page_balance` with `page_fill_spread` and
  `bottom_whitespace_spread_mm` for multi-page balance;
- `duplicate_page_pairs`.

Run the deterministic release gate:

```bash
python3 "$SKILL_DIR/scripts/validate_fit_manifest.py" \
  "$PRIVATE_ROOT/qa/fit-manifest.json" \
  --repo-root "$REPO_ROOT" \
  --expected-pages "$TARGET_PAGES"
```

Require `selection_policy` to be `balanced-reference-v1`. The reason-directed
orders are:

| Balanced result | `selection_reason` | `selection_order` |
| --- | --- | --- |
| passes | `balanced_reference_passed` | `balanced` |
| too many pages or overfull | `reference_over_target_or_overflow` | `balanced`, `compact`, `dense`, `airy` |
| too few pages or underfilled | `reference_under_target_or_underfilled` | `balanced`, `airy`, `compact`, `dense` |
| another quality failure | `reference_quality_failure` | `balanced`, `compact`, `airy`, `dense` |

When bounded elastic recovery is selected, retain the natural Balanced
underfill reason and full natural search order above. Record
`selection_detail=balanced_elastic_underfill_recovery`; never relabel the
elastic candidate as `balanced_reference_passed`.

The validator derives the expected reason from the natural balanced candidate and
confirms that the selected profile is the first eligible natural profile in
that reason-directed order. For elastic recovery it also proves that every
natural profile was ineligible, natural balanced already met the multi-page
target, failed only whitespace/fill/balance gates, and was followed by an
eligible zero-underfull elastic attempt. A
successful compile or a self-reported `success` field alone is insufficient.
The validator also opens the selected candidate and final PDFs, requires PDF
signatures, and compares their SHA-256 digests. Keep those artifacts in place
until the gate finishes.

## Recover from a failed fit

Apply read-only layout corrections first:

1. Move the unchanged text into a compatible generic component.
2. Replace a cramped grid with fewer columns or a full-width flow.
3. For an imbalanced multi-page render, finish the reason-directed natural
   density branch first. Use the fitter's bounded elastic attempt only if no
   natural profile passes, then improve natural page-break behavior before
   changing any source content.
4. Adjust bounded density without leaving the reason-directed fit policy.
5. Preserve every original sentence, fact, metric, section, and ordering.
6. Rerun the bounded profile search.

If the fit still fails, produce a proposed change list instead of editing:

- identify weak or repeated material that could be removed;
- show secondary clauses that could be shortened;
- show a section or entry reorder that would improve a page break;
- show the page target that would preserve everything.

Ask the user to authorize a specific option. Only after explicit authorization
may content-edit mode apply the agreed deletion, rewrite, or reorder. Preserve
ownership, scope, units, baselines, uncertainty, and every metric exactly.

Do not:

- reduce body text below the template's established density floor;
- use arbitrary negative `\vspace`, `\hspace`, or page scaling;
- hide content outside the page;
- force a manual page break that leaves a large avoidable gap;
- convert text to an image;
- silently delete, rewrite, or reorder original content;
- change a metric or fact even in content-edit mode;
- delete qualifiers that make a claim accurate.

## Enforce hard gates

Reject the output when any gate fails.

### Page and compiler gates

- Produce exactly `TARGET_PAGES`.
- Produce no compilation error, missing glyph, or overfull box above the
  repository threshold.
- Require zero underfull boxes when elastic page fill is selected.
- Produce no clipped, overlapping, or off-page content.
- Produce no blank or duplicate rendered page.

### Whitespace and fill gates

- Keep every page at or above the configured `min_page_fill_ratio`.
- Keep bottom whitespace at or below `max_bottom_whitespace_mm`.
- Keep the difference between the fullest and sparsest page at or below
  `max_page_fill_spread`.
- Keep the difference between the largest and smallest bottom whitespace at or
  below `max_bottom_whitespace_spread_mm`.
- Reject the common failure where page one is full and a later page is sparse,
  even when each page independently clears its minimum fill.
- Treat a large last-page gap as a failure too; restructure the page or
  reconsider the page target.
- Do not satisfy fill metrics by adding decorative filler or stretching
  spacing.

### Orphan and grouping gates

- Keep a section heading with its first entry.
- Keep an entry heading with at least its first meaningful line or bullet.
- Do not strand a bullet marker, date, role chip, or metadata row on another
  page.
- Do not wrap an entire long section in an unbreakable box to avoid an orphan;
  use breakable components and local keep-with-next behavior.
- When a section is immediately followed by a tall organization band and
  page-image review finds the heading stranded, place
  `\ResumeNeedSectionBand` before that section. It reserves only the combined
  heading/band opening; the remaining entry stays breakable.

### Long-field gates

- Test long names, organizations, degrees, dates, URLs, project titles,
  publication titles, labels, and tags.
- Allow semantic text to wrap through flexible-width columns or natural
  paragraphs.
- Do not put unbounded user text in a fixed `\hbox`.
- Break or relabel display URLs while preserving the actual link target.
- Fail on overlap, clipping, illegible compression, or an overfull warning.

### Repetition gates

- Map every rendered claim to fact IDs.
- Compare neighboring and cross-section bullets for the same action, method, or
  outcome.
- In read-only mode, report repeated topics without deleting or merging them.
- In explicitly authorized content-edit mode, remove a repeated topic unless
  each occurrence communicates a distinct scope that is explicit in the
  wording.
- Do not repeat a technology list in a tag row and a bullet without adding new
  evidence.

### Content-integrity gate

- Compare the source resume and rendered content in order.
- Preserve every fact, sentence, metric, section, and entry position in
  read-only mode.
- Require a recorded, explicit scope for every deletion, rewrite, or reorder.
- Never change source facts or metrics.
- Fail when layout fitting caused an unapproved editorial change.

### Visual-reference gate

- Compare the final render with the initial reference at the same scale.
- Preserve the recognizable typography, section rhythm, alignment, component
  treatment, and visual hierarchy.
- Treat an unrequested template or style change as a failure even if all
  numeric fit metrics pass.

## Run layout regression

Use `examples/layout-cases.json` as the scenario inventory. Expect it to cover
at least:

- a single-degree or undergraduate case;
- a research/publication-heavy case;
- an unconventional-section case;
- a long-content stress case.

Inspect the current manifest and regression runner rather than guessing their
schema:

```bash
rg -n 'layout-cases|fit_resume|layout regression' \
  "$REPO_ROOT/Makefile" \
  "$REPO_ROOT/scripts" \
  "$REPO_ROOT/examples" \
  "$REPO_ROOT/README.md"
```

Run all themes against the default content after changing palette or shared
layout logic. Run scenario fixtures with the themes declared by the current
regression contract; the baseline convention uses `ocean` for fixture cases.
Treat a missing fixture, stale path, changed page count, failed fit, or failed
hard gate as a regression.

## Run a fresh-agent forward test

After integrating the template, fitter, examples, and this skill, start a fresh
agent with no implementation context. Give it only:

- this skill;
- anonymized source material;
- a target role;
- a page target or enough information to choose one;
- the repository.

Exercise at least these cases:

1. one education entry plus arbitrary project sections;
2. three or more education entries;
3. publication- or competition-heavy content;
4. an unconventional achievement section;
5. long names, URLs, titles, and mixed-length cards;
6. content that cannot honestly fit the initial page target.

Require the fresh agent to:

- keep fact categories open;
- derive sections rather than fill a fixed schema;
- preserve the reference visual system;
- preserve original wording, metrics, facts, and order unless the prompt
  explicitly authorizes named edits;
- choose the target page count before drafting;
- use generic components after inspecting their signatures;
- run the fitter and manifest validator;
- adapt structure before increasing density, and request authorization before
  changing content;
- reject every hard-gate failure;
- report artifacts and unresolved facts.

Do not accept a forward test that succeeds only because it already knew the
template's implementation details.
