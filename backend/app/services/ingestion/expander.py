"""Context expansion for screened lines.

Stage 3 of the ingestion pipeline. When a ParsedLine's screening score
crosses the threshold, this stage builds an expanded EvidenceUnit by
collecting the triggering line plus surrounding lines within configurable
bounds, prioritizing semantic completeness.

Expansion strategy (in order of preference):
  1. Same logical block (paragraph, procedure step, caption, or policy statement)
  2. Same table row plus inherited table headers when table content is involved
  3. Same section block
  4. Fixed window of N lines above and below within the same page
  5. Minimum: the triggering line alone

The result is stored as an EvidenceUnit linking back to all source line IDs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_APPROX_CHARS_PER_TOKEN = 4


@dataclass
class ExpansionResult:
    trigger_line_id: int
    source_line_ids: list[int]
    content: str
    page_numbers: list[int]
    section_path: str | None
    table_coordinates: dict | None
    token_count: int


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)


def expand_line(
    trigger_idx: int,
    all_lines: list[dict],
    window: int = 10,
    max_tokens: int = 800,
) -> ExpansionResult:
    """Build an expanded evidence unit from a trigger line and surrounding context.

    Args:
        trigger_idx: Index into all_lines of the triggering line.
        all_lines: Full list of line dicts for the document (from DB or in-memory).
                   Each dict has keys: id, line_number, page_number, section_path,
                   table_id, row_index, col_index, content_type, content.
        window: Max lines to include above and below the trigger.
        max_tokens: Max token budget for the expanded unit.

    Returns:
        ExpansionResult with all traceability fields populated.
    """
    trigger = all_lines[trigger_idx]
    trigger_section = trigger.get("section_path")
    trigger_table = trigger.get("table_id")
    trigger_block = trigger.get("block_id")

    if trigger_table:
        return _expand_table(trigger, trigger_idx, all_lines, max_tokens)

    selected_idxs = _expand_by_block(trigger_idx, all_lines, trigger_block, max_tokens)

    if len(selected_idxs) < 2:
        selected_idxs = _expand_by_section(trigger_idx, all_lines, trigger_section, max_tokens)

    if len(selected_idxs) < 3:
        selected_idxs = _expand_by_window(trigger_idx, all_lines, window, max_tokens)

    selected_lines = [all_lines[i] for i in selected_idxs]
    content = "\n".join(ln["content"] for ln in selected_lines)
    page_numbers = list(dict.fromkeys(
        ln["page_number"] for ln in selected_lines if ln.get("page_number")
    ))

    return ExpansionResult(
        trigger_line_id=trigger["id"],
        source_line_ids=[ln["id"] for ln in selected_lines],
        content=content,
        page_numbers=page_numbers,
        section_path=trigger_section,
        table_coordinates=None,
        token_count=_estimate_tokens(content),
    )


def _expand_by_block(
    trigger_idx: int,
    all_lines: list[dict],
    block_id: str | None,
    max_tokens: int,
) -> list[int]:
    """Prefer the original logical parser block when provenance is available."""
    if not block_id:
        return [trigger_idx]

    idxs = [i for i, line in enumerate(all_lines) if line.get("block_id") == block_id]
    if not idxs:
        return [trigger_idx]
    return _trim_to_budget(idxs, all_lines, trigger_idx, max_tokens)


def _expand_by_section(
    trigger_idx: int,
    all_lines: list[dict],
    section_path: str | None,
    max_tokens: int,
) -> list[int]:
    """Collect lines sharing the same section path, centered on trigger."""
    # Find the contiguous block around trigger with the same section path
    start = trigger_idx
    end = trigger_idx

    # Expand backward
    for i in range(trigger_idx - 1, max(0, trigger_idx - 50) - 1, -1):
        ln = all_lines[i]
        if ln.get("content_type") == "heading":
            break
        if ln.get("section_path") != section_path:
            break
        start = i

    # Expand forward
    for i in range(trigger_idx + 1, min(len(all_lines), trigger_idx + 50)):
        ln = all_lines[i]
        if ln.get("content_type") == "heading":
            break
        if ln.get("section_path") != section_path:
            break
        end = i

    idxs = list(range(start, end + 1))
    # Trim to token budget
    return _trim_to_budget(idxs, all_lines, trigger_idx, max_tokens)


def _expand_by_window(
    trigger_idx: int,
    all_lines: list[dict],
    window: int,
    max_tokens: int,
) -> list[int]:
    """Fixed window expansion centered on trigger, same page only."""
    trigger_page = all_lines[trigger_idx].get("page_number")

    start = max(0, trigger_idx - window)
    end = min(len(all_lines) - 1, trigger_idx + window)

    # Filter to same page if page numbers available
    if trigger_page:
        idxs = [
            i for i in range(start, end + 1)
            if all_lines[i].get("page_number") in (trigger_page, None)
        ]
    else:
        idxs = list(range(start, end + 1))

    return _trim_to_budget(idxs, all_lines, trigger_idx, max_tokens)


def _expand_table(
    trigger: dict,
    trigger_idx: int,
    all_lines: list[dict],
    max_tokens: int,
) -> ExpansionResult:
    """Expand to include the trigger row plus header context from the same table."""
    table_id = trigger.get("table_id")
    trigger_row = trigger.get("row_index")
    table_lines = [
        (i, ln) for i, ln in enumerate(all_lines)
        if ln.get("table_id") == table_id
    ]

    if not table_lines:
        table_lines = [(trigger_idx, trigger)]
    else:
        header_lines = [(i, ln) for i, ln in table_lines if ln.get("row_index") == 0]
        row_lines = [(i, ln) for i, ln in table_lines if ln.get("row_index") == trigger_row]
        combined = header_lines + row_lines if trigger_row not in (None, 0) else row_lines or header_lines
        if combined:
            table_lines = []
            seen: set[int] = set()
            for i, ln in combined:
                if i in seen:
                    continue
                seen.add(i)
                table_lines.append((i, ln))

    selected = []
    tokens = 0
    for i, ln in table_lines:
        t = _estimate_tokens(ln["content"])
        if tokens + t > max_tokens and selected:
            break
        selected.append((i, ln))
        tokens += t

    selected_idxs = [i for i, _ in selected]
    selected_lns = [ln for _, ln in selected]
    content = "\n".join(ln["content"] for ln in selected_lns)
    page_numbers = list(dict.fromkeys(
        ln["page_number"] for ln in selected_lns if ln.get("page_number")
    ))

    # Build table coordinates summary
    rows = sorted(set(ln.get("row_index", 0) for ln in selected_lns if ln.get("row_index") is not None))
    cols = sorted(set(ln.get("col_index", 0) for ln in selected_lns if ln.get("col_index") is not None))
    table_coords = {"table_id": table_id, "rows": rows, "cols": cols}

    return ExpansionResult(
        trigger_line_id=trigger["id"],
        source_line_ids=[ln["id"] for ln in selected_lns],
        content=content,
        page_numbers=page_numbers,
        section_path=trigger.get("section_path"),
        table_coordinates=table_coords,
        token_count=_estimate_tokens(content),
    )


def _trim_to_budget(
    idxs: list[int],
    all_lines: list[dict],
    trigger_idx: int,
    max_tokens: int,
) -> list[int]:
    """Trim an index list to fit within token budget, keeping trigger."""
    if not idxs:
        return [trigger_idx]

    tokens = sum(_estimate_tokens(all_lines[i]["content"]) for i in idxs)
    if tokens <= max_tokens:
        return idxs

    # Trim from edges, preserving trigger
    result = list(idxs)
    while tokens > max_tokens and len(result) > 1:
        # Remove from whichever end is farther from trigger
        if result[0] != trigger_idx and (
            result[-1] == trigger_idx or
            abs(result[0] - trigger_idx) >= abs(result[-1] - trigger_idx)
        ):
            tokens -= _estimate_tokens(all_lines[result[0]]["content"])
            result = result[1:]
        else:
            tokens -= _estimate_tokens(all_lines[result[-1]]["content"])
            result = result[:-1]

    return result if result else [trigger_idx]
