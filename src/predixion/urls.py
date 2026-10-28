"""URL validation and conservative canonicalization.

These checks govern which URLs the application will *ask the extraction
provider* to read and which links it will render. The provider performs the
actual fetch on its own network; this module does not and cannot control the
provider's internal egress, redirects, or DNS resolution.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

MAX_URL_LENGTH = 2_048
ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({None, 80, 443})

BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "instance-data.ec2.internal",
    }
)
BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".intranet",
    ".lan",
    ".home",
    ".corp",
    ".home.arpa",
    ".localdomain",
)

# Tracking parameters removed during canonicalization. Anything else is kept,
# because parameters such as ?id= or ?v= may identify different documents.
TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "ref_src",
    }
)

_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class UnsafeURL(ValueError):
    pass


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Recognize IP literals, including integer/hex/octal IPv4 encodings."""
    candidate = host.strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass
    # inet_aton-style forms such as 2130706433, 0x7f000001, 0177.0.0.1, 127.1
    parts = candidate.split(".")
    if not 1 <= len(parts) <= 4 or not all(parts):
        return None
    try:
        nums = [int(p, 0) if not re.fullmatch(r"0\d+", p) else int(p, 8) for p in parts]
    except ValueError:
        return None
    if any(n < 0 for n in nums):
        return None
    try:
        if len(nums) == 1:
            value = nums[0]
        elif len(nums) == 2:
            value = (nums[0] << 24) | nums[1]
        elif len(nums) == 3:
            value = (nums[0] << 24) | (nums[1] << 16) | nums[2]
        else:
            if any(n > 255 for n in nums):
                return None
            value = (nums[0] << 24) | (nums[1] << 16) | (nums[2] << 8) | nums[3]
        return ipaddress.IPv4Address(value)
    except (ValueError, ipaddress.AddressValueError):
        return None


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _ip_is_public(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return _ip_is_public(ip.sixtofour)
        if ip in _NAT64:
            return _ip_is_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.teredo is not None or ip.is_site_local:
            return False
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return ip.is_global


def validate_public_url(url: str) -> str:
    """Return the URL if it is an acceptable public http(s) URL, else raise UnsafeURL."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise UnsafeURL("missing or overlong URL")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise UnsafeURL("URL contains whitespace or control characters")
    if "\\" in url:
        raise UnsafeURL("URL contains backslashes")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeURL("unparseable URL") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL("scheme not allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeURL("credentials in URL")
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("non-default port")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURL("missing host")
    if "%" in host:
        raise UnsafeURL("encoded or zone-scoped host")
    ip = _parse_ip_literal(host)
    if ip is not None:
        if not _ip_is_public(ip):
            raise UnsafeURL("private, loopback, link-local, or reserved address")
        return url
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeURL("invalid hostname") from exc
    if ascii_host in BLOCKED_HOSTNAMES or ascii_host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURL("local or internal hostname")
    labels = ascii_host.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL.match(label) for label in labels):
        raise UnsafeURL("hostname must be a public fully qualified domain name")
    if labels[-1].isdigit():
        raise UnsafeURL("numeric top-level label")
    return url


def is_safe_public_url(url: str) -> bool:
    try:
        validate_public_url(url)
    except UnsafeURL:
        return False
    return True


def canonicalize_url(url: str) -> str:
    """Conservative canonical form for de-duplication.

    Lowercases scheme/host, drops default ports, fragments, and known tracking
    parameters, removes a trailing slash on non-root paths. Keeps all other
    query parameters and their order-insensitive set.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").rstrip(".").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = quote(unquote(parts.path or "/"), safe="/:@!$&'()*+,;=-._~")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query_pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    query = urlencode(sorted(query_pairs))
    # http and https are treated as the same document for de-duplication.
    scheme = "https" if scheme in ("http", "https") else scheme
    return urlunsplit((scheme, netloc, path, query, ""))


def registrable_domain(url: str) -> str:
    """Approximate site identity (last two labels; three for common 2nd-level ccTLDs)."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in {"co", "com", "org", "net", "ac", "gov", "edu"} and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def hostname(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host
