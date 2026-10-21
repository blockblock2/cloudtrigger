"""Command line: run rules from a JSON file or flags, or just watch.

  cloudtrigger watch 1234567890 -u blockblock2
  cloudtrigger watch 1234567890 -u blockblock2 --server turbowarp
  cloudtrigger run 1234567890 -u blockblock2 --rule "door=1 -> light=1"
  cloudtrigger run 1234567890 -u blockblock2 --rules rules.json

Rule syntax:  <var><op><value> -> <var>=<value|$value>[, <var>=...]
  ops: =  !=  >  <      $value means "the value that just changed"
  "<var>=*" matches any change of that variable.
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import re
import sys

from .cloud import CloudWatcher

RULE_RE = re.compile(r"^\s*([^=!<>]+?)\s*(!=|=|>|<)\s*(\S+?)\s*->\s*(.+)$")


def parse_rule(text: str) -> dict:
    m = RULE_RE.match(text)
    if not m:
        raise SystemExit(f"Bad rule: {text!r}\n{__doc__}")
    var, op, val, actions = m.groups()
    sets = {}
    for part in actions.split(","):
        k, _, v = part.partition("=")
        if not v:
            raise SystemExit(f"Bad action {part!r} in rule {text!r}")
        sets[k.strip()] = v.strip()
    return {"var": var, "op": op, "value": val, "set": sets}


def add_rule(cloud: CloudWatcher, r: dict) -> None:
    op, val = r.get("op", "="), str(r.get("value", "*"))

    def test(v: str) -> bool:
        if val == "*":
            return True
        if op == "=":
            return v == val
        if op == "!=":
            return v != val
        try:
            return float(v) > float(val) if op == ">" else float(v) < float(val)
        except ValueError:
            return False

    sets = {k: (lambda c: c.value) if str(v) == "$value" else v for k, v in r["set"].items()}
    cloud.when(r["var"], test=test, set=sets)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="cloudtrigger", description="Scratch cloud variable triggers")
    p.add_argument("command", choices=["watch", "run"])
    p.add_argument("project_id")
    p.add_argument("-u", "--username", default=os.environ.get("SCRATCH_USERNAME"))
    p.add_argument("--server", default="scratch",
                   help='"scratch" (default), "turbowarp", or a wss:// URL')
    p.add_argument("--session-id", default=os.environ.get("SCRATCH_SESSION_ID"))
    p.add_argument("--rule", action="append", default=[], help='e.g. "door=1 -> light=1"')
    p.add_argument("--rules", help="JSON file with a list of rules")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if not a.username:
        p.error("need --username (or SCRATCH_USERNAME)")
    password = None
    if a.server == "scratch" and not a.session_id:
        password = os.environ.get("SCRATCH_PASSWORD") or getpass.getpass("Scratch password: ")

    cloud = CloudWatcher(a.project_id, a.username, password=password, session_id=a.session_id,
                         server=a.server)

    if a.command == "run":
        rules = [parse_rule(r) for r in a.rule]
        if a.rules:
            with open(a.rules) as f:
                rules += json.load(f)
        if not rules:
            p.error("run needs at least one --rule or --rules file")
        for r in rules:
            add_rule(cloud, r)
        print(f"{len(rules)} rule(s) loaded. Ctrl+C to stop.", file=sys.stderr)
    else:
        print("Watching. Ctrl+C to stop.", file=sys.stderr)

    cloud.run()


if __name__ == "__main__":
    main()
