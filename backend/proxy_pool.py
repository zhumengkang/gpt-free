"""代理池管理"""
import random
import httpx


class ProxyPool:
    """线程安全的代理池（只读使用，由主线程更新列表）"""

    def __init__(self, proxies: list[dict] | None = None):
        self._proxies = proxies or []

    def update(self, proxies: list[dict]):
        self._proxies = proxies

    def get_random(self) -> dict | None:
        enabled = [p for p in self._proxies if p.get("enabled")]
        if not enabled:
            return None
        return random.choice(enabled)

    def get_random_url(self) -> str | None:
        p = self.get_random()
        return p["url"] if p else None

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
