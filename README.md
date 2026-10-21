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
Cloud variables only hold numbers (max 256 digits). `encode("hi")` → `"0809"`, `decode("0809")` → `"hi"`.
Each character is two digits: its position in `cloudtrigger.encoding.CHARS` plus 1 — use the same character list in your Scratch project to decode.

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
cloud = CloudWatcher(1394305521, "blockblock2", server="turbowarp")
```

```bash
cloudtrigger watch 1394305521 -u blockblock2 --server turbowarp
```

The username is just a display name there. TurboWarp may reject names that look rude or impersonate someone.
You can also pass any `wss://` URL as `server` for other cloud servers.

## Good to know
- The account needs to be a **Scratcher** (not "New Scratcher") to use cloud variables.
- Values Scratch sends right when you connect are stored but don't fire handlers (pass `fire_on_initial=True` to change that).
- Sets are spaced ~0.11 s apart because Scratch drops faster ones.
- It reconnects automatically if the connection drops.
- One handler throwing an error doesn't stop the others.
