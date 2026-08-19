# Composable content API

`resume-components.tex` is a small visual DSL, not a resume schema. It does not
know what an “education”, “paper”, “competition”, or “project” record is.
Instead, content composes a few wrapping-safe primitives: a header, titled
sections, left/right bands, cards, raster grids, metadata rows, and lists.

Load `theme.tex` first and `resume-components.tex` second. The entrypoint owns
the document class, fonts, page geometry, and base font size.

## Core primitives

### Variable contact header

```tex
\begin{resumeheaderblock}[2]
  {示例使用者}
  {后端与工具工程方向}
  \resumecontact{MAIL}{\headerlink{mailto:hello@example.com}{hello@example.com}}
  \resumecontact{CODE}{\url{https://example.com/code/sample-user}}
  \resumecontact{CITY}{可远程协作}
\end{resumeheaderblock}
```

The optional number is the contact-column count (`1`, `2`, or `3`). Add or
remove `\resumecontact` items freely; an incomplete final row is valid. Labels
and values wrap inside their grid cells. Prefer one column when labels or
literal URLs are unusually long.

### Arbitrary section

```tex
\resumesection{社区维护、餐饮实验与公共写作}[Community \& Practice]
```

Only the first argument is required. The optional subtitle is descriptive, not
a fixed English-name field.

### Two-slot entry band

```tex
\resumeentryband{%
  \resumeentrytitle{任意主内容}\par
  \resumeentrydetail{团队、上下文、摘要或其他内容}
}{%
  \resumedate{很长的日期或状态}\par
  \resumerolechip{任意标签}
}
```

Both slots are wrapping `tabularx` columns. The command does not assign
semantics to either side.

### Optional flowing card

```tex
\begin{resumecard}
  任意段落、表格、\resumemetarow{左侧元信息}{右侧元信息}，
  或者一个 resumelist。
\end{resumecard}
```

Cards are breakable when used in the normal page flow, but they are not the
default resume treatment. Prefer natural paragraphs, blue item headings, and a
shallow entry band; use a card only when a bounded surface carries real
meaning. For a different semantic surface, pass ordinary `tcolorbox` options:

```tex
\begin{resumecard}[colback=SurfaceStrong,colframe=Accent]
  ...
\end{resumecard}
```

### Adaptive raster grid

```tex
\begin{resumegrid}[3]
  \resumegriditem{\lead{第一项}\par 任意自然流内容}
  \resumegriditem{\lead{第二项}\par 任意自然流内容}
  \resumegriditem{\lead{第三项}\par 任意自然流内容}
  \resumegriditem{\lead{第四项}\par 自动进入下一行}
\end{resumegrid}
```

Select `1`, `2`, or `3` columns and add any number of items. Rows equalize
their height by default for visual alignment. For content with deliberately
different heights, use:

```tex
\begin{resumegrid}[2][raster equal height=none]
  ...
\end{resumegrid}
```

Put long, multi-paragraph material in one-column natural flow instead of
forcing it into a dense multi-column row.

### Compact item heading

```tex
\resumeitemheading
  {任意项目、论文、社区成果或其他标题}
  {\resumemuted{日期、状态或标签}}
```

This produces the compact blue subheading used by the reference layout. It is
domain-neutral and both slots wrap.

### Wrapping metadata and lists

```tex
\resumemetarow
  {\plainlink{https://example.com}{一个可以换行的公开链接标签}}
  {很长的工具链、地点、日期或状态说明}

\begin{resumelist}
  \item \lead{动作：}证据支持的结果。
  \item \lead{约束：}边界、规模与验证方式。
\end{resumelist}
```

`\resumemetarow` uses two weighted `X` columns rather than
`\hbox to\linewidth`; either side may wrap.

### Invisible QA page markers

```tex
\resumeentryband{%
  \resumepagemarker{sample-band}%
  \resumeentrytitle{任意主内容}
}{...}
\begin{resumelist}
  \item \resumepagemarker{sample-first-item}任意首项
\end{resumelist}
```

`\resumepagemarker{key}` adds no visible material. It writes a namespaced,
deferred LaTeX label whose page is resolved at shipout, so layout regression
can assert semantic relationships without extracting PDF text. Keys are QA
identifiers rather than resume fields; keep them unique and use only letters,
digits, `.`, `_`, `:`, `/`, or `-`.

## Composition, not field mapping

Choose a visual primitive from content shape:

- repeated peers: `resumegrid` plus natural-flow `resumegriditem` content;
- a prominent record with compact side metadata: `\resumeentryband`;
- a named result followed by bullets: `\resumeitemheading` plus `resumelist`;
- prose that may cross a page: ordinary paragraphs (or an optional
  `resumecard` only when a bounded surface is intentional);
- details under any record: `\resumemetarow` and `resumelist`;
- any category name: `\resumesection`.

One university, three degrees, seven publications, two community roles, a
restaurant field study, or an entirely new category all use the same
primitives. Do not add a required field merely because another resume happens
to contain it. Omit unavailable information instead of inserting empty
placeholders.

## Long-content rules

- Keep visible text in normal paragraphs, `tabularx` slots, cards, or raster
  cells. Do not introduce `\hbox to\linewidth` for title/organization/date
  layouts.
- Use `\url` for long literal URLs so `xurl` may choose breakpoints. Use
  `\plainlink` or `\headerlink` when the visible label is already concise.
- Inline chips use a bounded `varwidth` and wrap when necessary. Prefer short
  labels because chips are navigational accents, not paragraphs.
- New content should use `\resumetagchip`, `\resumerolechip`,
  `\resumemedalchip`, or `\resumelinkchip`. The shorter historical names remain
  available for existing files.
- A raster row is an atomic visual unit. If one item is much longer than its
  peers, switch that group to one column or disable equal-height rows.
- If a section immediately precedes a tall `\resumeentryband` and rendered-page
  review finds the section heading stranded, put `\ResumeNeedSectionBand`
  before `\resumesection`. This protects only the opening pair; it does not
  make the full entry unbreakable.
- Let the layout engine and page flow decide page breaks. Do not add negative
  vertical space or forced page breaks to content fragments.

## Density overrides

The component file supplies every spacing and typography token with
`\providecommand`. A layout entrypoint can define tokens before loading it:

```tex
\newcommand{\ResumeGridRowGap}{1.2mm}
\newcommand{\ResumeCardPaddingY}{1.0mm}
\newcommand{\ResumeSectionNeedspace}{18mm}
\input{resume-components.tex}
```

This keeps content stable across compact, balanced, and spacious density
profiles.

## Compatibility

Existing content remains valid through wrappers for:

```tex
\resumeheader  \sectiontitle  \twocol  \threecol
\eduentry      \awardcard     \cventry
\project       \projecttag    \paper       \rowline
```

New content should prefer the core primitives. Compatibility wrappers retain
the old argument order when an entrypoint has not defined them. When an
existing `resume.tex` already provides those names, loading
`resume-components.tex` leaves their implementation and visual footprint
untouched; the namespaced API is additive.

## Example matrix

The repository includes four fictional content fragments:

| Fragment | Coverage | Verified pages |
| --- | --- | ---: |
| `examples/content-undergrad.tex` | one undergraduate degree, nested bullets, odd two-column item count | 1 |
| `examples/content-academic.tex` | bachelor + master + doctorate, papers, teaching and service | 1 |
| `examples/content-unconventional.tex` | dining observations, community care and custom outcomes | 1 |
| `examples/content-long.tex` | long bilingual fields, long chips, five contacts, odd grids and free-form sections | 2 |

The August 18, 2026 XeLaTeX QA run completed with zero `Overfull`,
`Underfull`, or `Missing character` diagnostics for every fragment. The
two-page stress case also keeps section headings with their first item and
keeps page-bottom whitespace within 15.3 mm across its two pages.
