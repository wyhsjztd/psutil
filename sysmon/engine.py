"""纯逻辑层：速率计算、历史窗口、告警判定。

这一层刻意不 import psutil，也不 import Qt，因此可以脱离运行环境做单元测试。
"""
from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional, Tuple


def compute_rate(
    prev_value: Optional[float],
    curr_value: Optional[float],
    prev_ts: Optional[float],
    curr_ts: float,
    nominal_dt: float,
    *,
    tolerance_factor: float = 2.0,
    min_tolerance: float = 0.5,
) -> Optional[float]:
    """由两个累计计数器的差值计算速率（单位/秒）。

    返回 None 的四种情况，宁可不显示也不显示错数：
      1. 首帧（没有前值）
      2. dt <= 0（时钟异常）
      3. dt 偏离名义间隔过多（暂停、改间隔、系统卡顿）
      4. 计数器回绕 / 重启导致差值为负

    显式的事件（暂停、修改采样间隔）由调用方 reset 基线处理，
    这里的 dt 检查只作为兜底保护，因此阈值放宽到 2 倍间隔。
    """
    if prev_value is None or curr_value is None or prev_ts is None:
        return None

    dt = curr_ts - prev_ts
    if dt <= 0:
        return None

    tolerance = max(nominal_dt * tolerance_factor, min_tolerance)
    if abs(dt - nominal_dt) > tolerance:
        return None

    delta = curr_value - prev_value
    if delta < 0:
        return None

    return delta / dt


class RateTracker:
    """持有上一次的 (值, 时间戳)，负责在事件发生时重置基线。"""

    def __init__(
        self,
        nominal_dt: float,
        *,
        tolerance_factor: float = 2.0,
        min_tolerance: float = 0.5,
    ) -> None:
        self.nominal_dt = nominal_dt
        self.tolerance_factor = tolerance_factor
        self.min_tolerance = min_tolerance
        self._prev: Optional[Tuple[float, float]] = None

    def reset(self) -> None:
        """丢弃基线，下一次 update 只记录不计算。"""
        self._prev = None

    def update(self, value: float, ts: float) -> Optional[float]:
        prev = self._prev
        self._prev = (value, ts)
        if prev is None:
            return None
        return compute_rate(
            prev[0],
            value,
            prev[1],
            ts,
            self.nominal_dt,
            tolerance_factor=self.tolerance_factor,
            min_tolerance=self.min_tolerance,
        )


class History:
    """环形历史缓存。

    容量按“时长”配置（默认 1 小时 @1Hz），绘图时再按时间窗裁剪，
    这样同一份缓存既能给 60 秒图表用，也能导出全量 CSV。
    存入的是 Snapshot 对象，engine 层不关心其内部结构。
    """

    def __init__(self, maxlen: int = 3600) -> None:
        self._data: Deque[object] = deque(maxlen=maxlen)

    def __len__(self) -> int:
        return len(self._data)

    def append(self, snapshot: object) -> None:
        self._data.append(snapshot)

    def clear(self) -> None:
        self._data.clear()

    def all(self) -> List[object]:
        return list(self._data)

    def window(self, now_mono: float, seconds: float) -> List[object]:
        """返回时间窗 [now_mono - seconds, now_mono] 内的快照。"""
        start = now_mono - seconds
        return [s for s in self._data if getattr(s, "mono", 0.0) >= start]


class HysteresisAlarm:
    """带滞回与冷却的阈值告警。

    - 超过 high 触发，低于 low 才解除，避免在阈值附近反复横跳
    - 两次通知之间至少间隔 cooldown 秒
    """

    def __init__(self, high: float = 80.0, low: float = 75.0, cooldown: float = 300.0) -> None:
        self.high = high
        self.low = low
        self.cooldown = cooldown
        self.active = False
        self._last_fired = float("-inf")

    def update(self, value: float, now: float) -> bool:
        """返回 True 表示本次应当发出一次通知。"""
        if not self.active:
            if value >= self.high:
                self.active = True
                if now - self._last_fired >= self.cooldown:
                    self._last_fired = now
                    return True
            return False

        if value <= self.low:
            self.active = False
        return False


def format_bytes(value: Optional[float], *, suffix: str = "/s") -> str:
    """把字节数格式化为易读文本，None 显示为 --。"""
    if value is None:
        return "--"
    units = ("B", "KB", "MB", "GB", "TB")
    v = float(value)
    for unit in units:
        if abs(v) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{v:.0f} B{suffix}"
            return f"{v:.1f} {unit}{suffix}"
        v /= 1024.0
    return f"{v:.1f} TB{suffix}"


def format_percent(value: Optional[float]) -> str:
    if value is None:
        return "--"
    return f"{value:.0f}%"
