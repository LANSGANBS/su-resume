# 中文技术简历 LaTeX 模板

一份面向软件工程师与 AI/Agent 工程师的单页中文简历模板。仓库中的姓名、经历、项目、链接和指标均为虚构示例，可安全公开使用。

## 快速开始

1. 将仓库上传到 Overleaf，主文档选择 `resume.tex`。
2. 编译器选择 XeLaTeX。
3. 在 `content.tex` 中替换示例内容。
4. 在 `resume.tex` 顶部修改 `\ResumeTheme` 切换主题色。

本地编译：

```bash
latexmk -xelatex -interaction=nonstopmode -halt-on-error resume.tex
```

支持的主题：`ocean`、`forest`、`plum`、`graphite`。

> 发布前请搜索并确认仓库中不存在真实姓名、手机号、邮箱、私有链接、公司内部项目名与敏感业务数据。
