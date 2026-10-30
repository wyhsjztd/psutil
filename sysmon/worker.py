"""采集线程。

所有 psutil 调用都发生在这里，UI 线程只接收冻结快照。
停止使用可中断的 Event.wait，避免关闭窗口后残留线程。
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

from .collector import Collector


class SampleWorker(QThread):
    sampled = Signal(object)  # 载荷为 Snapshot，一次 tick 只发一个信号

    def __init__(self, collector: Collector, interval: float = 1.0, parent=None) -> None:
        super().__init__(parent)
        self._interval = interval
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._pending_interval: Optional[float] = None
        self._reset_pending = True  # 启动后的第一帧只建立基线
        self._collector = collector

    # ------------------------------------------------------------ 外部控制
    def set_interval(self, interval: float) -> None:
        # 只投递意图，真正的修改在采集线程内完成，避免跨线程改状态
        self._pending_interval = interval
        self._reset_pending = True

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._reset_pending = True
        self._paused.clear()

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    # ------------------------------------------------------------ 线程主体
    def run(self) -> None:
        self._collector.warm_up()

        while not self._stop_event.is_set():
            if self._paused.is_set():
                self._stop_event.wait(0.05)
                continue

            if self._pending_interval is not None:
                self._interval = self._pending_interval
                self._collector.set_interval(self._pending_interval)
                self._pending_interval = None

            if self._reset_pending:
                self._collector.reset_rates()
                self._reset_pending = False

            started = time.perf_counter()
            try:
                snapshot = self._collector.sample()
            except Exception:
                # 单帧失败不应该结束整个采集线程
                self._stop_event.wait(self._interval)
                continue

            if not self._stop_event.is_set():
                self.sampled.emit(snapshot)

            elapsed = time.perf_counter() - started
            self._stop_event.wait(max(0.05, self._interval - elapsed))


class ProcessWorker(QThread):
    """独立采集进程列表。

    Windows 上全量遍历约 1 秒，若放在 1 Hz 采样线程里，会让速率计算的
    dt 远超名义间隔，导致网络与磁盘速率被判定为异常而长期显示 --。
    """

    def __init__(self, collector: Collector, interval: float = 3.0, parent=None) -> None:
        super().__init__(parent)
        self._collector = collector
        self._interval = interval
        self._stop_event = threading.Event()
        self._wake = threading.Event()

    def set_interval(self, interval: float) -> None:
        """看进程页时 3 秒刷新，其他页面降频，避免无谓的 CPU 占用。"""
        if interval != self._interval:
            self._interval = interval
            self._wake.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._collector.refresh_processes()
            except Exception:
                pass
            # 可被 set_interval / stop 提前唤醒
            self._wake.wait(self._interval)
            self._wake.clear()
