import json

import pytest

from cloudtrigger import CloudWatcher, decode, encode
from cloudtrigger.cli import add_rule, parse_rule
from cloudtrigger.cloud import check_value


class FakeWS:
    def __init__(self):
        self.sent = []

    def send(self, s):
        self.sent.append(json.loads(s))


def make():
    c = CloudWatcher(1, "me", session_id="x", min_interval=0)
    c._ws = FakeWS()
    c._connected.set()
    return c


def push(c, name, value):
    c._handle_line(json.dumps({"method": "set", "name": "☁ " + name, "value": value}))


def sets(c):
    return [(m["name"], m["value"]) for m in c._ws.sent if m["method"] == "set"]


def test_handler_sets_variable():
    c = make()

    @c.on_change("a")
    def h(ch):
        ch.set("b", ch.number + 1)

    push(c, "a", "5")
    assert sets(c) == [("☁ b", "6")]


def test_no_fire_when_value_same():
    c = make()
    hits = []
    c.on_any(lambda ch: hits.append(ch.value))
    push(c, "a", "1")
    push(c, "a", "1")
    assert hits == ["1"]


def test_initial_values_skipped():
    c = make()
    hits = []
    c.on_any(lambda ch: hits.append(ch))
    import time
    c._initial_until = time.monotonic() + 10
    push(c, "a", "1")
    assert hits == [] and c.get("a") == "1"


def test_when_rules():
    c = make()
    c.when("door", equals=1, set={"light": 1})
    c.when("score", above=100, set={"win": lambda ch: ch.value})
    push(c, "door", "0")
    push(c, "door", "1")
    push(c, "score", "50")
    push(c, "score", "150")
    assert sets(c) == [("☁ light", "1"), ("☁ win", "150")]


def test_handler_error_doesnt_crash():
    c = make()
    c.on_any(lambda ch: 1 / 0)
    c.mirror("a", "b")
    push(c, "a", "3")
    assert sets(c) == [("☁ b", "3")]


def test_value_checks():
    assert check_value(12) == "12"
    assert check_value("-1.5") == "-1.5"
    with pytest.raises(ValueError):
        check_value("hello")
    with pytest.raises(ValueError):
        check_value("1" * 257)


def test_encode_roundtrip():
    assert decode(encode("Hi there!")) == "Hi there!"
    assert encode("ab").isdigit()


def test_cli_rules():
    c = make()
    for r in ["door=1 -> light=1, fan=2", "score>10 -> echo=$value", "x=* -> y=9"]:
        add_rule(c, parse_rule(r))
    push(c, "door", "1")
    push(c, "score", "5")
    push(c, "score", "11")
    push(c, "x", "4")
    assert sets(c) == [("☁ light", "1"), ("☁ fan", "2"), ("☁ echo", "11"), ("☁ y", "9")]


def test_close_code_stops_with_reason(monkeypatch):
    import websocket
    from cloudtrigger.cloud import CloudClosed

    c = CloudWatcher(1, "me", session_id='"abc"', min_interval=0)

    class WS(FakeWS):
        def recv_data(self, control_frame=False):
            return websocket.ABNF.OPCODE_CLOSE, (4004).to_bytes(2, "big")
        def close(self):
            pass
        def settimeout(self, t):
            pass

    seen = {}
    def fake_conn(url, **kw):
        seen["cookie"] = kw["cookie"]
        return WS()
    monkeypatch.setattr(websocket, "create_connection", fake_conn)
    with pytest.raises(CloudClosed) as e:
        c.run()
    assert e.value.code == 4004 and "project unavailable" in str(e.value)
    assert seen["cookie"] == 'scratchsessionsid="abc";'


def test_turbowarp_needs_no_login(monkeypatch):
    import websocket
    from cloudtrigger.cloud import CloudClosed

    c = CloudWatcher(1, "mybot", server="turbowarp", min_interval=0)
    seen = {}

    class WS(FakeWS):
        def recv_data(self, control_frame=False):
            return websocket.ABNF.OPCODE_CLOSE, (4004).to_bytes(2, "big")
        def close(self): pass
        def settimeout(self, t): pass

    def fake_conn(url, **kw):
        seen.update(kw, url=url)
        return WS()
    monkeypatch.setattr(websocket, "create_connection", fake_conn)
    with pytest.raises(CloudClosed):
        c.run()
    assert seen["url"] == "wss://clouddata.turbowarp.org"
    assert "cookie" not in seen and seen["origin"] == "https://turbowarp.org"


def test_scratch_still_requires_login():
    with pytest.raises(ValueError):
        CloudWatcher(1, "me")


def test_login_failure_stops_without_retrying(monkeypatch):
    import cloudtrigger.cloud as cc
    from cloudtrigger import LoginError

    calls = []
    def bad_login(u, p):
        calls.append(1)
        raise LoginError("Scratch login failed (403): Something went wrong")
    monkeypatch.setattr(cc, "login", bad_login)
    c = CloudWatcher(1, "me", password="pw")
    with pytest.raises(LoginError):
        c.run()
    assert len(calls) == 1
    c2 = CloudWatcher(1, "me", password="pw")
    with pytest.raises(ConnectionError):
        c2.start()


def test_decode_survives_lost_leading_zero():
    d = encode("hi there")
    assert d.startswith("0")
    assert decode(d.lstrip("0")) == "hi there"
    assert decode(float(d.lstrip("0")) if len(d) < 15 else d) == "hi there"


def test_text_helpers():
    c = make()

    @c.on_change("request")
    def h(ch):
        ch.set_text("response", ch.text.upper())

    push(c, "request", encode("hey"))
    assert decode(sets(c)[0][1]) == "HEY"
    with pytest.raises(ValueError):
        c.set_text("x", "a" * 129)
