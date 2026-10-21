"""Example: a few ways to react to cloud changes.

Run:  SCRATCH_PASSWORD=... python examples/bot.py
Your Scratch project needs cloud variables named request, response, light,
door, score, high score, and echo.
"""
import logging
import os

from cloudtrigger import CloudWatcher, decode, encode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

cloud = CloudWatcher(
    project_id=1234567890,            # <- your project ID
    username="blockblock2",
    password=os.environ["SCRATCH_PASSWORD"],
)

# 1. Simple rules, no function needed
cloud.when("door", equals=1, set={"light": 1})
cloud.when("door", equals=0, set={"light": 0})
cloud.mirror("score", "echo")


# 2. A handler with your own logic
@cloud.on_change("score")
def high_score(change):
    best = float(cloud.get("high score", "0"))
    if change.number > best:
        change.set("high score", change.value)


# 3. Request/response: the Scratch game puts encoded text in "request",
#    Python answers in "response"
@cloud.on_change("request")
def answer(change):
    text = decode(change.value)
    reply = text.upper()[::-1]
    change.set("response", encode(reply))


# 4. Log everything
@cloud.on_any
def show(change):
    print(f"{change.name}: {change.old} -> {change.value}")


cloud.run()
