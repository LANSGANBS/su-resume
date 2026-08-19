# su-resume

一份面向软件工程师与 AI / Agent 工程师的一页、两页或更长 CV 中文技术简历 LaTeX 模板。内容、样式与主题色相互分离，支持 Overleaf 和本地 XeLaTeX；仓库自带隐私扫描、全主题构建、精确页数和页面均衡校验。

仓库中的姓名、学校、公司、经历、项目、链接和指标均为虚构示例，不对应真实个人或组织。

> **English summary:** A privacy-first one- or multi-page Chinese résumé/CV template for software and AI/agent engineers. It supports XeLaTeX, Overleaf, semantic color themes, adaptive density, reproducible builds, and repository/history privacy checks.

![Ocean、Forest、Plum、Graphite 四套主题预览](assets/previews/theme-gallery.png)

## 特点

- 一页、两页或更长 A4 排版，针对中文技术简历的信息密度与自然分页优化。
- `content.tex`、`theme.tex` 与版式命令分离，修改内容时不必碰样式。
- 内置 `ocean`、`forest`、`plum`、`graphite` 四套语义化主题色。
- 内置 `balanced`、`airy`、`compact`、`dense` 四档语义密度；默认保持 `balanced` 视觉参考。
- 自适应拟合只选择有界密度与分页策略，不改写、裁剪或隐藏用户内容；目标可以是任意正页数，内置回归重点覆盖最常见的一页与两页。
- 组合式内容 API 不限定教育、项目、论文或竞赛 schema；支持任意 section、可选字段、1 / 2 / 3+ 段教育和长字段自然换行。
- 默认示例可一次构建全部主题并确认每份 PDF 恰好一页；场景回归另覆盖自然、均衡的两页输出。
- 隐私检查覆盖手机号、非示例邮箱、内网链接、常见密钥、私钥、绝对用户目录、PNG 文本元数据、PDF 元数据和 Git 提交身份。
- 内置 AI-native `tailor-resume` Skill：先建立事实账本，再生成、脱敏、编译并逐页验收简历。
- CI 以最小权限运行隐私检查、测试和全主题编译。

## 快速开始

### 交给 AI Agent 安装

也可以把下面这段话直接粘贴给你的 AI Agent（Claude Code、Codex 等），
让它完成环境检查、安装与验证：

```text
请帮我安装并验证 su-resume，仅使用官方仓库 https://github.com/LANSGANBS/su-resume。先只读检查 Git、make、Bash、Python 3.10+、TeX Live 2023+、XeLaTeX、latexmk、Poppler（pdfinfo、pdftoppm、pdftotext 与中文 CMap 数据）和 Ghostscript；缺少依赖时按仓库 README 处理，执行 sudo、包管理器安装、修改全局环境、覆盖或删除文件前必须先征得我同意。

把仓库克隆到新目录；如果目标目录已经存在，先核对 remote 和 git status，不得覆盖、清理或丢弃已有修改。进入仓库运行 make ci；失败时保留完整错误并停止，不得跳过验证。

验证通过后，安装完整的 skills/tailor-resume 目录，而不是只复制 SKILL.md。先通过当前 Agent 的官方文档、配置或已注册的 Skill roots 确认安装机制；如果有官方 Skill 安装器则优先使用，否则只安装到已经确认的个人 Skill 根目录，不要假设 Claude Code、Codex 或其他 Agent 使用相同目录。目标不存在时先在临时目录完整复制并校验，再安全放置；目标已存在且内容完全相同时不重复写入，存在任何差异时不得合并或覆盖，先展示精简差异并询问我。安装后从已安装副本运行 Skill 单元测试，并按当前 Agent 的官方方式刷新 Skills 或开启新会话，确认 tailor-resume 可被发现。

最后分别报告仓库位置、依赖检查、make ci、四套主题 PDF、Skill 安装方式与最终位置。明确区分“仓库已就绪”“完整工具链已就绪”和“Skill 已安全安装”；如果 Agent 不支持 Skills、无法确认目录或任何校验失败，不要声称安装成功。
```

### Overleaf

1. 下载仓库源码或在 GitHub 中选择 **Download ZIP**。
2. 在 Overleaf 新建项目并上传源码，主文档选择 `resume.tex`。
3. 将编译器切换为 **XeLaTeX**。
4. 在 `content.tex` 中替换虚构示例。
5. 在 `resume.tex` 顶部修改 `\ResumeTheme` 选择主题。

Overleaf 不需要上传 `build/`、本地生成的 PDF 或任何包含真实信息的历史文件。

### 本地

依赖：

- TeX Live 2023 或更新版本；
- XeLaTeX；
- `pdfinfo`、`pdftoppm` 与 `pdftotext`（由 Poppler 提供），以及中文字体所需的
  Poppler CMap 数据；
- Ghostscript（`gs`），用于 Poppler 字体 / CMap 渲染失效时的确定性回退；
- Python 3.10 或更新版本。

macOS 可通过 Homebrew 安装 MacTeX、Poppler 与 Ghostscript：

```bash
brew install --cask mactex-no-gui
brew install poppler ghostscript
```

Debian / Ubuntu 将 Poppler 工具、Adobe CMap 数据与 Ghostscript 分开打包，
本地环境应与 CI 一样显式安装三者：

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends -y \
  fonts-noto-cjk fonts-texgyre ghostscript poppler-data poppler-utils \
  texlive-fonts-recommended texlive-lang-chinese \
  texlive-latex-extra texlive-xetex
```

自适应拟合和版式回归会拒绝已知的 Poppler 字体 / CMap 诊断，并改用
Ghostscript 以固定 A4 像素几何渲染；每个候选实际使用的后端会写入
manifest 的 `rasterizer` 字段。普通 `make build` 不执行像素门禁，但
`make fit`、`make layout-test` 与 `make ci` 需要完整工具链。

```bash
make build
```

产物位于 `build/<theme>/resume-<theme>.pdf`。也可以只构建指定主题：

```bash
make build THEMES="ocean graphite"
```

若只想手动编译默认主题：

```bash
latexmk -xelatex -interaction=nonstopmode -halt-on-error resume.tex
```

### 自适应一页或两页拟合

同一份内容可以在不改写正文的前提下选择最接近默认视觉的合格密度：

```bash
make fit FIT_CONTENT=content.tex FIT_THEME=ocean FIT_PAGES=1
```

拟合器先验收 `balanced`，再按失败原因从所有自然分页 profile 中选择：内容偏短时优先 `airy`，溢页时优先 `compact` / `dense`。只有全部自然候选都不合格，且 `balanced` 已达到多页目标、唯一问题是页面留白或均衡时，才尝试一次仅含有限伸缩量的 `elastic` 页面填充；它不会缩字、改文案或添加装饰性填充。若所有候选仍不能同时满足精确页数、留白、缺字和溢出门禁，命令会失败并保留 JSON 诊断，由使用者决定删减内容还是允许更多页。

完整参数、阈值、可审计 manifest 与 ACM `acmart` 分页机制研究见 [自适应版式说明](docs/LAYOUT.md)。

## 修改内容

日常编辑只需修改 `content.tex`。新内容优先使用
[`resume-components.tex`](resume-components.tex) 的组合式 API：

- `resumeheaderblock` + `\resumecontact`：任意数量的联系方式；
- `\resumesection`：任意名称的 section；
- `\resumeentryband`：浅色组织条或其他左右槽条目；
- `\resumeitemheading`、`\resumemetarow`：蓝色标题和可换行元信息；
- `resumegrid` + `\resumegriditem`：1 / 2 / 3 列、任意数量条目；
- `resumelist`：支持多层 bullet；
- `resumecard`：仅在内容形状确实需要时使用的可选容器。

API 只描述视觉组合，不预设“教育 / 经历 / 项目 / 论文”字段。一个大学、
本硕博三段教育、论文、竞赛、社区服务或自定义成果都可以复用同一组组件；
字段缺失时直接省略，不放空占位。完整示例和长字段规则见
[组合式内容 API](docs/CONTENT_API.md)。

现有 `\resumeheader`、`\sectiontitle`、`\eduentry`、`\awardcard`、
`\cventry`、`\project` 和 `\paper` 仍作为兼容接口保留，但不应被理解为
固定 schema。

示例中的数字只是排版占位。替换为真实数据前，应确认数据可公开、可解释，且不受保密协议或组织政策限制。

## 主题与颜色定制

在 `resume.tex` 顶部选择内置主题：

```tex
\providecommand{\ResumeTheme}{forest}
```

所有颜色都集中在 `theme.tex`，正文只使用语义颜色：

| Token | 用途 |
| --- | --- |
| `Accent` / `AccentStrong` | 分区标题、强调线与关键指标 |
| `AccentSoft` / `AccentSurface` | 标签与经历卡片浅色背景 |
| `Secondary` / `SecondarySoft` | 角色与职责标签 |
| `Ink` | 主文本 |
| `Muted` / `Subtle` | 次要文本与英文小标题 |
| `Rule` | 分隔线 |
| `Surface` / `SurfaceStrong` / `Paper` | 卡片与页面背景 |
| `Link` | 链接文本 |
| `Gold` / `Silver` / `Bronze` | 奖项标签 |

新增主题时，复制一个现有的 `\Use...Theme` 配置、覆盖全部语义 token，再把主题加入 `\ifdefstring` 分派和 `Makefile` 的 `THEMES`。`make test` 会按 WCAG 2.x 相对亮度检查核心语义文本配色：普通文本至少为 4.50:1；7.45pt 奖项标签针对实际的 `Color!11!Paper` 背景采用更保守的 4.65:1 门槛。随后运行 `make build` 检查所有主题。

密度与颜色互相独立。可在 `resume.tex` 中选择默认密度：

```tex
\providecommand{\ResumeDensity}{balanced}
```

日常应保留 `balanced`；需要自动判断时使用 `make fit`，不要手工堆叠负间距。

也可以从命令行临时选择主题，不改源码：

```bash
latexmk -xelatex \
  -usepretex='\def\ResumeTheme{forest}' \
  resume.tex
```

## AI-native Skill

仓库内置 [`tailor-resume`](skills/tailor-resume/SKILL.md) Skill，适合以下任务：

- 把经历笔记、旧简历或面试素材整理成 `content.tex`；
- 基于证据生成量化表述，不虚构公司、日期、指标或成果；
- 将原始材料隔离在 Git 仓库之外，并在公开前执行 denylist 隐私审计；
- 编译指定或全部主题，检查页数、缺字、溢出与重复渲染；
- 把 PDF 逐页渲染为 PNG，完成真正的视觉 QA。

Skill 必须按完整目录安装，不能只复制 `SKILL.md`。根据
[Codex 官方说明](https://learn.chatgpt.com/docs/customization/overview#skills)，
Codex 的用户级 Skill 根目录是 `~/.agents/skills`，仓库级目录是
`.agents/skills`；其他 Agent 请以其官方机制或实际配置为准，不要猜测目录。

首次安装到 Codex 用户级目录时，下面的命令会在目标已存在时拒绝覆盖：

```bash
mkdir -p ~/.agents/skills
if [[ -e ~/.agents/skills/tailor-resume ]]; then
  echo "tailor-resume already exists; compare it before updating." >&2
else
  cp -R skills/tailor-resume ~/.agents/skills/tailor-resume
fi
```

示例：

```text
用 $tailor-resume 把这些经历素材整理成一页中文后端简历，
先建立事实账本，不确定的内容不要猜，最后用 forest 主题渲染验收。
```

## 隐私检查

公开前先运行：

```bash
make privacy
make privacy-history
```

`make privacy` 检查当前仓库文件；`make privacy-history` 还会检查从 `HEAD` 可达的提交身份和历史 blob。扫描器不会输出命中的原文，只报告文件、行号与规则。

检查项包括：

- 中国大陆手机号样式（公开占位只使用不可拨号的 `1XX XXXX XXXX` 等格式）；
- RFC 保留域之外的邮箱；
- 私网、回环、本地域名和带凭据 URL；
- 常见平台 token、JWT、云访问密钥、私钥头和疑似高熵凭据赋值；
- `/Users/<name>`、`/home/<name>` 等本机用户名路径；
- 未批准的二进制文件、被提交的生成 PDF；
- 显式允许的 PNG 是否具有正确签名、合法 chunk/CRC，且不含文本或 EXIF chunk；
- PDF 中的作者、邮箱、链接、用户路径等元数据；
- Git author / committer 的非隐私邮箱，以及历史中已删除但仍可达的敏感内容。

扫描器是防呆工具，不可能判断某个姓名、公司名、项目名或业务数字是否真实。最终发布仍需人工逐字审阅。

## 从私人简历发布为公开仓库

不要直接把私人简历仓库改名后公开，也不要把旧仓库 `push --mirror` 到公开远端。推荐流程：

1. 复制模板文件到一个全新的目录或创建只有一个干净根提交的发布分支。
2. 将所有内容替换为虚构示例，并删除生成文件、图片 EXIF、附件和编辑器缓存。
3. 使用 GitHub 的隐私邮箱或专用公开身份创建提交。
4. 运行 `make ci`，确认当前文件、完整可达历史和全部主题均通过。
5. 用无痕窗口检查 GitHub 的提交、作者、Issue、Actions 日志和 Release 附件。

更完整的逐项清单见 [公开发布清单](docs/PRIVACY.md)。

## 目录结构

```text
.
├── content.tex                 # 虚构示例内容；使用者主要编辑此文件
├── resume.tex                  # 文档入口与排版命令
├── resume-components.tex       # 任意 section/条目/网格/列表的组合式 DSL
├── resume-layout.tex           # 四档密度与分页/Needspace token
├── theme.tex                   # 语义颜色与主题
├── assets/previews/            # 已清除元数据的主题预览
├── scripts/
│   ├── build_themes.sh         # 构建默认示例，验证单页与主题差异
│   ├── fit_resume.py           # 内容保持的密度选择与 PDF/PGM QA
│   ├── test_layouts.py         # 主题矩阵与内容场景回归
│   └── privacy_check.py        # 文件、图片、历史与 PDF 隐私扫描
├── examples/
│   ├── content-undergrad.tex   # 单段教育示例
│   ├── content-academic.tex    # 本硕博与论文示例
│   ├── content-unconventional.tex # 非传统 section 示例
│   ├── content-long.tex        # 长字段与高密度两页压力测试
│   └── layout-cases.json       # 全主题/全场景回归配置
├── skills/tailor-resume/       # AI-native 简历生成与验收 Skill
├── tests/                      # 仓库隐私扫描器回归测试
├── .github/workflows/ci.yml    # GitHub Actions
└── docs/
    ├── CONTENT_API.md          # 组合式内容 API
    ├── LAYOUT.md               # 自适应分页与拟合策略
    └── PRIVACY.md              # 发布前隐私清单
```

## 开发

```bash
make test              # 仓库扫描器 + Skill 脚本单元测试
make privacy-history   # 当前文件 + 可达 Git 历史
make build             # 默认示例的全主题 XeLaTeX + 单页校验
make fit               # 默认内容/Ocean/一页的自适应密度选择
make layout-test       # 全主题默认内容 + Ocean 场景回归
make ci                # 与 CI 等价的完整检查
```

贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 许可证

[MIT License](LICENSE)
