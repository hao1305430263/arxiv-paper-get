---
name: arxiv-paper-get
description: Download arXiv papers — fetches PDF + LaTeX source (.tar.gz), extracts source, creates a local workspace. Use when the user shares an arXiv URL and wants to save the paper locally.
source: user
visibility: public
---

# arxiv-paper-get

Download an arXiv paper to a local workspace. Fetches **both** PDF and LaTeX source
(`.tar.gz`) in parallel, extracts the source into a `source/` subdirectory, and writes
a metadata file + report skeleton.

## Detection

**Trigger when the user sends any of these:**

- An `arxiv.org/abs/…` or `arxiv.org/pdf/…` URL
- "download this paper", "fetch the paper", "get the arxiv paper", "pull the paper locally"
- Any message containing an arXiv identifier like `2506.01966` or `arxiv:2506.01966`
- The user says "save this paper" while a paper URL is in the conversation

**Do NOT trigger** when the user is only asking a question *about* a paper (e.g.,
"What does 2506.01966 say about…") without asking to download it.

## First-run setup (MUST do before anything else)

Before running the workflow, check whether the `arxiv-paper-get` CLI is installed:

```bash
arxiv-paper-get --help
```

If the command is **not found**, do NOT proceed silently. Tell the user:

> `arxiv-paper-get` is not installed yet. Install it with:
> ```bash
> uv tool install git+https://github.com/hao1305430263/arxiv-paper-get
> ```
>
> This only needs to be done once — it compiles the Python script into a global command.

After installation, verify with `arxiv-paper-get --help` and continue.

## Workflow

Once the CLI is confirmed available:

### 1. Extract the arXiv URL

From the user's message, extract the full arXiv URL.
If the user only gives an ID (e.g., `2506.01966`), construct the URL:
`https://arxiv.org/abs/2506.01966`

### 2. Run the download

```bash
arxiv-paper-get "https://arxiv.org/abs/XXXX.XXXXX"
```

The default base directory is `./papers` (relative to CWD). To override:

```bash
arxiv-paper-get "https://arxiv.org/abs/XXXX.XXXXX" "/path/to/custom/dir"
```

### 3. Parse the JSON output

The command prints a JSON object to stdout on success. Key fields:

| Field | Description |
|-------|-------------|
| `paper_dir` | Path to the paper workspace |
| `pdf_path` | Path to the downloaded PDF (or `null`) |
| `source_path` | Path to the source tarball (or `null`) |
| `source_extract_dir` | Path to extracted source, typically `paper_dir/source/` (or `null`) |
| `report_path` | Path to the report skeleton `.md` |
| `pdf_ok` | `true` if PDF downloaded successfully |
| `source_ok` | `true` if LaTeX source downloaded successfully |
| `source_extracted` | `true` if source was extracted |

### 4. Report to the user

After the command finishes, summarize:

```
📥 Downloaded: {title}
📄 PDF: {pdf_path or "not available"}
📦 Source: {source_extract_dir or "not available"}
📝 Report skeleton: {report_path}
```

If the source tarball was not available (common for older papers), note it:
> LaTeX source is not available for this paper — PDF only.

## Directory structure created

```
papers/{Paper Title}/
├── {Paper Title}.pdf          # PDF file
├── {Paper Title}.tar.gz       # LaTeX source tarball (if available)
├── source/                    # Extracted LaTeX source (if available)
│   ├── main.tex
│   └── ...
├── metadata.json              # Full paper metadata
└── {Paper Title}_report.md    # Report skeleton for note-taking
```

## Gotchas

- **TeX source** may not be available for all arXiv papers (pre-2000, some publishers).
  The tool handles this gracefully — PDF is still downloaded.
- **Write conflicts**: the tool never overwrites an existing report file.
- **Windows paths**: fully supported; the tool uses `pathlib.Path` throughout.
- **Offline**: the tool requires network access to `arxiv.org` and `export.arxiv.org`.

## Example session

```
User: download https://arxiv.org/abs/2506.01966

Agent: [checks: arxiv-paper-get --help → OK]
Agent: *runs `arxiv-paper-get "https://arxiv.org/abs/2506.01966"`*

📥 Downloaded: Matrix Is All You Need
📄 PDF: papers/Matrix_Is_All_You_Need/Matrix_Is_All_You_Need.pdf
📦 Source: papers/Matrix_Is_All_You_Need/source/
📝 Report skeleton: papers/Matrix_Is_All_You_Need/Matrix_Is_All_You_Need_report.md
```
