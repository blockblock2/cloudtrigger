"""Tiny helpers for writing Scratch 3 projects (.sb3) from Python."""
import hashlib
import io
import itertools
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cloudtrigger.encoding import CHARS  # noqa: E402

QUESTION_MARK = CHARS.index("?") + 1
CIPHER_VARS = ("result", "i", "j", "found", "code", "pair")

_ids = itertools.count(1)


def nid(prefix="b"):
    return f"{prefix}{next(_ids)}"


class Sprite:
    def __init__(self):
        self.blocks = {}
        self.vars = {}

    def var(self, name, value=""):
        vid = nid("v")
        self.vars[name] = vid
        return vid

    # ---- block helpers -------------------------------------------------
    def block(self, opcode, inputs=None, fields=None, top=False, shadow=False, mutation=None):
        bid = nid()
        b = {"opcode": opcode, "next": None, "parent": None, "inputs": {}, "fields": fields or {},
             "shadow": shadow, "topLevel": top}
        if top:
            b["x"], b["y"] = 0, 0
        if mutation:
            b["mutation"] = mutation
        self.blocks[bid] = b
        for k, v in (inputs or {}).items():
            b["inputs"][k] = self._input(v, bid)
        return bid

    def _input(self, v, parent):
        if isinstance(v, Bool):
            self.blocks[v.id]["parent"] = parent
            return [2, v.id]
        if isinstance(v, Sub):
            if v.id is None:
                return [2, None]
            self.blocks[v.id]["parent"] = parent
            return [2, v.id]
        if isinstance(v, Var):
            return [3, [12, v.name, v.vid], [10, ""]]
        if isinstance(v, Rep):
            self.blocks[v.id]["parent"] = parent
            return [3, v.id, [10, ""]]
        if isinstance(v, (int, float)):
            return [1, [4, str(v)]]
        return [1, [10, str(v)]]

    def chain(self, ids):
        """Link a list of stack block ids top to bottom; returns first id."""
        for a, b in zip(ids, ids[1:]):
            self.blocks[a]["next"] = b
            self.blocks[b]["parent"] = a
        return ids[0] if ids else None

    # convenience
    def setv(self, name, value, vid=None):
        return self.block("data_setvariableto", {"VALUE": value},
                          {"VARIABLE": [name, vid or self.vars[name]]})

    def changev(self, name, value):
        return self.block("data_changevariableby", {"VALUE": value}, {"VARIABLE": [name, self.vars[name]]})

    def v(self, name, vid=None):
        return Var(name, vid or self.vars[name])

    def rep(self, opcode, **inputs):
        return Rep(self.block(opcode, inputs))

    def boolean(self, opcode, **inputs):
        return Bool(self.block(opcode, inputs))

    def sub(self, ids):
        return Sub(self.chain(ids) if ids else None)


class Var:
    def __init__(self, name, vid):
        self.name, self.vid = name, vid


class Rep:
    def __init__(self, bid):
        self.id = bid


class Bool(Rep):
    pass


class Sub(Rep):
    pass


def define_proc(s, name, argname, warp=True):
    """Create a 'run without screen refresh' custom block with one text input.
    Returns (definition_id, argument-reporter factory, call factory)."""
    arg_id = nid("arg")
    proccode = f"{name} %s"
    defn = s.block("procedures_definition", top=True)
    shadow_arg = s.block("argument_reporter_string_number", fields={"VALUE": [argname, None]}, shadow=True)
    proto = s.block("procedures_prototype", shadow=True, mutation={
        "tagName": "mutation", "children": [], "proccode": proccode,
        "argumentids": json.dumps([arg_id]), "argumentnames": json.dumps([argname]),
        "argumentdefaults": json.dumps([""]), "warp": "true" if warp else "false"})
    s.blocks[proto]["inputs"][arg_id] = [1, shadow_arg]
    s.blocks[shadow_arg]["parent"] = proto
    s.blocks[defn]["inputs"]["custom_block"] = [1, proto]
    s.blocks[proto]["parent"] = defn

    def arg():
        return Rep(s.block("argument_reporter_string_number", fields={"VALUE": [argname, None]}))

    def call(value):
        bid = s.block("procedures_call", mutation={
            "tagName": "mutation", "children": [], "proccode": proccode,
            "argumentids": json.dumps([arg_id]), "warp": "true" if warp else "false"})
        s.blocks[bid]["inputs"][arg_id] = s._input(value, bid)
        return bid

    return defn, arg, call



def add_cipher(s):
    """Add 'encode (text)' and 'decode (digits)' custom blocks (results go in the
    'result' variable). The sprite needs a 'chars' variable plus CIPHER_VARS.
    Returns (enc_call, dec_call)."""
    # encode (text): result = digits ----------
    enc_def, enc_arg, enc_call = define_proc(s, "encode", "text")
    inner_if = s.block("control_if_else", {
        "CONDITION": s.boolean("operator_equals",
                               OPERAND1=s.rep("operator_letter_of", LETTER=s.v("j"), STRING=s.v("chars")),
                               OPERAND2=s.rep("operator_letter_of", LETTER=s.v("i"), STRING=enc_arg())),
        "SUBSTACK": s.sub([s.setv("found", 1)]),
        "SUBSTACK2": s.sub([s.changev("j", 1)]),
    })
    search = s.block("control_repeat_until", {
        "CONDITION": s.boolean("operator_or",
                               OPERAND1=s.boolean("operator_equals", OPERAND1=s.v("found"), OPERAND2=1),
                               OPERAND2=s.boolean("operator_gt", OPERAND1=s.v("j"),
                                                  OPERAND2=s.rep("operator_length", STRING=s.v("chars")))),
        "SUBSTACK": s.sub([inner_if]),
    })
    unknown = s.block("control_if", {
        "CONDITION": s.boolean("operator_equals", OPERAND1=s.v("found"), OPERAND2=0),
        "SUBSTACK": s.sub([s.setv("j", QUESTION_MARK)]),   # unknown character -> "?"
    })
    pad = s.block("control_if_else", {
        "CONDITION": s.boolean("operator_lt", OPERAND1=s.v("j"), OPERAND2=10),
        "SUBSTACK": s.sub([s.setv("result", s.rep(
            "operator_join", STRING1=s.v("result"),
            STRING2=s.rep("operator_join", STRING1="0", STRING2=s.v("j"))))]),
        "SUBSTACK2": s.sub([s.setv("result", s.rep("operator_join", STRING1=s.v("result"),
                                                   STRING2=s.v("j")))]),
    })
    each_letter = s.block("control_repeat", {
        "TIMES": s.rep("operator_length", STRING=enc_arg()),
        "SUBSTACK": s.sub([s.setv("j", 1), s.setv("found", 0), search, unknown, pad, s.changev("i", 1)]),
    })
    s.chain([enc_def, s.setv("result", ""), s.setv("i", 1), each_letter])

    # ---------- decode (digits): result = text ----------
    dec_def, dec_arg, dec_call = define_proc(s, "decode", "digits")
    fix_zero = s.block("control_if", {   # cloud numbers can lose a leading 0
        "CONDITION": s.boolean("operator_equals",
                               OPERAND1=s.rep("operator_mod",
                                              NUM1=s.rep("operator_length", STRING=s.v("code")), NUM2=2),
                               OPERAND2=1),
        "SUBSTACK": s.sub([s.setv("code", s.rep("operator_join", STRING1="0", STRING2=s.v("code")))]),
    })
    each_pair = s.block("control_repeat", {
        "TIMES": s.rep("operator_divide", NUM1=s.rep("operator_length", STRING=s.v("code")), NUM2=2),
        "SUBSTACK": s.sub([
            s.setv("pair", s.rep("operator_join",
                                 STRING1=s.rep("operator_letter_of", LETTER=s.v("i"), STRING=s.v("code")),
                                 STRING2=s.rep("operator_letter_of",
                                               LETTER=s.rep("operator_add", NUM1=s.v("i"), NUM2=1),
                                               STRING=s.v("code")))),
            s.setv("result", s.rep("operator_join", STRING1=s.v("result"),
                                   STRING2=s.rep("operator_letter_of", LETTER=s.v("pair"),
                                                 STRING=s.v("chars")))),
            s.changev("i", 2),
        ]),
    })
    s.chain([dec_def, s.setv("code", dec_arg()), fix_zero, s.setv("result", ""), s.setv("i", 1), each_pair])

    s.blocks[enc_def]["x"], s.blocks[enc_def]["y"] = 0, 900
    s.blocks[dec_def]["x"], s.blocks[dec_def]["y"] = 700, 900
    return enc_call, dec_call


def text_equals(s, a, b):
    """a = b compared as text. Scratch compares digit strings as numbers, which loses
    precision for long cloud values, so join an 'x' on the front of both."""
    return s.boolean("operator_equals", OPERAND1=s.rep("operator_join", STRING1="x", STRING2=a),
                     OPERAND2=s.rep("operator_join", STRING1="x", STRING2=b))


def svg_asset(data, name, cx, cy):
    md5 = hashlib.md5(data).hexdigest()
    return ({"name": name, "dataFormat": "svg", "assetId": md5, "md5ext": md5 + ".svg",
             "rotationCenterX": cx, "rotationCenterY": cy}, (md5 + ".svg", data))


def write_sb3(path, targets, files, extensions=()):
    project = {"targets": targets, "monitors": [], "extensions": list(extensions),
               "meta": {"semver": "3.0.0", "vm": "0.2.0", "agent": "cloudtrigger"}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(project, ensure_ascii=False))
        for fname, data in files:
            z.writestr(fname, data)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    print("wrote", os.path.normpath(path))


def stage_target(variables, backdrop_meta):
    return {"isStage": True, "name": "Stage", "variables": variables, "lists": {}, "broadcasts": {},
            "blocks": {}, "comments": {}, "currentCostume": 0, "costumes": [backdrop_meta],
            "sounds": [], "volume": 100, "layerOrder": 0, "tempo": 60, "videoTransparency": 50,
            "videoState": "on", "textToSpeechLanguage": None}


def sprite_target(name, s, variables, costumes, lists=None, x=0, y=0, size=100):
    return {"isStage": False, "name": name, "variables": variables, "lists": lists or {},
            "broadcasts": {}, "blocks": s.blocks, "comments": {}, "currentCostume": 0,
            "costumes": costumes, "sounds": [], "volume": 100, "layerOrder": 1, "visible": True,
            "x": x, "y": y, "size": size, "direction": 90, "draggable": False,
            "rotationStyle": "all around"}


LINK_VARS = ("reply", "k", "id", "seq", "packet", "tries", "got", "last seen")


def join(s, *parts):
    """join(a, join(b, join(c, ...))) as one reporter."""
    out = parts[-1]
    for part in reversed(parts[:-1]):
        out = s.rep("operator_join", STRING1=part, STRING2=out)
    return out


def add_link(s, request, response, enc_call, dec_call, timeout=3, max_tries=5):
    """Add 'parse (text)' and 'send (command)': talk to the bot through two cloud variables.
    After send, 'got' is 1 on success and the reply is split into the sprite list 'fields'.
    Returns (send_call, field, lists)."""
    list_id = nid("list")
    lst = ["fields", list_id]

    def list_block(opcode, **inputs):
        return s.block(opcode, inputs, {"LIST": list(lst)})

    def field(n):
        return Rep(list_block("data_itemoflist", INDEX=n))

    p_def, p_arg, p_call = define_proc(s, "parse", "text")
    split_if = s.block("control_if_else", {
        "CONDITION": s.boolean("operator_equals",
                               OPERAND1=s.rep("operator_letter_of", LETTER=s.v("k"), STRING=s.v("reply")),
                               OPERAND2="|"),
        "SUBSTACK": s.sub([list_block("data_addtolist", ITEM="")]),
        "SUBSTACK2": s.sub([list_block("data_replaceitemoflist",
                                       INDEX=Rep(list_block("data_lengthoflist")),
                                       ITEM=s.rep("operator_join",
                                                  STRING1=field(Rep(list_block("data_lengthoflist"))),
                                                  STRING2=s.rep("operator_letter_of", LETTER=s.v("k"),
                                                                STRING=s.v("reply"))))]),
    })
    s.chain([p_def, s.setv("reply", p_arg()), list_block("data_deletealloflist"),
             list_block("data_addtolist", ITEM=""), s.setv("k", 1),
             s.block("control_repeat", {"TIMES": s.rep("operator_length", STRING=s.v("reply")),
                                        "SUBSTACK": s.sub([split_if, s.changev("k", 1)])})])
    s.blocks[p_def]["x"], s.blocks[p_def]["y"] = 1400, 900

    send_def, send_arg, send_call = define_proc(s, "send", "command", warp=False)
    check_reply = s.block("control_if", {
        "CONDITION": s.boolean("operator_not", OPERAND=text_equals(s, response, s.v("last seen"))),
        "SUBSTACK": s.sub([
            s.setv("last seen", response),
            dec_call(response),
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
                               OPERAND2=s.boolean("operator_gt", OPERAND1=s.rep("sensing_timer"), OPERAND2=timeout)),
        "SUBSTACK": s.sub([check_reply]),
    })
    attempt = s.block("control_repeat_until", {
        "CONDITION": s.boolean("operator_or",
                               OPERAND1=s.boolean("operator_equals", OPERAND1=s.v("got"), OPERAND2=1),
                               OPERAND2=s.boolean("operator_gt", OPERAND1=s.v("tries"), OPERAND2=max_tries - 1)),
        "SUBSTACK": s.sub([s.setv(request.name, s.v("packet"), request.vid), s.block("sensing_resettimer"),
                           wait_loop, s.changev("tries", 1)]),
    })
    s.chain([send_def, s.changev("seq", 1),
             enc_call(join(s, s.v("id"), "|", s.v("seq"), "|", send_arg())),
             s.setv("packet", s.v("result")), s.setv("tries", 0), s.setv("got", 0), attempt])
    s.blocks[send_def]["x"], s.blocks[send_def]["y"] = 1400, 0
    return send_call, field, {list_id: ["fields", []]}
