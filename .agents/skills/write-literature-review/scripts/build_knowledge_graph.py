#!/usr/bin/env python3
"""Create graph-ready files from included literature-review references."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "using",
    "based",
    "review",
    "study",
    "studies",
    "analysis",
    "approach",
    "method",
    "methods",
}


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def workspace_path(workspace: Path, *parts: str) -> Path:
    return workspace.joinpath(*parts)


def stable_ref_id(index: int) -> str:
    return f"R{index:04d}"


def included_rows(workspace: Path) -> list[dict[str, Any]]:
    included_path = workspace / "included_references.jsonl"
    if included_path.exists():
        return iter_jsonl(included_path)
    filtered_path = workspace_path(workspace, "screening", "filtered_candidates.jsonl")
    if filtered_path.exists():
        return iter_jsonl(filtered_path)
    rows = iter_jsonl(workspace_path(workspace, "search", "deduped_candidates.jsonl"))
    return [row for row in rows if (row.get("screening") or {}).get("status") == "include"]


def concept_terms(row: dict[str, Any]) -> list[str]:
    terms = []
    terms.extend(row.get("concepts") or [])
    terms.extend(row.get("keywords") or [])
    title_words = re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", row.get("title") or "")
    terms.extend(w for w in title_words if w.lower() not in STOPWORDS)
    normalized = []
    seen = set()
    for term in terms:
        clean = re.sub(r"\s+", " ", str(term)).strip()
        key = clean.lower()
        if clean and key not in seen:
            normalized.append(clean)
            seen.add(key)
    return normalized[:20]


def build_graph(rows: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = []
    edges = []
    concept_sources: dict[str, set[str]] = defaultdict(set)
    for idx, row in enumerate(rows, 1):
        ref_id = row.get("ref_id") or stable_ref_id(idx)
        row["ref_id"] = ref_id
        nodes.append(
            {
                "id": ref_id,
                "type": "paper",
                "label": row.get("title", ref_id),
                "year": row.get("year"),
                "doi": row.get("doi"),
                "venue": row.get("venue"),
            }
        )
        for term in concept_terms(row):
            concept_id = "C:" + re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
            concept_sources[concept_id].add(ref_id)
            edges.append({"source": ref_id, "target": concept_id, "type": "studies"})
    for concept_id, refs in sorted(concept_sources.items()):
        label = concept_id[2:].replace("-", " ")
        nodes.append({"id": concept_id, "type": "concept", "label": label, "source_papers": sorted(refs)})
    return {"nodes": nodes, "edges": edges}


def write_references(workspace: Path, rows: list[dict[str, Any]]) -> None:
    by_subarea: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        subarea = row.get("subarea") or row.get("primary_subarea") or "Unclassified"
        by_subarea[subarea].append(row)
    lines = ["# References", ""]
    for subarea, items in sorted(by_subarea.items()):
        lines.extend([f"## {subarea}", ""])
        for row in items:
            authors = ", ".join((row.get("authors") or [])[:6])
            suffix = " et al." if len(row.get("authors") or []) > 6 else ""
            year = row.get("year") or "n.d."
            title = row.get("title") or "Untitled"
            venue = row.get("venue") or ""
            doi = row.get("doi") or row.get("id") or ""
            lines.append(f"- [{row.get('ref_id')}] {authors}{suffix} ({year}). {title}. {venue}. {doi}".strip())
        lines.append("")
    content = "\n".join(lines) + "\n"
    (workspace / "references.md").write_text(content, encoding="utf-8")
    references_dir = workspace_path(workspace, "references")
    references_dir.mkdir(parents=True, exist_ok=True)
    (references_dir / "references.md").write_text(content, encoding="utf-8")


def write_graph_markdown(workspace: Path, graph: dict[str, Any]) -> None:
    concepts = [n for n in graph["nodes"] if n["type"] == "concept"]
    top = sorted(concepts, key=lambda n: len(n.get("source_papers", [])), reverse=True)[:50]
    lines = ["# Knowledge Graph", "", "## Top Concepts", ""]
    for node in top:
        refs = ", ".join(node.get("source_papers", []))
        lines.append(f"- **{node['label']}**: {refs}")
    lines.extend(["", "## Edge Types", "", "- `studies`: paper discusses or uses a concept."])
    graph_dir = workspace_path(workspace, "graph")
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "knowledge_graph.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_graph_dot(workspace: Path, graph: dict[str, Any]) -> Path:
    graph_dir = workspace_path(workspace, "graph")
    graph_dir.mkdir(parents=True, exist_ok=True)
    dot_path = graph_dir / "knowledge_graph.dot"
    concept_nodes = [node for node in graph["nodes"] if node["type"] == "concept"]
    active_concepts = {node["id"]: node for node in concept_nodes[:50]}
    active_papers = {
        edge["source"]
        for edge in graph["edges"]
        if edge.get("target") in active_concepts and edge.get("source", "").startswith("R")
    }
    paper_lookup = {
        node["id"]: node for node in graph["nodes"] if node["type"] == "paper" and node["id"] in active_papers
    }
    lines = [
        "digraph KnowledgeGraph {",
        '  rankdir=LR;',
        '  graph [bgcolor="white"];',
        '  node [fontname="Helvetica"];',
        '  edge [color="#7a8a99"];',
    ]
    for node in paper_lookup.values():
        label = (node.get("label") or node["id"]).replace('"', '\\"')
        lines.append(f'  "{node["id"]}" [label="{label}", shape=box, style="rounded,filled", fillcolor="#dbeafe"];')
    for node in active_concepts.values():
        label = (node.get("label") or node["id"]).replace('"', '\\"')
        lines.append(f'  "{node["id"]}" [label="{label}", shape=ellipse, style="filled", fillcolor="#dcfce7"];')
    for edge in graph["edges"]:
        if edge.get("source") in paper_lookup and edge.get("target") in active_concepts:
            lines.append(f'  "{edge["source"]}" -> "{edge["target"]}";')
    lines.append("}")
    dot_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dot_path


def render_graph_png(workspace: Path, dot_path: Path) -> None:
    output_path = workspace / "knowledge_graph.png"
    dot_binary = shutil.which("dot")
    if not dot_binary:
        raise RuntimeError("Graphviz 'dot' is required to render knowledge_graph.png")
    subprocess.run([dot_binary, "-Tpng", str(dot_path), "-o", str(output_path)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    workspace = Path(args.workspace)
    rows = included_rows(workspace)
    graph = build_graph(rows)
    graph_dir = workspace_path(workspace, "graph")
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "knowledge_graph.json").write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    write_references(workspace, rows)
    write_graph_markdown(workspace, graph)
    dot_path = write_graph_dot(workspace, graph)
    render_graph_png(workspace, dot_path)
    print(f"wrote graph with {len(graph['nodes'])} nodes and {len(graph['edges'])} edges")


if __name__ == "__main__":
    main()
