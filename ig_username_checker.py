"""
Instagram Username Availability Checker (Automatic + Telegram delivery)
------------------------------------------------------------------------
Fully automatic: generates clean, meaningful username candidates itself
(no numbers, no dots, no underscores — letters only, no length limit),
checks each one against Instagram's signup-check endpoint, and sends
every AVAILABLE username straight to your Telegram via bot as it finds them.

Resumable: progress is saved to checker_state.json after every check, so
if you stop and restart (manually, or via a scheduled job), it picks up
where it left off instead of re-checking names it's already tried.

NOTE:
- This uses an unofficial/internal Instagram endpoint (the same one their
  signup form calls). It can change or get rate-limited at any time.
- Delay is intentionally kept, just shortened — going much lower raises
  the chance of Instagram blocking the IP entirely.
- For personal/small-scale use only.

Setup:
    1. Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID below.
    2. (Optional) Edit WORDS list to include words meaningful to you.
    3. Run: python ig_username_checker.py

Free hosting so you don't have to run it manually:
    - GitHub Actions scheduled workflow (free for public repos): runs this
      script for a few minutes every hour on a cron, commits
      checker_state.json back to the repo so it resumes next run.
    - Oracle Cloud Free Tier: gives a genuinely free-forever small VM if
      you want it running continuously instead of in scheduled bursts.

How to get a Telegram bot token + chat id:
    - Token: message @BotFather on Telegram, /newbot, follow prompts.
    - Chat ID: message your new bot anything, then visit
      https://api.telegram.org/bot<TOKEN>/getUpdates and read "chat":{"id": ...}
"""

import requests
import time
import random
import re
import json
import os

# ==== CONFIG ====
# Reads from environment variables (set as GitHub Secrets when deployed).
# Falls back to placeholders for local testing.
TELEGRAM_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TG_CHAT_ID", "YOUR_CHAT_ID_HERE")

# How many available usernames to find before stopping this run (None = run forever)
MAX_RESULTS = 20

# Cap on total checks per run — useful when scheduling short bursts (e.g. via
# GitHub Actions). Set to None to only stop based on MAX_RESULTS above.
MAX_CHECKS_PER_RUN = 100

STATE_FILE = "checker_state.json"

SIGNUP_URL = "https://www.instagram.com/accounts/web_create_ajax/attempt/"
BASE_URL = "https://www.instagram.com/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE_URL,
}

# Clean-username rule: letters only, nothing else, no length limit
CLEAN_USERNAME_RE = re.compile(r"^[a-zA-Z]+$")

# Word bank used to build meaningful candidates (edit freely).
# Swap in words relevant to your niche/brand for better results.
WORDS = [
    "storm", "ember", "haze", "drift", "orbit", "flux", "echo", "raven",
    "grove", "quartz", "misty", "lunar", "solar", "coral", "amber", "onyx",
    "swift", "aura", "nova", "vivid", "calm", "wild", "prime", "pulse",
    "north", "south", "azure", "ivory", "cedar", "willow", "maple", "sable",
    "rift", "ridge", "vale", "spire", "creek", "glow", "frost", "tide",
    "shade", "gleam", "spark", "dawn", "dusk", "brook", "field", "stone",
]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        return set(data.get("seen", [])), data.get("available", []), data.get("taken", 0), data.get("unclear", 0)
    return set(), [], 0, 0


def save_state(seen, available, taken, unclear):
    with open(STATE_FILE, "w") as f:
        json.dump({
            "seen": list(seen),
            "available": available,
            "taken": taken,
            "unclear": unclear,
        }, f)


def generate_usernames(seen):
    """Yield clean (letters-only) candidate usernames not already checked:
    single words first, then 2-word combos, then 3-word combos — no
    numbers/dots/underscores, no length cap."""
    singles = list(WORDS)
    random.shuffle(singles)
    for w in singles:
        if w not in seen and CLEAN_USERNAME_RE.match(w):
            yield w

    pairs = [(a, b) for a in WORDS for b in WORDS if a != b]
    random.shuffle(pairs)
    for a, b in pairs:
        candidate = a + b
        if candidate not in seen and CLEAN_USERNAME_RE.match(candidate):
            yield candidate

    triples = [(a, b, c) for a in WORDS for b in WORDS for c in WORDS if a != b and b != c and a != c]
    random.shuffle(triples)
    for a, b, c in triples:
        candidate = a + b + c
        if candidate not in seen and CLEAN_USERNAME_RE.match(candidate):
            yield candidate


def get_session():
    """Start a session and grab the csrf token cookie Instagram needs."""
    session = requests.Session()
    session.headers.update(HEADERS)
    resp = session.get(BASE_URL)
    csrf_token = resp.cookies.get("csrftoken")
    if not csrf_token:
        raise RuntimeError("Could not fetch CSRF token — Instagram may have changed their page.")
    session.headers.update({"X-CSRFToken": csrf_token})
    return session


def send_telegram(message):
    """Send a message to your Telegram chat via bot."""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        return  # not configured yet — skip silently
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except requests.RequestException as e:
        print(f"[Telegram error] {e}")


def check_username(session, username):
    """Returns True if available, False if taken, None if unclear/error."""
    data = {
        "email": f"{username}_{random.randint(1000,9999)}@example.com",
        "username": username,
        "first_name": "Test",
        "opt_into_one_tap": "false",
    }
    try:
        resp = session.post(SIGNUP_URL, data=data, timeout=10)
        result = resp.json()
    except (ValueError, requests.RequestException):
        return None

    errors = result.get("errors", {})
    username_errors = errors.get("username", [])

    if not username_errors:
        return True  # no error about username -> it's free

    for err in username_errors:
        msg = err.get("message", "").lower() if isinstance(err, dict) else str(err).lower()
        if "taken" in msg or "another account" in msg:
            return False
        if "only allowed" in msg or "letters" in msg or "too" in msg:
            return None  # invalid format, not a taken/available signal

    return None


def main():
    session = get_session()
    seen, available, taken, unclear = load_state()

    if not available and taken == 0 and unclear == 0:
        send_telegram("🔎 Instagram username search started...")
    else:
        send_telegram(f"▶️ Resuming search — {len(available)} found so far.")

    checks_this_run = 0
    new_available_this_run = 0

    for username in generate_usernames(seen):
        result = check_username(session, username)
        seen.add(username)

        if result is True:
            print(f"[AVAILABLE] {username}")
            available.append(username)
            new_available_this_run += 1
            send_telegram(f"✅ Available: {username}")
        elif result is False:
            print(f"[TAKEN]     {username}")
            taken += 1
        else:
            print(f"[UNCLEAR]   {username}")
            unclear += 1

        checks_this_run += 1
        save_state(seen, available, taken, unclear)  # checkpoint after every check

        if MAX_RESULTS and len(available) >= MAX_RESULTS:
            break
        if MAX_CHECKS_PER_RUN and checks_this_run >= MAX_CHECKS_PER_RUN:
            break

        # shortened delay — still randomized to look less like a bot.
        # Lowering this further raises block risk; this is close to the
        # practical floor for the free signup-check endpoint.
        time.sleep(random.uniform(1.5, 3))

    if new_available_this_run:
        new_names = "\n".join(available[-new_available_this_run:])
    else:
        new_names = "(none)"

    summary = (
        f"⏸ Paused after this run.\n"
        f"Checked this run: {checks_this_run}\n"
        f"New available this run: {new_available_this_run}\n"
        f"Total available: {len(available)}\n"
        f"Total taken: {taken}\nTotal unclear: {unclear}\n\n"
        f"New: {new_names}"
    )
    print("\n--- Summary ---")
    print(summary)
    send_telegram(summary)

    with open("available_usernames.txt", "w") as f:
        f.write("\n".join(available))

    summary = (
        f"⏸ Paused after this run.\n"
        f"Checked this run: {checks_this_run}\n"
        f"New available this run: {new_available_this_run}\n"
        f"Total available: {len(available)}\n"
        f"Total taken: {taken}\nTotal unclear: {unclear}\n\n"
        f"New: {new_names}"
    )
    print("\n--- Summary ---")
    print(summary)
    send_telegram(summary)

    with open("available_usernames.txt", "w") as f:
        f.write("\n".join(available))


if __name__ == "__main__":
    main()
