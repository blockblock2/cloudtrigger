"""Build examples/link-sample.sb3: only the server parts, ready to copy into a game.

  encode (text)   cipher:   text -> digits      (result in 'result')
  decode (digits) decipher: digits -> text      (result in 'result')
  parse (text)    split "a|b|c" into the list 'fields'
  send (command)  talk to the bot; afterwards 'got' = 1 and the reply is in 'fields'

The green-flag script is a tiny Wordle test: it asks for guesses and shows the bot's
raw reply (board, status, message), so you can check the link before drawing anything.

    python tools/make_link_sample_sb3.py
"""
import os

from sb3lib import (CHARS, CIPHER_VARS, LINK_VARS, Sprite, Var, add_cipher, add_link, join, nid,
                    sprite_target, stage_target, svg_asset, write_sb3)

OUT = os.path.join(os.path.dirname(__file__), "..", "examples", "link-sample.sb3")

BACKDROP = (b'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" viewBox="0 0 480 360">'
            b'<rect width="480" height="360" fill="#f4f7fb"/>'
            b'<text x="240" y="40" font-family="sans-serif" font-size="22" text-anchor="middle" '
            b'fill="#345">Link sample</text></svg>')
DOT = (b'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" viewBox="0 0 60 60">'
       b'<circle cx="30" cy="30" r="26" fill="#5b8def" stroke="#2c5bb8" stroke-width="4"/>'
       b'<circle cx="22" cy="26" r="5" fill="#fff"/><circle cx="38" cy="26" r="5" fill="#fff"/>'
       b'<rect x="20" y="38" width="20" height="4" rx="2" fill="#fff"/></svg>')


def build():
    cloud = {n: nid("cloud") for n in ("☁ request", "☁ response")}
    request, response = Var("☁ request", cloud["☁ request"]), Var("☁ response", cloud["☁ response"])

    s = Sprite()
    s.var("chars")
    for n in CIPHER_VARS + LINK_VARS:
        if n not in s.vars:
            s.var(n)
    sprite_vars = {vid: [n, CHARS if n == "chars" else ""] for n, vid in s.vars.items()}

    enc_call, dec_call = add_cipher(s)
    send_call, field, lists = add_link(s, request, response, enc_call, dec_call)

    def stop_if_no_bot(text):
        return s.block("control_if", {
            "CONDITION": s.boolean("operator_equals", OPERAND1=s.v("got"), OPERAND2=0),
            "SUBSTACK": s.sub([
                s.block("looks_say", {"MESSAGE": text}),
                s.block("control_stop", fields={"STOP_OPTION": ["this script", None]},
                        mutation={"tagName": "mutation", "children": [], "hasnext": "false"}),
            ]),
        })

    def show_reply(secs):
        return s.block("looks_sayforsecs", {"MESSAGE": join(
            s, "board: ", field(3), "   status: ", field(4), "   message: ", field(5)), "SECS": secs})

    s.chain([
        s.block("event_whenflagclicked", top=True),
        s.setv("chars", CHARS),
        s.block("control_if_else", {
            "CONDITION": s.boolean("operator_equals", OPERAND1=s.rep("sensing_username"), OPERAND2=""),
            "SUBSTACK": s.sub([s.setv("id", s.rep("operator_random", FROM=10000, TO=99999))]),
            "SUBSTACK2": s.sub([s.setv("id", s.rep("sensing_username"))]),
        }),
        s.setv("seq", s.rep("operator_random", FROM=1, TO=99999)),   # random start: a reload won't reuse old numbers
        s.setv("last seen", ""),
        s.block("looks_say", {"MESSAGE": "Connecting to the bot..."}),
        send_call("start"),
        stop_if_no_bot("The bot isn't answering."),
        show_reply(3),
        s.block("control_repeat_until", {
            "CONDITION": s.boolean("operator_not", OPERAND=s.boolean(
                "operator_equals", OPERAND1=field(4), OPERAND2="play")),
            "SUBSTACK": s.sub([
                s.block("sensing_askandwait", {"QUESTION": "Guess a 5-letter word:"}),
                send_call(join(s, "g:", s.rep("sensing_answer"))),
                stop_if_no_bot("Lost the connection to the bot."),
                show_reply(3),
            ]),
        }),
        s.block("looks_say", {"MESSAGE": join(s, field(4), "! ", field(5))}),
    ])

    bd_meta, bd_file = svg_asset(BACKDROP, "backdrop", 240, 180)
    dot_meta, dot_file = svg_asset(DOT, "bot", 30, 30)
    write_sb3(OUT, [
        stage_target({vid: [n, 0, True] for n, vid in cloud.items()}, bd_meta),
        sprite_target("Link", s, sprite_vars, [dot_meta], lists=lists, x=-150, y=0),
    ], [bd_file, dot_file])


if __name__ == "__main__":
    build()
