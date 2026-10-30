"""Windows 服务采集线程。

psutil.win_service_iter() 会逐条查询 WMI，几百个服务耗时可达数秒，
因此不能放进主采样线程，否则会打乱 1 秒采样节奏。
这里用独立线程低频采集，结果通过信号交给界面。
"""
from __future__ import annotations

import threading
from typing import Tuple

from PySide6.QtCore import QThread, Signal

from .models import ServiceInfo

try:  # 非 Windows 平台没有这个 API
    import psutil

    _HAS_WIN_SERVICE = hasattr(psutil, "win_service_iter")
except Exception:  # pragma: no cover
    _HAS_WIN_SERVICE = False


class ServiceWorker(QThread):
    services_ready = Signal(object)  # Tuple[ServiceInfo, ...]

    def __init__(self, interval: float = 30.0, parent=None) -> None:
        super().__init__(parent)
        self._interval = interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            data = self._collect()
            if not self._stop_event.is_set():
                self.services_ready.emit(data)
            self._stop_event.wait(self._interval)

    @staticmethod
    def _collect() -> Tuple[ServiceInfo, ...]:
        if not _HAS_WIN_SERVICE:
            return ()

        items = []
        try:
            for svc in psutil.win_service_iter():
                try:
                    items.append(
                        ServiceInfo(
                            name=svc.name(),
                            display_name=svc.display_name(),
                            status=svc.status(),
                            start_type=svc.start_type(),
                        )
                    )
                except Exception:
                    continue
        except Exception:
            return ()
        items.sort(key=lambda s: s.display_name.lower())
        return tuple(items)
