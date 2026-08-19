# 自适应版式与分页

这个模板把“视觉样式”和“信息密度”分开处理。颜色、层级和组件外观仍由原模板与 `theme.tex` 决定；`resume-layout.tex` 只提供一组语义化密度 token，以及避免孤行、孤标题和异常分页的输出规则。

## 密度 profile

命令行可以覆盖默认值：

```tex
\def\ResumeDensity{balanced}
```

四档 profile 的选择意图如下：

| Profile | 用途 | 正文字号 | 策略 |
| --- | --- | ---: | --- |
| `balanced` | 视觉参考与默认值 | 9.35pt | 保留原模板的自然尺寸与 `raggedbottom` |
| `airy` | 内容偏短、页面利用率不足 | 9.55pt | 小幅增加字号、行距、边距和组件留白 |
| `compact` | 参考版式轻微溢页 | 9.20pt | 优先压缩间距与边距，正文仅小幅变化 |
| `dense` | 内容较长但仍需维持目标页数 | 9.00pt | 最后手段；正文不低于 9pt |

`balanced` 是选择锚点，不是简单地从 `airy` 一路尝试到 `dense`。拟合器先验收自然分页的 `balanced`：

- `balanced` 合格时直接采用；
- 单页利用率不足时优先尝试 `airy`；
- 先按失败原因选取第一个合格的自然分页 profile；
- 只有所有自然候选都不合格，且多页 `balanced` 已达到精确页数、唯一问题是底部留白或页间填充不均时，最后尝试一次 `balanced + elastic`；
- 超出目标页数或出现 overfull box 时依次尝试 `compact`、`dense`；
- 没有 profile 合格时失败，不修改、裁剪或隐藏内容。

一页和两页都是合法目标。两页模式还比较各页的内容填充率与底部留白差，避免第一页接近满、第二页明显空。

`elastic` 不是第五档密度，也不是默认视觉模式。它只覆盖
`balanced` 的垂直 glue：section、列表、header 和 entry 间距均使用有限
`plus` 量，页面底部也只有有限缓冲；字体、边距、内容和条目顺序不变。
拟合器只在所有自然 profile 都不合格、自然 `balanced` 恰好达到目标页数，
并且它的所有拒绝原因都属于留白或均衡指标时触发 elastic。编译失败、页数
不符、overfull、缺字、空白页或重复页都不会触发该回退。elastic 候选必须
是零 underfull；有限 glue 容量不足时直接失败，不能靠异常大的中间空洞把
内容推到底部。

## 可组合 token

组件可以读取这些公开 token，而不必知道当前 profile：

- `\ResumeBaseFontSize`、`\ResumeBaseLineHeight`
- `\ResumeMarginTop`、`\ResumeMarginBottom`、`\ResumeMarginLeft`、`\ResumeMarginRight`
- `\ResumeSectionBefore`、`\ResumeSectionAfter`
- `\ResumeCardBefore`、`\ResumeCardAfter`、`\ResumeCardPaddingX`、`\ResumeCardPaddingY`
- `\ResumeGridGap`、`\ResumeGridGapTwo`、`\ResumeGridGapThree`
- `\ResumeGridRowGap`、`\ResumeHeaderColumnGap`、`\ResumeContactColumnGap`
- `\ResumeListItemSep`、`\ResumeListTopSep`、`\ResumeListLeftMargin`
- `\ResumeSectionNeedspace`、`\ResumeBandNeedspace`、`\ResumeEntryNeedspace`、`\ResumeProjectNeedspace`
- `\ResumeNeedSection`、`\ResumeNeedSectionBand`、`\ResumeNeedBand`、`\ResumeNeedEntry`、`\ResumeNeedProject`
- `\ResumeSpaceXS`、`\ResumeSpaceS`、`\ResumeSpaceM`、`\ResumeSpaceL`

section、band、entry 和 project 的 `Needspace` 阈值只保护标题与开头几行，
不把整个长条目锁在同一页。组织色带使用独立的
`\ResumeBandNeedspace`，保证色带至少和首个有效标题一起出现；普通
entry 与论文标题继续使用较小阈值，避免把后续条目误推到新页。分区标题
末尾另有强 keep-with-next penalty；当首个条目放不下时，TeX 会回退到
标题之前的断点，而不是把标题孤立在页尾。准确的 `\Needspace*` 不会
插入无界 `\vfil`。

当一个 section 紧接较高的组织色带，且逐页检查发现标题仍可能落在上一页，
在该 section 前使用 `\ResumeNeedSectionBand`。它只合并标题和色带的局部
保护高度，后续长正文仍然可以自然跨页；不要把整个 section 装进不可分页盒子。

## 自动拟合

```bash
python3 scripts/fit_resume.py \
  --content examples/content-long.tex \
  --theme ocean \
  --target-pages 2
```

拟合器对同一份内容编译 `balanced`、`airy`、`compact`、`dense`，检查：

- 精确页数；
- TeX 编译错误、overfull、underfull 和缺字；
- 空白页和像素完全重复的页面；
- 每页内容 bbox、内容填充率和底部留白；
- 多页填充率差与底部留白差。

页面优先由 `pdftoppm -gray` 渲染为 PGM。拟合器会检查渲染日志；命中
`Missing language pack`、`Unknown font tag`、`No font in show/space`
等已知字体 / CMap 失效诊断时，即使 `pdftoppm` 返回成功也不会接受其输出。
此时改用 Ghostscript 的 `pgmraw` 后端，并按请求 DPI 固定 A4 像素尺寸、
启用 `FIXEDMEDIA` / `PDFFitPage`，避免两个后端的页面舍入差异污染几何门禁。
若 Ghostscript 不存在或回退失败，候选不会获得完整页面指标，因而不能通过
拟合 / 版式回归。每个候选的 manifest 都记录 `rasterizer` 和
`raster_error`，可区分 `pdftoppm`、`ghostscript` 与渲染失败。bbox 与像素
指标仍由 Python 标准库计算。默认阈值：

| 指标 | 默认值 |
| --- | ---: |
| 单页最大底部留白 | 22mm |
| 单页最小纵向填充率 | 0.62 |
| 多页最大填充率差 | 0.22 |
| 多页最大底部留白差 | 25mm |
| 最大 underfull 数 | 20 |

输出目录包含每档 profile 的 PDF、TeX 日志、最终选中 PDF 和
`manifest.json`。manifest 除了记录所有候选、拒绝原因、实际 fallback
顺序和选择原因，还记录：

- `selected_page_fill_mode` 与 `attempted_page_fill_modes`；
- `page_fill_attempts` 中自然 / elastic 两次 `balanced` 的完整诊断；
- `selection_detail`，区分普通 profile 选择和 elastic 留白恢复；
- content、入口、layout、component 和 theme 文件的 SHA-256；
- `content_preserved`，用于确认拟合前后内容文件字节一致。

每次运行会先移除上一次的顶层 fitted PDF；只有本次选中合格候选后才通过
临时文件原子替换最终 PDF。因此失败重跑不会留下一个看似成功的旧产物。
失败时仍保留本次 manifest 诊断，但不会生成一个假装合格的最终 PDF。

elastic 模式还需要显式的 `\ResumeFinalizePage`。LaTeX 在
`\end{document}` 内部执行的 `\newpage` 会加入无界 `\vfil`，这会吞掉
有限 glue 的伸缩比；模板在正文结束后先用强制分页 penalty 发出最后一个
内容页，再交还给内核结束文档。natural 模式下该命令为空操作。

Makefile 快捷入口：

```bash
make fit FIT_CONTENT=content.tex FIT_THEME=ocean FIT_PAGES=1
```

## 版式回归

```bash
python3 scripts/test_layouts.py
```

回归矩阵读取 `examples/layout-cases.json`：

- 默认内容构建全部主题；
- `undergrad`、`academic`、`unconventional`、`long` 四个内容场景只构建 Ocean；
- 三个内容偏短的一页场景预期由 `airy` 接管；阈值只放宽到各自内容量能够达到的范围，不制造空字段；
- 场景阈值在当前基准值外保留约 1--2mm 的栅格化与跨平台字体容差，避免 120dpi 下单个像素的舍入差异造成伪回归；
- `long` 的目标是 `balanced + elastic` 的均衡两页，不会为了压成一页缩小到不可读字号，也不会放宽默认 22mm 底部留白门禁。
- 每份成功 manifest 都会再经过 Skill 的 `validate_fit_manifest.py`，避免回归脚本只相信拟合器自己的 `success` 字段。

配置可以提供：

- `geometry`：页面像素尺寸、bbox 比例、填充率、底部留白和容差；
- `reference.image`：PGM 或常见 8-bit 非交错 PNG；
- `reference.comparison_mode`：公开默认矩阵使用 `shape`，比较页面尺寸、
  归一化 bbox、填充率和墨迹比例，不启用逐像素 diff；
- `reference.page_dimension_tolerance_px` 及各形态指标的独立容差。

这样可以把用户认可的参考图作为视觉真值，而不是把某一次机器或字体环境下的渲染哈希写死。fixture 缺失时，脚本会一次列出所有缺失路径并以配置错误退出。
回归 manifest 还会为每个启用 reference 的 job 记录路径、文件 SHA-256、
页码、比较模式、候选与 reference 指标、所有实测漂移和 pass/fail 结果，
使 reference 更新可以审计，而不是静默替换图片。
`same_page_markers` 还可以声明必须同页 shipout 的两个或多个语义标记。
在内容中用零宽的 `\resumepagemarker{key}` 放置标记；回归会读取最终被选
候选的 LaTeX AUX 页标签，并记录每个标记的实际页码。这不依赖 PDF 字体、
CMap 或文本提取，也能拦截组织色带留在上一页、首项掉到下一页等仅靠几何
指标难以发现的语义分页错误。每个配置标记必须恰好出现一次。

## 从 ACM `acmart` 迁移了什么

研究基于本项目测试环境 TeX Live 2026 中的 `acmart` 2.16
（类文件日期 2025-08-27），并核对 ACM proceedings 模板说明：

- `geometry` 的 `heightrounded` 思路；
- section 前后使用有限阶的 `plus` / `minus` vertical glue；
- widow、club、broken penalty；
- 页面底部只能使用有限阶伸缩，不能使用 `fil` / `fill`；
- 只在适合的版式启用 `flushbottom`。

需要特别说明：`acmart` 2.16 先定义了 `\@textbottom` 的 `plus 1pt`，
随后又对多个版式调用 `\flushbottom`；LaTeX 内核的 `\flushbottom`
会把 `\@textbottom` 重置为 `\relax`。因此不能把那一行直接复制后宣称
底部有限伸缩已经生效。本模板只借鉴设计意图，并在调用 `\flushbottom`
之后安装自己的有限 bottom buffer；回归还会检查页面留白与 TeX 日志。

没有迁移：

- 两栏末页的 `balance` / `pbalance`；
- figure/table float 比例与双栏 float 输出逻辑；
- ACM 的字体、双栏几何、标题层级或出版元数据。

官方来源：

- <https://ctan.org/pkg/acmart>
- <https://www.acm.org/publications/proceedings-template>

这里借鉴的是分页机制，不是 SIGMOD/ACM 的视觉风格。
