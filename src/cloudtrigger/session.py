"""Logging into Scratch to get a session cookie for cloud data."""
from __future__ import annotations

import json
import re

import requests

SCRATCH = "https://scratch.mit.edu"
VERSION = "0.3.0"
# TurboWarp requires bots to name their library + version and give contact info.
UA = f"cloudtrigger/{VERSION} (Python cloud variable bot; +https://github.com/blockblock2/cloudtrigger)"


class LoginError(Exception):
    pass


def login(username: str, password: str) -> str:
    """Log in with a username/password and return the scratchsessionsid cookie."""
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.get(f"{SCRATCH}/csrf_token/", timeout=15)
    csrf = s.cookies.get("scratchcsrftoken")
    if not csrf:
        raise LoginError("Couldn't get a CSRF token from Scratch.")
    r = s.post(
        f"{SCRATCH}/login/",
        data=json.dumps({"username": username, "password": password}),
        headers={
            "X-CSRFToken": csrf,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": SCRATCH,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    session_id = s.cookies.get("scratchsessionsid")
    if not session_id:
        m = re.search(r'scratchsessionsid="?([^";]+)', r.headers.get("Set-Cookie", ""))
        session_id = m.group(1) if m else None
    if r.status_code != 200 or not session_id:
        try:
            msg = r.json()[0].get("msg", "")
        except Exception:
            msg = r.text[:200]
        raise LoginError(f"Scratch login failed ({r.status_code}): {msg}")
    return session_id
