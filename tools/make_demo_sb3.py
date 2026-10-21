"""Build examples/cipher-demo.sb3: type a word in Scratch, it's encoded into ☁ request,
the bot (examples/word_bot.py) answers in ☁ response, and Scratch decodes the reply.
The bot can also send ☁ message at any time.

    python tools/make_demo_sb3.py
"""
import os

from sb3lib import (CHARS, CIPHER_VARS, Sprite, Var, add_cipher, nid, sprite_target,
                    stage_target, svg_asset, text_equals, write_sb3)

OUT = os.path.join(os.path.dirname(__file__), "..", "examples", "cipher-demo.sb3")

ROBOT = (b'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="110" viewBox="0 0 96 110">'
         b'<line x1="48" y1="4" x2="48" y2="20" stroke="#456" stroke-width="4"/>'
         b'<circle cx="48" cy="6" r="6" fill="#f5a623"/>'
         b'<rect x="8" y="20" width="80" height="62" rx="16" fill="#5b8def" stroke="#2c5bb8" stroke-width="4"/>'
         b'<circle cx="32" cy="48" r="9" fill="#fff"/><circle cx="64" cy="48" r="9" fill="#fff"/>'
         b'<circle cx="34" cy="49" r="4" fill="#123"/><circle cx="66" cy="49" r="4" fill="#123"/>'
         b'<rect x="30" y="64" width="36" height="6" rx="3" fill="#123"/>'
         b'<rect x="24" y="84" width="48" height="22" rx="6" fill="#2c5bb8"/></svg>')
BACKDROP = (b'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" viewBox="0 0 480 360">'
            b'<rect width="480" height="360" fill="#eef3fb"/>'
            b'<text x="240" y="40" font-family="sans-serif" font-size="22" text-anchor="middle" '
            b'fill="#355">Cloud cipher demo</text></svg>')


def build():
    cloud = {n: nid("cloud") for n in ("☁ request", "☁ response", "☁ message")}

    def cv(n):
        return Var(n, cloud[n])

    s = Sprite()
    s.var("chars")
    for n in CIPHER_VARS + ("last message",):
        s.var(n)
    sprite_vars = {vid: [n, CHARS if n == "chars" else ""] for n, vid in s.vars.items()}
    enc_call, dec_call = add_cipher(s)

    # Scratch -> bot -> Scratch
    s.chain([
        s.block("event_whenflagclicked", top=True),
        s.setv("☁ response", 0, cloud["☁ response"]),
        s.block("sensing_askandwait", {"QUESTION": "Type a word for the bot:"}),
        enc_call(s.rep("sensing_answer")),
        s.setv("☁ request", s.v("result"), cloud["☁ request"]),
        s.block("looks_sayforsecs", {"MESSAGE": s.rep("operator_join", STRING1="Sent: ",
                                                        STRING2=s.v("result")), "SECS": 1}),
        s.block("control_wait_until", {"CONDITION": s.boolean(
            "operator_not", OPERAND=s.boolean("operator_equals", OPERAND1=cv("☁ response"), OPERAND2=0))}),
        dec_call(cv("☁ response")),
        s.block("looks_say", {"MESSAGE": s.rep("operator_join", STRING1="Bot says: ",
                                                 STRING2=s.v("result"))}),
    ])

    # bot -> Scratch at any time
    flag2 = s.block("event_whenflagclicked", top=True)
    s.blocks[flag2]["x"] = 650
    s.chain([
        flag2,
        s.setv("last message", cv("☁ message")),
        s.block("control_forever", {"SUBSTACK": s.sub([
            s.block("control_wait_until", {"CONDITION": s.boolean(
                "operator_not", OPERAND=text_equals(s, cv("☁ message"), s.v("last message")))}),
            s.setv("last message", cv("☁ message")),
            dec_call(cv("☁ message")),
            s.block("looks_sayforsecs", {"MESSAGE": s.rep("operator_join", STRING1="Message: ",
                                                            STRING2=s.v("result")), "SECS": 3}),
        ])}),
    ])

    bd_meta, bd_file = svg_asset(BACKDROP, "backdrop", 240, 180)
    rb_meta, rb_file = svg_asset(ROBOT, "robot", 48, 55)
    write_sb3(OUT, [
        stage_target({vid: [n, 0, True] for n, vid in cloud.items()}, bd_meta),
        sprite_target("Robot", s, sprite_vars, [rb_meta], y=-40),
    ], [bd_file, rb_file])


if __name__ == "__main__":
    build()
