"""Presentation only — takes `aggregations.py` return values and renders
them. Never queries the database directly."""

from __future__ import annotations
from html import escape


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


def render_dot_chart_svg(data: dict, width: int = 640, height: int = 140, dot_r: int = 4) -> str:
    """`aggregations.texture_size_points()`(または同形の`{points, mean, outlier_method}`)を
    受け取り、1点=1アセットのストリッププロットSVGを返す(<svg>...</svg>のみ、カード枠やタイトルは
    呼び出し側が用意する)。重なりを避けるための簡易ビースウォーム配置のみを行い、
    is_outlierの判定そのものはaggregations.py側で確定済みの値をそのまま使う。

    CSSクラス dot-normal / dot-outlier / dot-mean-line はテーマ側(呼び出し元のスタイルシート)で
    定義する — このモジュールは色を決めない。
    """
    points = data.get("points", [])
    if not points:
        return f'<svg viewBox="0 0 {width} {height}" class="dot-chart"></svg>'

    values = [p["value"] for p in points]
    min_v, max_v = min(values), max(values)
    span = (max_v - min_v) or 1
    pad = dot_r * 3

    def scale_x(v: float) -> float:
        return pad + (v - min_v) / span * (width - 2 * pad)

    baseline_y = height / 2
    step = dot_r * 2.2

    placed: list[tuple[float, float]] = []
    circles: list[str] = []
    for p in sorted(points, key=lambda p: p["value"]):
        x = scale_x(p["value"])
        y = baseline_y
        offset = 0.0
        direction = 1
        while any(abs(x - px) < step and abs(y - py) < step for px, py in placed):
            offset += step
            y = baseline_y + (offset if direction > 0 else -offset)
            direction *= -1
        placed.append((x, y))
        cls = "dot-outlier" if p.get("is_outlier") else "dot-normal"
        title = escape(f'{p["asset_id"]}: {p["value"]}')
        circles.append(f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{dot_r}"><title>{title}</title></circle>')

    mean_x = scale_x(data.get("mean", min_v))
    mean_line = f'<line x1="{mean_x:.1f}" y1="4" x2="{mean_x:.1f}" y2="{height - 4}" class="dot-mean-line" />'

    return f'<svg viewBox="0 0 {width} {height}" class="dot-chart">{mean_line}{"".join(circles)}</svg>'
