"""Sign a webhook or MQTT event for one configured SimaX policy."""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport", choices=["webhook", "mqtt"])
    parser.add_argument("--policy", required=True)
    parser.add_argument("--event-id", default=None, help="Reuse this ID when retrying the same event")
    parser.add_argument("--secret-env", default="SIMAX_SECRET_EVENTS")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=8883)
    parser.add_argument("--topic", default="simax/backup")
    parser.add_argument("--no-tls", action="store_true", help="Only for explicitly trusted private broker transport")
    parser.add_argument("--username", default="")
    parser.add_argument("--password-env", default="")
    args = parser.parse_args()
    event_id = args.event_id or uuid4().hex
    if not re.fullmatch(r"pol_[a-f0-9]{16}", args.policy) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", event_id):
        parser.error("Use a saved policy ID and a 1–128 character event ID.")
    if not re.fullmatch(r"SIMAX_SECRET_[A-Z0-9_]{1,80}", args.secret_env):
        parser.error("Use a SIMAX_SECRET_ signing-key reference.")
    load_dotenv(Path(args.env_file), override=False, interpolate=False, encoding="utf-8-sig")
    secret = os.environ.get(args.secret_env, "")
    if len(secret.encode()) < 32:
        parser.error("Set the event signing secret to at least 32 bytes.")
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
            if bool(args.username) != bool(args.password_env):
                parser.error("Set both broker username and password reference, or neither.")
            if args.password_env and not re.fullmatch(r"SIMAX_SECRET_[A-Z0-9_]{1,80}", args.password_env):
                parser.error("Use a SIMAX_SECRET_ broker password reference.")
            password = os.environ.get(args.password_env) if args.password_env else None
            if args.password_env and password is None:
                parser.error("Broker password variable is missing.")
            if not args.topic or any(c in args.topic for c in ("+", "#", "\x00")):
                parser.error("Use the policy's exact MQTT topic without wildcards.")
            payload = json.dumps({"event_id": event_id, "timestamp": timestamp, "signature": signature})
            tls = None if args.no_tls else {"ca_certs": os.environ.get("SIMAX_MQTT_CA_CERT") or None}
            publish.single(args.topic, payload, qos=1, retain=False, hostname=args.broker, port=args.port,
                           auth={"username": args.username, "password": password} if args.username else None, tls=tls)
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
