#!/usr/bin/env python3
"""One-shot collector: print subscription quota or local token usage JSON."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import providers
import local_usage.claude
import local_usage.codex
import local_usage.opencode
import local_usage.report
import local_usage.scan
from providers import common

TIMEOUT = 10
USAGE_SOURCES = {"claude": local_usage.claude.source, "codex": local_usage.codex.source, "opencode": local_usage.opencode.query}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def request(method: str, url: str, hosts, headers: dict, body=None, timeout: float = TIMEOUT, error_body: bool = False):
    """One allow-listed, non-redirecting HTTP call returning a bounded Response."""
    if urlsplit(url).hostname not in hosts:
        return common.Response(0, None, "host-not-allowed")
    # urllib's default User-Agent is blocked by OpenCode's WAF.
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

    def collect(module):
        try:
            return module.collect(request_fn, home, env)
        except Exception:
            return common.error_row((module.ID, module.NAME, module.ABBREV), "internal-error")

    rows = [collect(module) if getattr(module, "MAIN_THREAD", False) else None for module in modules]
    pooled = [index for index, module in enumerate(modules) if not getattr(module, "MAIN_THREAD", False)]
    with ThreadPoolExecutor(max_workers=max(1, len(pooled))) as executor:
        for index, row in zip(pooled, executor.map(collect, [modules[index] for index in pooled])):
            rows[index] = row
    return rows


def usage_document(home: str, env: dict, select=None) -> dict:
    """Scan the selected local logs and aggregate the usage windows."""
    selected = [provider for provider in USAGE_SOURCES if select is None or provider in select]
    connection = local_usage.scan.open_database(local_usage.scan.database_path(home, env))
    moment = time.time()
    try:
        result = local_usage.scan.scan(connection, [USAGE_SOURCES[provider](home, env) for provider in selected],
                                       now=moment, budget=local_usage.scan.BUDGET_BYTES)
        available = local_usage.report.windows(connection, moment, selected)
    finally:
        connection.close()
    return {"scanning": result.pending, "windows": available}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Print local AI agent subscription usage as JSON")
    parser.add_argument("--home", default=None, help="override the home directory (tests)")
    parser.add_argument("--provider", action="append", default=None, help="only this provider id (repeatable)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT)
    parser.add_argument("--usage", action="store_true", help="scan local logs for token usage instead")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    home = os.path.expanduser(args.home) if args.home else os.path.expanduser("~")

    if args.usage:
        document = {"usage": usage_document(home, os.environ, args.provider)}
    else:
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
