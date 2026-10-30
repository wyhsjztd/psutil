"""数据模型：所有跨模块传递的对象都在这里定义。

Snapshot 使用 frozen dataclass，配合 Signal(object) 传递时不会被下游意外修改，
同时也避开了 PySide6 自定义类型注册的坑。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class PartitionInfo:
    """单个磁盘分区的使用情况。"""

    mount: str
    used: int
    total: int
    percent: float


@dataclass(frozen=True)
class ProcessInfo:
    """进程列表中的一行。

    只保留低开销字段：进程遍历中 status / memory_info / num_threads
    各需额外系统调用，会把 1 秒采样节奏拖垮，因此不采集。
    """

    pid: int
    name: str
    cpu: float          # 区间平均 CPU 占用（%）
    mem_percent: float  # 内存占用（%）


@dataclass(frozen=True)
class ServiceInfo:
    name: str
    display_name: str
    status: str
    start_type: str


@dataclass(frozen=True)
class UserInfo:
    name: str
    host: str
    terminal: str
    started: float


@dataclass(frozen=True)
class Snapshot:
    """一次采样的完整快照。

    双时间戳：
    - mono: perf_counter 单调时钟，只用于计算速率，不受系统校时影响
    - wall: 墙上时间，用于图表 x 轴显示与 CSV 导出
    """

    mono: float
    wall: float

    # CPU
    cpu_percent: float
    cpu_per_core: Tuple[float, ...]
    cpu_freq: float
    cpu_cores: int
    cpu_threads: int
    uptime: float

    # 内存
    mem_percent: float
    mem_used: int
    mem_total: int
    mem_available: int
    swap_percent: float
    swap_used: int
    swap_total: int

    # 磁盘使用率
    partitions: Tuple[PartitionInfo, ...]

    # 网络（字节/秒），None 表示本帧无法计算
    net_up_rate: Optional[float]
    net_down_rate: Optional[float]
    net_sent: int
    net_recv: int
    net_connections: Optional[int]

    # 磁盘 IO（字节/秒）
    disk_read_rate: Optional[float]
    disk_write_rate: Optional[float]
    disk_read_total: int
    disk_write_total: int

    # 进程（由独立线程更新，采样时只读缓存）
    proc_count: int
    processes: Tuple[ProcessInfo, ...]

    # 登录用户（低频采集）
    users: Tuple[UserInfo, ...]

    # 本次采样中被跳过的异常项，用于状态栏提示
    errors: Tuple[str, ...] = ()

    # 是否为重建基线后的第一帧（速率字段必然为 None）
    is_baseline: bool = False
