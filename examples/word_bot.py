"""Pairs with examples/cipher-demo.sb3 — open it at turbowarp.org.

Scratch -> bot: the project encodes your word into ☁ request; this bot decodes it.
Bot -> Scratch: the bot encodes its reply into ☁ response, and can send ☁ message any time.

    python examples/word_bot.py <project id>
"""
import sys
import threading
import time

from cloudtrigger import CloudWatcher

project_id = sys.argv[1] if len(sys.argv) > 1 else "1394305521"
cloud = CloudWatcher(project_id, server="turbowarp")   # picks a "player123456" name


@cloud.on_change("request")
def reply(change):
    word = change.text                    # digits -> text
    print("Scratch sent:", word)
    change.set_text("response", word[::-1])   # text -> digits, sent back reversed


def announce_every_minute():
    while True:
        time.sleep(60)
        cloud.set_text("message", time.strftime("Bot time %H:%M"))


threading.Thread(target=announce_every_minute, daemon=True).start()
cloud.run()
