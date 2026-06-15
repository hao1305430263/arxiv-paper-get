#!/usr/bin/env python3
"""Download an arXiv paper's PDF and LaTeX source, extract, and create a workspace."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from xml.etree import ElementTree

USER_AGENT = "arxiv-paper-get/1.0 (+https://arxiv.org)"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# ---------------------------------------------------------------------------
# URL / ID parsing
# ---------------------------------------------------------------------------


def extract_arxiv_id(url: str) -> str:
    """Extract the bare arXiv ID from a URL like arxiv.org/abs/2506.01966"""
    parsed = parse.urlparse(url)
    if "arxiv.org" not in parsed.netloc:
        raise ValueError(f"Unsupported domain: {parsed.netloc or url}")

    path = parsed.path.strip("/")
    if not path:
        raise ValueError(f"Could not extract arXiv ID from URL: {url}")

    if path.startswith(("abs/", "pdf/", "html/", "e-print/")):
        paper_id = path.split("/", 1)[1]
    else:
        paper_id = path

    if paper_id.endswith(".pdf"):
        paper_id = paper_id[:-4]

    paper_id = paper_id.strip()
    if not paper_id:
        raise ValueError(f"Could not extract arXiv ID from URL: {url}")
    return paper_id


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def http_get(url: str) -> request.addinfourl:
    req = request.Request(url, headers={"User-Agent": USER_AGENT})
    return request.urlopen(req, timeout=30)


# ---------------------------------------------------------------------------
# arXiv API metadata
# ---------------------------------------------------------------------------


def fetch_metadata(arxiv_id: str) -> dict[str, Any]:
    """Query the arXiv API and return paper metadata."""
    encoded_id = parse.quote(arxiv_id, safe="")
    api_url = f"https://export.arxiv.org/api/query?id_list={encoded_id}"
    with http_get(api_url) as response:
        xml_bytes = response.read()

    root = ElementTree.fromstring(xml_bytes)
    entry = root.find("atom:entry", ATOM_NS)
    if entry is None:
        raise RuntimeError(f"No metadata returned for arXiv ID: {arxiv_id}")

    def text(path: str) -> str:
        node = entry.find(path, ATOM_NS)
        if node is None or node.text is None:
            return ""
        return " ".join(node.text.split())

    authors = [
        " ".join(author.text.split())
        for author in entry.findall("atom:author/atom:name", ATOM_NS)
        if author.text
    ]
    categories = [
        cat.attrib["term"]
        for cat in entry.findall("atom:category", ATOM_NS)
        if cat.attrib.get("term")
    ]

    primary_category_node = entry.find("arxiv:primary_category", ATOM_NS)
    primary_category = (
        primary_category_node.attrib.get("term", "")
        if primary_category_node is not None
        else ""
    )

    return {
        "arxiv_id": arxiv_id,
        "title": text("atom:title"),
        "abstract": text("atom:summary"),
        "authors": authors,
        "published": text("atom:published"),
        "updated": text("atom:updated"),
        "comment": text("arxiv:comment"),
        "journal_ref": text("arxiv:journal_ref"),
        "doi": text("arxiv:doi"),
        "primary_category": primary_category,
        "categories": categories,
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "source_url": f"https://arxiv.org/e-print/{arxiv_id}",
    }


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def sanitize_folder_name(title: str, fallback: str) -> str:
    """Turn a paper title into a safe directory / file name."""
    # Replace characters that are illegal on Windows and Unix
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback.replace("/", "-")
    return cleaned[:120].rstrip(" .")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_filename(name: str, fallback: str, suffix: str) -> str:
    """Create a safe filename from a title, appending a suffix."""
    base = sanitize_folder_name(name, fallback)
    return base + suffix


# ---------------------------------------------------------------------------
# Download helpers (chunked, 30 s timeout)
# ---------------------------------------------------------------------------


def _download_chunked(url: str, destination: Path) -> Path:
    """Stream *url* to *destination* in 64 KiB chunks."""
    with http_get(url) as response, destination.open("wb") as fh:
        while True:
            chunk = response.read(1024 * 64)
            if not chunk:
                break
            fh.write(chunk)
    return destination


def _infer_filename_from_headers(headers: Any) -> str:
    """Guess a filename from Content-Disposition or Content-Type."""
    content_disposition = headers.get("Content-Disposition", "")
    match = re.search(r'filename="?([^";]+)"?', content_disposition)
    if match:
        return match.group(1)

    content_type = headers.get_content_type()
    if "gzip" in content_type:
        return "source.tar.gz"
    if "tar" in content_type:
        return "source.tar"
    if content_type == "application/pdf":
        return "source.pdf"
    return "source"


# ---------------------------------------------------------------------------
# Download PDF
# ---------------------------------------------------------------------------


def download_pdf(pdf_url: str, paper_dir: Path, pdf_filename: str) -> Path | None:
    """Download the PDF. Returns the destination path, or None on failure."""
    destination = paper_dir / pdf_filename
    try:
        _download_chunked(pdf_url, destination)
        return destination
    except error.HTTPError as exc:
        print(f"PDF download failed (HTTP {exc.code}): {pdf_url}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"PDF download failed: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Download LaTeX source  (tar.gz)
# ---------------------------------------------------------------------------


def download_source(source_url: str, paper_dir: Path) -> Path | None:
    """Download the LaTeX source tarball. Returns path or None."""
    try:
        with http_get(source_url) as response:
            filename = _infer_filename_from_headers(response.headers)
            destination = paper_dir / filename
            with destination.open("wb") as fh:
                while True:
                    chunk = response.read(1024 * 64)
                    if not chunk:
                        break
                    fh.write(chunk)
        return destination
    except error.HTTPError as exc:
        if exc.code in {403, 404}:
            print(
                f"LaTeX source not available for this paper (HTTP {exc.code})",
                file=sys.stderr,
            )
            return None
        print(f"LaTeX source download failed (HTTP {exc.code})", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"LaTeX source download failed: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Extract tarball
# ---------------------------------------------------------------------------


def maybe_extract_source(source_path: Path | None, paper_dir: Path) -> Path | None:
    """Extract a source tarball into ``source/``.  Returns the directory or None."""
    if source_path is None or not source_path.exists():
        return None

    extract_dir = paper_dir / "source"
    ensure_dir(extract_dir)
    try:
        with tarfile.open(source_path, "r:*") as archive:
            # Path-traversal guard (cross-platform — uses relative_to)
            base = extract_dir.resolve()
            for member in archive.getmembers():
                target = (extract_dir / member.name).resolve()
                try:
                    target.relative_to(base)
                except ValueError:
                    raise RuntimeError(
                        f"Unsafe archive member path: {member.name}"
                    )
            archive.extractall(extract_dir)
        # Clean up the tarball after successful extraction
        source_path.unlink()
        return extract_dir
    except (tarfile.TarError, RuntimeError) as exc:
        print(f"Failed to extract source tarball: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def write_metadata(metadata: dict[str, Any], metadata_path: Path) -> None:
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# README.md generator (guides LLMs to the main document)
# ---------------------------------------------------------------------------


def _guess_main_tex(source_dir: Path) -> str | None:
    """Guess which .tex file is the main LaTeX document.

    Heuristics (tried in order):

    1. Common main-document filenames: ``main.tex``, ``paper.tex``, ``article.tex``,
       ``manuscript.tex``, ``root.tex``, ``ms.tex``, ``document.tex``, ``arxiv.tex``.
    2. Files containing ``\\documentclass`` — if only one, that's it; if multiple,
       the one with the most ``\\input`` / ``\\include`` calls wins (strongest
       root-document signal).
    3. The ``.tex`` file whose stem matches the parent directory name (e.g. a
       conference-name file like ``aaai24.tex`` in an ``aaai24/`` source tree).
    4. The largest ``.tex`` file that does **not** look like a section file
       (names starting with ``sec``, ``section``, ``appendix``, ``app``, ``s_``,
       ``ch_``, ``chapter_``).
    5. Last resort: the first ``.tex`` file found.
    """
    tex_files = sorted(source_dir.rglob("*.tex"))
    if not tex_files:
        return None

    # --- Priority 1: common main-document names (case-insensitive) -----------
    common_names = {
        "main.tex", "paper.tex", "article.tex", "manuscript.tex",
        "root.tex", "ms.tex", "document.tex", "arxiv.tex",
    }
    for tf in tex_files:
        if tf.name.lower() in common_names:
            return str(tf.relative_to(source_dir))

    # --- Priority 2: files containing \documentclass ------------------------
    docclass_files: list[tuple[Path, int]] = []
    for tf in tex_files:
        try:
            content = tf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if r"\documentclass" not in content:
            continue
        input_count = len(re.findall(r"\\input\b", content))
        include_count = len(re.findall(r"\\include\b", content))
        docclass_files.append((tf, input_count + include_count))

    if docclass_files:
        # The file with the most \input / \include calls is almost certainly
        # the root document.
        docclass_files.sort(key=lambda x: x[1], reverse=True)
        return str(docclass_files[0][0].relative_to(source_dir))

    # --- Priority 3: match parent directory name ---------------------------
    parent = source_dir.name.lower()
    for tf in tex_files:
        if tf.stem.lower() == parent:
            return str(tf.relative_to(source_dir))

    # --- Priority 4: largest .tex file that doesn't look like a section ----
    section_re = re.compile(
        r"^(sec|section|appendix|app|s|ch|chapter)[\W_]", re.IGNORECASE
    )
    candidates: list[tuple[Path, int]] = []
    for tf in tex_files:
        if not section_re.match(tf.name):
            candidates.append((tf, tf.stat().st_size))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        return str(candidates[0][0].relative_to(source_dir))

    # --- Priority 5: first .tex file ---------------------------------------
    return str(tex_files[0].relative_to(source_dir))


def _generate_file_tree(
    directory: Path,
    max_depth: int = 4,
    max_entries: int = 300,
) -> str:
    """Generate an ASCII file tree of *directory*."""

    lines: list[str] = []

    def _walk(current: Path, prefix: str = "", depth: int = 0) -> None:
        if depth > max_depth:
            lines.append(f"{prefix}... (max depth reached)")
            return
        if len(lines) >= max_entries:
            return

        entries = sorted(current.iterdir())
        for i, entry in enumerate(entries):
            if len(lines) >= max_entries:
                lines.append(f"{prefix}... (truncated)")
                return

            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                extension = "    " if is_last else "│   "
                _walk(entry, prefix + extension, depth + 1)
            else:
                lines.append(f"{prefix}{connector}{entry.name}")

    lines.append(f"{directory.name}/")
    _walk(directory)
    return "\n".join(lines)


def write_readme(
    metadata: dict[str, Any],
    paper_dir: Path,
    source_dir: Path | None,
    pdf_path: str | None,
) -> Path:
    """Create ``README.md`` in *paper_dir* that guides LLMs to the main document.

    * If LaTeX source was extracted, lists the file tree and guesses which
      ``.tex`` file is the root document.
    * If only a PDF is available, tells the LLM to use the PDF.
    * Never overwrites an existing ``README.md``.
    """
    readme_path = paper_dir / "README.md"
    if readme_path.exists():
        return readme_path

    title = metadata.get("title", "Untitled")
    authors = ", ".join(metadata.get("authors", []))
    arxiv_id = metadata.get("arxiv_id", "")
    abstract = metadata.get("abstract", "")
    published = metadata.get("published", "")
    doi = metadata.get("doi", "")
    categories = ", ".join(metadata.get("categories", []))

    lines: list[str] = [
        f"# {title}",
        "",
        "## Paper Info",
        "",
        f"- **arXiv ID:** [{arxiv_id}](https://arxiv.org/abs/{arxiv_id})",
        f"- **Authors:** {authors}",
        f"- **Published:** {published}",
    ]
    if categories:
        lines.append(f"- **Categories:** {categories}")
    if doi:
        lines.append(f"- **DOI:** [{doi}](https://doi.org/{doi})")

    lines += [
        "",
        "## Abstract",
        "",
        abstract,
        "",
        "---",
        "",
        "## Main Document",
        "",
    ]

    # --- Source available: guess main .tex and show file tree --------------
    source_available = source_dir is not None and source_dir.exists()
    if source_available:
        main_tex = _guess_main_tex(source_dir)
        if main_tex:
            lines.append(
                f"** `source/{main_tex}`** is the LaTeX main document."
            )
            lines.append("")
            lines.append(
                "Read this file first to understand the paper structure, "
                "then follow `\\input` / `\\include` references to other "
                "`.tex` files as needed."
            )
        else:
            lines.append(
                "No `.tex` file found in `source/` — the source may use a "
                "different format."
            )

        lines += [
            "",
            "## Source File Structure",
            "",
        ]
        tree = _generate_file_tree(source_dir)
        lines.append(tree)
        lines.append("")

    # --- Source NOT available: guide to PDF --------------------------------
    else:
        lines.append("LaTeX source is **not available** for this paper.")
        lines.append("")
        if pdf_path:
            lines.append(
                f"Use the PDF instead: `{Path(pdf_path).name}`"
            )
        else:
            lines.append(
                "No PDF available either — only metadata is present."
            )
        lines.append("")

    # --- General workspace guidance ----------------------------------------
    lines += [
        "---",
        "",
        "## How to Use This Workspace",
        "",
    ]
    if source_available and source_dir is not None and _guess_main_tex(source_dir):
        lines += [
            "1. Read the main `.tex` file listed in **Main Document** above — "
            "it contains the full paper text.",
            "2. Follow `\\input`/`\\include` references to other `.tex` files.",
            "3. Figures (`.pdf`/`.png`) are referenced from the LaTeX source.",
            "4. `metadata.json` has structured metadata (title, authors, DOI, "
            "categories, etc.).",
        ]
    else:
        lines += [
            "1. If only a PDF is available, extract text using a PDF→markdown "
            "conversion tool.",
            "2. `metadata.json` has structured metadata (title, authors, DOI, "
            "categories, etc.).",
        ]
    lines.append("")

    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return readme_path


#
# ---------------------------------------------------------------------------
# Parallel download orchestration
# ---------------------------------------------------------------------------


def _download_both(
    pdf_url: str,
    source_url: str,
    paper_dir: Path,
    pdf_filename: str,
) -> tuple[Path | None, Path | None]:
    """Download PDF and LaTeX source in parallel. Returns (pdf_path, source_path)."""
    results: dict[str, Path | None] = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(download_pdf, pdf_url, paper_dir, pdf_filename): "pdf",
            executor.submit(download_source, source_url, paper_dir): "source",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                print(f"Unexpected error during {key} download: {exc}", file=sys.stderr)
                results[key] = None

    return results.get("pdf"), results.get("source")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download an arXiv paper: PDF + LaTeX source, extract, and create a local workspace."
    )
    parser.add_argument("url", help="arXiv URL, e.g. https://arxiv.org/abs/2506.01966")
    parser.add_argument(
        "base_dir",
        nargs="?",
        default="papers",
        help="Base directory for paper folders. Defaults to ./papers",
    )
    args = parser.parse_args(argv)

    # Resolve base directory relative to CWD
    base_dir = Path(args.base_dir).resolve()
    ensure_dir(base_dir)

    # --- Step 1: identify the paper ---
    arxiv_id = extract_arxiv_id(args.url)
    print(f"arXiv ID: {arxiv_id}")

    metadata = fetch_metadata(arxiv_id)
    title = metadata["title"]
    print(f"Title: {title}")

    folder_name = sanitize_folder_name(title, arxiv_id)
    paper_dir = base_dir / folder_name
    ensure_dir(paper_dir)
    print(f"Workspace: {paper_dir}")

    # --- Step 2: download PDF + source in parallel ---
    pdf_filename = safe_filename(title, arxiv_id, ".pdf")
    pdf_path, source_path = _download_both(
        metadata["pdf_url"],
        metadata["source_url"],
        paper_dir,
        pdf_filename,
    )

    # --- Step 3: extract source tarball ---
    source_extract_dir = maybe_extract_source(source_path, paper_dir)

    # --- Step 4: write metadata and README ---
    metadata["paper_dir"] = str(paper_dir)
    metadata["pdf_path"] = str(pdf_path) if pdf_path else None
    metadata["source_path"] = str(source_path) if source_path else None
    metadata["source_extract_dir"] = (
        str(source_extract_dir) if source_extract_dir else None
    )
    metadata["downloaded_at"] = datetime.now(timezone.utc).isoformat()

    write_metadata(metadata, paper_dir / "metadata.json")
    readme_path = write_readme(
        metadata,
        paper_dir,
        source_extract_dir,
        metadata["pdf_path"],
    )

    # --- Step 5: print result summary as JSON ---
    result = {
        "arxiv_id": arxiv_id,
        "title": title,
        "paper_dir": str(paper_dir),
        "pdf_path": str(pdf_path) if pdf_path else None,
        "source_path": str(source_path) if source_path else None,
        "source_extract_dir": str(source_extract_dir) if source_extract_dir else None,
        "readme_path": str(readme_path),
        "metadata_path": str(paper_dir / "metadata.json"),
        "pdf_ok": pdf_path is not None,
        "source_ok": source_path is not None,
        "source_extracted": source_extract_dir is not None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# Allow running as `python -m arxiv_paper_get` too
if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
