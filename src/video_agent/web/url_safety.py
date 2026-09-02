"""URL 安全校验（SSRF 防护）——单一事实源。

供外部图片代理等场景使用；与 routes/providers.py 的
内网黑名单语义保持一致：私网地址拒绝，本机回环/本地反代显式放行。

加固要点：
1. 协议白名单——仅 http/https（file:/gopher:/data: 等一律拒绝）；
2. 域名解析后复验——DNS 指向内网/回环的域名一并拒绝（堵 DNS rebinding；
   回环仅对字面量 localhost/127.x 放行，域名解析到回环同样拒绝）。
"""
import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]

# 明确允许的本地字面量地址（不受 _BLOCKED_NETWORKS 限制）
_LOCAL_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

_ALLOWED_SCHEMES = ("http", "https")


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS)


def validate_external_url(url: str) -> None:
    """校验 URL 协议为 http(s) 且不指向内网地址，违反则抛 ValueError。

    本地回环字面量（127.x / localhost / ::1）显式放行，供本地反代等场景使用；
    域名经 DNS 解析后指向内网/回环同样拒绝（防 rebinding）。
    """
    parsed = urlparse(str(url or ""))
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(f"禁止访问该协议: {parsed.scheme or '(无)'}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL 缺少主机名")
    if host in _LOCAL_ALLOWED_HOSTS:
        return  # 字面量回环：本地反代场景显式放行
    try:
        ip = ipaddress.ip_address(host)
        if _blocked_ip(ip):
            raise ValueError(f"禁止访问内网地址: {host}")
        return
    except ValueError as e:
        if "禁止" in str(e):
            raise
        # host 是域名：DNS 解析后复验，解析失败拒绝（保守）
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise ValueError(f"域名解析失败，拒绝访问: {host}") from e
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _blocked_ip(ip):
            raise ValueError(f"禁止访问内网地址（解析自 {host}）: {addr}")
