"""Daily, cheat-proof Hangman for a Scratch project played on TurboWarp.

The secret word only ever lives here, on the server. The Scratch project sends a
guess, and this bot answers with the pattern ("_ a _ _ _"), the wrong letters and
whether you've won or lost. A lost game doesn't reveal the word; it's shown as
"yesterday's word" the next day, so you can't lose once to peek and then win.

One server can run both games: English and Spanish, each in its own project.

Environment variables:
  PROJECT_ID       project ID of the English game
  PROJECT_ID_ES    project ID of the Spanish game (Ahorcado)   — set at least one of these
  HANGMAN_SECRET   long random text; makes the daily word unguessable (required)
  HANGMAN_TZ       time zone the day changes in (default America/New_York)
  BOT_NAME         cloud username: a real Scratch account or "player" + digits
                   (default: a random player123456 name, as TurboWarp asks bots to use)
  PORT             if set, serves a tiny status page (needed by some free hosts)

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
        self._replies: dict[tuple[str, str], str] = {}   # answer retries with the same reply
        self._daily: dict[dt.date, tuple[str, str]] = {}  # day -> (word, definition)
        self._lock = threading.Lock()
        self._word_lock = threading.Lock()

    # ---------- daily word ----------
    def word_for(self, day: dt.date) -> tuple[str, str]:
        with self._word_lock:
            return self._word_for(day)

    def _word_for(self, day: dt.date) -> tuple[str, str]:
        if day in self._daily:
            return self._daily[day]
        digest = hashlib.sha256(f"{self.secret}|{day.isoformat()}".encode()).digest()
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
            if (pid, seq) in self._replies:
                return self._replies[(pid, seq)]
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
            self._replies[(pid, seq)] = reply
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


def serve_status(games: dict[str, "Hangman"], port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            stats = {lang: g.stats() for lang, g in games.items()}
            first = next(iter(stats.values()))
            body = json.dumps({"ok": True, **first, "games": stats}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_HEAD = do_GET

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
    projects = {"en": os.environ.get("PROJECT_ID"), "es": os.environ.get("PROJECT_ID_ES")}
    projects = {lang: pid.strip() for lang, pid in projects.items() if pid and pid.strip()}
    if not secret or not projects:
        raise SystemExit("Set HANGMAN_SECRET and PROJECT_ID and/or PROJECT_ID_ES.")

    tz = os.environ.get("HANGMAN_TZ", "America/New_York")
    games = {}
    for lang in projects:
        # English keeps the plain secret so its words don't change; Spanish gets its own.
        game_secret = secret if lang == "en" else f"{secret}|{lang}"
        games[lang] = Hangman(game_secret, load_language_words(lang), tz,
                              define=LANGUAGES[lang]["define"], lang=lang)
    if os.environ.get("PORT"):
        serve_status(games, int(os.environ["PORT"]))

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
