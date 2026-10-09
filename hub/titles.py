"""Look up a clip's title from its link (YouTube oEmbed, else og:title / <title>).

Now that the app is reachable from the internet, the server must not fetch
arbitrary addresses for people: it only follows http(s) links whose host resolves
to public IP addresses, and re-checks every redirect, so the endpoint can't be used
to probe the home network (SSRF).
"""
import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")


def check_public_url(url):
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http(s) links are supported")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        raise ValueError("can't resolve that host") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ValueError("links to private addresses aren't allowed")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_CheckedRedirects)


def http_get(url, limit=512 * 1024):
    check_public_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with _opener.open(req, timeout=8) as res:
        charset = res.headers.get_content_charset() or "utf-8"
        return res.read(limit).decode(charset, errors="replace")


def fetch_title(url):
    """Return the page title for url, or '' if none was found."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http(s) links are supported")

    if parts.hostname in YOUTUBE_HOSTS:
        oembed = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe="")
        try:
            return json.loads(http_get(oembed)).get("title", "")
        except Exception:
            pass  # fall back to scraping the page

    page = http_get(url)
    for pattern in (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title',
        r"<title[^>]*>(.*?)</title>",
    ):
        m = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        if m:
            return " ".join(html.unescape(m.group(1)).split())
    return ""
