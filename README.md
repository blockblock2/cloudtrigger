# cloudtrigger

Watch a Scratch project's cloud variables and **set cloud variables when something changes**.

```bash
pip install cloudtrigger          # or from this folder: pip install .
```

> **Heads up:** Scratch has changed its cloud server so outside programs can no longer read
> cloud variables on scratch.mit.edu. The bot can still log in and connect, but it won't see
> any changes there. **Use TurboWarp mode** (below) and have people play your project at
> `turbowarp.org/<project id>`.

## Python

```python
from cloudtrigger import CloudWatcher

cloud = CloudWatcher(1234567890, "blockblock2", password="...")

# rule: when door becomes 1, set light to 1
cloud.when("door", equals=1, set={"light": 1})

# rule with a number check, copying the new value
cloud.when("score", above=100, set={"winner": lambda c: c.value})

# copy one variable into another every time it changes
cloud.mirror("score", "echo")

# full control with a handler
@cloud.on_change("request")
def answer(change):
    print(change.name, change.old, "->", change.value)
    change.set("response", change.number * 2)

cloud.run()          # blocks; or cloud.start() to run in the background
```

Variable names are written without the `☁ ` — it's added for you.

What a handler gets (`change`): `.name`, `.value` (string), `.old`, `.number`, `.set(name, value)`.
You can also call `cloud.get("name")` and `cloud.set("name", value)` anywhere.

### Text
Cloud variables only hold numbers. `encode("hi")` → `"0910"`, `decode("0910")` → `"hi"`.
Each character is two digits: its position in `cloudtrigger.encoding.CHARS` plus 1.
`decode` copes with a lost leading zero (`"910"` still gives `"hi"`).

Shortcuts: `change.text` (decoded value), `change.set_text("reply", "hello")`,
`cloud.set_text(...)` and `cloud.get_text(...)`. One cloud variable holds 128 characters.

`examples/cipher-demo.sb3` has ready-made Scratch **encode** and **decode** blocks using the
same characters — copy them into your own project (drag the scripts onto your sprite in the
editor). Pair it with `examples/word_bot.py`.

## Examples
- `examples/hangman/` — a daily, cheat-proof Hangman game with a server bot ([guide](examples/hangman/README.md))
- `examples/cipher-demo.sb3` + `examples/word_bot.py` — text both ways between Scratch and a bot
- `examples/bot.py` — rules and handlers

## Command line

```bash
# just print changes
cloudtrigger watch 1234567890 -u blockblock2

# rules
cloudtrigger run 1234567890 -u blockblock2 \
  --rule "door=1 -> light=1" \
  --rule "score>100 -> winner=\$value, flash=1" \
  --rule "ping=* -> pong=1"
```

Ops: `=` `!=` `>` `<`, `*` = any change, `$value` = the value that just changed.
Rules can also go in a JSON file (`--rules rules.json`):

```json
[{"var": "door", "op": "=", "value": "1", "set": {"light": "1"}}]
```

Password comes from a prompt or `SCRATCH_PASSWORD`; you can pass `--session-id` / `SCRATCH_SESSION_ID` instead.

## TurboWarp (works even when Scratch's cloud is down)

Run your project at `turbowarp.org/<project id>` and point the bot at TurboWarp's cloud server. No password or Scratcher status needed:

```python
cloud = CloudWatcher(1394305521, server="turbowarp")
```

```bash
cloudtrigger watch 1394305521 --server turbowarp
```

TurboWarp only accepts real Scratch usernames or `player` + 2–7 digits. Leave the username out and
cloudtrigger picks a `player123456` name for you. Bots must also send contact info, which
cloudtrigger does in its User-Agent ([TurboWarp's rules](https://docs.turbowarp.org/cloud-variables)).
You can also pass any `wss://` URL as `server` for other cloud servers.

## Skipping the login

Scratch limits logins, so running a bot many times can get `Scratch login failed (403)`.
Use the session cookie from a browser where you're already logged in instead:
open scratch.mit.edu, then Developer Tools → Application (Chrome) or Storage (Safari/Firefox)
→ Cookies → `scratchsessionsid`, and copy its value.

```python
cloud = CloudWatcher(1394305521, "blockblock2", session_id=os.environ["SCRATCH_SESSION_ID"])
```

Treat it like a password: anyone with it can act as your account.

## Good to know
- The account needs to be a **Scratcher** (not "New Scratcher") to use cloud variables.
- Values Scratch sends right when you connect are stored but don't fire handlers (pass `fire_on_initial=True` to change that).
- Sets are spaced ~0.11 s apart because Scratch drops faster ones.
- It reconnects automatically if the connection drops.
- One handler throwing an error doesn't stop the others.
