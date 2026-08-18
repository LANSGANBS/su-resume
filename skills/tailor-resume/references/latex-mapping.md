# LaTeX content mapping

## Edit boundaries

- Put personalizable text and section ordering in `content.tex`.
- Keep layout macros and package setup in `resume.tex`.
- Keep palette definitions in `theme.tex`.
- Preserve `content.tex` as an included fragment; never add
  `\documentclass`, `\begin{document}`, or `\end{document}`.
- Use the existing header macro unless the user requests a layout redesign.

## Supported content macros

Use the repository definitions as the source of truth. The current template
provides:

| Macro | Purpose |
| --- | --- |
| `\resumeheader{name}{headline}{phone}{email}{code-profile}{website}` | Render the profile and contact header. |
| `\headerlink{url}{label}` | Render a bold link inside the header. |
| `\sectiontitle{中文}{English}` | Start a major section. |
| `\twocol{left}{right}` | Place two compact blocks side by side. |
| `\threecol{left}{middle}{right}` | Place three compact blocks side by side. |
| `\eduentry{mark}{school}{tags}{dates}{degree-or-detail}{location}` | Render one education card. |
| `\awardcard{title}{color}{badge}{date}` | Render one award or competition card. |
| `\cventry{mark}{organization}{team-or-summary}{date}{role-chip}` | Render an experience/project heading card. |
| `\project{name}` | Start a project subsection. |
| `\projecttag{name}{role}` | Start a project subsection with a role chip. |
| `\tagchip{text}` | Render a skill or category chip. |
| `\rolechip{text}` | Render a role chip. |
| `\linkchip{url}{label}` | Render a compact external link. |
| `\plainlink{url}{label}` | Render an inline link. |
| `\lead{text}` | Emphasize the lead phrase of a bullet. |
| `\metric{text}` | Emphasize a sourced metric. |
| `\paper{title}{venue-or-detail}{date}` | Render a research/writing item. |

Use ordinary `itemize` lists for contribution bullets. Do not invent macro
names; compile after every structural change.

## Escaping

Escape literal TeX-special characters in visible text:

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

Keep raw Unicode Chinese text; XeLaTeX handles it. Put URLs in `\plainlink` or
`\linkchip`, and escape special characters in the visible label.

## Theme selection

Read `theme.tex` before selecting a theme. The baseline defines `ocean`,
`forest`, `plum`, and `graphite`; the validation script discovers the current
set rather than trusting this list.

Set the default through `\ResumeTheme` in `resume.tex`. To add a theme:

1. Add one named branch in `theme.tex`.
2. Override every semantic token used by the current palette, including accent,
   secondary, ink, muted, rule, surface, paper, link, and medal colors.
3. Keep content free of hard-coded palette colors.
4. Preserve readable text/background contrast in chips, links, rules, and
   cards.
5. Build and visually inspect every theme with `--all-themes`.

## Pagination

Let sections flow naturally; do not insert manual negative spacing or forced
page breaks until content prioritization is complete. For a one-page target,
remove weak content before compressing layout. For a multi-page target, keep
section headings with the first following entry and avoid isolated bullets at
page boundaries.
