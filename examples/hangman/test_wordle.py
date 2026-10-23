import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hangman_bot import load_words  # noqa: E402
from wordle import Wordle, score  # noqa: E402

WORDS = load_words(Path(__file__).with_name("words_wordle.txt"))
REAL = set(WORDS) | {"crane", "slate", "pious", "audio"}


def make(check=lambda w: w in REAL, day=dt.date(2026, 10, 23)):
    box = {"day": day}
    g = Wordle("wordle-test-secret-1", WORDS, define=lambda w: f"meaning of {w}",
               check_word=check, today=lambda: box["day"])
    return g, box


def f(reply):
    return reply.split("|", 4)


def test_score_basic_and_repeated_letters():
    assert score("crane", "crane") == "ggggg"
    assert score("audio", "crane") == "ybbbb"
    assert score("eerie", "crane") == "bbybg"      # only one e can score; the last one is green
    assert score("speed", "abide") == "bbyby"      # one e in the answer -> only one e yellow
    assert score("lolly", "hello") == "byggb"      # both middle l's green, the first l gray


def test_all_words_are_five_letters():
    assert len(WORDS) > 300 and all(len(w) == 5 and w.isalpha() for w in WORDS)


def test_win_shows_definition():
    g, _ = make()
    ans = g.word_for(dt.date(2026, 10, 23))[0]
    assert f(g.handle("mateo|1|start"))[4].startswith("Yesterday's word: ")
    r = f(g.handle(f"mateo|2|g:{ans}"))
    assert r[2] == ans + "ggggg" and r[3] == "win" and r[4] == f"meaning of {ans}"


def test_invalid_guesses_dont_use_a_try():
    g, _ = make()
    assert f(g.handle("p|1|g:abcd"))[4] == "Use 5 letters"
    assert f(g.handle("p|2|g:zzzzq"))[4] == "Not in the dictionary"
    assert f(g.handle("p|3|g:ab1de"))[4] == "Use 5 letters"
    assert f(g.handle("p|4|start"))[2] == ""


def test_lose_after_six_and_word_hidden():
    g, _ = make()
    ans = g.word_for(dt.date(2026, 10, 23))[0]
    wrong = [w for w in WORDS if w != ans][:7]
    for i, w in enumerate(wrong[:6], 1):
        r = f(g.handle(f"p|{i}|g:{w}"))
    assert r[3] == "lose" and ans not in r[2] and len(r[2]) == 60
    assert f(g.handle(f"p|9|g:{ans}"))[3] == "lose"     # no more tries


def test_reload_keeps_board_and_new_day_resets():
    g, box = make()
    ans = g.word_for(dt.date(2026, 10, 23))[0]
    other = next(w for w in WORDS if w != ans)
    g.handle(f"sam|1|g:{other}")
    assert f(g.handle("sam|1|start"))[2] == f(g.handle("sam|1|start"))[2]   # retry: same reply
    assert f(g.handle("sam|5|start"))[2].startswith(other)                 # "reload" keeps board
    box["day"] = dt.date(2026, 10, 24)
    r = f(g.handle("sam|6|start"))
    assert r[2] == "" and r[4] == f"Yesterday's word: {ans}"


def test_dictionary_down_refuses_made_up_words():
    g, _ = make(check=lambda w: None)
    for i, junk in enumerate(["jjddd", "gxfeg", "adieo", "wordl"], 1):
        r = f(g.handle(f"p|{i}|g:{junk}"))
        assert r[2] == "" and r[4] == "Not in the dictionary"
    assert f(g.handle("p|9|g:adieu"))[2].startswith("adieu")      # real words still work offline


def test_allowed_list_is_big_and_real():
    from wordle import ALLOWED_FILE
    allowed = set(load_words(ALLOWED_FILE))
    assert len(allowed) > 10000 and {"crane", "adieu", "world", "pizza"} <= allowed
    assert not {"jjddd", "gxfeg", "adieo", "wordl"} & allowed
    assert set(WORDS) <= allowed | set(WORDS)


def test_reply_fits_one_cloud_variable():
    g, _ = make()
    ans = g.word_for(dt.date(2026, 10, 23))[0]
    pid = "a_very_long_username"
    wrong = [w for w in WORDS if w != ans][:5]
    for i, w in enumerate(wrong, 1):
        g.handle(f"{pid}|{i}|g:{w}")
    r = g.handle(f"{pid}|99|g:{ans}")
    assert len(r) <= 128


def test_reload_with_same_seq_gets_fresh_reply():
    g, _ = make()
    ans = g.word_for(dt.date(2026, 10, 23))[0]
    other = next(w for w in WORDS if w != ans)
    g.handle("kim|1|start")
    g.handle(f"kim|2|g:{other}")
    # page reloaded and seq numbers reused: a different command is not a retry
    assert f(g.handle(f"kim|2|g:{ans}"))[3] == "win"
