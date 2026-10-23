"""Daily Wordle for a Scratch project on TurboWarp, run by the same server as Hangman.

The secret word stays on the server. Scratch sends a 5-letter guess; the bot answers
with every row so far and its colours:
    g = green  (right letter, right place)
    y = yellow (in the word, wrong place)
    b = gray   (not in the word)

Players are identified by their TurboWarp username, so reloading the page brings
back the same board instead of a fresh set of 6 tries.

Messages (cloudtrigger.encode()'d text in one cloud variable):
  ☁ request   Scratch -> bot   "<player>|<seq>|start"   or   "<player>|<seq>|g:<guess>"
  ☁ response  bot -> Scratch   "<player>|<seq>|<board>|<play/win/lose>|<message>"
  <board> is each row as 5 letters + 5 colours, joined together: "cranebgybbslateggggg"
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from hangman_bot import DICTIONARY_URL, Hangman, lookup_definition

TRIES = 6
LENGTH = 5


def score(guess: str, answer: str) -> str:
    """Wordle colours for one guess, handling repeated letters the way Wordle does."""
    colours = ["b"] * LENGTH
    left: dict[str, int] = {}
    for i, (g, a) in enumerate(zip(guess, answer)):
        if g == a:
            colours[i] = "g"
        else:
            left[a] = left.get(a, 0) + 1
    for i, g in enumerate(guess):
        if colours[i] != "g" and left.get(g, 0) > 0:
            colours[i] = "y"
            left[g] -= 1
    return "".join(colours)


def is_real_word(word: str, timeout: float = 3) -> Optional[bool]:
    """True/False from the online dictionary, or None if it can't be reached."""
    url = DICTIONARY_URL.format(urllib.parse.quote(word))
    req = urllib.request.Request(url, headers={"User-Agent": "cloudtrigger-wordle"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            json.load(r)
            return True
    except urllib.error.HTTPError as e:
        return False if e.code == 404 else None
    except Exception:
        return None


class Wordle(Hangman):
    """Same daily-word picking as Hangman (secret + date, dictionary-checked)."""

    def __init__(self, secret: str, words: list[str], tz: str = "America/New_York",
                 define: Callable[[str], Optional[str]] = lookup_definition,
                 check_word: Callable[[str], Optional[bool]] = is_real_word,
                 today: Optional[Callable[[], dt.date]] = None):
        words = [w for w in words if len(w) == LENGTH]
        super().__init__(secret, words, tz, define=define, today=today, lang="en")
        self.check_word = check_word
        self._known: dict[str, bool] = {w: True for w in words}
        self._known_lock = threading.Lock()

    def _real(self, word: str) -> bool:
        with self._known_lock:
            if word in self._known:
                return self._known[word]
        ok = self.check_word(word)
        if ok is None:          # dictionary down: don't block the player
            return True
        with self._known_lock:
            if len(self._known) > 20000:
                self._known = {w: True for w in self.words}
            self._known[word] = ok
        return ok

    def handle(self, text: str) -> Optional[str]:
        parts = text.split("|")
        if len(parts) != 3 or not parts[0] or not parts[1]:
            return None
        pid, seq, cmd = parts[0][:20], parts[1][:6], parts[2].strip().lower()
        guess = cmd[2:] if cmd.startswith("g:") else None
        real = None
        if guess is not None and len(guess) == LENGTH and guess.isalpha() and guess.isascii():
            real = self._real(guess)            # may ask the dictionary: do it outside the lock
        with self._lock:
            day = self._roll_day()
            if (pid, seq, cmd) in self._replies:
                return self._replies[(pid, seq, cmd)]
            answer, definition = self.word_for(day)
            rows = self._games.setdefault(pid, [])
            message = ""
            if cmd == "start":
                message = f"Yesterday's word: {self.word_for(day - dt.timedelta(days=1))[0]}"
            elif guess is not None and self._state(answer, rows) == "play":
                if len(guess) != LENGTH or not guess.isalpha() or not guess.isascii():
                    message = "Use 5 letters"
                elif not real:
                    message = "Not in the dictionary"
                else:
                    rows.append(guess + score(guess, answer))
            status = self._state(answer, rows)
            if status == "win":
                message = definition or "You got it!"
            elif status == "lose":
                message = "Out of tries! See the word tomorrow."
            reply = self._fit(f"{pid}|{seq}|{''.join(rows)}|{status}|", message)
            self._replies[(pid, seq, cmd)] = reply
            if len(self._replies) > 5000:
                self._replies.clear()
            return reply

    @staticmethod
    def _state(answer: str, rows: list[str]) -> str:
        if rows and rows[-1][LENGTH:] == "g" * LENGTH:
            return "win"
        return "lose" if len(rows) >= TRIES else "play"
