---
name: tailor-resume
description: Turn raw resume or CV files, career notes, project evidence, or interview material into an evidence-backed, privacy-safe, adaptively fitted LaTeX resume. Use when Codex must tailor, anonymize, restructure, theme, fit, or visually verify this repository's resume or GitHub-ready template; support arbitrary sections, optional fields, long text, and one, two, three, or more education records; target one or multiple pages; preserve a supplied visual reference and source wording; prevent layout regressions; or audit a resume repository before publishing it.
---

# Tailor Resume

Build from evidence, derive the document structure from the candidate's actual
material, and treat the rendered PDF rather than the TeX source as the final
artifact.

## Set up the private workspace

1. Resolve the repository root and this skill directory as absolute paths.
2. Choose the output mode:
   - Use **public mode** for a reusable template or public repository. Write
     only anonymized, public-approved text to tracked files.
   - Use **private mode** for an application resume. Work in a private copy or
     worktree and never commit personal content to the public repository.
3. Create an isolated workspace outside every Git worktree:

```bash
python3 "$SKILL_DIR/scripts/init_private_workspace.py" \
  --repo-root "$REPO_ROOT"
```

4. Store raw files only under the returned `sources_dir`, intermediate notes
   only under `working_dir`, and builds only under `qa_dir`. Never place
   original documents, screenshots, exports, or copied images in the public
   repository.
5. If raw material already sits inside the repository, stop before staging it.
   Copy it to the private workspace, add a local ignore rule if needed, and
   remove the public-tree copy only with the user's authorization.

## Fix the document contract before drafting

Record these decisions before writing layout-specific TeX:

- target role and evidence priorities;
- public or private mode;
- content authority: read-only adaptation or explicitly authorized editing;
- target page count;
- theme preference or themes to compare;
- the supplied visual reference, if any.

Honor an explicit page count. Otherwise choose one page only when the strongest
material remains substantive and readable; choose two or more pages when
removing the overflow would discard important evidence. Do not draft a long
resume and decide the page count afterward. Do not add filler merely to occupy
space.

Treat the user-supplied reference image or initial template as visual truth;
do not substitute a README preview or another current variant as the sole
master. Preserve the reference's high-density accent-rule hierarchy (blue in
the baseline), pale organization bands, and multilevel bullet treatment. Do
not silently switch templates, alter the information hierarchy, or invent a
new style. Compose different content with existing components and adjust only
the requested semantic theme color or bounded density. Perform a visual
redesign only when the user explicitly authorizes it.

Treat an existing resume's facts, sentences, metrics, and ordering as read-only
by default. A request to format, fit, theme, or anonymize does not authorize
rewriting. Enter content-edit mode only when the user explicitly asks to
rewrite, shorten, remove, or reorder material; record that scope before making
the change. Never alter the underlying facts or metrics in either mode.

Read [adaptive-layout.md](references/adaptive-layout.md) for the content-file,
density, fitting, regression, and hard-gate contract.

## Establish the fact ledger

Read [content-rubric.md](references/content-rubric.md). Inventory every source
in `fact-ledger.json`, then record each candidate claim with exact evidence and
public-safe wording.

- Treat `category` as an open, user-derived label. Never restrict it to
  education, experience, project, competition, publication, or any other
  predefined list.
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

## Derive a content plan instead of filling a schema

Group usable facts into the sections that best communicate this candidate.
Allow any number and kind of sections, entries, cards, metadata rows, and
bullets. A section may represent education, work, research, competition,
writing, open source, caregiving, community service, culinary work, or a
candidate-specific achievement; its label does not change the underlying
composition workflow.

When adapting an existing resume in read-only mode, preserve its section order,
entry order, sentences, metrics, and fact selection. Map them to compatible
components without editorial changes. Derive a new order only for unordered raw
material or after explicit user authorization.

For every planned entry, record:

- the fact IDs it renders;
- its primary text, optional metadata, and optional supporting details;
- its original position and whether the user authorized editorial changes;
- whether it needs a full-width flow, a compact card, or a grid slot.

Do not create empty fields to imitate the sample. One, two, three, or more
education records are ordinary repeated entries, not separate schemas.

## Compose the content fragment

1. Read [latex-mapping.md](references/latex-mapping.md).
2. Inspect the current `resume.tex` and `resume-components.tex` definitions
   before using a component. Treat their implemented signatures as the source
   of truth.
3. Prefer domain-neutral section, grid, card, entry-band, metadata-row, list,
   contact, and header primitives. Use education-, award-, or experience-named
   macros only as compatibility wrappers when the content truly matches.
4. Choose one, two, or three columns from measured content length and
   homogeneity, not from the section label. Let long or irregular entries flow
   full width.
5. Keep `content.tex` or an example content file as an included fragment. Use
   the `\ResumeContentFile` entry point rather than replacing the main document.
6. Use only source-backed `public_text` in public mode. Replace private contact
   details with reserved-domain addresses and visibly non-dialable phone
   placeholders such as `1XX XXXX XXXX`; remove private URLs and internal
   codenames. Never publish a fully numeric "example" phone number.
7. Keep palette values out of content. Select an existing theme or add semantic
   theme tokens in the template layer.
8. Preserve the established typography, spacing rhythm, card treatment, and
   hierarchy unless the user explicitly requested a visual redesign.

## Fit the selected page target

Use the repository fitter after the content structure is credible:

```bash
python3 "$REPO_ROOT/scripts/fit_resume.py" \
  --content "$CONTENT_FILE" \
  --theme "$THEME" \
  --target-pages "$TARGET_PAGES" \
  --output-dir "$PRIVATE_ROOT/qa/fit" \
  --manifest "$PRIVATE_ROOT/qa/fit-manifest.json" \
  --keep-renders
```

Let the fitter start from the reference-faithful `balanced` profile. Select it
immediately when it passes. Try `airy` only when the balanced render is
underfilled or has excessive bottom whitespace. Try `compact` and then `dense`
when balanced exceeds the target pages or overflows. Do not select `airy`
merely because it is more spacious, and never begin with `dense`. Let the
reason-directed natural profile search finish first. Only when every natural
profile is ineligible and an exact multi-page `balanced` render fails solely
on whitespace or page-balance gates may the fitter try bounded `elastic`.
Never set elastic manually or accept it with an underfull box. When the
natural search and any eligible elastic recovery find no passing profile:

1. map the same content to more suitable compatible components;
2. change grid columns, bounded density, or natural page breaks;
3. if the page target still fails, report the smallest content edits or reorder
   operations that would help, but do not apply them without authorization;
4. ask to increase the target page count when preservation is more important;
5. only in explicitly authorized content-edit mode, remove weak or duplicated
   material, shorten supporting clauses, or reorder sections within the agreed
   scope;
6. rerun the bounded density profiles.

Never bypass failure by inventing a smaller font, negative spacing, page
scaling, or an unbounded density profile.

Validate the fitter's machine-readable result:

```bash
python3 "$SKILL_DIR/scripts/validate_fit_manifest.py" \
  "$PRIVATE_ROOT/qa/fit-manifest.json" \
  --repo-root "$REPO_ROOT" \
  --expected-pages "$TARGET_PAGES"
```

Require the validator to recompute source hashes, confirm content preservation,
validate the selected page-fill mode and complete natural/elastic attempt chain,
and prove that the final PDF is byte-identical to the selected candidate. Do not
hand-edit the manifest or move/delete its artifacts before validation.

If `fit_resume.py` is absent, compile the exact public or external private
fragment at the template's default density:

```bash
python3 "$SKILL_DIR/scripts/validate_resume.py" "$REPO_ROOT" \
  --content "$CONTENT_FILE" \
  --theme "$THEME" \
  --expected-pages "$TARGET_PAGES" \
  --out-dir "$PRIVATE_ROOT/qa/validation"
```

The validator records content provenance and renderer attempts. It rejects
Poppler font/CMap failures and falls back to Ghostscript or another independent
renderer. Report that automatic profile selection was unavailable; a compiler
or fallback-render pass is not a density-search or fit pass.

For read-only adaptation of an existing resume, compare the source baseline
PDF with the selected candidate after fitting:

```bash
python3 "$SKILL_DIR/scripts/validate_text_parity.py" \
  "$BASELINE_PDF" \
  "$SELECTED_PDF" \
  --json-out "$PRIVATE_ROOT/qa/text-parity.json"
```

Require exact equality of the normalized visible-text sequence. This catches
deleted, added, rewritten, or reordered wording and metrics even when line
wraps and page breaks changed. The parity tool fails closed when `pdftotext`
reports broken font/CMap extraction or returns no visible text; never treat that
as parity. A source-file hash alone is insufficient because the adapted TeX is
expected to differ in layout code. If reliable extraction or a baseline PDF is
unavailable, record and compare an explicit ordered fact/text ledger; do not
claim deterministic zero-change parity from visual inspection alone.

## Enforce layout and content gates

Reject the resume until all applicable checks in
[acceptance-checklist.md](references/acceptance-checklist.md) pass. In
particular, fail on:

- a page count different from the chosen target;
- compilation errors, missing glyphs, overfull content, clipped text, blank
  pages, or duplicate rendered pages;
- bottom whitespace or page fill outside the fitter thresholds;
- a multi-page fill-ratio or bottom-whitespace spread outside its threshold,
  including a full first page followed by a sparse later page;
- a section heading stranded without its first entry or a bullet separated from
  the entry it explains;
- long names, dates, links, labels, or identifiers that do not wrap safely;
- repeated topics that spend page area restating the same evidence;
- an unauthorized deletion, rewrite, metric change, or order change;
- an unrequested departure from the reference image or established visual
  system.

Open every rendered page image at readable scale. Check hierarchy, alignment,
column balance, clipping, density, contrast, links, and page boundaries.
Inspect `examples/layout-cases.json` and run the repository's layout regression
workflow after changing shared components or layout behavior.

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
confirmed are intentionally public. Automated patterns cannot reliably detect
names, confidential business context, or misleading anonymization, so complete
the manual privacy checklist too.

The Skill audit above checks the current public tree and private denylist; it
does not replace repository-history and commit-identity checks. Before pushing
or declaring a GitHub repository publishable, also run:

```bash
make privacy-history
git log --format='%h %an <%ae> %s'
```

Require every reachable author and committer identity to be intentionally
public, and rerun the history gate after any history rewrite. Do not publish
when current files pass but a deleted secret, private artifact, or unapproved
identity remains reachable in Git history.

## Finish

Report:

- output mode, target page count, selected density, and theme;
- content-file, PDF, rendered-page, and fit-manifest paths;
- layout regression and visual-QA results;
- unresolved fact IDs and approved public domains;
- privacy-audit result;
- confirmation that the reference visual system was preserved unless a
  redesign was explicitly authorized;
- confirmation that original wording, metrics, facts, and order were preserved,
  including the visible-text parity result for read-only adaptation, or a
  summary of explicitly authorized content edits;
- confirmation that raw sources and private QA artifacts remain outside Git.

Do not stage, commit, upload, or publish raw material, the fact ledger,
denylist, private build outputs, or personalized content from private mode.
