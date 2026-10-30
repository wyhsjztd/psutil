"""engine 层单元测试：不依赖 psutil，也不依赖 Qt。

运行：python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sysmon.engine import (
    HysteresisAlarm,
    RateTracker,
    compute_rate,
    format_bytes,
)


class TestComputeRate(unittest.TestCase):
    def test_first_frame_returns_none(self):
        self.assertIsNone(compute_rate(None, 100, None, 10.0, 1.0))

    def test_normal_delta(self):
        # 1 秒内增加 1000 字节 -> 1000 B/s
        self.assertAlmostEqual(compute_rate(1000, 2000, 10.0, 11.0, 1.0), 1000.0)

    def test_zero_dt_returns_none(self):
        self.assertIsNone(compute_rate(1000, 2000, 10.0, 10.0, 1.0))

    def test_negative_dt_returns_none(self):
        self.assertIsNone(compute_rate(1000, 2000, 10.0, 9.0, 1.0))

    def test_counter_wrap_returns_none(self):
        # 系统重启后计数器归零，差值为负
        self.assertIsNone(compute_rate(5000, 100, 10.0, 11.0, 1.0))

    def test_pause_gap_returns_none(self):
        # 暂停 30 秒后恢复，dt 远超名义间隔，必须丢弃
        self.assertIsNone(compute_rate(1000, 2000, 10.0, 40.0, 1.0))

    def test_small_jitter_allowed(self):
        # 1 秒采样下 1.2 秒的实际间隔应被接受
        rate = compute_rate(1000, 2200, 10.0, 11.2, 1.0)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 1000.0)

    def test_interval_change_respected(self):
        # 改为 5 秒间隔后，5 秒的 dt 必须被接受
        rate = compute_rate(0, 2500, 10.0, 15.0, 5.0)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 500.0)


class TestRateTracker(unittest.TestCase):
    def test_tracker_first_update_none(self):
        t = RateTracker(1.0)
        self.assertIsNone(t.update(100, 0.0))

    def test_tracker_second_update(self):
        t = RateTracker(1.0)
        t.update(100, 0.0)
        self.assertAlmostEqual(t.update(200, 1.0), 100.0)

    def test_reset_discards_baseline(self):
        t = RateTracker(1.0)
        t.update(100, 0.0)
        t.reset()
        # reset 后的第一帧只记录，不计算
        self.assertIsNone(t.update(500, 1.0))
        self.assertAlmostEqual(t.update(600, 2.0), 100.0)


class TestHysteresisAlarm(unittest.TestCase):
    def test_fires_on_high(self):
        a = HysteresisAlarm(high=80, low=75, cooldown=300)
        self.assertTrue(a.update(85, 0))

    def test_no_refire_while_active(self):
        a = HysteresisAlarm(high=80, low=75, cooldown=300)
        a.update(85, 0)
        self.assertFalse(a.update(90, 10))

    def test_rearm_after_low_and_cooldown(self):
        a = HysteresisAlarm(high=80, low=75, cooldown=300)
        a.update(85, 0)
        a.update(70, 10)          # 解除
        self.assertTrue(a.update(82, 400))  # 冷却已过，重新触发

    def test_cooldown_blocks_rearm(self):
        a = HysteresisAlarm(high=80, low=75, cooldown=300)
        a.update(85, 0)
        a.update(70, 10)
        self.assertFalse(a.update(82, 100))  # 冷却未过


class TestFormatBytes(unittest.TestCase):
    def test_none(self):
        self.assertEqual(format_bytes(None), "--")

    def test_kb(self):
        self.assertEqual(format_bytes(1536), "1.5 KB/s")

    def test_mb(self):
        self.assertEqual(format_bytes(5 * 1024 * 1024), "5.0 MB/s")

    def test_capacity_suffix(self):
        self.assertEqual(format_bytes(2 * 1024 ** 3, suffix=""), "2.0 GB")


if __name__ == "__main__":
    unittest.main()
