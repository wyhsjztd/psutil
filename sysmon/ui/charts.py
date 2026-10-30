"""基于 pyqtgraph 的实时曲线卡片。

x 轴使用「相对启动的秒数」，窗口固定为 60 秒。
采样间隔改变时窗口起点随之移动，旧间隔的数据不会混进新窗口。
缺失数据用 NaN 表示，曲线在该处自动断开。
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence

import pyqtgraph as pg
from PySide6.QtGui import QBrush, QColor, QGradient, QLinearGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import C
from .widgets import LegendDot

pg.setConfigOptions(antialias=True)




class _SecondsAxis(pg.AxisItem):
    """x 轴显示相对当前时刻的秒数，0s 位于最右端。"""

    def tickStrings(self, values, scale, spacing):
        # 窗口很窄时刻度可能小于 1 秒，整数格式会输出一串重复的 "-1s"
        fmt = "{:.0f}s" if spacing >= 1 else "{:.1f}s"
        out = []
        for v in values:
            if abs(v) < 1e-9:
                out.append("0s")
            else:
                out.append(fmt.format(v))
        return out


class _PercentAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [f"{v:.0f}%" for v in values]


class _BytesAxis(pg.AxisItem):
    """字节刻度。

    单位必须整轴统一：若逐刻度各自选单位，1000 会显示成 "1000B"、
    2000 显示成 "2.0K"，同一根轴上单位来回切换，很难读。
    """

    _UNITS = (("B", 1.0), ("K", 1024.0), ("M", 1024.0 ** 2), ("G", 1024.0 ** 3))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._divisor = 1.0
        self._unit = "B"

    def set_scale(self, ymax: float) -> None:
        ymax = max(ymax, 1.0)
        for unit, divisor in self._UNITS:
            if ymax < divisor * 1024.0 or unit == "G":
                self._divisor, self._unit = divisor, unit
                return

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            if v < 0:
                out.append("")
                continue
            scaled = v / self._divisor
            if scaled < 10:
                out.append(f"{scaled:.1f}{self._unit}")
            else:
                out.append(f"{scaled:.0f}{self._unit}")
        return out


class ChartCard(QFrame):
    """带标题与图例的曲线卡片。"""

    def __init__(
        self,
        title: str = "",
        window: float = 60.0,
        fixed_y: Optional[tuple] = None,
        y_unit: str = "value",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ChartCard")
        self.window = window
        self.fixed_y = fixed_y
        self.y_unit = y_unit

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(16)

        self._title = QLabel(title)
        self._title.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")
        head.addWidget(self._title)
        head.addStretch(1)

        root.addLayout(head)

        left_axis = self._make_y_axis(y_unit)
        self._y_axis = left_axis

        self.plot = pg.PlotWidget(axisItems={"bottom": _SecondsAxis("bottom"), "left": left_axis})
        # 与卡片同色，避免 QGraphicsView 默认白底
        self.plot.setBackground(C.CARD_BASE)
        self.plot.setStyleSheet("background: transparent;")
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setXRange(-window, 0, padding=0)

        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setStyle(tickLength=0)
            axis.setPen(pg.mkPen(C.BORDER))
            axis.setTextPen(pg.mkPen(C.TEXT_FAINT))
            axis.setLabel(None)

        self.plot.showGrid(x=False, y=True, alpha=0.08)
        root.addWidget(self.plot, 1)

        self._items: List[pg.PlotDataItem] = []
        self._legends: List[LegendDot] = []
        self._head = head

    # ------------------------------------------------------------- 构建曲线
    def add_series(self, color: str, label: str = "", fill: bool = True, fill_alpha: int = 60):
        pen = pg.mkPen(color, width=2)
        brush = self._make_brush(color, fill_alpha) if fill else None
        item = self.plot.plot(
            [],
            [],
            pen=pen,
            brush=brush,
            fillLevel=0,
            antialias=True,
        )
        self._items.append(item)

        if label:
            legend = LegendDot(color, label)
            self._head.addWidget(legend)
            self._legends.append(legend)
        return item

    def set_legend(self, index: int, text: str) -> None:
        if 0 <= index < len(self._legends):
            self._legends[index].set_value(text)

    # ------------------------------------------------------------- 刷新数据
    def set_view(
        self,
        x_start: float,
        x_end: float,
        series: Sequence[tuple],
    ) -> None:
        """series 为 [(xs, ys), ...]，与 add_series 的顺序一致。"""
        for item, (xs, ys) in zip(self._items, series):
            item.setData(xs, ys, connect="finite")

        self.plot.setXRange(x_start, x_end, padding=0)

        if self.fixed_y is not None:
            self.plot.setYRange(self.fixed_y[0], self.fixed_y[1], padding=0)
            return

        # 只按可见窗口内的点取量程：切换采样间隔后窗口可能只覆盖最近几秒，
        # 若把窗口外的历史点也算进来，Y 轴会被旧的高值顶住，新曲线被压成一条直线。
        values = []
        for xs, ys in series:
            for x, v in zip(xs, ys):
                if math.isnan(v):
                    continue
                if x_start <= x <= x_end:
                    values.append(v)
        ymax = max(values) if values else 0.0
        top = max(ymax * 1.25, 1.0)
        if isinstance(self._y_axis, _BytesAxis):
            self._y_axis.set_scale(top)
        self.plot.setYRange(0.0, top, padding=0)

    def clear(self) -> None:
        for item in self._items:
            item.setData([], [])
        for legend in self._legends:
            legend.set_value("--")

    # ------------------------------------------------------------- 内部
    @staticmethod
    def _make_y_axis(y_unit: str) -> pg.AxisItem:
        if y_unit == "percent":
            axis = _PercentAxis("left")
            axis.setRange(0, 100)
        elif y_unit == "bytes":
            axis = _BytesAxis("left")
        else:
            axis = pg.AxisItem("left")
            axis.setStyle(showValues=False)
        axis.setWidth(52)
        return axis

    @staticmethod
    def _make_brush(color: str, alpha: int) -> QBrush:
        grad = QLinearGradient(0, 0, 0, 1)
        grad.setCoordinateMode(QGradient.CoordinateMode.ObjectBoundingMode)
        top = QColor(color)
        top.setAlpha(alpha)
        bottom = QColor(color)
        bottom.setAlpha(0)
        grad.setColorAt(0.0, top)
        mid = QColor(color)
        mid.setAlpha(int(alpha * 0.3))
        grad.setColorAt(0.55, mid)
        grad.setColorAt(1.0, bottom)
        return QBrush(grad)


def build_series(
    snapshots: Sequence[object],
    getter,
    t0: float,
    nominal_dt: float,
) -> tuple:
    """把快照序列转成 (xs, ys)，缺失值用 NaN 断开。

    x 为相对 t0 的秒数；当相邻两点跨度超过 2.5 倍采样间隔时，
    中间插入 NaN，使暂停区间在图上显示为空白而不是一条直线。
    """
    xs: List[float] = []
    ys: List[float] = []
    prev_x: Optional[float] = None

    for snap in snapshots:
        x = snap.mono - t0
        if prev_x is not None and x - prev_x > nominal_dt * 2.5:
            xs.append((prev_x + x) / 2.0)
            ys.append(float("nan"))

        value = getter(snap)
        xs.append(x)
        ys.append(float("nan") if value is None else float(value))
        prev_x = x

    return xs, ys
