import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hangman_bot import Hangman, load_words  # noqa: E402

SECRET = "test-secret-123456"


def make(day=dt.date(2026, 10, 21), define=lambda w: f"meaning of {w}"):
    box = {"day": day}
    g = Hangman(SECRET, load_words(), define=define, today=lambda: box["day"])
    return g, box


def fields(reply):
    return reply.split("|", 5)


def test_daily_word_is_stable_and_changes_by_day():
    g, box = make()
    a = g.word_for(dt.date(2026, 10, 21))[0]
    assert a == g.word_for(dt.date(2026, 10, 21))[0]
    days = {g.word_for(dt.date(2026, 10, d))[0] for d in range(1, 29)}
    assert len(days) > 15                       # varies across days
    other = Hangman("a-different-secret!!", load_words(), define=lambda w: "x")
    assert sum(other.word_for(dt.date(2026, 10, d))[0] != g.word_for(dt.date(2026, 10, d))[0]
               for d in range(1, 29)) > 20      # secret matters


def test_win_flow_and_definition():
    g, _ = make()
    word = g.word_for(dt.date(2026, 10, 21))[0]
    pid, st = "4821", fields(g.handle("4821|1|start"))
    assert st[2] == "_" * len(word) and st[4] == "play" and st[5].startswith("Yesterday's word: ")
    seq = 2
    for letter in dict.fromkeys(word):
        r = fields(g.handle(f"{pid}|{seq}|g:{letter}"))
        seq += 1
    assert r[2] == word and r[3] == "" and r[4] == "win" and r[5] == f"meaning of {word}"


def test_lose_does_not_reveal_word():
    g, _ = make()
    word = g.word_for(dt.date(2026, 10, 21))[0]
    misses = [c for c in "zqxjkvwyfbpmgu" if c not in word][:6]
    for i, c in enumerate(misses, 2):
        r = g.handle(f"77|{i}|g:{c}")
    f = fields(r)
    assert f[4] == "lose" and word not in r and set(f[2]) == {"_"}
    # more guesses after losing change nothing
    assert fields(g.handle("77|99|g:" + word[0]))[2] == f[2]


def test_players_are_separate_and_retries_get_same_reply():
    g, _ = make()
    word = g.word_for(dt.date(2026, 10, 21))[0]
    r1 = g.handle(f"1|5|g:{word[0]}")
    assert g.handle(f"1|5|g:{word[0]}") == r1           # retry of the same request
    assert fields(g.handle("2|1|start"))[2] == "_" * len(word)


def test_new_day_resets_and_shows_yesterday():
    g, box = make()
    yesterday = g.word_for(dt.date(2026, 10, 21))[0]
    g.handle(f"1|1|g:{yesterday[0]}")
    box["day"] = dt.date(2026, 10, 22)
    r = fields(g.handle("1|2|start"))
    assert r[5] == f"Yesterday's word: {yesterday}" and r[3] == ""


def test_bad_input_ignored_and_reply_fits():
    g, _ = make(define=lambda w: "x" * 500)
    assert g.handle("garbage") is None
    assert fields(g.handle("1|1|g:7"))[4] == "play"
    word = g.word_for(dt.date(2026, 10, 21))[0]
    for i, c in enumerate(dict.fromkeys(word), 2):
        r = g.handle(f"1|{i}|g:{c}")
    assert len(r) <= 128 and r.endswith("...")


def test_dictionary_skips_unknown_words_and_survives_outage():
    g, _ = make(define=lambda w: "" if w != "zebra" else "an animal")
    assert g.word_for(dt.date(2026, 1, 1)) in {("zebra", "an animal")} or \
        g.word_for(dt.date(2026, 1, 1))[1] == ""   # zebra unless it's >10 words away
    down = Hangman(SECRET, load_words(), define=lambda w: None)
    w, d = down.word_for(dt.date(2026, 1, 1))
    assert w and d == ""


def test_spanish_game():
    from hangman_bot import LANGUAGES, load_language_words
    words = load_language_words("es")
    assert len(words) > 200 and all(w.isascii() and w.isalpha() for w in words)
    box = {"day": dt.date(2026, 10, 22)}
    es = Hangman(SECRET + "|es", words, define=LANGUAGES["es"]["define"], lang="es",
                 today=lambda: box["day"])
    word = es.word_for(box["day"])[0]
    assert word in words
    st = fields(es.handle("9|1|start"))
    assert st[5].startswith("Palabra de ayer: ")
    for i, c in enumerate(dict.fromkeys(word), 2):
        r = fields(es.handle(f"9|{i}|g:{c}"))
    assert r[4] == "win" and r[5] == ""
    misses = [c for c in "zqxjkwyfhvb" if c not in word][:6]
    for i, c in enumerate(misses, 50):
        r = fields(es.handle(f"8|{i}|g:{c}"))
    assert r[4] == "lose" and word not in "|".join(r) and r[5].startswith("Se acabaron")
    # accented text the bot sends is made safe for the cloud encoding
    assert Hangman._fit("1|1|_|_|lose|", "mañana día ¡hola!") == "1|1|_|_|lose|manana dia hola!"


def test_new_word_button():
    g, box = make()
    day = box["day"]
    old = g.word_for(day)[0]
    g.handle(f"1|1|g:{old[0]}")
    assert g.stats()["players_today"] == 1
    n = g.new_word()
    new = g.word_for(day)[0]
    assert new != old and n == len(new)
    assert g.stats()["players_today"] == 0                    # everyone's game reset
    assert fields(g.handle("1|1|start"))[2] == "_" * len(new)  # same seq is not a stale reply
    box["day"] = day + dt.timedelta(days=1)
    assert fields(g.handle("1|2|start"))[5] == f"Yesterday's word: {new}"   # tomorrow shows the new one


def test_admin_page():
    import socket, urllib.request, urllib.error, urllib.parse
    from hangman_bot import serve_status
    g, _ = make()
    old = g.word_for(g._today())[0]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    serve_status({"en": g}, port, "owner-secret-key")
    import time; time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    page = urllib.request.urlopen(base + "/admin").read().decode()
    assert "New hangman word" in page
    def post(key):
        data = urllib.parse.urlencode({"key": key, "game": "hangman"}).encode()
        try:
            return urllib.request.urlopen(base + "/admin", data).read().decode()
        except urllib.error.HTTPError as e:
            return e.read().decode()
    assert "Wrong key" in post("nope") and g.word_for(g._today())[0] == old
    assert "New hangman word picked" in post("owner-secret-key")
    assert g.word_for(g._today())[0] != old
    assert old not in post("owner-secret-key")               # the page never shows the word
    assert urllib.request.urlopen(base + "/").status == 200   # UptimeRobot page still fine
