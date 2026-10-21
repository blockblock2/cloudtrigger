"""Watch a Scratch project's cloud variables and react to changes."""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

import websocket

from .encoding import decode, encode
from .session import UA, LoginError, login

LOGIN_HINT = ("If the password is right, Scratch is probably limiting logins after too many "
              "tries: wait 15-30 minutes, or pass session_id= from your browser's "
              "scratchsessionsid cookie so no login is needed.")

log = logging.getLogger("cloudtrigger")

CLOUD_URL = "wss://clouddata.scratch.mit.edu"
SERVERS = {
    "scratch": CLOUD_URL,
    "turbowarp": "wss://clouddata.turbowarp.org",
}
CLOUD_PREFIX = "☁ "  # "☁ "
MAX_LEN = 256
VALUE_RE = re.compile(r"^-?\d*\.?\d+(e[+-]?\d+)?$|^-?\d+\.?$", re.I)

Value = Union[int, float, str]

# Close codes the Scratch cloud server uses
CLOSE_REASONS = {
    4000: "generic error",
    4002: "username/session not accepted (log in again, or the account can't use cloud data)",
    4003: "cloud server overloaded, try again later",
    4004: "project unavailable (wrong project ID, project not saved, or no cloud variables)",
    4005: "security error (blocked origin or session)",
}
FATAL_CODES = {4002, 4004, 4005}
HINTS = ("Check: the project ID is right, the project is saved and has at least one "
         "cloud variable, and the account is a full Scratcher (not 'New Scratcher').")


class CloudClosed(ConnectionError):
    def __init__(self, code: Optional[int], reason: str = ""):
        self.code, self.reason = code, reason
        meaning = CLOSE_REASONS.get(code, "") if code else "no close code"
        super().__init__(f"code {code}: {meaning}{' — ' + reason if reason else ''}")


def full_name(name: str) -> str:
    """'score' -> '☁ score' (leaves names that already have the cloud prefix alone)."""
    return name if name.startswith(CLOUD_PREFIX) else CLOUD_PREFIX + name


def short_name(name: str) -> str:
    return name[len(CLOUD_PREFIX):] if name.startswith(CLOUD_PREFIX) else name


def check_value(value: Value) -> str:
    """Scratch cloud variables only hold numbers up to 256 characters."""
    s = str(value)
    if not VALUE_RE.match(s):
        raise ValueError(f"Cloud variables can only hold numbers, got {value!r}. "
                         "Use cloudtrigger.encode() to store text.")
    if len(s) > MAX_LEN:
        raise ValueError(f"Cloud values max out at {MAX_LEN} characters (got {len(s)}).")
    return s


@dataclass
class Change:
    """One detected change to a cloud variable."""
    name: str            # short name, e.g. "score"
    value: str           # new value (always a string, like Scratch sends it)
    old: Optional[str]   # previous value we knew about (None if first time seen)
    cloud: "CloudWatcher"
    initial: bool = False  # True for the values Scratch sends right after connecting

    @property
    def number(self) -> Union[int, float]:
        """The value as a number (int when it's a whole number)."""
        f = float(self.value)
        return int(f) if f.is_integer() and "e" not in self.value.lower() else f

    def set(self, name: str, value: Value) -> None:
        """Shortcut so handlers can do `change.set("reply", 1)`."""
        self.cloud.set(name, value)

    @property
    def text(self) -> str:
        """The value decoded from digits back into text (see cloudtrigger.encode)."""
        return decode(self.value)

    def set_text(self, name: str, text: str) -> None:
        """Encode text and put it in a cloud variable: `change.set_text("reply", "hi")`."""
        self.cloud.set_text(name, text)


Handler = Callable[[Change], Any]


class CloudWatcher:
    """
    Connect to a project's cloud variables, run handlers when they change,
    and set variables back.

        cloud = CloudWatcher(1234567890, "user", password="...")

        @cloud.on_change("request")
        def answer(change):
            change.set("response", change.number * 2)

        cloud.run()
    """

    def __init__(
        self,
        project_id: Union[int, str],
        username: Optional[str] = None,
        password: Optional[str] = None,
        session_id: Optional[str] = None,
        min_interval: float = 0.11,
        fire_on_initial: bool = False,
        reconnect: bool = True,
        server: str = "scratch",
    ):
        """
        server: "scratch" (needs password or session_id), "turbowarp" (no login;
        run the project at turbowarp.org/<id>), or any wss:// URL.

        username: your Scratch username. For TurboWarp it must be a real Scratch
        account or "player" + digits; leave it out and a "player123456" name is picked.
        """
        if server in SERVERS:
            self.server, self.url = server, SERVERS[server]
        elif server.startswith(("ws://", "wss://")):
            self.server, self.url = "custom", server
        else:
            raise ValueError(f"server must be one of {list(SERVERS)} or a wss:// URL")
        if self.server == "scratch" and not (password or session_id):
            raise ValueError("Give either password= or session_id= (or use server='turbowarp').")
        self.project_id = str(project_id)
        if not username:
            if self.server == "scratch":
                raise ValueError("username is required for server='scratch'.")
            username = f"player{random.randint(100000, 9999999)}"
        self.username = username
        self._password = password
        self.session_id = session_id
        self.min_interval = min_interval        # Scratch drops sets faster than ~10/sec
        self.fire_on_initial = fire_on_initial
        self.reconnect = reconnect

        self.values: dict[str, str] = {}        # short name -> current value
        self._handlers: dict[Optional[str], list[Handler]] = {}
        self._rules: list[Callable[[Change], None]] = []
        self._ws: Optional[websocket.WebSocket] = None
        self._send_lock = threading.Lock()
        self._last_send = 0.0
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._initial_until = 0.0
        self._error: Optional[BaseException] = None

    # ---------- registering reactions ----------

    def on_change(self, *names: str) -> Callable[[Handler], Handler]:
        """Decorator: run when any of the named variables changes (no names = any variable)."""
        def deco(fn: Handler) -> Handler:
            for n in (names or (None,)):
                key = short_name(n) if n else None
                self._handlers.setdefault(key, []).append(fn)
            return fn
        return deco

    def on_any(self, fn: Handler) -> Handler:
        """Decorator: run on every change."""
        return self.on_change()(fn)

    def when(
        self,
        name: str,
        *,
        equals: Optional[Value] = None,
        above: Optional[float] = None,
        below: Optional[float] = None,
        test: Optional[Callable[[str], bool]] = None,
        set: Optional[dict[str, Union[Value, Callable[[Change], Value]]]] = None,
        then: Optional[Handler] = None,
    ) -> "CloudWatcher":
        """
        Simple rule without writing a function:

            cloud.when("door", equals=1, set={"light": 1})
            cloud.when("score", above=100, set={"winner": lambda c: c.value})
        """
        target = short_name(name)

        def rule(change: Change) -> None:
            if change.name != target:
                return
            v = change.value
            if equals is not None and v != str(equals):
                return
            try:
                if above is not None and not float(v) > above:
                    return
                if below is not None and not float(v) < below:
                    return
            except ValueError:
                return
            if test is not None and not test(v):
                return
            for k, val in (set or {}).items():
                change.set(k, val(change) if callable(val) else val)
            if then:
                then(change)

        self._rules.append(rule)
        return self

    def mirror(self, source: str, dest: str, transform: Optional[Callable[[str], Value]] = None):
        """Copy `source` into `dest` every time it changes (optionally transformed)."""
        return self.when(source, set={dest: lambda c: transform(c.value) if transform else c.value})

    # ---------- reading / writing ----------

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.values.get(short_name(name), default)

    def set(self, name: str, value: Value) -> None:
        """Set a cloud variable. Rate-limited so Scratch doesn't drop it."""
        s = check_value(value)
        if not self._connected.wait(timeout=30):
            raise ConnectionError("Not connected to Scratch cloud.")
        with self._send_lock:
            wait = self.min_interval - (time.monotonic() - self._last_send)
            if wait > 0:
                time.sleep(wait)
            self._send({"method": "set", "name": full_name(name), "value": s})
            self._last_send = time.monotonic()
        self.values[short_name(name)] = s
        log.info("set %s = %s", short_name(name), s)

    def set_text(self, name: str, text: str) -> None:
        """Encode text into digits and set it. Max 128 characters (256 digits)."""
        digits = encode(text)
        if len(digits) > MAX_LEN:
            raise ValueError(f"Text too long for one cloud variable: {len(text)} chars (max {MAX_LEN // 2}).")
        self.set(name, digits)

    def get_text(self, name: str, default: str = "") -> str:
        v = self.get(name)
        return decode(v) if v not in (None, "", "0") else default

    # ---------- connection ----------

    def _send(self, payload: dict) -> None:
        payload = {**payload, "user": self.username, "project_id": self.project_id}
        assert self._ws is not None
        self._ws.send(json.dumps(payload) + "\n")

    def _connect(self) -> None:
        kw: dict = {"header": [f"User-Agent: {UA}"], "timeout": 10}
        if self.server == "scratch":
            if not self.session_id:
                log.info("logging in as %s", self.username)
                self.session_id = login(self.username, self._password)  # type: ignore[arg-type]
            sid = self.session_id.strip().strip('"')  # requests may keep Scratch's quotes
            kw.update(origin="https://scratch.mit.edu", cookie=f'scratchsessionsid="{sid}";')
        elif self.server == "turbowarp":
            kw.update(origin="https://turbowarp.org")
        self._ws = websocket.create_connection(self.url, **kw)
        self._ws.settimeout(None)
        self._send({"method": "handshake"})
        self._initial_until = time.monotonic() + 1.5
        self._connected.set()
        log.info("connected to project %s on %s", self.project_id, self.server)

    def _dispatch(self, change: Change) -> None:
        for fn in self._handlers.get(change.name, []) + self._handlers.get(None, []):
            self._safe(fn, change)
        for rule in self._rules:
            self._safe(rule, change)

    def _safe(self, fn: Callable, change: Change) -> None:
        try:
            fn(change)
        except Exception:
            log.exception("handler %s failed on %s=%s",
                          getattr(fn, "__name__", fn), change.name, change.value)

    def _handle_line(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        if msg.get("method") != "set":
            return
        name = short_name(msg.get("name", ""))
        value = str(msg.get("value"))
        initial = time.monotonic() < self._initial_until
        old = self.values.get(name)
        self.values[name] = value
        if old == value:
            return
        if initial and not self.fire_on_initial:
            log.debug("initial %s = %s", name, value)
            return
        log.info("change %s: %s -> %s", name, old, value)
        self._dispatch(Change(name, value, old, self, initial))

    def _receive_forever(self) -> None:
        ws = self._ws
        assert ws is not None
        while not self._stop.is_set():
            opcode, data = ws.recv_data(control_frame=True)
            if opcode == websocket.ABNF.OPCODE_CLOSE:
                code = int.from_bytes(data[:2], "big") if len(data) >= 2 else None
                reason = data[2:].decode("utf-8", "replace") if len(data) > 2 else ""
                raise CloudClosed(code, reason)
            if opcode == websocket.ABNF.OPCODE_PING:
                ws.pong(data)
                continue
            if opcode not in (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY):
                continue
            self._got_data = True
            text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
            for line in text.split("\n"):
                if line.strip():
                    self._handle_line(line)

    def run(self) -> None:
        """Connect and process changes until stop() or Ctrl+C."""
        if not logging.getLogger().handlers and not log.handlers:
            # nobody set up logging: show cloudtrigger's messages anyway
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
            log.addHandler(h)
            log.setLevel(logging.INFO)
        backoff = 2
        quick_drops = 0
        while not self._stop.is_set():
            self._got_data = False
            started = time.monotonic()
            try:
                self._connect()
                self._receive_forever()
            except KeyboardInterrupt:
                break
            except LoginError as e:
                # Retrying a failed login just gets you blocked for longer.
                self._error = e
                self.close()
                log.error("%s. %s", e, LOGIN_HINT)
                raise
            except Exception as e:
                self._error = e
                self._connected.clear()
                self.close()
                if self._stop.is_set():
                    break
                fatal = isinstance(e, CloudClosed) and e.code in FATAL_CODES
                if isinstance(e, CloudClosed) and e.code == 4002:
                    # bad session: log in again once before giving up
                    if self._password and not getattr(self, "_relogged", False):
                        self._relogged = True
                        self.session_id = None
                        fatal = False
                if self._got_data or time.monotonic() - started > 30:
                    quick_drops, backoff = 0, 2
                elif isinstance(e, CloudClosed):
                    # the server keeps hanging up on us: something's wrong with the setup.
                    # Plain network errors don't count, so a server bot keeps retrying.
                    quick_drops += 1
                if fatal or not self.reconnect or quick_drops >= 4:
                    log.error("Scratch closed the cloud connection: %s", e)
                    if not fatal:
                        log.error("It kept closing right after connecting. %s", HINTS)
                    raise
                log.warning("disconnected (%s); reconnecting in %ss", e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        self.close()

    def start(self) -> threading.Thread:
        """Run in a background thread; returns the thread."""
        t = threading.Thread(target=self.run, daemon=True, name="cloudtrigger")
        t.start()
        deadline = time.monotonic() + 30
        while not self._connected.is_set() and t.is_alive() and time.monotonic() < deadline:
            self._connected.wait(timeout=0.2)
        if not self._connected.is_set():
            raise ConnectionError(f"Couldn't connect: {self._error}") from self._error
        return t

    def stop(self) -> None:
        self._stop.set()
        self.close()

    def close(self) -> None:
        self._connected.clear()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
