"""Daily, cheat-proof Hangman for a Scratch project played on TurboWarp.

The secret word only ever lives here, on the server. The Scratch project sends a
guess, and this bot answers with the pattern ("_ a _ _ _"), the wrong letters and
whether you've won or lost. A lost game doesn't reveal the word; it's shown as
"yesterday's word" the next day, so you can't lose once to peek and then win.

One server can run both games: English and Spanish, each in its own project.

Environment variables:
  PROJECT_ID       project ID of the English game
  PROJECT_ID_ES    project ID of the Spanish game (Ahorcado)
  PROJECT_ID_WORDLE project ID of the Wordle game (see wordle.py)   — set at least one of these
  HANGMAN_SECRET   long random text; makes the daily word unguessable (required)
  HANGMAN_TZ       time zone the day changes in (default America/New_York)
  BOT_NAME         cloud username: a real Scratch account or "player" + digits
                   (default: a random player123456 name, as TurboWarp asks bots to use)
  PORT             if set, serves a tiny status page (needed by some free hosts)
  ADMIN_KEY        password for the owner page /admin, which has a "New word" button per game

Messages (both directions are cloudtrigger.encode()'d text in one cloud variable):
  ☁ request   Scratch -> bot   "<player id>|<seq>|start"   or   "<player id>|<seq>|g:<letter>"
  ☁ response  bot -> Scratch   "<player id>|<seq>|<pattern>|<wrong letters>|<play/win/lose>|<extra>"
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import string
import unicodedata
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

log = logging.getLogger("hangman")

MAX_WRONG = 6
MAX_TEXT = 128            # one cloud variable holds 256 digits = 128 characters
WORDS_FILE = Path(__file__).with_name("words.txt")
HERE = Path(__file__).parent
DICTIONARY_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{}"


def load_words(path: Path = WORDS_FILE) -> list[str]:
    words = []
    for line in path.read_text().splitlines():
        w = line.strip().lower()
        if w and not w.startswith("#") and w.isalpha() and w.isascii():
            words.append(w)
    if not words:
        raise SystemExit(f"No words in {path}")
    return words


def lookup_definition(word: str, timeout: float = 6) -> Optional[str]:
    """Return a short dictionary definition, "" if the dictionary has no entry,
    or None if the dictionary couldn't be reached."""
    url = DICTIONARY_URL.format(urllib.parse.quote(word))
    req = urllib.request.Request(url, headers={"User-Agent": "cloudtrigger-hangman"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return "" if e.code == 404 else None
    except Exception:
        return None
    try:
        for entry in data:
            for meaning in entry.get("meanings", []):
                for d in meaning.get("definitions", []):
                    text = d.get("definition", "").strip()
                    if text:
                        pos = meaning.get("partOfSpeech", "")
                        return f"({pos}) {text}" if pos else text
    except AttributeError:
        pass
    return ""


def no_definition(word: str) -> str:
    return "x"   # list is hand-checked: accept every word, show no meaning


# Bot-side text. It travels through cloudtrigger.encode(), which has no accents,
# "ñ" or "¡", so these are written without them (the Scratch side adds its own).
LANGUAGES = {
    "en": {"words": "words.txt", "define": lookup_definition,
           "yesterday": "Yesterday's word: {}", "win": "You got it!",
           "lose": "Out of guesses! See the word tomorrow."},
    "es": {"words": "words_es.txt", "define": no_definition,
           "yesterday": "Palabra de ayer: {}", "win": "",
           "lose": "Se acabaron los intentos. Vuelve luego para ver la palabra."},
}


# Status page address for each game: https://<your server>.onrender.com/<name>
PAGES = {"en": "hangman", "es": "ahorcado", "wordle": "wordle"}


@dataclass
class Game:
    guessed: set = field(default_factory=set)
    wrong: list = field(default_factory=list)


class Hangman:
    def __init__(self, secret: str, words: list[str], tz: str = "America/New_York",
                 define: Callable[[str], Optional[str]] = lookup_definition,
                 today: Optional[Callable[[], dt.date]] = None, lang: str = "en"):
        if len(secret) < 12:
            raise ValueError("HANGMAN_SECRET should be at least 12 random characters.")
        self.secret = secret
        self.words = words
        self.lang = lang
        self.text = LANGUAGES[lang]
        self.define = define
        self.tz = ZoneInfo(tz) if ZoneInfo else None
        self._today = today or (lambda: dt.datetime.now(self.tz).date())
        self._day: Optional[dt.date] = None
        self._games: dict[str, Game] = {}
        self._replies: dict[tuple[str, str, str], str] = {}   # answer retries with the same reply
        self._daily: dict[dt.date, tuple[str, str]] = {}  # day -> (word, definition)
        self._lock = threading.Lock()
        self._word_lock = threading.Lock()
        self._rerolls: dict[dt.date, int] = {}            # day -> how many times "New word" was pressed

    # ---------- daily word ----------
    def word_for(self, day: dt.date) -> tuple[str, str]:
        with self._word_lock:
            return self._word_for(day)

    def _word_for(self, day: dt.date) -> tuple[str, str]:
        if day in self._daily:
            return self._daily[day]
        n = self._rerolls.get(day, 0)
        seed = f"{self.secret}|{day.isoformat()}" + (f"|new{n}" if n else "")
        digest = hashlib.sha256(seed.encode()).digest()
        start = int.from_bytes(digest[:8], "big") % len(self.words)
        chosen = (self.words[start], "")
        for k in range(10):   # use the first candidate the dictionary knows
            w = self.words[(start + k) % len(self.words)]
            d = self.define(w)
            if d is None:      # dictionary unreachable: keep the first word
                break
            if d:
                chosen = (w, "" if d == "x" and self.define is no_definition else d)
                break
        self._daily[day] = chosen
        for old in [d for d in self._daily if d < day - dt.timedelta(days=2)]:
            del self._daily[old]
        return chosen

    def new_word(self) -> int:
        """Owner's "New word" button: pick a different word for today and reset everyone's
        game. Returns the new word's length (the word itself is never shown)."""
        with self._lock:
            day = self._roll_day()
            with self._word_lock:
                old = self._word_for(day)[0]
                new = old
                for _ in range(5):                       # make sure it's actually different
                    self._rerolls[day] = self._rerolls.get(day, 0) + 1
                    self._daily.pop(day, None)
                    new = self._word_for(day)[0]
                    if new != old:
                        break
                for gone in [d for d in self._rerolls if d < day - dt.timedelta(days=2)]:
                    del self._rerolls[gone]
            self._games.clear()
            self._replies.clear()
            log.info("[%s] new word picked by the owner (%d letters)", self.lang, len(new))
            return len(new)

    def _roll_day(self) -> dt.date:
        day = self._today()
        if day != self._day:
            if self._day is not None:
                log.info("new day %s: resetting games", day)
            self._day = day
            self._games.clear()
            self._replies.clear()
        return day

    # ---------- one request ----------
    def handle(self, text: str) -> Optional[str]:
        """Take a decoded request, return the decoded reply (or None to ignore it)."""
        parts = text.split("|")
        if len(parts) != 3 or not parts[0] or not parts[1]:
            return None
        pid, seq, cmd = parts[0][:12], parts[1][:6], parts[2].strip().lower()
        with self._lock:
            day = self._roll_day()
            if (pid, seq, cmd) in self._replies:
                return self._replies[(pid, seq, cmd)]
            word, definition = self.word_for(day)
            game = self._games.setdefault(pid, Game())
            extra = ""
            if cmd == "start":
                y_word, _ = self.word_for(day - dt.timedelta(days=1))
                extra = self.text["yesterday"].format(y_word)
            elif cmd.startswith("g:") and len(cmd) == 3 and cmd[2] in string.ascii_lowercase:
                letter = cmd[2]
                if self._status(word, game) == "play" and letter not in game.guessed:
                    game.guessed.add(letter)
                    if letter not in word:
                        game.wrong.append(letter)
            status = self._status(word, game)
            if status == "win":
                extra = definition or self.text["win"]
            elif status == "lose":
                extra = self.text["lose"]
            pattern = "".join(c if c in game.guessed else "_" for c in word)
            reply = self._fit(f"{pid}|{seq}|{pattern}|{''.join(game.wrong)}|{status}|", extra)
            self._replies[(pid, seq, cmd)] = reply
            if len(self._replies) > 5000:
                self._replies.clear()
            return reply

    @staticmethod
    def _status(word: str, game: Game) -> str:
        if all(c in game.guessed for c in word):
            return "win"
        if len(game.wrong) >= MAX_WRONG:
            return "lose"
        return "play"

    @staticmethod
    def _fit(head: str, extra: str) -> str:
        from cloudtrigger.encoding import CHARS
        extra = extra.replace("\n", " ").replace("|", "/")      # "|" separates fields
        extra = unicodedata.normalize("NFKD", extra).encode("ascii", "ignore").decode()  # á -> a
        extra = "".join(c if c in CHARS else "?" for c in extra)
        room = MAX_TEXT - len(head)
        if len(extra) > room:
            extra = extra[: max(0, room - 3)] + "..."
        return head + extra

    def stats(self) -> dict:
        return {"day": str(self._day), "players_today": len(self._games),
                "words": len(self.words)}


def load_language_words(lang: str) -> list[str]:
    return load_words(HERE / LANGUAGES[lang]["words"])


ADMIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Word games: owner</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;padding:0 16px;color:#1a1a1b;background:#fff}
 h1{font-size:22px} input{width:100%;padding:10px;font-size:16px;box-sizing:border-box;margin:6px 0 16px}
 button{display:block;width:100%;padding:12px;margin:8px 0;font-size:16px;font-weight:600;border:0;
        border-radius:8px;background:#6aaa64;color:#fff;cursor:pointer}
 .msg{padding:10px 12px;border-radius:8px;margin-bottom:16px} .ok{background:#e3f1e1} .bad{background:#fbe3e3}
 small{color:#666}
</style></head><body>
<h1>New word</h1>{message}
<form method="post" action="/admin">
 <label>Owner key<input name="key" type="password" autocomplete="current-password" required></label>
 {buttons}
</form>
<small>Picks a different word for today and resets everyone's board for that game.
Restarting the server goes back to the day's normal word.</small>
</body></html>"""


def serve_status(games: dict[str, "Hangman"], port: int, admin_key: str = "") -> None:
    import hmac
    import time

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _admin(self, message: str = "", code: int = 200) -> None:
            buttons = "".join(f'<button name="game" value="{name}">New {name} word</button>'
                              for name in (PAGES[lang] for lang in games))
            html = ADMIN_PAGE.replace("{message}", message).replace("{buttons}", buttons)
            self._send(code, html.encode(), "text/html; charset=utf-8")

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0].strip("/").lower()
            if path == "admin":
                if not admin_key:
                    return self._admin('<div class="msg bad">Set ADMIN_KEY on the server first.</div>')
                return self._admin()
            stats = {PAGES[lang]: g.stats() for lang, g in games.items()}
            code = 200
            if not path:                       # "/" — every game (UptimeRobot checks this)
                first = next(iter(stats.values()))
                data = {"ok": True, **first, "games": stats}
            elif path in stats:                # "/hangman", "/ahorcado", ...
                data = {"ok": True, "game": path, **stats[path]}
            else:
                code = 404
                data = {"ok": False, "error": "no such game", "games": sorted(stats)}
            self._send(code, json.dumps(data).encode(), "application/json")

        do_HEAD = do_GET

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0].strip("/").lower() != "admin":
                return self._send(404, b"not found", "text/plain")
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            key = (form.get("key") or [""])[0]
            name = (form.get("game") or [""])[0]
            if not admin_key or not hmac.compare_digest(key.encode(), admin_key.encode()):
                time.sleep(1)                  # slow down guessing
                return self._admin('<div class="msg bad">Wrong key.</div>', 403)
            lang = next((lang for lang in games if PAGES[lang] == name), None)
            if lang is None:
                return self._admin('<div class="msg bad">No such game.</div>', 404)
            letters = games[lang].new_word()
            self._admin(f'<div class="msg ok">New {name} word picked ({letters} letters). '
                        f'Everyone\'s {name} board was reset.</div>')

        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("status page on port %s", port)


def run_game(lang: str, project_id: str, game: Hangman) -> None:
    """Connect one game to its project, reconnecting forever if anything goes wrong."""
    from cloudtrigger import CloudWatcher

    while True:
        cloud = CloudWatcher(project_id, os.environ.get("BOT_NAME") or None,
                             server=os.environ.get("CLOUD_SERVER", "turbowarp"))

        @cloud.on_change("request")
        def on_request(change):
            reply = game.handle(change.text)
            if reply:
                change.set_text("response", reply)

        try:
            log.info("[%s] connecting to project %s", lang, project_id)
            cloud.run()
        except Exception as e:
            log.error("[%s] stopped: %s. Trying again in 60s.", lang, e)
        threading.Event().wait(60)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("cloudtrigger").setLevel(logging.WARNING)   # don't log every set
    secret = os.environ.get("HANGMAN_SECRET")
    projects = {"en": os.environ.get("PROJECT_ID"), "es": os.environ.get("PROJECT_ID_ES"),
                "wordle": os.environ.get("PROJECT_ID_WORDLE")}
    projects = {lang: pid.strip() for lang, pid in projects.items() if pid and pid.strip()}
    if not secret or not projects:
        raise SystemExit("Set HANGMAN_SECRET and PROJECT_ID and/or PROJECT_ID_ES.")

    tz = os.environ.get("HANGMAN_TZ", "America/New_York")
    games = {}
    for lang in projects:
        # English keeps the plain secret so its words don't change; others get their own.
        game_secret = secret if lang == "en" else f"{secret}|{lang}"
        if lang == "wordle":
            from wordle import Wordle
            games[lang] = Wordle(game_secret, load_words(HERE / "words_wordle.txt"), tz)
            continue
        games[lang] = Hangman(game_secret, load_language_words(lang), tz,
                              define=LANGUAGES[lang]["define"], lang=lang)
    if os.environ.get("PORT"):
        serve_status(games, int(os.environ["PORT"]), os.environ.get("ADMIN_KEY", "").strip())

    def prepare_words() -> None:
        """Look words up ahead of time so no player waits on the dictionary."""
        while True:
            for game in games.values():
                today = game._today()
                try:
                    for d in (today - dt.timedelta(days=1), today, today + dt.timedelta(days=1)):
                        game.word_for(d)
                except Exception:
                    log.exception("preparing words failed")
            threading.Event().wait(600)

    for lang, game in games.items():
        word, definition = game.word_for(game._today())
        log.info("[%s] ready: today's word has %d letters", lang, len(word))
    threading.Thread(target=prepare_words, daemon=True).start()

    threads = [threading.Thread(target=run_game, args=(lang, pid, games[lang]), daemon=True,
                                name=f"game-{lang}") for lang, pid in projects.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
