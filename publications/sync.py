#!/usr/bin/env python3
"""Synchronize publication metadata from INSPIRE and generate site/CV output."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "publications"
MANUAL_PATH = HERE / "manual.json"
INSPIRE_PATH = HERE / "inspire.json"
DATA_PATH = HERE / "publications.json"
TEX_PATH = ROOT / "cv" / "publications.tex"
INDEX_PATH = ROOT / "index.html"
START_MARKER = "<!-- PUBLICATIONS:START -->"
END_MARKER = "<!-- PUBLICATIONS:END -->"
API_URL = "https://inspirehep.net/api/literature"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_inspire(bai: str) -> dict:
    params = urllib.parse.urlencode(
        {
            "q": f"a {bai}",
            "sort": "mostrecent",
            "size": "50",
            "fields": ",".join(
                [
                    "titles",
                    "authors.full_name",
                    "arxiv_eprints",
                    "publication_info",
                    "dois",
                    "earliest_date",
                    "citation_count",
                    "document_type",
                ]
            ),
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"User-Agent": "rwhitehill.github.io publication sync"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def compact_name(name: str) -> str:
    """Convert INSPIRE's family-first names to consistent CV-style initials."""
    if "," not in name:
        return name
    family, given = (part.strip() for part in name.split(",", 1))
    if family == "Whitehill":
        return "R. M. Whitehill"
    given = re.sub(r"(?<=\.)(?=[A-Z])", " ", given)
    initials = []
    for index, part in enumerate(given.split()):
        initials.append(part if "." in part or index > 0 else f"{part[0]}.")
    return f"{' '.join(initials)} {family}"


def journal_citation(metadata: dict) -> str | None:
    publications = metadata.get("publication_info") or []
    if not publications:
        return None
    info = publications[0]
    title = {
        "Phys.Lett.B": "Phys. Lett. B",
        "Phys.Rev.D": "Phys. Rev. D",
    }.get(info.get("journal_title"), info.get("journal_title"))
    if not title:
        return None
    volume = info.get("journal_volume")
    article = info.get("artid")
    year = info.get("year")
    pieces = [title]
    if volume:
        pieces.append(str(volume))
    citation = " ".join(pieces)
    if article:
        citation += f", {article}"
    if year:
        citation += f" ({year})"
    return citation


def normalize_inspire(raw: dict, overrides: dict) -> list[dict]:
    records = []
    for hit in raw.get("hits", {}).get("hits", []):
        record_id = str(hit["id"])
        metadata = hit["metadata"]
        override = overrides.get(record_id, {})
        date = metadata.get("earliest_date", "")
        publication_info = metadata.get("publication_info") or []
        publication_year = publication_info[0].get("year") if publication_info else None
        year = int(publication_year or date[:4])
        arxiv_info = (metadata.get("arxiv_eprints") or [{}])[0]
        arxiv = arxiv_info.get("value")
        categories = arxiv_info.get("categories") or []
        doi = ((metadata.get("dois") or [{}])[0]).get("value")
        journal = journal_citation(metadata)
        title = override.get("title") or metadata["titles"][0]["title"]
        status = override.get("status") or journal or "Preprint"
        records.append(
            {
                "id": record_id,
                "source": "inspire",
                "title": title,
                "title_latex": override.get("title_latex"),
                "authors": [compact_name(author["full_name"]) for author in metadata.get("authors", [])],
                "year": year,
                "sort_date": date,
                "status": status,
                "journal": journal,
                "arxiv": arxiv,
                "arxiv_category": categories[0] if categories else None,
                "doi": doi,
                "inspire_id": record_id,
                "citations": metadata.get("citation_count"),
                "updated": hit.get("updated"),
            }
        )
    return records


def normalize_manual(items: list[dict]) -> list[dict]:
    return [
        {
            **item,
            "source": "manual",
            "title_latex": item.get("title_latex"),
            "journal": None,
            "arxiv": None,
            "arxiv_category": None,
            "doi": None,
            "inspire_id": None,
            "citations": None,
            "updated": None,
        }
        for item in items
    ]


def validate(records: list[dict]) -> None:
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate publication IDs found")
    for record in records:
        for required in ("id", "title", "authors", "year", "sort_date", "status"):
            if not record.get(required):
                raise ValueError(f"{record['id']} is missing {required}")
        if not any("Whitehill" in author for author in record["authors"]):
            raise ValueError(f"{record['id']} does not include Richard Whitehill")


def join_authors_html(authors: list[str]) -> str:
    rendered = []
    for author in authors:
        escaped = html.escape(author)
        rendered.append(f"<strong>{escaped}</strong>" if "Whitehill" in author else escaped)
    if len(rendered) == 1:
        return rendered[0]
    if len(rendered) == 2:
        return " and ".join(rendered)
    return ", ".join(rendered[:-1]) + ", and " + rendered[-1]


def link(url: str, label: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>'


def publication_html(record: dict) -> str:
    title_url = (
        f"https://inspirehep.net/literature/{record['inspire_id']}"
        if record["inspire_id"]
        else None
    )
    title = html.escape(record["title"])
    if title_url:
        title = (
            f'<a href="{html.escape(title_url, quote=True)}" target="_blank" '
            f'rel="noopener noreferrer" aria-label="{html.escape(record["title"], quote=True)} on INSPIRE">'
            f"{title}</a>"
        )

    metadata = [f'<span class="publication-status">{html.escape(record["status"])}</span>']
    if record["doi"]:
        metadata.append(link(f"https://doi.org/{record['doi']}", "DOI"))
    if record["arxiv"]:
        label = f"arXiv:{record['arxiv']}"
        metadata.append(link(f"https://arxiv.org/abs/{record['arxiv']}", label))
    metadata_html = '<span aria-hidden="true"> · </span>'.join(metadata)

    return "\n".join(
        [
            '            <li class="publication-item">',
            f'              <div class="publication-year">{record["year"]}</div>',
            '              <div class="publication-details">',
            f'                <h4>{title}</h4>',
            f'                <p class="publication-authors">{join_authors_html(record["authors"])}</p>',
            f'                <p class="publication-meta">{metadata_html}</p>',
            "              </div>",
            "            </li>",
        ]
    )


def render_web(records: list[dict]) -> str:
    current = [record for record in records if not record["journal"]]
    published = [record for record in records if record["journal"]]
    sections = []
    for heading, items in (("Preprints &amp; works in progress", current), ("Published", published)):
        rows = "\n".join(publication_html(record) for record in items)
        sections.append(
            "\n".join(
                [
                    '        <section class="publication-group">',
                    f"          <h3>{heading}</h3>",
                    '          <ol class="publication-list">',
                    rows,
                    "          </ol>",
                    "        </section>",
                ]
            )
        )
    return "\n".join(sections)


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def join_authors_latex(authors: list[str]) -> str:
    rendered = []
    for author in authors:
        escaped = latex_escape(author).replace(" ", "~")
        rendered.append(rf"\textbf{{{escaped}}}" if "Whitehill" in author else escaped)
    if len(rendered) == 1:
        return rendered[0]
    if len(rendered) == 2:
        return " and ".join(rendered)
    return ", ".join(rendered[:-1]) + ", and " + rendered[-1]


def render_latex(records: list[dict]) -> str:
    lines = ["% Generated by publications/sync.py; edit publications/manual.json instead.", r"\begin{enumerate}[leftmargin=*]"]
    for record in records:
        status = latex_escape(record["status"])
        links = []
        if record["doi"]:
            links.append(rf"\href{{https://doi.org/{record['doi']}}}{{DOI}}")
        if record["arxiv"]:
            category = f" [{latex_escape(record['arxiv_category'])}]" if record["arxiv_category"] else ""
            links.append(rf"\href{{https://arxiv.org/abs/{record['arxiv']}}}{{arXiv:{record['arxiv']}{category}}}")
        metadata = status if record["journal"] else f"{status} ({record['year']})"
        if links:
            metadata += ", " + ", ".join(links)
        title = record.get("title_latex") or latex_escape(record["title"])
        lines.extend(
            [
                "",
                rf"    \item {join_authors_latex(record['authors'])} \\",
                rf"    {metadata} \\",
                rf"    \textit{{{title}}}",
            ]
        )
    lines.extend([r"\end{enumerate}", ""])
    return "\n".join(lines)


def update_index(fragment: str) -> None:
    index = INDEX_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
        flags=re.DOTALL,
    )
    replacement = f"{START_MARKER}\n{fragment}\n        {END_MARKER}"
    updated, count = pattern.subn(replacement, index)
    if count != 1:
        raise ValueError("Expected exactly one publication marker block in index.html")
    INDEX_PATH.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Use the committed INSPIRE cache")
    args = parser.parse_args()

    manual = read_json(MANUAL_PATH)
    if args.offline:
        raw = read_json(INSPIRE_PATH)
    else:
        raw = fetch_inspire(manual["profile"]["inspire_bai"])
        write_json(INSPIRE_PATH, raw)

    records = normalize_manual(manual["works_in_progress"])
    records.extend(normalize_inspire(raw, manual.get("overrides", {})))
    records.sort(key=lambda record: record["sort_date"], reverse=True)
    validate(records)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": manual["profile"],
        "publications": records,
    }
    write_json(DATA_PATH, output)
    TEX_PATH.write_text(render_latex(records), encoding="utf-8")
    update_index(render_web(records))
    print(f"Synchronized {len(records)} publications ({len(raw['hits']['hits'])} from INSPIRE).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
