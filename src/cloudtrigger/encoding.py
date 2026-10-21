"""Pack text into the digits-only format cloud variables need.

Each character becomes two digits (index in CHARS + 1), the same scheme most
Scratch cloud-encoder projects use, so you can decode it in Scratch with a
simple 'letter (i) of' loop over CHARS.
"""

CHARS = (
    " abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    "!@#$%^&*()-_=+[]{};:'\",.<>/?\\|`~"
)


def encode(text: str) -> str:
    out = []
    for ch in text:
        i = CHARS.find(ch)
        if i == -1:
            i = CHARS.index("?")
        out.append(f"{i + 1:02d}")
    return "".join(out)


def decode(digits: str) -> str:
    s = str(digits).strip()
    if s.endswith(".0"):          # a number that went through float()
        s = s[:-2]
    if len(s) % 2:                # cloud numbers can lose their leading 0 ("0910" -> "910")
        s = "0" + s
    return "".join(
        CHARS[int(s[i:i + 2]) - 1]
        for i in range(0, len(s) - 1, 2)
        if 1 <= int(s[i:i + 2]) <= len(CHARS)
    )
