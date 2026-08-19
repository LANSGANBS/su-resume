# Compositional LaTeX mapping

## Contents

1. [Keep the layers separate](#keep-the-layers-separate)
2. [Inspect capabilities before composing](#inspect-capabilities-before-composing)
3. [Model slots, not resume domains](#model-slots-not-resume-domains)
4. [Choose flow and grid columns](#choose-flow-and-grid-columns)
5. [Handle arbitrary sections and entries](#handle-arbitrary-sections-and-entries)
6. [Handle long and optional fields](#handle-long-and-optional-fields)
7. [Use compatibility wrappers carefully](#use-compatibility-wrappers-carefully)
8. [Preserve content and visual identity](#preserve-content-and-visual-identity)
9. [Escape visible text](#escape-visible-text)

## Keep the layers separate

- Put candidate-specific text and composition in a content fragment.
- Select the fragment through `\ResumeContentFile`.
- Select bounded spacing and typography through `\ResumeDensity`.
- Select semantic colors through `\ResumeTheme`.
- Keep generic components in `resume-components.tex` when that file exists.
- Keep main document setup in `resume.tex`.
- Keep palette definitions in `theme.tex`.
- Never add `\documentclass`, `\begin{document}`, or `\end{document}` to a
  content fragment.
- Do not put raw color values, geometry, font declarations, or page scaling in
  candidate content.

## Inspect capabilities before composing

Read the component definitions every time the template version may have
changed:

```bash
rg -n \
  'newcommand|NewDocumentCommand|NewDocumentEnvironment|newenvironment' \
  "$REPO_ROOT/resume-components.tex" \
  "$REPO_ROOT/resume.tex"
```

Look for domain-neutral capabilities such as:

- a variable-contact header block and contact item;
- an arbitrary section heading;
- an entry band with free-form left and right slots;
- a generic breakable card;
- a one-, two-, or three-column grid with any number of items;
- a metadata row;
- a resume-specific list;
- title, detail, date, chip, and link styling helpers.

The current component file may expose names containing `resumeheaderblock`,
`resumecontact`, `resumesection`, `resumeentryband`, `resumecard`,
`resumegrid`, `resumegriditem`, `resumemetarow`, `resumelist`,
`resumeitemheading`, `resumetagchip`, `resumerolechip`, `resumemedalchip`, or
`resumelinkchip`. Treat these as discovery hints, not fixed call signatures.
Use the implemented definition and examples as the source of truth. If a
needed generic component is absent, compose with the lowest-level existing TeX
structure and compile immediately; do not invent an undocumented macro.

## Model slots, not resume domains

Represent each entry as semantic slots:

- **primary**: the main name, title, or result;
- **secondary**: optional role, degree, venue, scope, or subtitle;
- **meta**: optional date, place, status, or link;
- **body**: optional prose, bullets, tags, or nested entries;
- **mark**: optional short monogram or visual marker.

Slots may be empty. Do not fabricate a value to satisfy a macro. Do not require
every entry to have an organization, role, date, badge, or metric.

Map a content plan by structure:

```text
document
  header
    contact*
  section*
    flow | grid
      entry*
        primary
        secondary?
        meta*
        body?
```

The `*` multiplicity is intentional. It supports zero or more contacts, any
number of sections, and any number of entries per section without changing the
schema.

## Choose flow and grid columns

Choose columns from rendered content, not from section names.

### Use one column

Use a full-width flow when:

- an entry contains prose, bullets, a long title, or multiple metadata values;
- entries have very different heights;
- a date, link, venue, or organization needs wrapping;
- preserving source order across a page break matters;
- two or three columns would create overfull or underfilled cards.

### Use two columns

Use two columns when:

- entries are compact and roughly similar in height;
- each entry still has enough width for its longest unbreakable token;
- comparison or visual balance improves scanning;
- the section has two entries, or more entries that form stable rows.

### Use three columns

Use three columns only when:

- every card is short and homogeneous;
- primary text and metadata fit without aggressive wrapping;
- no card contains prose bullets or long URLs;
- the rendered row remains balanced at every supported density.

Do not use three columns simply because the sample has three awards.

### Handle repeated education entries

Treat education as ordinary repeated entries:

- one record: use one compact full-width card or one grid item without an empty
  neighbor;
- two records: use two columns only when both fit comfortably; otherwise stack;
- three records: use three columns only for short, homogeneous records; use
  two-plus-one or a one-column flow for longer records;
- four or more records: let the generic grid wrap items or use a chronological
  full-width flow.

Apply the same logic to publications, competitions, work history, open-source
contributions, certifications, culinary achievements, or any other section.

## Handle arbitrary sections and entries

Create the title from the content plan and use the generic section component.
Do not route a section through a hard-coded enum. The following are all valid
when supported by evidence:

- education;
- work or projects;
- publications or talks;
- competitions or awards;
- community or caregiving;
- teaching or mentoring;
- culinary or operational achievements;
- a candidate-specific section not anticipated by the template author.

Within a section, combine generic primitives:

- use an entry band for a visually prominent heading plus metadata;
- use a card for a compact independent unit;
- use a metadata row for paired, short values;
- use a list for multiple contributions;
- use a natural paragraph when a list would create artificial structure;
- nest a grid only when the component explicitly supports it and the render
  remains break-safe.

Do not create a new domain-specific macro merely because a section has a new
label. Add a reusable primitive only when the existing primitives cannot
express the layout.

## Handle long and optional fields

- Put unbounded user text in flexible-width columns, breakable boxes, or natural
  paragraphs.
- Use `tabularx` `X` columns or the generic component's equivalent for mixed
  fixed/flexible rows.
- Never put an arbitrary name, title, URL label, organization, degree, venue,
  or date inside a fixed-width `\hbox`.
- Let optional slots disappear cleanly without leaving separators, empty chips,
  or blank columns.
- Use a concise display label for a long URL while preserving the actual link
  target.
- Prefer normal wrapping over font shrinking.
- Keep a section title with its first entry and an entry title with its first
  meaningful line, but do not wrap a whole long section in an unbreakable box.
- Compile after every structural change and fail on overfull output.

## Use compatibility wrappers carefully

The repository may retain macros such as:

- `\resumeheader`;
- `\sectiontitle`;
- `\twocol` and `\threecol`;
- `\eduentry`, `\awardcard`, and `\cventry`;
- `\project`, `\projecttag`, and `\paper`;
- `\rowline`.

Use them only when their implemented shape matches the content exactly. Treat
them as compatibility wrappers, not the resume schema. For example:

- do not force a third education record into an award card;
- do not omit a publication because `\paper` expects a date;
- do not force a community achievement into `\cventry`;
- do not use `\twocol` with an empty second argument to imitate a single card.

Prefer the generic components for new content and for entries with optional,
long, or unusual fields.

## Preserve content and visual identity

In read-only adaptation mode:

- preserve every source fact, sentence, metric, section, and entry order;
- move unchanged text only into compatible components;
- change only column count, bounded density, and page-break behavior;
- keep a source-to-output mapping for verification.

In explicitly authorized content-edit mode:

- edit only within the user's stated scope;
- preserve the underlying facts, metrics, ownership, units, and uncertainty;
- report deletions, rewrites, and reorders.

In both modes:

- treat the user reference or initial template, not a README preview, as visual
  truth;
- preserve its recognizable typography, spacing rhythm, hierarchy, alignment,
  high-density accent rules, pale organization bands, and multilevel bullets;
- use only existing semantic theme and density controls unless the user
  authorizes a redesign;
- do not switch to another template because a section is unconventional.

## Escape visible text

Escape literal TeX-special characters:

| Literal | TeX |
| --- | --- |
| `&` | `\&` |
| `%` | `\%` |
| `_` | `\_` |
| `#` | `\#` |
| `$` | `\$` |
| `{` / `}` | `\{` / `\}` |
| `~` | `\textasciitilde{}` |
| `^` | `\textasciicircum{}` |
| `\` | `\textbackslash{}` |

Keep raw Unicode Chinese text for XeLaTeX. Put URLs in the implemented generic
link helper or the compatible `\plainlink`/`\linkchip` helper. Escape special
characters in visible labels without corrupting the link target.
