from PyQt6.QtWidgets import QWidget, QVBoxLayout

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from ..utils.constants import TARGET_YIELD, YIELD_COLOR_HIGH, YIELD_COLOR_MID, YIELD_COLOR_LOW, CHART_TARGET_COLOR
from ..backend.data_models import QueryResult, FailCodeData
from typing import List
from collections import defaultdict


def _yield_color(y: float) -> str:
    if y >= TARGET_YIELD:
        return YIELD_COLOR_HIGH
    if y >= 80.0:
        return YIELD_COLOR_MID
    return YIELD_COLOR_LOW


class YieldChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.figure = Figure(figsize=(12, 4), dpi=96, facecolor="#FFFFFF")
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)

        self._draw_placeholder()

    def _draw_placeholder(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor("#FAFAFA")
        ax.text(
            0.5, 0.5, "Run a query to display Work Order yield chart",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=13, color="#9E9E9E",
        )
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor("#EEEEEE")
        self.figure.tight_layout()
        self.canvas.draw()

    def update_chart(self, result: QueryResult):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor("#FAFAFA")

        wos = result.work_orders
        if not wos:
            ax.text(0.5, 0.5, "No data returned for this query.",
                    ha="center", va="center", transform=ax.transAxes,
                    fontsize=12, color="#9E9E9E")
            self.canvas.draw()
            return

        short_labels = [w.wo_number.split("-")[-1] for w in wos]
        yields = [w.yield_pct for w in wos]
        colors = [_yield_color(y) for y in yields]
        xs = list(range(len(wos)))

        bars = ax.bar(xs, yields, color=colors, edgecolor="white", linewidth=0.6, zorder=3)

        # target line
        ax.axhline(
            y=TARGET_YIELD, color=CHART_TARGET_COLOR,
            linestyle="--", linewidth=1.4, label=f"Target {TARGET_YIELD:.0f}%", zorder=4,
        )

        # percentage labels on top of every bar — font and rotation scale with WO count
        n = len(wos)
        lbl_fontsize = max(6, 10 - n // 8)
        lbl_rotation = 90 if n > 25 else 0
        lbl_va       = "bottom" if lbl_rotation == 0 else "bottom"
        lbl_pad      = 0.3
        for bar, y in zip(bars, yields):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + lbl_pad,
                f"{y:.1f}%",
                ha="center", va="bottom",
                fontsize=lbl_fontsize,
                rotation=lbl_rotation,
                color="#212529",
                fontweight="bold",
                zorder=5,
            )

        ax.set_xticks(xs)
        step = max(1, n // 20)
        ax.set_xticklabels(
            [lbl if i % step == 0 else "" for i, lbl in enumerate(short_labels)],
            rotation=45, ha="right", fontsize=8,
        )
        # Extra headroom so rotated labels don't clip the top
        ax.set_ylim(0, 115 if lbl_rotation == 90 else 110)
        ax.set_ylabel("Yield (%)", fontsize=10)
        ax.set_xlabel("Work Order", fontsize=10)
        ax.set_title(
            f"{result.query_params.product_type}  ·  {result.total_wos} WOs  ·  "
            f"Avg {result.avg_yield:.1f}%  ·  Min {result.min_yield:.1f}%  ·  Max {result.max_yield:.1f}%",
            fontsize=11, pad=10,
        )
        ax.legend(fontsize=9)
        ax.grid(axis="y", color="#EEEEEE", linewidth=0.8, zorder=0)
        for spine in ax.spines.values():
            spine.set_edgecolor("#DDDDDD")

        self.figure.tight_layout()
        self.canvas.draw()


class FailModeChartWidget(QWidget):
    """Horizontal stacked bar chart — fail codes on Y-axis, count on X-axis,
    each bar stacked by operation (top-N ops coloured, rest grouped as Other)."""

    _MAX_OPS   = 8
    _MAX_CODES = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.figure = Figure(figsize=(12, 5), dpi=96, facecolor="#FFFFFF")
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)
        self._draw_placeholder()

    def _draw_placeholder(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor("#FAFAFA")
        ax.text(0.5, 0.5, "No fail code data", ha="center", va="center",
                transform=ax.transAxes, fontsize=13, color="#9E9E9E")
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_edgecolor("#EEEEEE")
        self.figure.tight_layout()
        self.canvas.draw()

    def update_chart(self, fail_codes: "List[FailCodeData]"):
        self.figure.clear()
        if not fail_codes:
            self._draw_placeholder()
            return

        # Aggregate: label → {operation → count}
        label_map: dict = {}
        for fc in fail_codes:
            label = fc.fail_code + (f"  {fc.fail_desc}" if fc.fail_desc else "")
            if label not in label_map:
                label_map[label] = defaultdict(int)
            label_map[label][fc.operation] += fc.count

        # Sort by total count desc, cap rows
        sorted_labels = sorted(
            label_map, key=lambda l: sum(label_map[l].values()), reverse=True
        )[:self._MAX_CODES]

        # Operations ranked by total fail count
        op_totals: dict = defaultdict(int)
        for fc in fail_codes:
            op_totals[fc.operation] += fc.count
        top_ops   = sorted(op_totals, key=op_totals.get, reverse=True)[:self._MAX_OPS]
        has_other = len(op_totals) > self._MAX_OPS

        import matplotlib.pyplot as plt
        cmap   = plt.cm.get_cmap("tab10")
        colors = {op: cmap(i / max(len(top_ops), 1)) for i, op in enumerate(top_ops)}

        ax = self.figure.add_subplot(111)
        ax.set_facecolor("#FAFAFA")

        ys    = list(range(len(sorted_labels)))
        lefts = [0.0] * len(sorted_labels)

        ops_to_plot = top_ops + (["__other__"] if has_other else [])
        for op in ops_to_plot:
            widths = []
            for lbl in sorted_labels:
                if op == "__other__":
                    w = sum(v for k, v in label_map[lbl].items() if k not in top_ops)
                else:
                    w = label_map[lbl].get(op, 0)
                widths.append(float(w))

            color   = "#B0BEC5" if op == "__other__" else colors[op]
            display = "Other ops" if op == "__other__" else op
            bars = ax.barh(ys, widths, left=lefts, color=color, label=display,
                           edgecolor="white", linewidth=0.5)

            max_w = max(widths) if widths else 1
            for bar, w in zip(bars, widths):
                if w > 0 and bar.get_width() > max_w * 0.06:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_y() + bar.get_height() / 2,
                        str(int(w)), ha="center", va="center",
                        fontsize=7, color="white", fontweight="bold",
                    )
            lefts = [l + w for l, w in zip(lefts, widths)]

        # Total at right end
        for i, lbl in enumerate(sorted_labels):
            total = sum(label_map[lbl].values())
            ax.text(lefts[i] + 0.3, i, f" {total}", va="center", fontsize=8, color="#333")

        ax.set_yticks(ys)
        ax.set_yticklabels(sorted_labels, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Count", fontsize=10)
        ax.set_title("Fail Mode Distribution", fontsize=11, pad=10)
        ax.legend(fontsize=8, loc="lower right")
        ax.grid(axis="x", color="#EEEEEE", linewidth=0.8, zorder=0)
        for sp in ax.spines.values():
            sp.set_edgecolor("#DDDDDD")
        self.figure.tight_layout()
        self.canvas.draw()
