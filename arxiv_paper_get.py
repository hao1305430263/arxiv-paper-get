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
            # Path-traversal guard
            base = extract_dir.resolve()
            for member in archive.getmembers():
                target = (extract_dir / member.name).resolve()
                if not str(target).startswith(str(base) + "/") and target != base:
                    raise RuntimeError(f"Unsafe archive member path: {member.name}")
            archive.extractall(extract_dir)
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

    # --- Step 4: write metadata and report skeleton ---
    report_filename = safe_filename(title, arxiv_id, "_report.md")
    report_path = paper_dir / report_filename

    metadata["paper_dir"] = str(paper_dir)
    metadata["pdf_path"] = str(pdf_path) if pdf_path else None
    metadata["source_path"] = str(source_path) if source_path else None
    metadata["source_extract_dir"] = (
        str(source_extract_dir) if source_extract_dir else None
    )
    metadata["report_path"] = str(report_path)
    metadata["downloaded_at"] = datetime.now(timezone.utc).isoformat()

    write_metadata(metadata, paper_dir / "metadata.json")

    # --- Step 5: print result summary as JSON ---
    result = {
        "arxiv_id": arxiv_id,
        "title": title,
        "paper_dir": str(paper_dir),
        "pdf_path": str(pdf_path) if pdf_path else None,
        "source_path": str(source_path) if source_path else None,
        "source_extract_dir": str(source_extract_dir) if source_extract_dir else None,
        "report_path": str(report_path),
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
