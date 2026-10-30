"""通用小控件：迷你曲线、导航卡片、统计项、分区行。"""
from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import C


def mono_font(size: int = 10) -> QFont:
    """等宽字体，避免数值变化时宽度跳动。"""
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    f.setPointSize(size)
    return f


class Sparkline(QWidget):
    """导航卡片里的迷你曲线，自绘，开销极低。"""

    def __init__(
        self,
        color: str,
        y_max: Optional[float] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._values: List[float] = []
        # 百分比类指标固定 0–100，否则 3% 会被自动缩放画成满格，视觉上误导
        self._y_max = y_max
        self.setMinimumHeight(38)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_values(self, values: Sequence[Optional[float]]) -> None:
        self._values = [float(v) for v in values if v is not None]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if len(self._values) < 2:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        pad = 2.0

        if self._y_max is not None:
            vmin, vmax = 0.0, self._y_max
            span = vmax - vmin
        else:
            vmax = max(self._values)
            vmin = min(self._values)
            span = vmax - vmin
            if span < 1e-9:
                span = 1.0
                vmin = vmax - 0.5

        n = len(self._values)
        points = []
        for i, value in enumerate(self._values):
            x = pad + (w - 2 * pad) * i / (n - 1)
            y = h - pad - (h - 2 * pad) * (value - vmin) / span
            points.append(QPointF(x, y))

        path = QPainterPath()
        path.moveTo(points[0])
        for pt in points[1:]:
            path.lineTo(pt)

        fill = QPainterPath(path)
        fill.lineTo(points[-1].x(), h)
        fill.lineTo(points[0].x(), h)
        fill.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        top = QColor(self._color)
        top.setAlpha(70)
        bottom = QColor(self._color)
        bottom.setAlpha(0)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        painter.fillPath(fill, QBrush(grad))

        pen = QPen(self._color, 1.5)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


class NavCard(QFrame):
    """左侧导航卡片：标题 + 当前值 + 迷你曲线。"""

    clicked = Signal(str)

    def __init__(
        self,
        key: str,
        title: str,
        color: str,
        y_max: Optional[float] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("NavCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(96)
        self.setProperty("selected", False)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 8, 12, 8)
        root.setSpacing(0)

        self._bar = QFrame()
        self._bar.setObjectName("NavBar")
        self._bar.setFixedWidth(3)
        self._bar.setProperty("active", False)
        root.addWidget(self._bar)
        root.addSpacing(12)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel(title)
        self._title.setStyleSheet(f"color:{C.TEXT};font-size:13px;font-weight:500;")
        self._value = QLabel("--")
        self._value.setFont(mono_font(10))
        self._value.setStyleSheet(f"color:{C.TEXT_DIM};")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._value)

        self._spark = Sparkline(color, y_max=y_max)
        body.addLayout(head)
        body.addWidget(self._spark, 1)
        root.addLayout(body, 1)

    # ---------------------------------------------------------------- 状态
    def set_value(self, text: str) -> None:
        self._value.setText(text)

    def set_values(self, values: Sequence[Optional[float]]) -> None:
        self._spark.set_values(values)

    def set_selected(self, selected: bool) -> None:
        for widget, prop in ((self, "selected"), (self._bar, "active")):
            widget.setProperty(prop, selected)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class CompactNavItem(QFrame):
    """无缩略图的紧凑导航项，用于服务、用户等非性能页面。"""

    clicked = Signal(str)

    def __init__(self, key: str, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("NavCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(46)
        self.setProperty("selected", False)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 12, 0)
        root.setSpacing(0)

        self._bar = QFrame()
        self._bar.setObjectName("NavBar")
        self._bar.setFixedWidth(3)
        self._bar.setProperty("active", False)
        root.addWidget(self._bar)
        root.addSpacing(12)

        self._title = QLabel(title)
        self._title.setStyleSheet(f"color:{C.TEXT};font-size:13px;")
        self._value = QLabel("--")
        self._value.setFont(mono_font(9))
        self._value.setStyleSheet(f"color:{C.TEXT_DIM};")

        root.addWidget(self._title)
        root.addStretch(1)
        root.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)

    def set_selected(self, selected: bool) -> None:
        for widget, prop in ((self, "selected"), (self._bar, "active")):
            widget.setProperty(prop, selected)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class Stat(QWidget):
    """一组「小标签 + 数值」，用于页面底部的统计信息。"""

    def __init__(self, label: str, value: str = "--", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._label = QLabel(label)
        self._label.setProperty("role", "statLabel")
        self._value = QLabel(value)
        self._value.setProperty("role", "statValue")
        self._value.setFont(mono_font(10))

        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set_value(self, text: str, color: Optional[str] = None) -> None:
        self._value.setText(text)
        if color:
            self._value.setStyleSheet(f"color:{color};")


class PartitionRow(QWidget):
    """磁盘页的分区行：盘符 + 进度条 + 百分比 + 容量明细。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)

        self._mount = QLabel("--")
        self._mount.setStyleSheet(f"color:{C.TEXT};font-size:13px;font-weight:500;")
        self._mount.setFixedWidth(56)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)

        self._percent = QLabel("--")
        self._percent.setFont(mono_font(10))
        self._percent.setStyleSheet(f"color:{C.TEXT_DIM};")
        self._percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._percent.setFixedWidth(52)

        top.addWidget(self._mount)
        top.addWidget(self._bar, 1)
        top.addWidget(self._percent)

        self._detail = QLabel("")
        self._detail.setStyleSheet(f"color:{C.TEXT_FAINT};font-size:11px;")

        layout.addLayout(top)
        layout.addWidget(self._detail)

        # 缓存上一帧状态：每帧重复 setStyleSheet 会触发控件子树重新计算样式
        self._last_color: Optional[str] = None
        self._last_value: Optional[int] = None

    def set_data(self, mount: str, percent: float, used_text: str, total_text: str) -> None:
        self._mount.setText(mount)
        self._detail.setText(f"{used_text} / {total_text}")

        value = int(round(percent))
        if value != self._last_value:
            self._bar.setValue(value)
            self._percent.setText(f"{percent:.0f}%")
            self._last_value = value

        if percent >= 90:
            color = C.DANGER
        elif percent >= 75:
            color = C.WARN
        else:
            color = C.ACCENT
        if color != self._last_color:
            self._bar.setStyleSheet(
                f"QProgressBar{{background:#3a3a3a;border:none;border-radius:3px;}}"
                f"QProgressBar::chunk{{background:{color};border-radius:3px;}}"
            )
            self._last_color = color


class LegendDot(QWidget):
    """图例：小圆点 + 名称 + 当前值。"""

    def __init__(self, color: str, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background:{color};border-radius:4px;")

        self._label = QLabel(label)
        self._label.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")

        self._value = QLabel("--")
        self._value.setFont(mono_font(9))
        self._value.setStyleSheet(f"color:{C.TEXT};font-size:12px;")

        layout.addWidget(dot)
        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)
