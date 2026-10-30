"""采集层：唯一与 psutil 打交道的模块。

设计要点：
- 所有 psutil 异常在此隔离，任何单个指标失败都不能中断整次采样
- 磁盘分区列表带 TTL 缓存，避免每 tick 枚举（断连的网络盘会让 disk_partitions 阻塞）
- 先按文件系统类型过滤再调用 disk_usage，而不是调用完再捕获异常
- 进程、连接数、用户等较慢的指标降频采集
- 服务枚举非常慢（WMI 逐条查询），放到独立线程，见 services.py
"""
from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

import psutil

from .engine import RateTracker
from .models import PartitionInfo, ProcessInfo, Snapshot, UserInfo

PARTITION_CACHE_SECONDS = 30.0
CONNECTIONS_EVERY_N_TICKS = 5
USERS_EVERY_N_TICKS = 10


class Collector:
    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self._cpu_warmed = False

        # 上行/下行、读/写是四个独立计数器，必须各自持有基线
        self._net_up_tracker = RateTracker(interval)
        self._net_down_tracker = RateTracker(interval)
        self._disk_read_tracker = RateTracker(interval)
        self._disk_write_tracker = RateTracker(interval)

        self._part_cache: Optional[List[psutil._common.sdiskpart]] = None
        self._part_cache_time = float("-inf")

        self._boot_time = 0.0
        try:
            self._boot_time = psutil.boot_time()
        except Exception:
            pass

        self._tick = 0
        self._proc_lock = threading.Lock()
        self._proc_cache: Tuple[ProcessInfo, ...] = ()
        self._proc_count = 0
        self._conn_count: Optional[int] = None
        self._users_cache: Tuple[UserInfo, ...] = ()

    # ------------------------------------------------------------------ 控制
    def reset_rates(self) -> None:
        """暂停恢复 / 修改采样间隔时调用：丢弃全部基线。

        除四个字节计数器外，还必须清掉 psutil 内部的缓存：
        - cpu_percent 的模块级 _last_cpu_times，否则恢复了半个小时的暂停后，
          首帧返回的是整个暂停区间的平均值；
        - process_iter 的进程对象缓存，否则进程的 cpu_percent 同样跨暂停。
        """
        for tracker in self._trackers():
            tracker.reset()

        try:
            psutil.cpu_percent(interval=None)
            psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            pass

        try:
            psutil.process_iter.cache_clear()
        except Exception:
            pass

    def set_interval(self, interval: float) -> None:
        self.interval = interval
        for tracker in self._trackers():
            tracker.nominal_dt = interval
        self.reset_rates()

    def _trackers(self):
        return (
            self._net_up_tracker,
            self._net_down_tracker,
            self._disk_read_tracker,
            self._disk_write_tracker,
        )

    def warm_up(self) -> None:
        """预热 CPU 采样，否则第一帧 cpu_percent 恒为 0.0。"""
        if not self._cpu_warmed:
            try:
                psutil.cpu_percent(interval=None)
                psutil.cpu_percent(interval=None, percpu=True)
            except Exception:
                pass
            self._cpu_warmed = True

    # ------------------------------------------------------------------ 采样
    def sample(self) -> Snapshot:
        mono = time.perf_counter()
        wall = time.time()
        errors: List[str] = []
        self._tick += 1

        cpu_percent, cpu_per_core, cpu_freq = self._sample_cpu(errors)
        (
            mem_percent,
            mem_used,
            mem_total,
            mem_available,
            swap_percent,
            swap_used,
            swap_total,
        ) = self._sample_memory(errors)
        partitions = self._sample_partitions(mono, errors)
        net_up, net_down, net_sent, net_recv = self._sample_network(mono)
        disk_r, disk_w, disk_rt, disk_wt = self._sample_disk_io(mono)
        proc_cache, proc_count = self._read_processes()
        self._maybe_sample_connections(errors)
        self._maybe_sample_users(errors)

        return Snapshot(
            mono=mono,
            wall=wall,
            cpu_percent=cpu_percent,
            cpu_per_core=cpu_per_core,
            cpu_freq=cpu_freq,
            cpu_cores=psutil.cpu_count(logical=False) or 0,
            cpu_threads=psutil.cpu_count(logical=True) or 0,
            uptime=max(0.0, wall - self._boot_time) if self._boot_time else 0.0,
            mem_percent=mem_percent,
            mem_used=mem_used,
            mem_total=mem_total,
            mem_available=mem_available,
            swap_percent=swap_percent,
            swap_used=swap_used,
            swap_total=swap_total,
            partitions=partitions,
            net_up_rate=net_up,
            net_down_rate=net_down,
            net_sent=net_sent,
            net_recv=net_recv,
            net_connections=self._conn_count,
            disk_read_rate=disk_r,
            disk_write_rate=disk_w,
            disk_read_total=disk_rt,
            disk_write_total=disk_wt,
            proc_count=proc_count,
            processes=proc_cache,
            users=self._users_cache,
            errors=tuple(errors),
            is_baseline=(net_up is None and disk_r is None),
        )

    # ------------------------------------------------------------------ 各指标
    def _sample_cpu(self, errors: List[str]):
        try:
            percent = psutil.cpu_percent(interval=None)
            per_core = tuple(psutil.cpu_percent(interval=None, percpu=True))
        except Exception:
            errors.append("CPU")
            percent, per_core = 0.0, ()

        freq = 0.0
        try:
            f = psutil.cpu_freq()
            if f:
                freq = float(f.current)
        except Exception:
            pass
        return percent, per_core, freq

    @staticmethod
    def _sample_memory(errors: List[str]):
        try:
            vm = psutil.virtual_memory()
        except Exception:
            errors.append("内存")
            vm = None

        try:
            sm = psutil.swap_memory()
        except Exception:
            sm = None

        return (
            vm.percent if vm else 0.0,
            vm.used if vm else 0,
            vm.total if vm else 0,
            vm.available if vm else 0,
            sm.percent if sm else 0.0,
            sm.used if sm else 0,
            sm.total if sm else 0,
        )

    def _sample_partitions(self, mono: float, errors: List[str]) -> Tuple[PartitionInfo, ...]:
        if self._part_cache is None or mono - self._part_cache_time > PARTITION_CACHE_SECONDS:
            self._part_cache = self._enumerate_partitions()
            self._part_cache_time = mono

        result: List[PartitionInfo] = []
        for part in self._part_cache or []:
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                # 光驱空仓、刚拔掉的移动盘等，跳过即可，不记为错误
                continue
            result.append(
                PartitionInfo(
                    mount=part.mountpoint,
                    used=usage.used,
                    total=usage.total,
                    percent=usage.percent,
                )
            )
        if not result and self._part_cache:
            errors.append("磁盘")
        return tuple(result)

    @staticmethod
    def _enumerate_partitions() -> List[psutil._common.sdiskpart]:
        """枚举并预过滤分区。过滤放在 disk_usage 之前，避免访问无效设备。"""
        try:
            parts = psutil.disk_partitions(all=False)
        except Exception:
            return []

        filtered = []
        for p in parts:
            opts = (p.opts or "").lower()
            fstype = (p.fstype or "").lower()
            # 光驱 / 空文件系统
            if "cdrom" in opts or not fstype:
                continue
            # 网络映射盘：Windows 上 device 是 "Z:\\" 而非 UNC 路径，
            # 只能靠 opts 中的 remote 标记识别（GetDriveType -> DRIVE_REMOTE）。
            # 服务器离线时 disk_usage 会在 SMB 超时上阻塞数十秒。
            if "remote" in opts or p.device.startswith("\\\\"):
                continue
            filtered.append(p)
        return filtered

    def _sample_network(self, mono: float):
        try:
            counters = psutil.net_io_counters(pernic=False)
        except Exception:
            return None, None, 0, 0
        if counters is None:
            return None, None, 0, 0

        up = self._net_up_tracker.update(counters.bytes_sent, mono)
        down = self._net_down_tracker.update(counters.bytes_recv, mono)
        return up, down, counters.bytes_sent, counters.bytes_recv

    def _sample_disk_io(self, mono: float):
        try:
            per_disk = psutil.disk_io_counters(perdisk=True)
        except Exception:
            return None, None, 0, 0
        if not per_disk:
            return None, None, 0, 0

        read_total = sum(d.read_bytes for d in per_disk.values())
        write_total = sum(d.write_bytes for d in per_disk.values())

        read_rate = self._disk_read_tracker.update(read_total, mono)
        write_rate = self._disk_write_tracker.update(write_total, mono)
        return read_rate, write_rate, read_total, write_total

    def refresh_processes(self) -> None:
        """由独立的进程线程周期调用。

        全量遍历在 Windows 上约 1 秒，不能放在 1 Hz 采样线程里。
        只读取低开销字段，status / memory_info / num_threads 会让耗时翻数倍。
        """
        # psutil 的进程 CPU 以单个核心为 100%，多核上可超过 100%
        # （空闲时 System Idle Process 约为 N×100%）。
        # 任务管理器的口径是「全部核心合计 = 100%」，这里换算保持一致。
        cores = psutil.cpu_count(logical=True) or 1

        procs: List[ProcessInfo] = []
        try:
            for p in psutil.process_iter(
                ["pid", "name", "cpu_percent", "memory_percent"]
            ):
                try:
                    info = p.info
                    procs.append(
                        ProcessInfo(
                            pid=info["pid"],
                            name=info.get("name") or "?",
                            cpu=(info.get("cpu_percent") or 0.0) / cores,
                            mem_percent=info.get("memory_percent") or 0.0,
                        )
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                    continue
        except Exception:
            return

        procs.sort(key=lambda x: x.cpu, reverse=True)
        with self._proc_lock:
            self._proc_cache = tuple(procs)
            self._proc_count = len(procs)

    def _read_processes(self) -> Tuple[Tuple[ProcessInfo, ...], int]:
        with self._proc_lock:
            return self._proc_cache, self._proc_count

    def _maybe_sample_connections(self, errors: List[str]) -> None:
        # 首帧必须采一次，否则启动后前几秒会把「尚未采集」显示成 0
        if self._conn_count is not None and self._tick % CONNECTIONS_EVERY_N_TICKS != 0:
            return
        try:
            self._conn_count = len(psutil.net_connections(kind="inet"))
        except (psutil.AccessDenied, OSError):
            # 非管理员权限下可能拿不到，保持上一次的值
            pass
        except Exception:
            errors.append("连接")

    def _maybe_sample_users(self, errors: List[str]) -> None:
        if self._tick % USERS_EVERY_N_TICKS != 0 and self._users_cache:
            return
        try:
            users = tuple(
                UserInfo(
                    name=u.name,
                    host=u.host or "",
                    terminal=u.terminal or "",
                    started=u.started,
                )
                for u in psutil.users()
            )
            self._users_cache = users
        except Exception:
            errors.append("用户")
