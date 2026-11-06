"""Read-only local monitoring probe; never starts backup or restore jobs."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--policy", help="Optional saved policy ID; otherwise every policy must be enabled and current")
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost"}
            or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
        parser.error("Use a local loopback HTTP URL without credentials or a path.")
    try:
        try:
            response = urlopen(args.base_url.rstrip("/") + "/api/health/protection", timeout=10)
        except HTTPError as error:
            if error.code != 503:
                raise
            response = error
        with response:
            report = json.load(response)
        policies = [p for p in report["policies"] if not args.policy or p["policy_id"] == args.policy]
        ok = report["runtime_running"] and report["storage_ok"] and bool(policies)
        ok = ok and all(p["enabled"] and p["status"] == "current" for p in policies)
        print(json.dumps({"ok": ok, "checked": report["checked"], "runtime_running": report["runtime_running"],
                          "storage_ok": report["storage_ok"], "policies": policies}))
        return 0 if ok else 1
    except (URLError, OSError, ValueError, KeyError, TypeError):
        print("SimaX protection probe failed: runtime unreachable or invalid health response.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
