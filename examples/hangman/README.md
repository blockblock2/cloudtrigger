# Daily Hangman

A Scratch Hangman game with a **new word every day** that **can't be cheated**:

- The word never goes into the Scratch project. Scratch only sends your guess; the bot
  sends back the pattern (`_ a _ _ _`), your wrong letters and whether you've won.
- The daily word comes from the date plus a secret only the server knows, so the code
  being public doesn't help anyone guess it.
- Words are checked in a free online dictionary ([dictionaryapi.dev](https://dictionaryapi.dev)),
  and when you win you see what the word means.
- Losing doesn't show the word. It's shown as "yesterday's word" the next day, so you
  can't lose once to peek and then win.

Files:

| File | What it is |
|---|---|
| `hangman.sb3` | The Scratch project (English) |
| `ahorcado.sb3` | The same game in Spanish (Ahorcado Diario) |
| `hangman_bot.py` | The bot that holds the word and checks guesses |
| `words.txt` | English words it picks from (one per line, edit freely) |
| `words_es.txt` | Spanish words (letters a-z only: no accents or ñ, which cloud variables can't send) |
| `test_hangman.py` | Tests for the game logic |

## 1. Put the project on Scratch

1. On scratch.mit.edu: **File → Load from your computer**, pick `hangman.sb3`.
2. Click **Share** (TurboWarp can only open shared projects), then copy the number in the URL.
3. In the project's instructions, tell players to play at `https://turbowarp.org/<that number>`.
   Scratch's own cloud doesn't talk to bots anymore, so it only works on TurboWarp.

## 2. Try it on your computer

```bash
pip install cloudtrigger
cd examples/hangman
PROJECT_ID=<your project number> HANGMAN_SECRET='any-long-random-text-here' python3 hangman_bot.py
```

Open `turbowarp.org/<your project number>` and press the green flag.

## 3. Run it online for free (Render)

1. Sign up at [render.com](https://render.com) with your GitHub account.
2. **New → Blueprint**, pick the `cloudtrigger` repo. Render reads `render.yaml`.
3. When it asks for **PROJECT_ID**, paste your project number. The secret is made for you.
4. Click **Apply**. In a minute or two the logs say `ready: today's word has N letters`.

Render's free plan **sleeps after 15 minutes with no visitors**, and the bot's connection to
TurboWarp doesn't count as a visitor. To keep it awake, use a free uptime checker:

5. Sign up at [uptimerobot.com](https://uptimerobot.com) (free) → **Add New Monitor** →
   type **HTTP(s)**, URL = your Render address (like `https://daily-hangman-xxxx.onrender.com`),
   interval **5 minutes**.

750 free hours a month is enough for this one service to run all month.

If the bot is ever asleep or down, the game says *"The Hangman bot isn't answering."*

## Spanish version (two projects, one server)

`ahorcado.sb3` is its own Scratch project with its own daily word. The **same** Render
service runs both games, so it doesn't use any more free hours:

1. Upload `ahorcado.sb3` to Scratch, share it, copy its number.
2. In Render: **daily-hangman → Environment → Add Environment Variable**:
   `PROJECT_ID_ES` = that number. **Save**. Render restarts the bot with both games.
3. The logs show `[en] ready` and `[es] ready`, and the status page lists both under `games`.

Why not a second server? Render's 750 free hours are per account; two services running
all month need about 1,490 hours, so both would stop around the 15th.

The Spanish game doesn't show word meanings (there's no free Spanish dictionary service
to rely on); its words are hand-picked instead.

## Changing things

- **Words:** edit `words.txt` and push to GitHub. Render redeploys automatically.
- **When the day changes:** `HANGMAN_TZ` in `render.yaml` (default `America/New_York`).
- **Rebuild the Scratch project** after editing `tools/make_hangman_sb3.py`:
  `python tools/make_hangman_sb3.py`.

## How Scratch and the bot talk

Both directions use `cloudtrigger.encode()` (each character → 2 digits) in one cloud variable:

```
☁ request   Scratch → bot   <player id>|<seq>|start        or   <player id>|<seq>|g:<letter>
☁ response  bot → Scratch   <player id>|<seq>|<pattern>|<wrong letters>|<play/win/lose>|<extra>
```

Each player gets a random id, and `seq` goes up with every guess, so everyone playing at the same
time only reads their own replies. If no reply comes in 3 seconds (another player may have
overwritten `☁ request` at the same moment), Scratch sends again, up to 5 times.
