"""MQTT 3.1.1 clean-session subscriptions with durable application acknowledgments."""

import os
import time

import paho.mqtt.client as mqtt

from .events import EventRejected, verify_signature
from .models import MqttEvent


class MqttManager:
    def __init__(self, events):
        self.events = events
        self.clients = {}
        self.retry_at = {}
        self.restart = set()

    def build(self, policy):
        if len(policy.get("event_secret", "").encode()) < 32:
            raise EventRejected("Set an event secret of at least 32 bytes.")
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="simax-" + policy["id"],
                             clean_session=True, protocol=mqtt.MQTTv311, manual_ack=True)
        client.connect_timeout = 10
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        if policy["mqtt_username"]:
            password = policy.get("mqtt_password")
            if password is None:
                raise EventRejected("Save a broker password in the policy settings.")
            client.username_pw_set(policy["mqtt_username"], password)
        if policy["mqtt_tls"]:
            client.tls_set(ca_certs=os.environ.get("SIMAX_MQTT_CA_CERT") or None)

        def health(status, message):
            try:
                self.events.health(policy, status, message)
            except Exception:
                pass  # A catalog outage must not prevent disconnect or cause an acknowledgment.

        def connected(client, userdata, flags, reason, properties):
            if reason.is_failure:
                health("degraded", "MQTT broker rejected the connection; check broker credentials and permissions.")
                return
            health("connecting", "MQTT connected; waiting for topic subscription approval. Offline messages are not replayed.")
            result, _ = client.subscribe(policy["mqtt_topic"], qos=1)
            if result != mqtt.MQTT_ERR_SUCCESS:
                health("degraded", "MQTT subscription could not be sent.")

        def subscribed(client, userdata, mid, reasons, properties):
            if len(reasons) != 1 or reasons[0].value != 1:
                health("degraded", "Broker did not grant QoS 1 for the configured topic.")
                self.restart.add(policy["id"])
                client.disconnect()
                return
            health("listening", "MQTT QoS 1 subscription active. Clean sessions have no offline replay; retained messages are rejected.")

        def message(client, userdata, msg):
            try:
                if msg.retain or msg.qos != 1 or msg.topic != policy["mqtt_topic"] or len(msg.payload) > 4096:
                    raise EventRejected("MQTT message is retained, oversized, wrong QoS, or on another topic.")
                event = MqttEvent.model_validate_json(msg.payload)
                verify_signature(policy, event.timestamp, event.signature, event.event_id.encode())
                self.events.receive(policy, event.event_id, "mqtt")
            except ValueError:
                health("rejected", "MQTT message rejected. Check topic, QoS 1, retained flag, event schema, timestamp and signature.")
            except Exception:
                health("degraded", "MQTT event could not be persisted. Intake stopped; republish with the same event ID after recovery.")
                self.restart.add(policy["id"])
                client.disconnect()
                return  # Never acknowledge a valid request that failed to persist.
            client.ack(msg.mid, msg.qos)

        client.on_connect = connected
        client.on_subscribe = subscribed
        client.on_message = message
        client.on_connect_fail = lambda *args: health("degraded", "MQTT connection unavailable; reconnecting. There is an observation gap.")
        client.on_disconnect = lambda *args: health("degraded", "MQTT disconnected. Clean sessions do not preserve offline messages; reconnecting while enabled.")
        return client

    def reconcile(self, policies):
        wanted = {p["id"]: p for p in policies if p["enabled"] and p["trigger"] == "mqtt"}
        for key, (revision, client) in list(self.clients.items()):
            if key not in wanted or wanted[key]["revision"] != revision or key in self.restart:
                client.disconnect()
                client.loop_stop()
                del self.clients[key]
                if key in self.restart:
                    self.restart.discard(key)
                    self.retry_at[key] = time.monotonic() + 30
        for key, policy in wanted.items():
            if key in self.clients or time.monotonic() < self.retry_at.get(key, 0):
                continue
            try:
                client = self.build(policy)
                self.events.health(policy, "connecting", "Connecting to the configured MQTT broker.")
                client.connect_async(policy["mqtt_host"], policy["mqtt_port"], keepalive=30)
                client.loop_start()
                self.clients[key] = (policy["revision"], client)
            except Exception:
                self.events.health(policy, "degraded", "MQTT setup failed. Check event secret, broker credentials and CA certificate configuration.")
                self.retry_at[key] = time.monotonic() + 30

    def close(self):
        for _, client in self.clients.values():
            client.disconnect()
            client.loop_stop()
        self.clients.clear()
