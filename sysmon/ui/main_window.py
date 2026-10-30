"""主窗口：顶部工具栏 + 左侧导航 + 右侧页面栈 + 状态栏。"""
from __future__ import annotations

import csv
import datetime
from typing import Dict, List, Optional

import platform
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRect,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..collector import Collector
from ..engine import HysteresisAlarm, History, format_bytes, format_percent
from ..services import ServiceWorker
from ..worker import ProcessWorker, SampleWorker
from .pages import (
    CpuPage,
    DiskIoPage,
    DiskPage,
    MemoryPage,
    NetworkPage,
    ProcessPage,
    ServicesPage,
    UsersPage,
)
from .theme import C, QSS
from .widgets import CompactNavItem, NavCard

WINDOW_SECONDS = 60.0
INTERVAL_OPTIONS = (1.0, 2.0, 5.0)
INTERVAL_LABELS = ("1 秒", "2 秒", "5 秒")

NAV_ORDER = ("proc", "cpu", "mem", "disk", "net", "io", "services", "users")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("系统监视器")
        self.resize(1200, 780)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(QSS)

        self._graph_start: Optional[float] = None
        self._nominal_dt = 1.0
        self._paused = False

        self._history = History(3600)
        self._alarm = HysteresisAlarm(80.0, 75.0, 300.0)
        self._last_snap = None
        self._last_snaps: List[object] = []
        self._services_cache = None

        self._cards: Dict[str, object] = {}
        self._pages: Dict[str, object] = {}
        self._current_key = "proc"

        self._build_ui()
        self._start_workers()

    # ------------------------------------------------------------------ 构建
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_nav())
        body.addWidget(self._build_stack(), 1)
        root.addLayout(body, 1)

        self.statusBar().showMessage("正在采集…")

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(56)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(10)

        logo = QLabel()
        logo.setFixedSize(10, 10)
        logo.setStyleSheet(f"background:{C.ACCENT};border-radius:5px;")

        title = QLabel("系统监视器")
        title.setStyleSheet(f"color:{C.TEXT};font-size:14px;font-weight:600;")

        host = QLabel(platform.node() or "")
        host.setStyleSheet(f"color:{C.TEXT_FAINT};font-size:11px;")

        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addSpacing(4)
        layout.addWidget(host)
        layout.addStretch(1)

        interval_label = QLabel("采样间隔")
        interval_label.setStyleSheet(f"color:{C.TEXT_DIM};font-size:12px;")

        self._interval_combo = QComboBox()
        self._interval_combo.addItems(list(INTERVAL_LABELS))
        self._interval_combo.currentIndexChanged.connect(self._on_interval_changed)

        self._pause_btn = QPushButton("暂停")
        self._pause_btn.clicked.connect(self._toggle_pause)

        self._export_btn = QPushButton("导出 CSV")
        self._export_btn.clicked.connect(self._export_csv)

        layout.addWidget(interval_label)
        layout.addWidget(self._interval_combo)
        layout.addWidget(self._pause_btn)
        layout.addWidget(self._export_btn)
        return bar

    def _build_nav(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFixedWidth(252)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")

        container = QWidget()
        container.setObjectName("NavPanel")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        self._nav_container = container

        specs = (
            ("proc", "进程", C.CPU, None),
            ("cpu", "CPU", C.CPU, 100.0),
            ("mem", "内存", C.MEM, 100.0),
            ("disk", "磁盘", C.DISK, 100.0),
            ("net", "网络", C.NET_DOWN, None),
            ("io", "磁盘 I/O", C.IO_WRITE, None),
        )
        for key, label, color, y_max in specs:
            card = NavCard(key, label, color, y_max=y_max)
            card.setToolTip(f"查看{label}详情")
            card.clicked.connect(self._select)
            layout.addWidget(card)
            self._cards[key] = card

        layout.addSpacing(6)
        for key, label in (("services", "服务"), ("users", "用户")):
            item = CompactNavItem(key, label)
            item.setToolTip(f"查看{label}详情")
            item.clicked.connect(self._select)
            layout.addWidget(item)
            self._cards[key] = item

        layout.addStretch(1)

        # 共享的选中指示条：切页时在卡片之间滑动，给用户空间上的连续性
        self._nav_indicator = QFrame(container)
        self._nav_indicator.setFixedWidth(3)
        self._nav_indicator.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._nav_indicator.setStyleSheet(
            f"background:{C.ACCENT};border-radius:1px;"
        )
        self._nav_indicator.hide()
        self._nav_indicator_anim = QPropertyAnimation(
            self._nav_indicator, b"geometry", self
        )
        self._nav_indicator_anim.setDuration(180)
        self._nav_indicator_anim.setEasingCurve(QEasingCurve.OutCubic)

        scroll.setWidget(container)
        return scroll

    def _move_indicator(self, key: str, animate: bool = True) -> None:
        card = self._cards.get(key)
        if card is None:
            return
        geo = card.geometry()
        if geo.height() <= 0:
            # 首次布局尚未完成，等事件循环空闲后再定位
            QTimer.singleShot(0, lambda: self._move_indicator(key, animate=False))
            return

        target = QRect(4, geo.y() + 10, 3, max(20, geo.height() - 20))
        self._nav_indicator.show()
        self._nav_indicator.raise_()

        if animate and self._nav_indicator.geometry().height() > 0:
            self._nav_indicator_anim.stop()
            self._nav_indicator_anim.setStartValue(self._nav_indicator.geometry())
            self._nav_indicator_anim.setEndValue(target)
            self._nav_indicator_anim.start()
        else:
            self._nav_indicator.setGeometry(target)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_nav_indicator"):
            self._move_indicator(self._current_key, animate=False)

    def _build_stack(self) -> QWidget:
        self._stack = QStackedWidget()

        self._pages = {
            "proc": ProcessPage(),
            "cpu": CpuPage(),
            "mem": MemoryPage(),
            "disk": DiskPage(),
            "net": NetworkPage(),
            "io": DiskIoPage(),
            "services": ServicesPage(),
            "users": UsersPage(),
        }
        for key in NAV_ORDER:
            self._stack.addWidget(self._pages[key])

        self._select("proc")
        return self._stack

    # ------------------------------------------------------------------ 线程
    def _start_workers(self) -> None:
        self._collector = Collector(self._nominal_dt)

        self._worker = SampleWorker(self._collector, self._nominal_dt, self)
        self._worker.sampled.connect(self._on_snapshot)
        self._worker.start()

        self._process_worker = ProcessWorker(self._collector, 3.0, self)
        self._process_worker.start()

        self._service_worker = ServiceWorker(30.0, self)
        self._service_worker.services_ready.connect(self._on_services)
        self._service_worker.start()

    # ------------------------------------------------------------------ 交互
    def _select(self, key: str) -> None:
        self._current_key = key
        for card_key, card in self._cards.items():
            card.set_selected(card_key == key)
        self._move_indicator(key)
        self._stack.setCurrentWidget(self._pages[key])

        # 进程遍历在 Windows 上约 1 秒 CPU，只在需要看进程列表时保持高频
        if hasattr(self, "_process_worker"):
            self._process_worker.set_interval(3.0 if key == "proc" else 30.0)

        if key == "services" and self._services_cache is not None:
            self._pages["services"].set_services(self._services_cache)

        self._refresh_current()

    def _x_range(self, snap) -> tuple:
        """x 轴坐标相对当前时刻，0s 在最右端，左侧为负。

        这样切换采样间隔后窗口语义不变，轴标签也始终是「-60s … 0s」。
        """
        age = max(0.0, snap.mono - (self._graph_start or snap.mono))
        return -max(1.0, min(WINDOW_SECONDS, age)), 0.0

    def _refresh_current(self) -> None:
        if self._last_snap is None:
            return
        snap = self._last_snap
        x_start, x_end = self._x_range(snap)
        self._pages[self._current_key].update_data(
            snap, self._last_snaps, snap.mono, self._nominal_dt, x_start, x_end
        )

    def _on_interval_changed(self, index: int) -> None:
        value = INTERVAL_OPTIONS[index]
        if value == self._nominal_dt:
            return
        self._nominal_dt = value
        self._worker.set_interval(value)
        # 不重置图表窗口：x 轴是真实时间，新旧密度的点落在各自的时间位置上，
        # 语义仍然正确。若在此清空窗口，切换后会只剩 0~1 个点，曲线直接消失。
        # 速率正确性由 SampleWorker 侧的基线重置保证。

    def _toggle_pause(self) -> None:
        if self._paused:
            self._worker.resume()
            self._paused = False
            self._pause_btn.setText("暂停")
        else:
            self._worker.pause()
            self._paused = True
            self._pause_btn.setText("继续")

    # ------------------------------------------------------------------ 数据
    def _on_snapshot(self, snap) -> None:
        if self._graph_start is None:
            self._graph_start = snap.mono

        self._history.append(snap)
        self._last_snap = snap

        x_start, x_end = self._x_range(snap)

        snaps = self._history.window(snap.mono, WINDOW_SECONDS)
        self._last_snaps = snaps

        self._update_nav(snap, snaps)
        self._pages[self._current_key].update_data(
            snap, snaps, snap.mono, self._nominal_dt, x_start, x_end
        )
        if self._alarm.update(snap.cpu_percent, snap.wall):
            self.statusBar().showMessage(
                f"CPU 占用率过高：{snap.cpu_percent:.0f}%（阈值 80%）", 8000
            )
        self._update_status(snap)

    def _on_services(self, services) -> None:
        # 服务表有 300+ 行，重建一次在 UI 线程上有可感知的耗时。
        # 不在服务页时只缓存，等用户切过去再渲染。
        self._services_cache = services
        self._cards["services"].set_value(f"{len(services)} 个")
        if self._current_key == "services":
            self._pages["services"].set_services(services)

    def _update_nav(self, snap, snaps) -> None:
        cards = self._cards

        cards["proc"].set_value(str(snap.proc_count))
        cards["proc"].set_values([s.proc_count for s in snaps])

        cards["cpu"].set_value(f"{snap.cpu_percent:.0f}%")
        cards["cpu"].set_values([s.cpu_percent for s in snaps])

        cards["mem"].set_value(f"{snap.mem_percent:.0f}%")
        cards["mem"].set_values([s.mem_percent for s in snaps])

        # 磁盘卡片对应任务管理器的「磁盘」：显示活动时间占比，而不是容量使用率。
        # 容量使用率是另一个指标，放在磁盘页的分区列表里。
        cards["disk"].set_value(format_percent(snap.disk_busy_percent))
        cards["disk"].set_values([s.disk_busy_percent for s in snaps])

        cards["net"].set_value(format_bytes(snap.net_down_rate))
        cards["net"].set_values(
            [
                None
                if s.net_down_rate is None
                else (s.net_down_rate or 0) + (s.net_up_rate or 0)
                for s in snaps
            ]
        )

        io_total = None
        if snap.disk_read_rate is not None or snap.disk_write_rate is not None:
            io_total = (snap.disk_read_rate or 0) + (snap.disk_write_rate or 0)
        cards["io"].set_value(format_bytes(io_total))
        cards["io"].set_values(
            [
                None
                if s.disk_read_rate is None
                else (s.disk_read_rate or 0) + (s.disk_write_rate or 0)
                for s in snaps
            ]
        )

        cards["users"].set_value(f"{len(snap.users)} 个")

    def _update_status(self, snap) -> None:
        parts = [
            f"最近采样 {datetime.datetime.fromtimestamp(snap.wall):%H:%M:%S}",
            f"数据点 {len(self._history)}",
        ]
        if snap.is_baseline:
            parts.append("正在建立采样基线")
        if self._alarm.active:
            parts.append("⚠ CPU 占用率过高")
        if snap.errors:
            parts.append("采集异常：" + "、".join(snap.errors))
        self.statusBar().showMessage(" · ".join(parts))

    # ------------------------------------------------------------------ 导出
    def _export_csv(self) -> None:
        snapshots = self._history.all()
        if not snapshots:
            QMessageBox.information(self, "导出数据", "还没有采集到数据。")
            return

        default_name = f"sysmon_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出采样数据", default_name, "CSV 文件 (*.csv)"
        )
        if not path:
            return

        header = [
            "时间(ISO8601)",
            "CPU(%)",
            "内存(%)",
            "磁盘活动(%)",
            "分区最大容量使用率(%)",
            "网络下行(B/s)",
            "网络上行(B/s)",
            "磁盘读(B/s)",
            "磁盘写(B/s)",
            "进程数",
        ]
        try:
            # utf-8-sig 保证中文 Windows 上 Excel 双击打开不乱码
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                for s in snapshots:
                    max_part = max((p.percent for p in s.partitions), default=0.0)
                    writer.writerow(
                        [
                            datetime.datetime.fromtimestamp(s.wall).isoformat(timespec="seconds"),
                            f"{s.cpu_percent:.2f}",
                            f"{s.mem_percent:.2f}",
                            "" if s.disk_busy_percent is None else f"{s.disk_busy_percent:.1f}",
                            f"{max_part:.2f}",
                            "" if s.net_down_rate is None else f"{s.net_down_rate:.0f}",
                            "" if s.net_up_rate is None else f"{s.net_up_rate:.0f}",
                            "" if s.disk_read_rate is None else f"{s.disk_read_rate:.0f}",
                            "" if s.disk_write_rate is None else f"{s.disk_write_rate:.0f}",
                            s.proc_count,
                        ]
                    )
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：{exc}")
            return

        self.statusBar().showMessage(f"已导出 {len(snapshots)} 条记录 → {path}", 6000)

    # ------------------------------------------------------------------ 收尾
    def changeEvent(self, event) -> None:  # noqa: N802
        """窗口最小化时暂停采集。

        系统监视器常被最小化挂在托盘里，此时继续每秒采样只是白白占用 CPU。
        """
        if event.type() == QEvent.WindowStateChange and hasattr(self, "_worker"):
            if self.isMinimized():
                self._worker.pause()
                self._process_worker.set_interval(300.0)
            else:
                self._worker.resume()
                self._process_worker.set_interval(
                    3.0 if self._current_key == "proc" else 30.0
                )
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        """停止全部采集线程。

        必须确认线程真正结束：QThread 作为子对象随窗口析构，若仍在 run() 中，
        Qt 会以 qFatal("QThread: Destroyed while thread is still running") 直接终止进程。
        线程可能阻塞在一次无界的系统调用（如断连网络盘的 disk_usage），
        因此超时后强制 terminate，宁可冒终止线程的风险也不能让进程崩溃。
        """
        workers = (self._worker, self._process_worker, self._service_worker)
        for worker in workers:
            worker.stop()

        for worker in workers:
            if not worker.wait(2000):
                worker.terminate()
                worker.wait(1000)

        super().closeEvent(event)
