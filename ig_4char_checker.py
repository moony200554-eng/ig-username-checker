"""
Instagram 4-Character Username Checker (Automatic + Telegram delivery)
------------------------------------------------------------------------
Separate from the main "meaningful words" checker — this one specifically
brute-forces every valid 4-character username combo, allowing letters,
numbers, dots (.), and underscores (_) — since 4-char handles are rare
and valuable, and don't need to spell an actual word.

Follows Instagram's real username rules:
- Only letters, numbers, periods, underscores
- Cannot start or end with a period
- Cannot have two periods in a row

Resumable: progress saved to checker_state_4char.json (separate from the
main checker's state file, so the two never interfere with each other).

NOTE:
- Uses the same unofficial signup-check endpoint as the main script.
- Delay kept short but randomized to reduce block risk.
- For personal/small-scale use only.

Setup:
    Reads TG_BOT_TOKEN / TG_CHAT_ID from environment variables (same
    GitHub Secrets you already set up) — or edit the fallback values
    below for local testing.
    Run: python ig_4char_checker.py
"""

import requests
import time
import random
import re
import json
import os
import string

# ==== CONFIG ====
TELEGRAM_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TG_CHAT_ID", "YOUR_CHAT_ID_HERE")

# How many available usernames to find before stopping this run (None = run forever)
MAX_RESULTS = 20

# Cap on total checks per run — useful for scheduled short bursts
MAX_CHECKS_PER_RUN = 100

STATE_FILE = "checker_state_4char.json"

SIGNUP_URL = "https://www.instagram.com/accounts/web_create_ajax/attempt/"
BASE_URL = "https://www.instagram.com/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE_URL,
}

# Instagram-valid characters for a username
CHARSET = string.ascii_lowercase + string.digits + "._"

# Instagram-valid 4-char rule: allowed chars, no leading/trailing period,
# no two periods in a row
VALID_4CHAR_RE = re.compile(r"^(?!.*\.\.)[a-z0-9_][a-z0-9_.]{2}[a-z0-9_]$")


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


def generate_4char_usernames(seen):
    """Yield every valid 4-character username combo not already checked,
    in random order."""
    combos = []
    for a in CHARSET:
        for b in CHARSET:
            for c in CHARSET:
                for d in CHARSET:
                    candidate = a + b + c + d
                    if VALID_4CHAR_RE.match(candidate) and candidate not in seen:
                        combos.append(candidate)
    random.shuffle(combos)
    for candidate in combos:
        yield candidate


def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    resp = session.get(BASE_URL)
    csrf_token = resp.cookies.get("csrftoken")
    if not csrf_token:
        raise RuntimeError("Could not fetch CSRF token — Instagram may have changed their page.")
    session.headers.update({"X-CSRFToken": csrf_token})
    return session


def send_telegram(message):
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except requests.RequestException as e:
        print(f"[Telegram error] {e}")


def check_username(session, username):
    data = {
        "email": f"{username.replace('.', '')}_{random.randint(1000,9999)}@example.com",
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
        return True

    for err in username_errors:
        msg = err.get("message", "").lower() if isinstance(err, dict) else str(err).lower()
        if "taken" in msg or "another account" in msg:
            return False
        if "only allowed" in msg or "letters" in msg or "too" in msg:
            return None

    return None


def main():
    session = get_session()
    seen, available, taken, unclear = load_state()

    if not available and taken == 0 and unclear == 0:
        send_telegram("🔎 4-character username search started...")
    else:
        send_telegram(f"▶️ Resuming 4-char search — {len(available)} found so far.")

    checks_this_run = 0
    new_available_this_run = 0

    for username in generate_4char_usernames(seen):
        result = check_username(session, username)
        seen.add(username)

        if result is True:
            print(f"[AVAILABLE] {username}")
            available.append(username)
            new_available_this_run += 1
            send_telegram(f"✅ Available (4-char): {username}")
        elif result is False:
            print(f"[TAKEN]     {username}")
            taken += 1
        else:
            print(f"[UNCLEAR]   {username}")
            unclear += 1

        checks_this_run += 1
        save_state(seen, available, taken, unclear)

        if MAX_RESULTS and len(available) >= MAX_RESULTS:
            break
        if MAX_CHECKS_PER_RUN and checks_this_run >= MAX_CHECKS_PER_RUN:
            break

        time.sleep(random.uniform(1.5, 3))

    summary = (
        f"⏸ Paused after this run (4-char).\n"
        f"New this run: {new_available_this_run}\n"
        f"Total available: {len(available)}\n"
        f"Total taken: {taken}\nTotal unclear: {unclear}\n\n"
        + "\n".join(available[-new_available_this_run:]) if new_available_this_run else "No new ones this run."
    )
    print("\n--- Summary ---")
    print(summary)
    send_telegram(summary)

    with open("available_4char_usernames.txt", "w") as f:
        f.write("\n".join(available))


if __name__ == "__main__":
    main()
