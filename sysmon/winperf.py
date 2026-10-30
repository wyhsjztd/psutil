"""Windows 性能计数器（PDH）访问。

psutil 的 disk_io_counters 虽然提供 read_time / write_time，
但这两项来自 IOCTL_DISK_PERFORMANCE，在 NVMe 或未启用 diskperf 的机器上恒为 0
（本项目开发机实测：写入 213 MB 后增量仍为 0），无法据此计算活动时间。
任务管理器用的是性能计数器里的 "% Disk Time"，这里直接读同一个来源。

使用 PdhAddEnglishCounterW 而不是 PdhAddCounterW，保证在中文等本地化
Windows 上也能用英文计数器名。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Optional

_PDH_FMT_DOUBLE = 0x00000200
_PDH_FMT_NOCAP100 = 0x00008000
_ERROR_SUCCESS = 0

_COUNTER_PATH = r"\PhysicalDisk(_Total)\% Disk Time"


class _PdhFmtCounterValue(ctypes.Structure):
    class _Value(ctypes.Union):
        _fields_ = [
            ("doubleValue", ctypes.c_double),
            ("longValue", ctypes.c_long),
            ("largeValue", ctypes.c_longlong),
        ]

    _anonymous_ = ("u",)
    _fields_ = [("status", wintypes.DWORD), ("u", _Value)]


class DiskActivity:
    """磁盘活动时间占比（0–100），语义与任务管理器「性能 → 磁盘」一致。"""

    def __init__(self) -> None:
        self._pdh = None
        self._query = wintypes.HANDLE()
        self._counter = wintypes.HANDLE()
        self._available = False
        self._primed = False

        if sys.platform != "win32":
            return

        try:
            pdh = ctypes.WinDLL("pdh")
            if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) != _ERROR_SUCCESS:
                return
            if (
                pdh.PdhAddEnglishCounterW(
                    self._query, _COUNTER_PATH, 0, ctypes.byref(self._counter)
                )
                != _ERROR_SUCCESS
            ):
                pdh.PdhCloseQuery(self._query)
                return
            self._pdh = pdh
            self._available = True
            self.rebase()
        except Exception:
            self._pdh = None
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def rebase(self) -> None:
        """丢弃当前基线。暂停恢复后必须先调用，否则下一帧会把整段暂停计入。"""
        if not self._available:
            return
        try:
            self._pdh.PdhCollectQueryData(self._query)
            self._primed = False
        except Exception:
            self._available = False

    def read(self) -> Optional[float]:
        """采集一次并返回活动时间百分比；不可用时返回 None。"""
        if not self._available:
            return None
        try:
            if self._pdh.PdhCollectQueryData(self._query) != _ERROR_SUCCESS:
                return None
            value = _PdhFmtCounterValue()
            rc = self._pdh.PdhGetFormattedCounterValue(
                self._counter,
                _PDH_FMT_DOUBLE | _PDH_FMT_NOCAP100,
                None,
                ctypes.byref(value),
            )
            if rc != _ERROR_SUCCESS or value.status != _ERROR_SUCCESS:
                return None
            # 首次取数只有基线、没有差值
            if not self._primed:
                self._primed = True
                return None
            # _Total 是各磁盘之和，多盘并发时可能超过 100
            return max(0.0, min(100.0, float(value.doubleValue)))
        except Exception:
            return None

    def close(self) -> None:
        if self._available:
            try:
                self._pdh.PdhCloseQuery(self._query)
            except Exception:
                pass
            self._available = False