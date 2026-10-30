"""功能页面：进程 / CPU / 内存 / 磁盘 / 网络 / 磁盘 IO / 服务 / 用户。

每个页面只做渲染，不调用 psutil（进程页的“结束任务”除外），
也不持有自己的定时器。
"""
from __future__ import annotations

import datetime
from typing import List, Optional, Sequence

import psutil
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QScrollArea,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..engine import format_bytes, format_percent
from .charts import ChartCard, build_series
from .theme import C
from .widgets import PartitionRow, Stat, mono_font

SERVICE_STATUS = {
    "running": "正在运行",
    "stopped": "已停止",
    "start_pending": "正在启动",
    "stop_pending": "正在停止",
    "continue_pending": "正在继续",
    "pause_pending": "正在暂停",
    "paused": "已暂停",
    "unknown": "未知",
}

SERVICE_START_TYPE = {
    "automatic": "自动",
    "manual": "手动",
    "disabled": "已禁用",
    "boot": "系统引导",
    "system": "系统",
}


def format_uptime(seconds: float) -> str:
    if seconds <= 0:
        return "--"
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分"


class ProcessTableModel(QAbstractTableModel):
    """进程表模型。

    用模型/视图替代 QTableWidget：后者每 3 秒要销毁并新建上千个
    QTableWidgetItem，实测在 340+ 进程时单次重建可达数秒，直接把 UI 卡死。
    模型只持有一份数据元组，刷新时一次 reset，开销与进程数量线性且很低。
    """

    HEADERS = ("名称", "PID", "CPU", "内存")
    SORT_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows = ()

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def row_at(self, row: int):
        return self._rows[row]

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        proc = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return proc.name
            if col == 1:
                return str(proc.pid)
            if col == 2:
                return f"{proc.cpu:.1f}%"
            return f"{proc.mem_percent:.1f}%"

        if role == self.SORT_ROLE:
            # 数值列必须按数值排序，否则 "9.9%" 会排在 "10.0%" 之后
            if col == 0:
                return proc.name.lower()
            if col == 1:
                return proc.pid
            if col == 2:
                return proc.cpu
            return proc.mem_percent

        if role == Qt.TextAlignmentRole:
            align = Qt.AlignLeft if col == 0 else Qt.AlignRight
            return int(align | Qt.AlignVCenter)

        if role == Qt.ToolTipRole and col == 0:
            return proc.name

        # 空闲进程在多核机器上恒接近 100%，不应被当成高负载告警
        if (
            role == Qt.ForegroundRole
            and col == 2
            and proc.cpu >= 50
            and "idle" not in proc.name.lower()
        ):
            return QColor(C.WARN)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return self.HEADERS[section]
        if role == Qt.TextAlignmentRole:
            align = Qt.AlignLeft if section == 0 else Qt.AlignRight
            return int(align | Qt.AlignVCenter)
        return None


class ProcessFilterProxy(QSortFilterProxyModel):
    """按名称或 PID 过滤。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._needle = ""

    def set_needle(self, text: str) -> None:
        text = text.strip().lower()
        if text != self._needle:
            self._needle = text
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        if not self._needle:
            return True
        model = self.sourceModel()
        if model is None:
            return True
        proc = model.row_at(source_row)
        return self._needle in proc.name.lower() or self._needle in str(proc.pid)


# ---------------------------------------------------------------- 每核柱状图
class CoreBars(QWidget):
    """CPU 每核心利用率，自绘竖向小柱。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._values: List[float] = []
        self.setMinimumHeight(58)

    def set_values(self, values: Sequence[float]) -> None:
        self._values = list(values)
        self.update()

    @staticmethod
    def _color(value: float) -> QColor:
        """蓝 -> 橙 -> 红 平滑过渡。"""
        blue = (76, 194, 255)
        orange = (240, 163, 94)
        red = (239, 91, 91)
        t = max(0.0, min(1.0, (value - 45.0) / 55.0))
        if t < 0.5:
            a, b, k = blue, orange, t * 2
        else:
            a, b, k = orange, red, (t - 0.5) * 2
        return QColor(
            int(a[0] + (b[0] - a[0]) * k),
            int(a[1] + (b[1] - a[1]) * k),
            int(a[2] + (b[2] - a[2]) * k),
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._values:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        n = len(self._values)
        gap = 3.0
        bar_w = max(2.0, (self.width() - gap * (n - 1)) / n)
        h = self.height()
        radius = min(2.0, bar_w / 2)

        for i, value in enumerate(self._values):
            x = i * (bar_w + gap)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 16))
            painter.drawRoundedRect(int(x), 0, int(bar_w), h, radius, radius)

            fill_h = max(1.0, h * max(0.0, min(100.0, value)) / 100.0)
            painter.setBrush(self._color(value))
            painter.drawRoundedRect(
                int(x), int(h - fill_h), int(bar_w), int(fill_h), radius, radius
            )


# ---------------------------------------------------------------- 页面基类
class BasePage(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(26, 20, 26, 20)
        self._root.setSpacing(12)

        self._title = QLabel(title)
        self._title.setProperty("role", "pageTitle")

        self._subtitle = QLabel(subtitle)
        self._subtitle.setProperty("role", "subtitle")

        self._root.addWidget(self._title)
        self._root.addWidget(self._subtitle)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)

    def update_data(
        self,
        snap: object,
        snaps: Sequence[object],
        t0: float,
        nominal_dt: float,
        x_start: float,
        x_end: float,
    ) -> None:
        raise NotImplementedError


def _big_value(size: int = 44) -> QLabel:
    label = QLabel("--")
    label.setStyleSheet(f"font-size:{size}px;font-weight:600;color:{C.TEXT};")
    return label


def _make_table(columns: Sequence[str], stretch_col: int = 0) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setFocusPolicy(Qt.NoFocus)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(32)
    table.setSortingEnabled(True)

    header = table.horizontalHeader()
    header.setSectionResizeMode(stretch_col, QHeaderView.Stretch)
    for col in range(len(columns)):
        if col != stretch_col:
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        # 表头与单元格对齐保持一致：文本列靠左，数值列靠右
        item = table.horizontalHeaderItem(col)
        if item is not None:
            item.setTextAlignment(
                (Qt.AlignLeft if col == stretch_col else Qt.AlignRight) | Qt.AlignVCenter
            )
    return table


# ---------------------------------------------------------------- 进程
class ProcessPage(BasePage):
    COLUMNS = ("名称", "PID", "CPU", "内存")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("进程", "系统当前运行的所有进程（每 3 秒刷新）", parent)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索进程名称或 PID")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(260)

        self._count = QLabel("--")
        self._count.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")

        toolbar.addWidget(self._search)
        toolbar.addStretch(1)
        toolbar.addWidget(self._count)
        self._root.addLayout(toolbar)

        self._model = ProcessTableModel(self)
        self._proxy = ProcessFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(ProcessTableModel.SORT_ROLE)
        self._search.textChanged.connect(self._proxy.set_needle)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(2, Qt.DescendingOrder)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(32)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(self.COLUMNS)):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents
            )
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_menu)
        self._root.addWidget(self._table, 1)

        self._last = None

    def update_data(self, snap, snaps, t0, nominal_dt, x_start, x_end) -> None:
        if snap.processes == self._last:
            return
        self._last = snap.processes
        self._model.set_rows(snap.processes)
        self._count.setText(f"{len(snap.processes)} 个进程")

    def _show_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        proc = self._model.row_at(self._proxy.mapToSource(index).row())

        menu = QMenu(self)
        action = menu.addAction(f"结束任务：{proc.name} (PID {proc.pid})")
        action.triggered.connect(lambda: self._kill(proc.pid, proc.name))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _kill(self, pid: int, name: str) -> None:
        ret = QMessageBox.question(
            self,
            "结束任务",
            f"确定要结束「{name}」(PID {pid}) 吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        try:
            psutil.Process(pid).terminate()
        except psutil.NoSuchProcess:
            QMessageBox.information(self, "结束任务", "该进程已经结束。")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "结束任务", "权限不足，请以管理员身份运行。")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "结束任务", f"操作失败：{exc}")


# ---------------------------------------------------------------- CPU
class CpuPage(BasePage):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("CPU", "正在读取处理器信息…", parent)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)

        self._big = _big_value()
        caption = QLabel("利用率")
        caption.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")
        self._freq = QLabel("-- GHz")
        self._freq.setStyleSheet(f"color:{C.TEXT_DIM};font-size:13px;")
        self._freq.setFont(mono_font(10))

        left.addWidget(self._big)
        left.addWidget(caption)
        left.addSpacing(8)
        left.addWidget(self._freq)
        left.addStretch(1)

        self._chart = ChartCard("总利用率", fixed_y=(0, 100), y_unit="percent")
        self._chart.add_series(C.CPU, "总利用率", fill_alpha=70)

        body.addLayout(left, 0)
        body.addWidget(self._chart, 1)
        self._root.addLayout(body, 1)

        core_card = QFrame()
        core_card.setObjectName("Card")
        core_layout = QVBoxLayout(core_card)
        core_layout.setContentsMargins(16, 10, 16, 12)
        core_layout.setSpacing(6)

        core_head = QHBoxLayout()
        core_title = QLabel("各逻辑处理器")
        core_title.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")
        self._core_hint = QLabel("--")
        self._core_hint.setStyleSheet(f"color:{C.TEXT_FAINT};font-size:11px;")
        core_head.addWidget(core_title)
        core_head.addStretch(1)
        core_head.addWidget(self._core_hint)

        self._cores = CoreBars()
        core_layout.addLayout(core_head)
        core_layout.addWidget(self._cores)
        self._root.addWidget(core_card)

        stats = QHBoxLayout()
        stats.setSpacing(36)
        self._stat_proc = Stat("进程数")
        self._stat_cores = Stat("核心 / 逻辑处理器")
        self._stat_uptime = Stat("正常运行时间")
        for s in (self._stat_proc, self._stat_cores, self._stat_uptime):
            stats.addWidget(s)
        stats.addStretch(1)
        self._root.addLayout(stats)

        self._info_set = False

    def update_data(self, snap, snaps, t0, nominal_dt, x_start, x_end) -> None:
        self._big.setText(f"{snap.cpu_percent:.0f}%")

        if snap.cpu_percent >= 90:
            color = C.DANGER
        elif snap.cpu_percent >= 80:
            color = C.WARN
        else:
            color = C.TEXT
        self._big.setStyleSheet(f"font-size:44px;font-weight:600;color:{color};")

        if snap.cpu_freq > 0:
            self._freq.setText(f"{snap.cpu_freq / 1000:.2f} GHz")

        if not self._info_set and snap.cpu_cores:
            self.set_subtitle(
                f"{snap.cpu_cores} 核 {snap.cpu_threads} 逻辑处理器"
                + (f" · {snap.cpu_freq / 1000:.2f} GHz" if snap.cpu_freq > 0 else "")
            )
            self._info_set = True

        self._stat_proc.set_value(str(snap.proc_count))
        self._stat_cores.set_value(f"{snap.cpu_cores} / {snap.cpu_threads}")
        self._stat_uptime.set_value(format_uptime(snap.uptime))

        self._cores.set_values(snap.cpu_per_core)
        self._core_hint.setText(f"共 {len(snap.cpu_per_core)} 个")

        xs, ys = build_series(snaps, lambda s: s.cpu_percent, t0, nominal_dt)
        self._chart.set_view(x_start, x_end, [(xs, ys)])
        self._chart.set_legend(0, f"{snap.cpu_percent:.0f}%")


# ---------------------------------------------------------------- 内存
class MemoryPage(BasePage):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("内存", "物理内存使用情况", parent)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)

        self._big = _big_value()
        caption = QLabel("利用率")
        caption.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")
        self._detail = QLabel("--")
        self._detail.setStyleSheet(f"color:{C.TEXT_DIM};font-size:13px;")
        self._detail.setFont(mono_font(10))

        left.addWidget(self._big)
        left.addWidget(caption)
        left.addSpacing(8)
        left.addWidget(self._detail)
        left.addStretch(1)

        self._chart = ChartCard("内存占用率", fixed_y=(0, 100), y_unit="percent")
        self._chart.add_series(C.MEM, "内存占用率", fill_alpha=70)

        body.addLayout(left, 0)
        body.addWidget(self._chart, 1)
        self._root.addLayout(body, 1)

        stats = QHBoxLayout()
        stats.setSpacing(36)
        self._stat_used = Stat("已用")
        self._stat_avail = Stat("可用")
        self._stat_total = Stat("总计")
        self._stat_swap = Stat("交换 / 分页文件")
        for s in (self._stat_used, self._stat_avail, self._stat_total, self._stat_swap):
            stats.addWidget(s)
        stats.addStretch(1)
        self._root.addLayout(stats)

    def update_data(self, snap, snaps, t0, nominal_dt, x_start, x_end) -> None:
        self._big.setText(f"{snap.mem_percent:.0f}%")
        color = C.WARN if snap.mem_percent >= 85 else C.TEXT
        self._big.setStyleSheet(f"font-size:44px;font-weight:600;color:{color};")

        used = format_bytes(snap.mem_used, suffix="")
        total = format_bytes(snap.mem_total, suffix="")
        self._detail.setText(f"{used} / {total}")

        self._stat_used.set_value(used)
        self._stat_avail.set_value(format_bytes(snap.mem_available, suffix=""))
        self._stat_total.set_value(total)
        if snap.swap_total:
            self._stat_swap.set_value(
                f"{format_bytes(snap.swap_used, suffix='')} / "
                f"{format_bytes(snap.swap_total, suffix='')} ({snap.swap_percent:.0f}%)"
            )

        xs, ys = build_series(snaps, lambda s: s.mem_percent, t0, nominal_dt)
        self._chart.set_view(x_start, x_end, [(xs, ys)])
        self._chart.set_legend(0, f"{snap.mem_percent:.0f}%")


# ---------------------------------------------------------------- 磁盘
class DiskPage(BasePage):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("磁盘", "各分区容量使用率 · 下方为磁盘活动时间与吞吐", parent)

        card = QFrame()
        card.setObjectName("ChartCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 14, 18, 14)
        card_layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("分区容量使用率（与任务管理器的「磁盘占用」含义不同）")
        title.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")
        header.addWidget(title)
        header.addStretch(1)
        card_layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 8, 0)
        self._container_layout.setSpacing(2)
        self._container_layout.addStretch(1)
        self._scroll.setWidget(self._container)
        card_layout.addWidget(self._scroll, 1)

        self._root.addWidget(card, 3)

        self._chart = ChartCard("吞吐量", y_unit="bytes")
        self._chart.add_series(C.IO_READ, "读取", fill_alpha=55)
        self._chart.add_series(C.IO_WRITE, "写入", fill_alpha=35)
        self._root.addWidget(self._chart, 2)

        stats = QHBoxLayout()
        stats.setSpacing(36)
        self._stat_busy = Stat("活动时间")
        self._stat_read = Stat("当前读取")
        self._stat_write = Stat("当前写入")
        self._stat_count = Stat("分区数量")
        for s in (self._stat_busy, self._stat_read, self._stat_write, self._stat_count):
            stats.addWidget(s)
        stats.addStretch(1)
        self._root.addLayout(stats)

        self._rows: List[PartitionRow] = []

    def _rebuild_rows(self, count: int) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []

        for _ in range(count):
            row = PartitionRow()
            self._container_layout.addWidget(row)
            self._rows.append(row)
        self._container_layout.addStretch(1)

    def update_data(self, snap, snaps, t0, nominal_dt, x_start, x_end) -> None:
        parts = snap.partitions
        if len(parts) != len(self._rows):
            self._rebuild_rows(len(parts))

        for row, part in zip(self._rows, parts):
            row.set_data(
                part.mount,
                part.percent,
                format_bytes(part.used, suffix=""),
                format_bytes(part.total, suffix=""),
            )

        self._stat_busy.set_value(format_percent(snap.disk_busy_percent))
        self._stat_read.set_value(format_bytes(snap.disk_read_rate))
        self._stat_write.set_value(format_bytes(snap.disk_write_rate))
        self._stat_count.set_value(str(len(parts)))

        rd = build_series(snaps, lambda s: s.disk_read_rate, t0, nominal_dt)
        wr = build_series(snaps, lambda s: s.disk_write_rate, t0, nominal_dt)
        self._chart.set_view(x_start, x_end, [rd, wr])
        self._chart.set_legend(0, format_bytes(snap.disk_read_rate))
        self._chart.set_legend(1, format_bytes(snap.disk_write_rate))


# ---------------------------------------------------------------- 网络
class NetworkPage(BasePage):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("网络", "所有网卡汇总（包含回环与虚拟网卡）", parent)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)

        self._down = _big_value(30)
        down_caption = QLabel("接收速率")
        down_caption.setStyleSheet(f"color:{C.NET_DOWN};font-size:12px;")
        self._up = _big_value(30)
        up_caption = QLabel("发送速率")
        up_caption.setStyleSheet(f"color:{C.NET_UP};font-size:12px;")

        left.addWidget(down_caption)
        left.addWidget(self._down)
        left.addSpacing(14)
        left.addWidget(up_caption)
        left.addWidget(self._up)
        left.addStretch(1)

        self._chart = ChartCard("网络吞吐", y_unit="bytes")
        self._chart.add_series(C.NET_DOWN, "接收", fill_alpha=55)
        self._chart.add_series(C.NET_UP, "发送", fill_alpha=35)

        body.addLayout(left, 0)
        body.addWidget(self._chart, 1)
        self._root.addLayout(body, 1)

        stats = QHBoxLayout()
        stats.setSpacing(36)
        self._stat_recv = Stat("累计接收")
        self._stat_sent = Stat("累计发送")
        self._stat_conn = Stat("TCP 连接数")
        for s in (self._stat_recv, self._stat_sent, self._stat_conn):
            stats.addWidget(s)
        stats.addStretch(1)
        self._root.addLayout(stats)

    def update_data(self, snap, snaps, t0, nominal_dt, x_start, x_end) -> None:
        self._down.setText(format_bytes(snap.net_down_rate))
        self._up.setText(format_bytes(snap.net_up_rate))

        self._stat_recv.set_value(format_bytes(snap.net_recv, suffix=""))
        self._stat_sent.set_value(format_bytes(snap.net_sent, suffix=""))
        self._stat_conn.set_value(
            "--" if snap.net_connections is None else str(snap.net_connections)
        )

        down = build_series(snaps, lambda s: s.net_down_rate, t0, nominal_dt)
        up = build_series(snaps, lambda s: s.net_up_rate, t0, nominal_dt)
        self._chart.set_view(x_start, x_end, [down, up])
        self._chart.set_legend(0, format_bytes(snap.net_down_rate))
        self._chart.set_legend(1, format_bytes(snap.net_up_rate))


# ---------------------------------------------------------------- 磁盘 IO
class DiskIoPage(BasePage):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("磁盘 I/O", "所有物理磁盘读写吞吐汇总", parent)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)

        self._read = _big_value(30)
        read_caption = QLabel("读取速率")
        read_caption.setStyleSheet(f"color:{C.IO_READ};font-size:12px;")
        self._write = _big_value(30)
        write_caption = QLabel("写入速率")
        write_caption.setStyleSheet(f"color:{C.IO_WRITE};font-size:12px;")

        left.addWidget(read_caption)
        left.addWidget(self._read)
        left.addSpacing(14)
        left.addWidget(write_caption)
        left.addWidget(self._write)
        left.addStretch(1)

        self._chart = ChartCard("磁盘吞吐", y_unit="bytes")
        self._chart.add_series(C.IO_READ, "读取", fill_alpha=55)
        self._chart.add_series(C.IO_WRITE, "写入", fill_alpha=35)

        body.addLayout(left, 0)
        body.addWidget(self._chart, 1)
        self._root.addLayout(body, 1)

        stats = QHBoxLayout()
        stats.setSpacing(36)
        self._stat_read = Stat("累计读取")
        self._stat_write = Stat("累计写入")
        stats.addWidget(self._stat_read)
        stats.addWidget(self._stat_write)
        stats.addStretch(1)
        self._root.addLayout(stats)

    def update_data(self, snap, snaps, t0, nominal_dt, x_start, x_end) -> None:
        self._read.setText(format_bytes(snap.disk_read_rate))
        self._write.setText(format_bytes(snap.disk_write_rate))

        self._stat_read.set_value(format_bytes(snap.disk_read_total, suffix=""))
        self._stat_write.set_value(format_bytes(snap.disk_write_total, suffix=""))

        rd = build_series(snaps, lambda s: s.disk_read_rate, t0, nominal_dt)
        wr = build_series(snaps, lambda s: s.disk_write_rate, t0, nominal_dt)
        self._chart.set_view(x_start, x_end, [rd, wr])
        self._chart.set_legend(0, format_bytes(snap.disk_read_rate))
        self._chart.set_legend(1, format_bytes(snap.disk_write_rate))


# ---------------------------------------------------------------- 服务
class ServicesPage(BasePage):
    COLUMNS = ("名称", "显示名称", "状态", "启动类型")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("服务", "本机 Windows 服务（每 30 秒刷新）", parent)

        toolbar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索服务")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(260)
        self._search.textChanged.connect(self._apply_filter)

        self._count = QLabel("正在读取…")
        self._count.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")

        toolbar.addWidget(self._search)
        toolbar.addStretch(1)
        toolbar.addWidget(self._count)
        self._root.addLayout(toolbar)

        self._table = _make_table(self.COLUMNS, stretch_col=1)
        self._root.addWidget(self._table, 1)

        self._last = None

    def update_data(self, snap, snaps, t0, nominal_dt, x_start, x_end) -> None:
        pass

    def set_services(self, services: Sequence) -> None:
        if services == self._last:
            return
        self._last = services

        table = self._table
        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        table.setRowCount(len(services))
        for row, svc in enumerate(services):
            values = (
                svc.name,
                svc.display_name,
                SERVICE_STATUS.get(svc.status, svc.status),
                SERVICE_START_TYPE.get(svc.start_type, svc.start_type),
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 2 and svc.status == "running":
                    item.setForeground(QColor(C.NET_UP))
                table.setItem(row, col, item)
        table.setUpdatesEnabled(True)
        table.setSortingEnabled(True)
        self._count.setText(f"{len(services)} 个服务")
        self._apply_filter()

    def _apply_filter(self) -> None:
        text = self._search.text().strip().lower()
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 0)
            display_item = self._table.item(row, 1)
            name = name_item.text().lower() if name_item else ""
            display = display_item.text().lower() if display_item else ""
            visible = not text or text in name or text in display
            self._table.setRowHidden(row, not visible)


# ---------------------------------------------------------------- 用户
class UsersPage(BasePage):
    COLUMNS = ("用户", "主机", "会话", "登录时间")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("用户", "当前登录到本机的用户", parent)

        self._table = _make_table(self.COLUMNS, stretch_col=0)
        self._root.addWidget(self._table, 1)

        self._last = None

    def update_data(self, snap, snaps, t0, nominal_dt, x_start, x_end) -> None:
        if snap.users == self._last:
            return
        self._last = snap.users

        table = self._table
        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        table.setRowCount(len(snap.users))
        for row, user in enumerate(snap.users):
            try:
                started = datetime.datetime.fromtimestamp(user.started).strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, ValueError, OverflowError):
                started = "--"
            values = (user.name, user.host or "--", user.terminal or "--", started)
            for col, text in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(text))
        table.setUpdatesEnabled(True)
        table.setSortingEnabled(True)
