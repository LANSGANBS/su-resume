# 贡献指南

感谢改进这个模板。提交变更前，请把“可公开、可复现、不过度绑定个人环境”作为默认约束。

## 开发流程

1. 从最新主分支创建短生命周期分支。
2. 只在虚构示例上开发；不要把真实简历、截图、构建产物或私有附件放进分支。
3. 保持职责分离：
   - 示例内容放在 `content.tex`；
   - 版式与组件命令放在 `resume.tex`；
   - 主题 token 放在 `theme.tex`；
   - 工程脚本放在 `scripts/`。
4. 运行 `make ci`。
5. 在 Pull Request 中说明视觉变化、兼容性影响和验证结果。

## 隐私要求

- 测试数据必须使用 `example.com`、`example.org`、`example.net`、`.test` 或 `.invalid` 等保留域。
- 手机号应使用明显的占位形式，不能复制真实通讯录内容。
- 不要在 Issue、PR 描述、评论、提交消息、分支名或测试快照中粘贴真实 token、Cookie、内网地址和个人目录。
- 不要提交 PDF、编辑器缓存、字体、图片或其他二进制文件，除非变更确有必要且已清除元数据、确认许可证。
- 提交身份建议启用 GitHub 的 **Keep my email addresses private**。
- 如果敏感内容曾进入 Git 历史，单纯删除文件不够；在合并或公开前必须重写历史并轮换已暴露凭据。

扫描器仅是第二道防线。提交者仍需人工确认示例实体、业务指标和措辞不来源于受限材料。

## 版式与主题

- 目标纸张为 A4，所有内置主题必须保持一页。
- 颜色通过语义 token 引用，不要在 `content.tex` 写死颜色值。
- 新主题需要兼顾普通文本、强调文本、浅色背景和黑白打印的可读性。
- 避免依赖操作系统专有字体；应保留仓库现有的跨平台 fallback。
- 不要启用 LaTeX shell escape，也不要引入构建时网络下载。

## Visual golden 生命周期

`assets/previews/theme-{ocean,forest,plum,graphite}.png` 既是公开预览，也是
默认主题的形态级 visual reference。`make layout-test` 只读取它们，绝不
自动覆盖；接受新的 reference 必须经过下面四个明确阶段。

1. **生成候选。** 先从待提交源码运行 `make build`，再以与回归一致的
   120dpi 生成到忽略目录，不要直接写入 `assets/previews/`：

   ```bash
   mkdir -p build/visual-candidates
   for theme in ocean forest plum graphite; do
     python3 scripts/render_pdf_page.py \
       "build/${theme}/resume-${theme}.pdf" \
       "build/visual-candidates/theme-${theme}.png"
   done
   ```

   这个渲染入口固定生成 993x1404 的 A4 首屏 PNG。它会先尝试 Poppler，
   但即使进程返回成功，只要日志命中已知字体 / CMap 故障或输出签名、尺寸
   不符，就会清理残片并回退到 Ghostscript；两个后端都不可用时会失败退出，
   不会留下可被误认成新候选的旧文件。命令只报告实际后端，不回显 PDF 文本。

2. **人工审阅。** 逐张打开四个候选，确认它们只包含公开虚构示例，
   尺寸为 993x1404，且没有裁切、重叠、缺字、孤立标题或意外分页。
   四张图的几何结构应一致，差异只来自语义主题色。随后只用这四张候选
   重建 `theme-gallery.png`，并再次检查缩略图、标签和主题对应关系。
3. **显式接受。** 只有审阅者明确同意视觉变化后，才把候选复制到
   `assets/previews/`。不要把“让 CI 变绿”当作接受理由，也不要使用私人
   简历、用户截图或未脱敏材料更新 golden。
4. **隐私与 CI。** 接受后先扫描所有 PNG，再跑完整门禁：

   ```bash
   python3 scripts/privacy_check.py assets/previews/*.png --allow-binary .png
   make test
   make build
   make layout-test
   make privacy
   make privacy-history
   ```

公开回归使用 `shape` comparison：比较页面尺寸、归一化内容 bbox、纵向
填充率和墨迹密度，不做逐像素相等判断。这样既能拦截版式形态漂移，也不
会把字体栅格化的细微平台差异误判为失败。每个 job 的
`regression-manifest.json` 会记录 reference 路径、SHA-256、页码、比较
模式、实测漂移和最终结果，PR 应附上这些信息以及人工审阅结论。

## 验证

```bash
make test
make privacy-history
make build
```

`make build` 会构建 `Makefile` 中列出的每个主题，用 `pdfinfo` 确认 PDF 恰好一页，再用 `scripts/render_pdf_page.py` 的受校验首屏渲染比较主题，防止主题选择失效。视觉变更还应人工打开所有主题，检查溢出、孤行、字体 fallback、链接和打印效果。

## Commit 与 Pull Request

- Commit 尽量单一目的，使用清晰的祈使句标题。
- 不要用生成文件制造大体积 diff。
- PR 应附带：
  - 变更动机；
  - 影响的文件和主题；
  - 执行过的验证命令；
  - 若有视觉变化，提供已脱敏截图。

## 许可证

提交贡献即表示你有权提供这些内容，并同意按仓库的 MIT License 分发。
