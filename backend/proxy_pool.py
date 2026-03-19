"""代理池管理 - 增强版：健康追踪 + 智能选择 + 自动排除坏代理"""
import random
import threading
import time
import httpx


class ProxyPool:
    """线程安全的代理池，支持健康追踪和自动故障转移"""

    def __init__(self, proxies: list[dict] | None = None):
        self._proxies = proxies or []
        self._lock = threading.Lock()
        # {proxy_url: {"fails": int, "last_fail": float, "disabled_until": float}}
        self._health: dict[str, dict] = {}
        # 连续失败多少次后临时禁用
        self._max_consecutive_fails = 3
        # 禁用时长（秒），随失败次数递增
        self._base_cooldown = 60

    def update(self, proxies: list[dict]):
        self._proxies = proxies

    def mark_fail(self, proxy_url: str):
        """标记代理失败，连续失败超过阈值则临时禁用"""
        if not proxy_url:
            return
        with self._lock:
            h = self._health.setdefault(proxy_url, {"fails": 0, "last_fail": 0, "disabled_until": 0})
            h["fails"] += 1
            h["last_fail"] = time.time()
            if h["fails"] >= self._max_consecutive_fails:
                cooldown = self._base_cooldown * (h["fails"] - self._max_consecutive_fails + 1)
                cooldown = min(cooldown, 600)  # 最多禁用10分钟
                h["disabled_until"] = time.time() + cooldown

    def mark_success(self, proxy_url: str):
        """标记代理成功，重置失败计数"""
        if not proxy_url:
            return
        with self._lock:
            if proxy_url in self._health:
                self._health[proxy_url] = {"fails": 0, "last_fail": 0, "disabled_until": 0}

    def is_available(self, proxy_url: str) -> bool:
        """检查代理是否可用（未被临时禁用）"""
        with self._lock:
            h = self._health.get(proxy_url)
            if not h:
                return True
            return time.time() >= h["disabled_until"]

    def get_random(self, exclude: set[str] | None = None) -> dict | None:
        """随机选择一个健康的代理，可排除指定代理"""
        now = time.time()
        exclude = exclude or set()
        enabled = [
            p for p in self._proxies
            if p.get("enabled")
            and p["url"] not in exclude
            and self.is_available(p["url"])
        ]
        if not enabled:
            # 所有代理都被禁用了，放宽限制：只排除 exclude 列表
            enabled = [
                p for p in self._proxies
                if p.get("enabled") and p["url"] not in exclude
            ]
        if not enabled:
            # 连 exclude 都满足不了，返回任意启用的
            enabled = [p for p in self._proxies if p.get("enabled")]
        if not enabled:
            return None
        # 优先选择失败次数少的
        enabled.sort(key=lambda p: self._health.get(p["url"], {}).get("fails", 0))
        # 从前半部分随机选（偏向健康的）
        top_half = enabled[:max(1, len(enabled) // 2)]
        return random.choice(top_half)

    def get_random_url(self, exclude: set[str] | None = None) -> str | None:
        p = self.get_random(exclude=exclude)
        return p["url"] if p else None

    def get_health_summary(self) -> dict:
        """返回代理健康状态摘要"""
        with self._lock:
            total = len([p for p in self._proxies if p.get("enabled")])
            now = time.time()
            disabled = sum(
                1 for h in self._health.values()
                if h["disabled_until"] > now
            )
            return {"total_enabled": total, "temporarily_disabled": disabled}

    @staticmethod
    def test_proxy(url: str, timeout: int = 10) -> tuple[bool, str]:
        """测试代理连通性，返回 (成功, 信息)"""
        try:
            with httpx.Client(proxy=url, timeout=timeout, verify=False) as client:
                resp = client.get("https://cloudflare.com/cdn-cgi/trace")
                if resp.status_code == 200:
                    return True, resp.text[:200]
                return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)
