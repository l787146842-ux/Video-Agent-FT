"""URL 安全校验（SSRF 防护）——单一事实源。

供 eval/quality.py 与外部图片代理等场景使用；与 routes/providers.py 的
内网黑名单语义保持一致：私网地址拒绝，本机回环/本地反代显式放行。
"""
import ipaddress
from urllib.parse import urlparse


_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]

# 明确允许的本地地址（不受 _BLOCKED_NETWORKS 限制）
_LOCAL_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def validate_external_url(url: str) -> None:
    """校验 URL 不指向内网地址，违反则抛 ValueError。

    本地回环地址（127.x / localhost / ::1）明确放行，供本地反代等场景使用。
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in _LOCAL_ALLOWED_HOSTS:
        return
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback:
            return
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                raise ValueError(f"禁止访问内网地址: {host}")
    except ValueError as e:
        if "禁止" in str(e):
            raise
        # host 是域名，允许通过（DNS 解析交给 httpx 处理）
