#!/usr/bin/env python3
"""One-shot collector: read local agent credentials, print normalized usage JSON."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import providers
from providers import common

TIMEOUT = 10


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def request(method: str, url: str, hosts, headers: dict, body=None, timeout: float = TIMEOUT, error_body: bool = False):
    """One allow-listed, non-redirecting HTTP call returning a bounded Response."""
    if urlsplit(url).hostname not in hosts:
        return common.Response(0, None, "host-not-allowed")
    merged = {"User-Agent": "omarchy-ai-usage/1.0", "Accept": "application/json"}
    merged.update(headers)
    for value in merged.values():
        if any(char in str(value) for char in "\r\n\0"):
            return common.Response(0, None, "invalid-auth")
    try:
        http_request = urllib.request.Request(url, data=body, method=method, headers=merged)
        with _OPENER.open(http_request, timeout=timeout) as response:
            raw = response.read()
            try:
                data = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                data = None
            return common.Response(response.status, data)
    except urllib.error.HTTPError as error:
        data = None
        if error_body:
            try:
                data = json.loads(error.read(4096).decode("utf-8", "replace"))
            except (ValueError, OSError):
                data = None
        return common.Response(error.code, data)
    except (socket.timeout, TimeoutError):
        return common.Response(0, None, "timeout")
    except urllib.error.URLError:
        return common.Response(0, None, "network")
    except ValueError:
        return common.Response(0, None, "invalid-request")
    except Exception:
        return common.Response(0, None, "network")


def collect_all(home: str, env: dict, request_fn=request, select=None) -> list:
    modules = providers.REGISTRY
    if select is not None:
        modules = [module for module in modules if module.ID in select]
    rows = []
    for module in modules:
        try:
            rows.append(module.collect(request_fn, home, env))
        except Exception:
            rows.append(common.error_row((module.ID, module.NAME, module.ABBREV), "internal-error"))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Print local AI agent subscription usage as JSON")
    parser.add_argument("--home", default=None, help="override the home directory (tests)")
    parser.add_argument("--provider", action="append", default=None, help="only this provider id (repeatable)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    home = os.path.expanduser(args.home) if args.home else os.path.expanduser("~")

    def request_fn(method, url, hosts, headers, body=None, error_body=False):
        return request(method, url, hosts, headers, body, args.timeout, error_body=error_body)

    document = {
        "refreshedAt": common.now_iso(),
        "providers": collect_all(home, os.environ, request_fn, args.provider),
    }
    json.dump(document, sys.stdout, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
