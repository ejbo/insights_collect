"""DedupMerger — group snippets by URL (and rough text similarity), aggregate provider hits."""

from collections import defaultdict
from difflib import SequenceMatcher

from app.agents.state import ReportState


def _norm_url(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip().split("#", 1)[0]
    if u.endswith("/"):
        u = u[:-1]
    return u.lower()


def _similar(a: str, b: str, threshold: float = 0.85) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a[:200], b[:200]).ratio() >= threshold


async def dedup_merger_node(state: ReportState) -> dict:
    snippets = state.get("raw_snippets") or []
    if not snippets:
        return {"snippets_clusters": []}

    # First pass: group by normalized URL
    by_url: dict[str | None, list] = defaultdict(list)
    no_url: list = []
    for s in snippets:
        u = _norm_url(s.url)
        if u:
            by_url[u].append(s)
        else:
            no_url.append(s)

    clusters: list[dict] = []
    for url, group in by_url.items():
        clusters.append({
            "key_url": url,
            "snippets": group,
            "providers": sorted({s.provider for s in group}),
            "title": next((s.title for s in group if s.title), None),
            "domain": next((s.source_domain for s in group if s.source_domain), None),
        })

    # Second pass: cluster URL-less snippets by rough text similarity
    leftover_clusters: list[dict] = []
    for s in no_url:
        placed = False
        for c in leftover_clusters:
            if _similar(c["snippets"][0].snippet, s.snippet):
                c["snippets"].append(s)
                if s.provider not in c["providers"]:
                    c["providers"].append(s.provider)
                placed = True
                break
        if not placed:
            leftover_clusters.append({
                "key_url": None,
                "snippets": [s],
                "providers": [s.provider],
                "title": s.title,
                "domain": s.source_domain,
            })

    clusters.extend(leftover_clusters)
    return {
        "snippets_clusters": clusters,
        "notes": [f"dedup: {len(snippets)} snippets → {len(clusters)} clusters"],
    }
