"""Build examples/wordle-board-sample.sb3: a Wordle game for the cloudtrigger Wordle bot.

  Tile sprite  draws the board with Pen stamps and handles typing
  Link sprite  encode / decode / parse / send, talks to the bot through ☁ request/☁ response

Global variables (for all sprites):
  board   rows from the bot: 5 letters + 5 colours each ("cranebgybb...")
  guess   what the player is typing right now
  locked  1 while waiting for the bot or after the game ends (typing ignored)
  demo    1 = pretend to be the bot (every guess comes back gray), 0 = real bot (default)

Keys: letters type, left arrow deletes (Scratch can't see Backspace), Enter submits.
Enter with 5 letters broadcasts "submit".

    python tools/make_board_sample_sb3.py
"""
import io
import os
import sys

from PIL import Image

from sb3lib import (CHARS, CIPHER_VARS, LINK_VARS, Rep, Sprite, Var, add_cipher, add_link, define_proc, join,
                    nid, sprite_target, stage_target, svg_asset, write_sb3)

sys.path.insert(0, os.path.dirname(__file__))
from make_wordle_tiles import frames  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "examples", "wordle-board-sample.sb3")
ABC = "abcdefghijklmnopqrstuvwxyz"


def png_asset(img, name):
    import hashlib
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    md5 = hashlib.md5(data).hexdigest()
    return ({"name": name, "bitmapResolution": 2, "dataFormat": "png", "assetId": md5,
             "md5ext": md5 + ".png", "rotationCenterX": 40, "rotationCenterY": 40},
            (md5 + ".png", data))


ROBOT = (b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="90" viewBox="0 0 80 90">'
         b'<line x1="40" y1="4" x2="40" y2="18" stroke="#456" stroke-width="4"/>'
         b'<circle cx="40" cy="6" r="5" fill="#6aaa64"/>'
         b'<rect x="6" y="18" width="68" height="52" rx="14" fill="#5b8def" stroke="#2c5bb8" stroke-width="4"/>'
         b'<circle cx="27" cy="42" r="8" fill="#fff"/><circle cx="53" cy="42" r="8" fill="#fff"/>'
         b'<circle cx="29" cy="43" r="3.5" fill="#123"/><circle cx="55" cy="43" r="3.5" fill="#123"/>'
         b'<rect x="20" y="72" width="40" height="16" rx="5" fill="#2c5bb8"/></svg>')


def build_link(g, bc, gv):
    """The Link sprite: cipher, decipher and link blocks, plus the start and submit scripts."""
    s = Sprite()
    s.var("chars")
    for n in CIPHER_VARS + LINK_VARS:
        if n not in s.vars:
            s.var(n)
    request, response = Var("☁ request", g["☁ request"]), Var("☁ response", g["☁ response"])
    enc_call, dec_call = add_cipher(s)
    send_call, field, lists = add_link(s, request, response, enc_call, dec_call)

    def setg(n, value):
        return s.setv(n, value, g[n])

    def eq(a, b):
        return s.boolean("operator_equals", OPERAND1=a, OPERAND2=b)

    def draw_and_wait():
        bid = s.block("event_broadcastandwait")
        s.blocks[bid]["inputs"]["BROADCAST_INPUT"] = [1, [11, "draw", bc["draw"]]]
        return bid

    def stop_script():
        return s.block("control_stop", fields={"STOP_OPTION": ["this script", None]},
                       mutation={"tagName": "mutation", "children": [], "hasnext": "false"})

    def show_result():
        """Copy the reply onto the board, say the message, unlock typing if still playing."""
        return [
            setg("board", field(3)),
            draw_and_wait(),
            s.block("control_if_else", {
                "CONDITION": eq(field(4), "play"),
                "SUBSTACK": s.sub([
                    s.block("control_if", {
                        "CONDITION": s.boolean("operator_not", OPERAND=eq(field(5), "")),
                        "SUBSTACK": s.sub([s.block("looks_sayforsecs", {"MESSAGE": field(5), "SECS": 2})]),
                    }),
                    setg("locked", 0),
                ]),
                "SUBSTACK2": s.sub([
                    setg("locked", 1),
                    s.block("control_if_else", {
                        "CONDITION": eq(field(4), "win"),
                        "SUBSTACK": s.sub([s.block("looks_say", {"MESSAGE": join(s, "You got it! ", field(5))})]),
                        "SUBSTACK2": s.sub([s.block("looks_say", {"MESSAGE": field(5)})]),
                    }),
                ]),
            }),
        ]

    # green flag: who am I, then ask the bot for today's board
    s.chain([
        s.block("event_whenflagclicked", top=True),
        s.setv("chars", CHARS),
        s.block("control_if_else", {
            "CONDITION": eq(s.rep("sensing_username"), ""),
            "SUBSTACK": s.sub([s.setv("id", s.rep("operator_random", FROM=10000, TO=99999))]),
            "SUBSTACK2": s.sub([s.setv("id", s.rep("sensing_username"))]),
        }),
        s.setv("seq", s.rep("operator_random", FROM=1, TO=99999)),
        s.setv("last seen", ""),
        s.block("control_if", {"CONDITION": eq(gv("demo"), 1), "SUBSTACK": s.sub([stop_script()])}),
        setg("locked", 1),
        s.block("looks_say", {"MESSAGE": "Getting today's puzzle..."}),
        send_call("start"),
        s.block("control_if", {"CONDITION": eq(s.v("got"), 0), "SUBSTACK": s.sub([
            s.block("looks_say", {"MESSAGE": "The Wordle bot isn't answering. Try again later!"}),
            stop_script()])}),
        s.block("looks_say", {"MESSAGE": ""}),
        *show_result(),
    ])

    # Enter pressed with 5 letters: send the guess
    rcv = s.block("event_whenbroadcastreceived", fields={"BROADCAST_OPTION": ["submit", bc["submit"]]}, top=True)
    s.blocks[rcv]["x"], s.blocks[rcv]["y"] = 0, 600
    s.chain([rcv, s.block("control_if", {"CONDITION": eq(gv("demo"), 0), "SUBSTACK": s.sub([
        send_call(join(s, "g:", gv("guess"))),
        s.block("control_if_else", {
            "CONDITION": eq(s.v("got"), 1),
            "SUBSTACK": s.sub([
                s.block("control_if", {   # the guess was accepted: clear the typing row
                    "CONDITION": s.boolean("operator_gt",
                                           OPERAND1=s.rep("operator_length", STRING=field(3)),
                                           OPERAND2=s.rep("operator_length", STRING=gv("board"))),
                    "SUBSTACK": s.sub([setg("guess", "")]),
                }),
                *show_result(),
            ]),
            "SUBSTACK2": s.sub([
                s.block("looks_sayforsecs", {"MESSAGE": "The bot isn't answering.", "SECS": 2}),
                setg("locked", 0),
            ]),
        }),
    ])})])

    sprite_vars = {vid: [n, CHARS if n == "chars" else ""] for n, vid in s.vars.items()}
    meta, f = svg_asset(ROBOT, "robot", 40, 45)
    return s, sprite_vars, lists, [meta], [f]


def build():
    g = {n: nid("g") for n in ("board", "guess", "locked", "demo", "☁ request", "☁ response")}
    bc = {n: nid("bc") for n in ("draw", "submit")}

    def gv(n):
        return Var(n, g[n])

    s = Sprite()
    for n in ("r", "c", "L", "col", "n", "k", "rows", "new guess"):
        s.var(n)

    def setg(n, value):
        return s.setv(n, value, g[n])

    def _broadcast(name, wait):
        bid = s.block("event_broadcastandwait" if wait else "event_broadcast")
        s.blocks[bid]["inputs"]["BROADCAST_INPUT"] = [1, [11, name, bc[name]]]
        return bid

    def when_received(name):
        return s.block("event_whenbroadcastreceived", fields={"BROADCAST_OPTION": [name, bc[name]]}, top=True)

    def key_pressed(key):
        """<key (key) pressed?>; key can be text or a reporter."""
        bid = s.block("sensing_keypressed")
        menu = s.block("sensing_keyoptions", fields={"KEY_OPTION": ["space", None]}, shadow=True)
        s.blocks[menu]["parent"] = bid
        if isinstance(key, Rep):
            s.blocks[key.id]["parent"] = bid
            s.blocks[bid]["inputs"]["KEY_OPTION"] = [3, key.id, menu]
        else:
            s.blocks[menu]["fields"]["KEY_OPTION"] = [key, None]
            s.blocks[bid]["inputs"]["KEY_OPTION"] = [1, menu]
        from sb3lib import Bool
        return Bool(bid)

    def costume(value):
        return s.block("looks_switchcostumeto", {"COSTUME": value})

    def eq(a, b):
        return s.boolean("operator_equals", OPERAND1=a, OPERAND2=b)

    def add(a, b):
        return s.rep("operator_add", NUM1=a, NUM2=b)

    def mul(a, b):
        return s.rep("operator_multiply", NUM1=a, NUM2=b)

    def sub(a, b):
        return s.rep("operator_subtract", NUM1=a, NUM2=b)

    # ---- letter number (L): n = 1..26 ----
    ln_def, ln_arg, ln_call = define_proc(s, "letter number", "L")
    s.chain([ln_def, s.setv("n", 1), s.block("control_repeat_until", {
        "CONDITION": s.boolean("operator_or",
                               OPERAND1=eq(s.rep("operator_letter_of", LETTER=s.v("n"), STRING=ABC), ln_arg()),
                               OPERAND2=s.boolean("operator_gt", OPERAND1=s.v("n"), OPERAND2=26)),
        "SUBSTACK": s.sub([s.changev("n", 1)])})])
    s.blocks[ln_def]["x"], s.blocks[ln_def]["y"] = 900, 0

    # ---- draw board: stamp 30 tiles ----
    db_def, _db_arg, db_call = define_proc(s, "draw board", "unused")
    colored = s.sub([
        s.setv("L", s.rep("operator_letter_of", LETTER=add(mul(sub(s.v("r"), 1), 10), s.v("c")), STRING=gv("board"))),
        s.setv("col", s.rep("operator_letter_of",
                            LETTER=add(add(mul(sub(s.v("r"), 1), 10), 5), s.v("c")), STRING=gv("board"))),
        ln_call(s.v("L")),
        s.block("control_if_else", {
            "CONDITION": eq(s.v("col"), "g"),
            "SUBSTACK": s.sub([costume(add(add(78, s.v("n")), 1))]),
            "SUBSTACK2": s.sub([s.block("control_if_else", {
                "CONDITION": eq(s.v("col"), "y"),
                "SUBSTACK": s.sub([costume(add(add(52, s.v("n")), 1))]),
                "SUBSTACK2": s.sub([costume(add(add(26, s.v("n")), 1))]),
            })]),
        }),
    ])
    typed_or_empty = s.sub([s.block("control_if_else", {
        "CONDITION": s.boolean("operator_and",
                               OPERAND1=eq(s.v("r"), add(s.v("rows"), 1)),
                               OPERAND2=s.boolean("operator_not", OPERAND=s.boolean(
                                   "operator_gt", OPERAND1=s.v("c"),
                                   OPERAND2=s.rep("operator_length", STRING=gv("guess"))))),
        "SUBSTACK": s.sub([ln_call(s.rep("operator_letter_of", LETTER=s.v("c"), STRING=gv("guess"))),
                           costume(add(s.v("n"), 1))]),            # white "typed" tile
        "SUBSTACK2": s.sub([costume(1)]),                           # empty tile
    })])
    s.chain([db_def,
             s.block("pen_clear"),
             s.block("looks_hide"),
             s.setv("rows", s.rep("operator_divide",
                                  NUM1=s.rep("operator_length", STRING=gv("board")), NUM2=10)),
             s.setv("r", 1),
             s.block("control_repeat", {"TIMES": 6, "SUBSTACK": s.sub([
                 s.setv("c", 1),
                 s.block("control_repeat", {"TIMES": 5, "SUBSTACK": s.sub([
                     s.block("motion_gotoxy", {"X": add(-84, mul(sub(s.v("c"), 1), 42)),
                                               "Y": sub(115, mul(sub(s.v("r"), 1), 42))}),
                     s.block("control_if_else", {
                         "CONDITION": s.boolean("operator_gt", OPERAND1=s.v("r"), OPERAND2=s.v("rows")),
                         "SUBSTACK": typed_or_empty,
                         "SUBSTACK2": colored,
                     }),
                     s.block("pen_stamp"),
                     s.changev("c", 1),
                 ])}),
                 s.changev("r", 1),
             ])})])
    s.blocks[db_def]["x"], s.blocks[db_def]["y"] = 0, 700

    # ---- start ----
    s.chain([s.block("event_whenflagclicked", top=True),
             setg("board", ""), setg("guess", ""),
             s.block("control_if", {"CONDITION": eq(gv("demo"), 1), "SUBSTACK": s.sub([setg("locked", 0)])}),
             db_call("")])
    s.chain([when_received("draw"), db_call("")])

    # ---- typing ----
    letter_k = lambda: s.rep("operator_letter_of", LETTER=s.v("k"), STRING=ABC)  # noqa: E731
    find_letter = s.block("control_repeat", {"TIMES": 26, "SUBSTACK": s.sub([
        s.block("control_if", {
            "CONDITION": s.boolean("operator_and",
                                   OPERAND1=key_pressed(letter_k()),
                                   OPERAND2=s.boolean("operator_lt",
                                                      OPERAND1=s.rep("operator_length", STRING=gv("guess")),
                                                      OPERAND2=5)),
            "SUBSTACK": s.sub([setg("guess", s.rep("operator_join", STRING1=gv("guess"), STRING2=letter_k())),
                               s.setv("k", 26)]),
        }),
        s.changev("k", 1),
    ])})
    delete_last = s.block("control_if", {
        "CONDITION": key_pressed("left arrow"),
        "SUBSTACK": s.sub([
            s.setv("new guess", ""), s.setv("k", 1),
            s.block("control_repeat", {
                "TIMES": sub(s.rep("operator_length", STRING=gv("guess")), 1),
                "SUBSTACK": s.sub([
                    s.setv("new guess", s.rep("operator_join", STRING1=s.v("new guess"),
                                              STRING2=s.rep("operator_letter_of", LETTER=s.v("k"),
                                                            STRING=gv("guess")))),
                    s.changev("k", 1)])}),
            setg("guess", s.v("new guess")),
        ]),
    })
    enter = s.block("control_if", {
        "CONDITION": s.boolean("operator_and", OPERAND1=key_pressed("enter"),
                               OPERAND2=eq(s.rep("operator_length", STRING=gv("guess")), 5)),
        "SUBSTACK": s.sub([setg("locked", 1), _broadcast("submit", False)]),
    })
    s.chain([s.block("event_whenflagclicked", top=True),
             s.block("control_forever", {"SUBSTACK": s.sub([
                 s.block("control_wait_until", {"CONDITION": key_pressed("any")}),
                 s.block("control_if", {
                     "CONDITION": eq(gv("locked"), 0),
                     "SUBSTACK": s.sub([s.setv("k", 1), find_letter, delete_last, enter, db_call("")]),
                 }),
                 s.block("control_wait_until", {"CONDITION": s.boolean(
                     "operator_not", OPERAND=key_pressed("any"))}),
             ])})])
    flag_ids = [b for b, v in s.blocks.items() if v["opcode"] == "event_whenflagclicked"]
    s.blocks[flag_ids[-1]]["x"], s.blocks[flag_ids[-1]]["y"] = 0, 250

    # ---- demo bot: every guess comes back gray (set demo to 0 to use your link) ----
    rcv = when_received("submit")
    s.blocks[rcv]["x"], s.blocks[rcv]["y"] = 450, 250
    s.chain([rcv, s.block("control_if", {
        "CONDITION": eq(gv("demo"), 1),
        "SUBSTACK": s.sub([
            setg("board", s.rep("operator_join", STRING1=gv("board"),
                                STRING2=s.rep("operator_join", STRING1=gv("guess"), STRING2="bbbbb"))),
            setg("guess", ""),
            db_call(""),
            s.block("control_if_else", {
                "CONDITION": s.boolean("operator_lt",
                                       OPERAND1=s.rep("operator_length", STRING=gv("board")), OPERAND2=60),
                "SUBSTACK": s.sub([setg("locked", 0)]),
                "SUBSTACK2": s.sub([setg("locked", 1)]),
            }),
        ]),
    })])

    # switch-costume inputs need a costume-menu shadow under the reporter
    for bid, b in list(s.blocks.items()):
        if b["opcode"] == "looks_switchcostumeto":
            menu = s.block("looks_costume", fields={"COSTUME": ["tile", None]}, shadow=True)
            s.blocks[menu]["parent"] = bid
            inp = b["inputs"]["COSTUME"]
            # a reporter covers the menu; a plain number becomes a number covering the menu
            b["inputs"]["COSTUME"] = [3, inp[1], menu] if inp[0] == 3 else [3, [4, inp[1][1]], menu]

    costumes, files = [], []
    names = ["empty"] + [f"{style}-{ch}" for style in ("typed", "gray", "yellow", "green") for ch in ABC]
    for img, name in zip(frames(), names):
        meta, f = png_asset(img, name)
        costumes.append(meta)
        files.append(f)

    link, link_vars, link_lists, link_costumes, link_files = build_link(g, bc, gv)

    white = Image.new("RGB", (960, 720), "#ffffff")
    bd_meta, bd_file = png_asset(white, "white")
    bd_meta.update(rotationCenterX=480, rotationCenterY=360)

    stage = stage_target({g["board"]: ["board", ""], g["guess"]: ["guess", ""],
                          g["locked"]: ["locked", 1], g["demo"]: ["demo", 0],
                          g["☁ request"]: ["☁ request", 0, True], g["☁ response"]: ["☁ response", 0, True]},
                         bd_meta)
    stage["broadcasts"] = {bc[n]: n for n in bc}
    sprite_vars = {vid: [n, ""] for n, vid in s.vars.items()}
    link_target = sprite_target("Link", link, link_vars, link_costumes, lists=link_lists, x=-190, y=-110,
                                size=70)
    link_target["layerOrder"] = 2
    write_sb3(OUT, [stage, sprite_target("Tile", s, sprite_vars, costumes), link_target],
              files + [bd_file] + link_files, extensions=["pen"])


if __name__ == "__main__":
    build()
