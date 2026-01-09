import time
import os
import random


class RateLimiter:
    def __init__(self, cfg):
        self.enabled = bool(getattr(cfg, "rate_limit_enabled", True))
        self.max_load_ratio = float(getattr(cfg, "max_load_avg_ratio", 0.8))
        self.min_sleep_ms = int(getattr(cfg, "min_sleep_ms", 5))
        self.max_sleep_ms = int(getattr(cfg, "max_sleep_ms", 200))
        self._ma_latency = 0.0

    def update_write_stats(self, elapsed: float, ops_count: int):
        if elapsed <= 0:
            return
        a = 0.9
        if self._ma_latency == 0.0:
            self._ma_latency = elapsed
        else:
            self._ma_latency = a * self._ma_latency + (1 - a) * elapsed

    def _load_ratio(self) -> float:
        try:
            la1 = os.getloadavg()[0]
            cpus = max(1, os.cpu_count() or 1)
            return la1 / cpus
        except Exception:
            return 0.0

    def should_throttle(self) -> bool:
        if not self.enabled:
            return False
        lr = self._load_ratio()
        if lr >= self.max_load_ratio:
            return True
        if self._ma_latency > 0.5:
            return True
        return False

    def sleep_if_needed(self):
        if not self.enabled:
            return
        lr = self._load_ratio()
        if lr < self.max_load_ratio and self._ma_latency <= 0.5:
            return
        over = max(0.0, lr - self.max_load_ratio)
        base = self.min_sleep_ms
        extra = int(min(self.max_sleep_ms - base, (self.max_sleep_ms - base) * min(1.0, over * 1.5)))
        ms = base + extra
        ms += random.randint(0, 10)
        time.sleep(ms / 1000.0)
