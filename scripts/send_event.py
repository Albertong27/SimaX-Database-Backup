"""Sign a webhook or MQTT event for one configured SimaX policy."""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simax.db import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport", choices=["webhook", "mqtt"])
    parser.add_argument("--policy", required=True)
    parser.add_argument("--event-id", default=None, help="Reuse this ID when retrying the same event")
    parser.add_argument("--data-dir", default="data", help="Local encrypted catalog, unlocked by the same OS account")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    event_id = args.event_id or uuid4().hex
    if not re.fullmatch(r"pol_[a-f0-9]{16}", args.policy) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", event_id):
        parser.error("Use a saved policy ID and a 1–128 character event ID.")
    if not (Path(args.data_dir) / "simax.sqlite3").is_file():
        parser.error("The encrypted catalog does not exist.")
    try:
        policy = Store(Path(args.data_dir)).get("policies", args.policy)
    except (ValueError, LookupError, OSError):
        parser.error("Cannot unlock the selected policy. Use its original catalog, key and OS account.")
    if policy["trigger"] != args.transport:
        parser.error("Transport must match the saved policy.")
    secret = policy.get("event_secret", "")
    if len(secret.encode()) < 32:
        parser.error("Save an event signing secret of at least 32 bytes in the policy.")
    timestamp = int(time.time())
    body = json.dumps({"event_id": event_id}, separators=(",", ":")).encode()
    signed_payload = body if args.transport == "webhook" else event_id.encode()
    message = args.policy.encode() + b"\n" + str(timestamp).encode() + b"\n" + signed_payload
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    try:
        if args.transport == "webhook":
            url = urlsplit(args.base_url)
            if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost"} or url.username or url.query or url.fragment or url.path not in {"", "/"}:
                parser.error("The management webhook is loopback-only; use http://127.0.0.1:PORT.")
            request = Request(args.base_url.rstrip("/") + "/api/triggers/webhook/" + args.policy, data=body,
                              headers={"Content-Type": "application/json", "X-SimaX-Request": "1",
                                       "X-SimaX-Timestamp": str(timestamp), "X-SimaX-Signature": signature})
            with urlopen(request, timeout=15) as response:
                print(f"HTTP {response.status}: accepted for durable intake; backup completion is separate. Event ID: {event_id}")
        else:
            import paho.mqtt.publish as publish
            payload = json.dumps({"event_id": event_id, "timestamp": timestamp, "signature": signature})
            tls = None if not policy["mqtt_tls"] else {"ca_certs": os.environ.get("SIMAX_MQTT_CA_CERT") or None}
            publish.single(policy["mqtt_topic"], payload, qos=1, retain=False, hostname=policy["mqtt_host"], port=policy["mqtt_port"],
                           auth={"username": policy["mqtt_username"], "password": policy["mqtt_password"]} if policy["mqtt_username"] else None, tls=tls)
            print(f"MQTT publish acknowledged by broker; verify SimaX intake separately. Event ID: {event_id}")
    except HTTPError as error:
        print(f"Webhook rejected with HTTP {error.code}. Check policy, signature and event identity; raw response withheld.")
        return 1
    except Exception:
        print("Delivery failed. Check connectivity, credentials, certificates and policy configuration; retry using the same event ID.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
