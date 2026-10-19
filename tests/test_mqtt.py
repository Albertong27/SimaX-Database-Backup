"""Paho integration against an isolated scripted MQTT 3.1.1 TCP broker."""

import json
import queue
import socket
import struct
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from simax.mqtt import MqttManager
from test_app import setup  # noqa: F401
from test_events import SECRET, event_policy, signed


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    pytest.fail("MQTT test condition timed out")


def packet(kind, body):
    size = len(body)
    encoded = bytearray([kind])
    while True:
        part = size % 128
        size //= 128
        encoded.append(part | (128 if size else 0))
        if not size:
            return bytes(encoded) + body


def read_packet(sock):
    first = sock.recv(1)
    if not first:
        raise EOFError
    size, multiplier = 0, 1
    while True:
        part = sock.recv(1)[0]
        size += (part & 127) * multiplier
        if part < 128:
            break
        multiplier *= 128
    body = bytearray()
    while len(body) < size:
        chunk = sock.recv(size - len(body))
        if not chunk:
            raise EOFError
        body.extend(chunk)
    return first[0], bytes(body)


@pytest.fixture
def broker():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    commands, acks, connections, errors = queue.Queue(), [], [], []
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                sock, _ = listener.accept()
            except socket.timeout:
                continue
            with sock:
                sock.settimeout(1)
                try:
                    kind, body = read_packet(sock)
                    assert kind == 0x10 and body[7] & 2  # clean session
                    sock.sendall(packet(0x20, b"\x00\x00"))
                    kind, body = read_packet(sock)
                    assert kind == 0x82
                    length = int.from_bytes(body[2:4], "big")
                    assert body[4:4 + length].decode() == "simax/fixture" and body[-1] == 1
                    sock.sendall(packet(0x90, body[:2] + b"\x01"))
                    connections.append(True)
                    sock.settimeout(0.05)
                    while not stop.is_set():
                        try:
                            item = commands.get_nowait()
                            if item == "disconnect":
                                break
                            sock.sendall(item)
                        except queue.Empty:
                            pass
                        try:
                            kind, body = read_packet(sock)
                            if kind == 0x40:
                                acks.append(int.from_bytes(body, "big"))
                            elif kind == 0xC0:
                                sock.sendall(packet(0xD0, b""))
                            elif kind == 0xE0:
                                break
                        except socket.timeout:
                            continue
                except (EOFError, ConnectionError):
                    pass
                except Exception as error:
                    errors.append(error)
        listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield SimpleNamespace(port=listener.getsockname()[1], commands=commands, acks=acks, connections=connections)
    stop.set()
    thread.join(3)
    assert not thread.is_alive()
    assert not errors


def message(policy, event_id, mid, *, retained=False, topic="simax/fixture", expired=False, qos=1):
    stamp = int(time.time()) - (600 if expired else 0)
    signature = signed(policy, event_id.encode(), timestamp=stamp)["X-SimaX-Signature"]
    payload = json.dumps({"event_id": event_id, "timestamp": stamp, "signature": signature}).encode()
    topic = topic.encode()
    return packet(0x30 | (qos << 1) | int(retained), struct.pack("!H", len(topic)) + topic + (struct.pack("!H", mid) if qos else b"") + payload)


def test_real_paho_delivery_duplicates_retained_topics_and_reconnect(setup, monkeypatch, broker):
    client, service, _ = setup
    monkeypatch.setenv("SIMAX_SECRET_EVENTS", SECRET)
    policy = event_policy(client, service, "mqtt", mqtt_host="127.0.0.1", mqtt_port=broker.port,
                          mqtt_topic="simax/fixture", mqtt_tls=False)
    manager = MqttManager(service.events)
    try:
        manager.reconcile([policy])
        wait_until(lambda: len(broker.connections) == 1)
        for payload in [message(policy, "retained", 1, retained=True), message(policy, "valid", 2),
                        message(policy, "valid", 3), message(policy, "other", 4, topic="other/topic"),
                        message(policy, "old", 5, expired=True), message(policy, "qos-zero", 0, qos=0)]:
            broker.commands.put(payload)
        wait_until(lambda: set(broker.acks) == {1, 2, 3, 4, 5})
        assert service.store.get("trigger_state", policy["id"])["pending"]["count"] == 1
        broker.commands.put("disconnect")
        wait_until(lambda: len(broker.connections) == 2)
        broker.commands.put(message(policy, "valid", 6))
        wait_until(lambda: 6 in broker.acks)
        assert service.store.get("trigger_state", policy["id"])["pending"]["count"] == 1
        service.events.dispatch(time.time() + 11)
        assert len(service.store.all("runs")) == 1
        assert service.store.all("runs")[0]["origin"] == "mqtt"
        service.execute(service.store.all("runs")[0])
        assert service.store.all("runs")[0]["status"] == "succeeded"
        assert len(service.store.all("artifacts")) == 1
        manager.reconcile([])
        assert not manager.clients
    finally:
        manager.close()


def test_persistence_failure_is_not_acknowledged(setup, monkeypatch):
    client, service, _ = setup
    monkeypatch.setenv("SIMAX_SECRET_EVENTS", SECRET)
    policy = event_policy(client, service, "mqtt", mqtt_tls=False)
    manager = MqttManager(service.events)
    subscriber = manager.build(policy)
    transport = Mock()
    event_id = "storage-failure"
    stamp = int(time.time())
    signature = signed(policy, event_id.encode(), timestamp=stamp)["X-SimaX-Signature"]
    msg = SimpleNamespace(topic=policy["mqtt_topic"], retain=False, qos=1, mid=7,
                          payload=json.dumps({"event_id": event_id, "timestamp": stamp, "signature": signature}).encode())
    monkeypatch.setattr(service.events, "receive", Mock(side_effect=RuntimeError("disk full")))
    subscriber.on_message(transport, None, msg)
    transport.ack.assert_not_called()
    transport.disconnect.assert_called_once()


def test_tls_and_broker_password_configuration(setup, monkeypatch):
    client, service, _ = setup
    monkeypatch.setenv("SIMAX_SECRET_EVENTS", SECRET)
    monkeypatch.setenv("SIMAX_SECRET_BROKER", "isolated-broker-password")
    policy = event_policy(client, service, "mqtt", mqtt_username="fixture", mqtt_password="isolated-broker-password")
    transport = Mock()
    monkeypatch.setattr("simax.mqtt.mqtt.Client", Mock(return_value=transport))
    MqttManager(service.events).build(policy)
    transport.tls_set.assert_called_once_with(ca_certs=None)
    transport.tls_insecure_set.assert_not_called()
    transport.username_pw_set.assert_called_once_with("fixture", "isolated-broker-password")
