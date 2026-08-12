"""Presentation only — takes `aggregations.py` return values and renders
them. Never queries the database directly."""

from __future__ import annotations


def render_bar_chart(data: dict[str, int | float], title: str, width: int = 40) -> str:
    if not data:
        return f"{title}\n(no data)"

    max_value = max(data.values()) or 1
    lines = [title]
    for label, value in data.items():
        bar_len = int((value / max_value) * width) if max_value else 0
        bar = "#" * bar_len
        lines.append(f"{label:>12} | {bar} {value}")
    return "\n".join(lines)
