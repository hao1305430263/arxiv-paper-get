# arxiv-paper-get

**Download an arXiv paper — PDF + LaTeX source — in one command.**

Given an arXiv URL, `arxiv-paper-get` fetches the paper's **PDF** and **LaTeX source
tarball in parallel**, extracts the source into a `source/` directory, and creates a
ready-to-use local workspace with metadata and a README that guides LLMs to the main
document.

> **GitHub:** [hao1305430263/arxiv-paper-get](https://github.com/hao1305430263/arxiv-paper-get)

---

## Features

- **Parallel download** — PDF and LaTeX source (`.tar.gz`) are fetched simultaneously.
- **Auto-extract** — the source tarball is unpacked into `source/` with path-traversal
  protection.
- **Rich metadata** — title, authors, abstract, categories, DOI, journal ref, and more
  are saved as `metadata.json` (sourced from the official arXiv API).
- **LLM-friendly README** — auto-generates `README.md` with the source file tree and
  identifies the main `.tex` document, so downstream LLMs know exactly where to start
  reading. Never overwrites an existing README.
- **Zero dependencies** — uses only the Python standard library. No `pip install` of
  anything else required.
- **Cross-platform** — `pathlib.Path` throughout; Windows and Unix paths are handled
  correctly.
- **Graceful degradation** — if LaTeX source is not available (common for older or
  some publisher-hosted papers), the PDF is still downloaded and the tool exits
  cleanly.

---

## Installation

### Option A: Claude Code plugin marketplace (recommended)

In Claude Code, add this repo as a plugin marketplace, then install:

```
/plugin marketplace add hao1305430263/arxiv-paper-get
/plugin install arxiv-paper-get@arxiv-paper-get
```

This installs the Claude Code plugin, which carries the `arxiv-paper-get` skill.
Once installed, the skill auto-triggers whenever you share an arXiv link.

### Option B: npx skills (cross-agent)

```bash
npx skills add https://github.com/hao1305430263/arxiv-paper-get
```

### 3. Install the Python CLI

Regardless of which option you used above, also install the CLI tool:

```bash
uv tool install git+https://github.com/hao1305430263/arxiv-paper-get
```

### Uninstall

```bash
uv tool uninstall arxiv-paper-get
```

---

## Usage

```bash
# Default: saves to ./papers/
arxiv-paper-get "https://arxiv.org/abs/2506.01966"

# Custom base directory
arxiv-paper-get "https://arxiv.org/abs/2506.01966" "/path/to/my/papers"
```

### Output

The command prints a JSON summary to stdout:

```json
{
  "arxiv_id": "2506.01966",
  "title": "Matrix Is All You Need",
  "paper_dir": "papers/Matrix_Is_All_You_Need",
  "pdf_path": "papers/Matrix_Is_All_You_Need/Matrix_Is_All_You_Need.pdf",
  "source_path": null,
  "source_extract_dir": "papers/Matrix_Is_All_You_Need/source",
  "readme_path": "papers/Matrix_Is_All_You_Need/README.md",
  "metadata_path": "papers/Matrix_Is_All_You_Need/metadata.json",
  "pdf_ok": true,
  "source_ok": true,
  "source_extracted": true
}
```

### Directory structure created

```
papers/{Paper Title}/
├── {Paper Title}.pdf          # PDF file
├── source/                    # Extracted LaTeX source (if available)
│   ├── main.tex
│   ├── sections/
│   └── ...
├── metadata.json              # Full paper metadata
└── README.md                  # Guides LLMs to the main .tex document
```

> The LaTeX source tarball (`.tar.gz`) is auto-cleaned after successful extraction.

---

## Credits

Based on the `paper-interpreter` skill by [chujianyun](https://github.com/chujianyun/skills).

---

---

# arxiv-paper-get（中文说明）

**一条命令下载 arXiv 论文 —— PDF + LaTeX 源码。**

给定一个 arXiv 链接，`arxiv-paper-get` 会**并行下载**论文的 PDF 和 LaTeX 源码压缩包，
自动将源码解压到 `source/` 目录，并创建包含元数据和 README 引导文件（指引大模型找到主 `.tex` 文档）的本地工作区。

> **GitHub:** [hao1305430263/arxiv-paper-get](https://github.com/hao1305430263/arxiv-paper-get)

---

## 功能特性

- **并行下载** — PDF 和 LaTeX 源码（`.tar.gz`）同时获取，互不等待。
- **自动解压** — 源码包自动解压到 `source/` 子目录，内置路径穿越保护。
- **完整元数据** — 标题、作者、摘要、分类、DOI、期刊引用等信息保存为
  `metadata.json`（通过 arXiv 官方 API 获取）。
- **LLM 引导 README** — 自动生成 `README.md`，列出源码文件树并标注 LaTeX
  主文档，指引大模型找到入口文件。已有 README 不会被覆盖。
- **零依赖** — 仅使用 Python 标准库，无需额外安装任何第三方包。
- **跨平台** — 全面使用 `pathlib.Path`，Windows 与 Unix 路径均正确处理。
- **优雅降级** — 如果论文的 LaTeX 源码不可用（老旧论文或部分出版社论文常见），
  仍然会下载 PDF 并正常退出。

---

## 安装

### 方式 A：Claude Code 插件市场（推荐）

在 Claude Code 中，先将本仓库添加为插件市场，然后安装：

```
/plugin marketplace add hao1305430263/arxiv-paper-get
/plugin install arxiv-paper-get@arxiv-paper-get
```

这会安装一个 Claude Code 插件，其中包含 `arxiv-paper-get` skill。
安装后，当你向 Claude Code 分享 arXiv 链接时，skill 会自动触发。

### 方式 B：npx skills（跨 Agent）

```bash
npx skills add https://github.com/hao1305430263/arxiv-paper-get
```

### 3. 安装 Python CLI

无论选择哪种方式，都需要额外安装命令行工具：

```bash
uv tool install git+https://github.com/hao1305430263/arxiv-paper-get
```

### 卸载

```bash
uv tool uninstall arxiv-paper-get
```

---

## 用法

```bash
# 默认保存到 ./papers/
arxiv-paper-get "https://arxiv.org/abs/2506.01966"

# 指定保存目录
arxiv-paper-get "https://arxiv.org/abs/2506.01966" "/path/to/my/papers"
```

### 输出

命令执行后在 stdout 输出 JSON 摘要（见上方英文部分，`report_path` 已改为 `readme_path`）。

### 生成的目录结构

```
papers/{论文标题}/
├── {论文标题}.pdf              # PDF 文件
├── source/                     # 解压后的 LaTeX 源码（如有）
│   ├── main.tex
│   ├── sections/
│   └── ...
├── metadata.json               # 论文元数据
└── README.md                   # 引导大模型找到主 .tex 文档
```

> LaTeX 源码压缩包（`.tar.gz`）解压成功后自动删除。

---

## 致谢

基于 [chujianyun](https://github.com/chujianyun/skills) 的 `paper-interpreter` skill
改写：输出英文化、并行下载、Windows 兼容、独立打包。
