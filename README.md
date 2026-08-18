# 中文技术简历 LaTeX 模板

一份面向软件工程师与 AI / Agent 工程师的单页中文简历模板。内容、样式与主题色相互分离，支持 Overleaf 和本地 XeLaTeX；仓库自带隐私扫描、全主题构建与单页校验。

仓库中的姓名、学校、公司、经历、项目、链接和指标均为虚构示例，不对应真实个人或组织。

> **English summary:** A privacy-first, single-page Chinese résumé template for software and AI/agent engineers. It supports XeLaTeX, Overleaf, semantic color themes, reproducible multi-theme builds, and repository/history privacy checks.

## 特点

- 单页 A4 排版，针对中文技术简历的信息密度优化。
- `content.tex`、`theme.tex` 与版式命令分离，修改内容时不必碰样式。
- 内置 `ocean`、`forest`、`plum`、`graphite` 四套语义化主题色。
- 本地一次构建全部主题，并自动确认每份 PDF 恰好一页。
- 隐私检查覆盖手机号、非示例邮箱、内网链接、常见密钥、私钥、绝对用户目录、意外二进制文件、PDF 元数据和 Git 提交身份。
- CI 以最小权限运行隐私检查、测试和全主题编译。

## 快速开始

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
- `pdfinfo`（通常由 Poppler 提供）；
- Python 3.9 或更新版本。

macOS 可安装 MacTeX 与 Poppler；Debian / Ubuntu 可安装 `texlive-xetex`、`texlive-lang-chinese`、`texlive-latex-extra`、`fonts-noto-cjk` 和 `poppler-utils`。

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

## 修改内容

日常编辑只需修改 `content.tex`：

- 顶部是姓名、求职方向和联系方式；
- `\sectiontitle` 创建分区；
- `\cventry` 创建经历卡片；
- `\project` / `\projecttag` 创建项目标题；
- `\lead` 与 `\metric` 突出职责和量化结果。

示例中的数字只是排版占位。替换为真实数据前，应确认数据可公开、可解释，且不受保密协议或组织政策限制。

## 主题与颜色定制

在 `resume.tex` 顶部选择内置主题：

```tex
\providecommand{\ResumeTheme}{forest}
```

所有颜色都集中在 `theme.tex`，正文只使用语义颜色：

| Token | 用途 |
| --- | --- |
| `Accent` / `AccentSoft` | 分区标题、强调线、浅色背景 |
| `Role` / `RoleSoft` | 角色与职责标签 |
| `Ink` | 主文本 |
| `Muted` | 次要文本 |
| `Rule` | 分隔线 |
| `Surface` | 卡片背景 |

新增主题时，复制一段现有的 `\ifstrequal` 配置并只替换十六进制颜色。请保证正文与背景有足够对比度，然后将主题名加入 `Makefile` 的 `THEMES`，运行 `make build` 检查所有主题。

## 隐私检查

公开前先运行：

```bash
make privacy
make privacy-history
```

`make privacy` 检查当前仓库文件；`make privacy-history` 还会检查从 `HEAD` 可达的提交身份和历史 blob。扫描器不会输出命中的原文，只报告文件、行号与规则。

检查项包括：

- 中国大陆手机号样式（保留明显的全零示例号）；
- RFC 保留域之外的邮箱；
- 私网、回环、本地域名和带凭据 URL；
- 常见平台 token、JWT、云访问密钥、私钥头和疑似高熵凭据赋值；
- `/Users/<name>`、`/home/<name>` 等本机用户名路径；
- 未批准的二进制文件、被提交的生成 PDF；
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
├── theme.tex                   # 语义颜色与主题
├── scripts/
│   ├── build_themes.sh         # 构建主题并验证单页
│   └── privacy_check.py        # 文件、历史与 PDF 隐私扫描
├── tests/                      # 扫描器回归测试
├── .github/workflows/ci.yml    # GitHub Actions
└── docs/PRIVACY.md             # 发布前隐私清单
```

## 开发

```bash
make test              # 扫描器单元测试
make privacy-history   # 当前文件 + 可达 Git 历史
make build             # 全主题 XeLaTeX + 单页校验
make ci                # 与 CI 等价的完整检查
```

贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 许可证

[MIT License](LICENSE)
