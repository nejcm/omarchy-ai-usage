#!/usr/bin/env python3
"""One-shot collector for local AI agent subscription usage.

Reads each provider's local credential file, queries that provider's quota
endpoint, and prints one normalized JSON document. Tokens never reach stdout,
stderr, argv, or disk; error paths carry bounded codes only.
"""

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


def request(method: str, url: str, hosts, headers: dict, body=None, timeout: float = TIMEOUT):
    """Perform one HTTP call, refusing any host outside the provider's list.

    Returns a common.Response; transport failures and disallowed hosts become a
    status-0 response with a bounded error code rather than an exception.
    """
    if urlsplit(url).hostname not in hosts:
        return common.Response(0, None, "host-not-allowed")
    merged = {"User-Agent": "omarchy-ai-usage/1.0", "Accept": "application/json"}
    merged.update(headers)
    http_request = urllib.request.Request(url, data=body, method=method, headers=merged)
    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            raw = response.read()
            try:
                data = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                data = None
            return common.Response(response.status, data)
    except urllib.error.HTTPError as error:
        return common.Response(error.code, None)
    except (socket.timeout, TimeoutError):
        return common.Response(0, None, "timeout")
    except urllib.error.URLError:
        return common.Response(0, None, "network")
    except OSError:
        return common.Response(0, None, "network")


def collect_all(home: str, env: dict, request_fn=request, select=None) -> list:
    modules = providers.REGISTRY
    if select:
        modules = [module for module in modules if module.ID in select]
    return [module.collect(request_fn, home, env) for module in modules]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Print local AI agent subscription usage as JSON")
    parser.add_argument("--home", default=None, help="override the home directory (tests)")
    parser.add_argument("--provider", action="append", default=None, help="only this provider id (repeatable)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    home = os.path.expanduser(args.home) if args.home else os.path.expanduser("~")

    def request_fn(method, url, hosts, headers, body=None):
        return request(method, url, hosts, headers, body, args.timeout)

    document = {
        "refreshedAt": common.now_iso(),
        "providers": collect_all(home, os.environ, request_fn, args.provider),
    }
    json.dump(document, sys.stdout, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
