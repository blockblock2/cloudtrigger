"""Build examples/hangman/hangman.sb3 — the Scratch side of the daily Hangman.

The project never contains the word. It sends "<id>|<seq>|start" or "<id>|<seq>|g:<letter>"
in ☁ request, waits for the bot's matching reply in ☁ response, and shows it.
If no reply comes within 3 seconds it sends again (another player may have
overwritten ☁ request at the same moment), and gives up after 5 tries.

    python tools/make_hangman_sb3.py          # both languages
    python tools/make_hangman_sb3.py es       # just Spanish (ahorcado.sb3)
"""
import os

from sb3lib import (CHARS, CIPHER_VARS, Sprite, Var, add_cipher, define_proc, nid, sprite_target,
                    stage_target, svg_asset, text_equals, write_sb3)

import sys

HERE = os.path.join(os.path.dirname(__file__), "..", "examples", "hangman")

# Text shown in Scratch. This never goes through the cloud, so accents are fine here.
TEXT = {
    "en": {"file": "hangman.sb3", "title": "Daily Hangman", "subtitle": "A new word every day",
           "asking": "Asking the bot for today's puzzle...",
           "no_bot": "The Hangman bot isn't answering. Try again later!",
           "lost_bot": "Lost the connection to the bot.",
           "one_letter": "Type just one letter!",
           "wrong": "    Wrong: ", "guess": "    Guess a letter:",
           "win": "You got it: ", "win_end": "!  "},
    "es": {"file": "ahorcado.sb3", "title": "Ahorcado Diario", "subtitle": "Una palabra nueva cada día",
           "asking": "Pidiendo la palabra de hoy al bot...",
           "no_bot": "El bot del Ahorcado no responde. ¡Inténtalo más tarde!",
           "lost_bot": "Se perdió la conexión con el bot.",
           "one_letter": "¡Escribe solo una letra!",
           "wrong": "    Fallos: ", "guess": "    Adivina una letra:",
           "win": "¡Lo lograste! Era: ", "win_end": "  "},
}
TIMEOUT_SECS = 3
MAX_TRIES = 5


def gallows_svg(stage: int) -> bytes:
    parts = [
        '<line x1="20" y1="230" x2="160" y2="230" stroke="#5a3e2b" stroke-width="8" stroke-linecap="round"/>',
        '<line x1="50" y1="230" x2="50" y2="20" stroke="#5a3e2b" stroke-width="8" stroke-linecap="round"/>',
        '<line x1="46" y1="20" x2="150" y2="20" stroke="#5a3e2b" stroke-width="8" stroke-linecap="round"/>',
        '<line x1="150" y1="20" x2="150" y2="50" stroke="#8a6a4a" stroke-width="4"/>',
    ]
    body = [
        '<circle cx="150" cy="70" r="20" fill="#ffe3b3" stroke="#333" stroke-width="4"/>',
        '<line x1="150" y1="90" x2="150" y2="150" stroke="#333" stroke-width="5" stroke-linecap="round"/>',
        '<line x1="150" y1="105" x2="122" y2="130" stroke="#333" stroke-width="5" stroke-linecap="round"/>',
        '<line x1="150" y1="105" x2="178" y2="130" stroke="#333" stroke-width="5" stroke-linecap="round"/>',
        '<line x1="150" y1="150" x2="128" y2="190" stroke="#333" stroke-width="5" stroke-linecap="round"/>',
        '<line x1="150" y1="150" x2="172" y2="190" stroke="#333" stroke-width="5" stroke-linecap="round"/>',
    ]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="240" viewBox="0 0 200 240">'
           + "".join(parts) + "".join(body[:stage]) + "</svg>")
    return svg.encode()


BACKDROP_TEMPLATE = ('<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" viewBox="0 0 480 360">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#dcecff"/><stop offset="1" stop-color="#f7fbff"/></linearGradient></defs>'
            '<rect width="480" height="360" fill="url(#g)"/>'
            '<text x="240" y="38" font-family="sans-serif" font-size="26" font-weight="bold" '
            'text-anchor="middle" fill="#234">{title}</text>'
            '<text x="240" y="62" font-family="sans-serif" font-size="14" text-anchor="middle" '
            'fill="#567">{subtitle}</text></svg>')


def build(lang="en"):
    t = TEXT[lang]
    cloud = {n: nid("cloud") for n in ("☁ request", "☁ response")}

    def cv(n):
        return Var(n, cloud[n])

    s = Sprite()
    s.var("chars")
    for n in CIPHER_VARS + ("reply", "k", "id", "seq", "packet", "tries", "got", "last seen",
                            "pattern", "wrong", "status", "extra", "shown", "si"):
        s.var(n)
    sprite_vars = {vid: [n, CHARS if n == "chars" else ""] for n, vid in s.vars.items()}
    list_id = nid("list")
    lists = {list_id: ["fields", []]}
    L = ["fields", list_id]

    enc_call, dec_call = add_cipher(s)

    # small helpers for list blocks
    def list_block(opcode, **inputs):
        return s.block(opcode, inputs, {"LIST": list(L)})

    def list_rep(opcode, **inputs):
        from sb3lib import Rep
        return Rep(list_block(opcode, **inputs))

    def field(n):
        return list_rep("data_itemoflist", INDEX=n)

    # ---- parse (reply): split on "|" into the 'fields' list (no screen refresh) ----
    p_def, p_arg, p_call = define_proc(s, "parse", "text")
    split_if = s.block("control_if_else", {
        "CONDITION": s.boolean("operator_equals",
                               OPERAND1=s.rep("operator_letter_of", LETTER=s.v("k"), STRING=s.v("reply")),
                               OPERAND2="|"),
        "SUBSTACK": s.sub([list_block("data_addtolist", ITEM="")]),
        "SUBSTACK2": s.sub([list_block("data_replaceitemoflist",
                                       INDEX=list_rep("data_lengthoflist"),
                                       ITEM=s.rep("operator_join",
                                                  STRING1=field(list_rep("data_lengthoflist")),
                                                  STRING2=s.rep("operator_letter_of", LETTER=s.v("k"),
                                                                STRING=s.v("reply"))))]),
    })
    s.chain([p_def,
             s.setv("reply", p_arg()),
             list_block("data_deletealloflist"),
             list_block("data_addtolist", ITEM=""),
             s.setv("k", 1),
             s.block("control_repeat", {"TIMES": s.rep("operator_length", STRING=s.v("reply")),
                                        "SUBSTACK": s.sub([split_if, s.changev("k", 1)])})])
    s.blocks[p_def]["x"], s.blocks[p_def]["y"] = 0, 1500

    # ---- spaced (text): "c_t" -> "c _ t" so blanks are easy to count ----
    sp_def, sp_arg, sp_call = define_proc(s, "spaced", "text")
    s.chain([sp_def,
             s.setv("shown", ""),
             s.setv("si", 1),
             s.block("control_repeat", {"TIMES": s.rep("operator_length", STRING=sp_arg()), "SUBSTACK": s.sub([
                 s.setv("shown", s.rep("operator_join", STRING1=s.v("shown"), STRING2=s.rep(
                     "operator_join", STRING1=s.rep("operator_letter_of", LETTER=s.v("si"), STRING=sp_arg()),
                     STRING2=" "))),
                 s.changev("si", 1)])})])
    s.blocks[sp_def]["x"], s.blocks[sp_def]["y"] = 700, 1500

    # ---- send (command): talk to the bot and wait for our reply (screen refresh ON) ----
    send_arg_id = nid("arg")
    send_def = s.block("procedures_definition", top=True)
    send_shadow = s.block("argument_reporter_string_number", fields={"VALUE": ["command", None]}, shadow=True)
    send_proto = s.block("procedures_prototype", shadow=True, mutation={
        "tagName": "mutation", "children": [], "proccode": "send %s",
        "argumentids": f'["{send_arg_id}"]', "argumentnames": '["command"]',
        "argumentdefaults": '[""]', "warp": "false"})
    s.blocks[send_proto]["inputs"][send_arg_id] = [1, send_shadow]
    s.blocks[send_shadow]["parent"] = send_proto
    s.blocks[send_def]["inputs"]["custom_block"] = [1, send_proto]
    s.blocks[send_proto]["parent"] = send_def
    s.blocks[send_def]["x"], s.blocks[send_def]["y"] = 1400, 0

    def send_arg():
        from sb3lib import Rep
        return Rep(s.block("argument_reporter_string_number", fields={"VALUE": ["command", None]}))

    def send_call(value):
        bid = s.block("procedures_call", mutation={
            "tagName": "mutation", "children": [], "proccode": "send %s",
            "argumentids": f'["{send_arg_id}"]', "warp": "false"})
        s.blocks[bid]["inputs"][send_arg_id] = s._input(value, bid)
        return bid

    def join(*parts):
        out = parts[-1]
        for p in reversed(parts[:-1]):
            out = s.rep("operator_join", STRING1=p, STRING2=out)
        return out

    check_reply = s.block("control_if", {
        "CONDITION": s.boolean("operator_not", OPERAND=text_equals(s, cv("☁ response"), s.v("last seen"))),
        "SUBSTACK": s.sub([
            s.setv("last seen", cv("☁ response")),
            dec_call(cv("☁ response")),
            p_call(s.v("result")),
            s.block("control_if", {
                "CONDITION": s.boolean("operator_and",
                                       OPERAND1=s.boolean("operator_equals", OPERAND1=field(1), OPERAND2=s.v("id")),
                                       OPERAND2=s.boolean("operator_equals", OPERAND1=field(2), OPERAND2=s.v("seq"))),
                "SUBSTACK": s.sub([s.setv("got", 1)]),
            }),
        ]),
    })
    wait_loop = s.block("control_repeat_until", {
        "CONDITION": s.boolean("operator_or",
                               OPERAND1=s.boolean("operator_equals", OPERAND1=s.v("got"), OPERAND2=1),
                               OPERAND2=s.boolean("operator_gt", OPERAND1=s.rep("sensing_timer"),
                                                  OPERAND2=TIMEOUT_SECS)),
        "SUBSTACK": s.sub([check_reply]),
    })
    attempt = s.block("control_repeat_until", {
        "CONDITION": s.boolean("operator_or",
                               OPERAND1=s.boolean("operator_equals", OPERAND1=s.v("got"), OPERAND2=1),
                               OPERAND2=s.boolean("operator_gt", OPERAND1=s.v("tries"),
                                                  OPERAND2=MAX_TRIES - 1)),
        "SUBSTACK": s.sub([
            s.setv("☁ request", s.v("packet"), cloud["☁ request"]),
            s.block("sensing_resettimer"),
            wait_loop,
            s.changev("tries", 1),
        ]),
    })
    s.chain([send_def,
             s.changev("seq", 1),
             enc_call(join(s.v("id"), "|", s.v("seq"), "|", send_arg())),
             s.setv("packet", s.v("result")),
             s.setv("tries", 0),
             s.setv("got", 0),
             attempt,
             s.block("control_if", {
                 "CONDITION": s.boolean("operator_equals", OPERAND1=s.v("got"), OPERAND2=1),
                 "SUBSTACK": s.sub([
                     s.setv("pattern", field(3)),
                     s.setv("wrong", field(4)),
                     s.setv("status", field(5)),
                     s.setv("extra", field(6)),
                 ]),
             })])

    def costume_for_misses():
        return s.block("looks_switchcostumeto", {"COSTUME": s.rep(
            "operator_add", NUM1=s.rep("operator_length", STRING=s.v("wrong")), NUM2=1)})

    # costume menu input needs a shadow menu block; replace the plain input with one
    def fix_costume_inputs():
        for bid, b in list(s.blocks.items()):
            if b["opcode"] == "looks_switchcostumeto":
                menu = s.block("looks_costume", fields={"COSTUME": ["0 misses", None]}, shadow=True)
                s.blocks[menu]["parent"] = bid
                inp = b["inputs"]["COSTUME"]
                b["inputs"]["COSTUME"] = [3, inp[1], menu] if inp[0] == 3 else [1, menu]

    no_bot = s.block("control_if", {
        "CONDITION": s.boolean("operator_equals", OPERAND1=s.v("got"), OPERAND2=0),
        "SUBSTACK": s.sub([
            s.block("looks_say", {"MESSAGE": t["no_bot"]}),
            s.block("control_stop", fields={"STOP_OPTION": ["this script", None]},
                    mutation={"tagName": "mutation", "children": [], "hasnext": "false"}),
        ]),
    })

    guess_branch = s.block("control_if_else", {
        "CONDITION": s.boolean("operator_equals",
                               OPERAND1=s.rep("operator_length", STRING=s.rep("sensing_answer")), OPERAND2=1),
        "SUBSTACK": s.sub([
            send_call(join("g:", s.rep("sensing_answer"))),
            costume_for_misses(),
            s.block("control_if", {
                "CONDITION": s.boolean("operator_equals", OPERAND1=s.v("got"), OPERAND2=0),
                "SUBSTACK": s.sub([
                    s.block("looks_say", {"MESSAGE": t["lost_bot"]}),
                    s.block("control_stop", fields={"STOP_OPTION": ["this script", None]},
                            mutation={"tagName": "mutation", "children": [], "hasnext": "false"}),
                ]),
            }),
        ]),
        "SUBSTACK2": s.sub([s.block("looks_sayforsecs", {"MESSAGE": t["one_letter"], "SECS": 1})]),
    })

    play_loop = s.block("control_repeat_until", {
        "CONDITION": s.boolean("operator_not",
                               OPERAND=s.boolean("operator_equals", OPERAND1=s.v("status"), OPERAND2="play")),
        "SUBSTACK": s.sub([
            sp_call(s.v("pattern")),
            s.block("sensing_askandwait", {"QUESTION": join(
                s.v("shown"), t["wrong"], s.v("wrong"), t["guess"])}),
            guess_branch,
        ]),
    })

    ending = s.block("control_if_else", {
        "CONDITION": s.boolean("operator_equals", OPERAND1=s.v("status"), OPERAND2="win"),
        "SUBSTACK": s.sub([s.block("looks_say", {"MESSAGE": join(
            t["win"], s.v("pattern"), t["win_end"], s.v("extra"))})]),
        "SUBSTACK2": s.sub([s.block("looks_say", {"MESSAGE": s.v("extra")})]),
    })

    s.chain([
        s.block("event_whenflagclicked", top=True),
        s.block("looks_switchcostumeto", {"COSTUME": 1}),
        s.setv("id", s.rep("operator_random", FROM=10000, TO=99999)),
        s.setv("seq", 0),
        s.setv("last seen", ""),
        s.setv("status", ""),
        s.block("looks_say", {"MESSAGE": t["asking"]}),
        send_call("start"),
        no_bot,
        s.block("looks_sayforsecs", {"MESSAGE": s.v("extra"), "SECS": 2}),
        costume_for_misses(),
        play_loop,
        costume_for_misses(),
        ending,
    ])
    fix_costume_inputs()

    costumes, files = [], []
    for k in range(7):
        meta, f = svg_asset(gallows_svg(k), f"{k} misses", 100, 120)
        costumes.append(meta)
        files.append(f)
    backdrop = BACKDROP_TEMPLATE.format(title=t["title"], subtitle=t["subtitle"]).encode("utf-8")
    bd_meta, bd_file = svg_asset(backdrop, "backdrop", 240, 180)
    write_sb3(os.path.join(HERE, t["file"]), [
        stage_target({vid: [n, 0, True] for n, vid in cloud.items()}, bd_meta),
        sprite_target("Hangman", s, sprite_vars, costumes, lists=lists, x=-120, y=-30),
    ], files + [bd_file])


if __name__ == "__main__":
    for lang in (sys.argv[1:] or TEXT):
        build(lang)
