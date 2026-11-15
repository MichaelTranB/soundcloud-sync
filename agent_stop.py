#!/usr/bin/env python3
"""Claude's "keep going" check for a Have-Claude-download-them run (app.py starts Claude with it as a Stop hook).

Each time Claude goes to stop, it counts the free links still on The Crate's list. While some are left, Claude is
sent back to the list once with a reminder: songs waiting on a sign-in are skipped and come back later, so one
login doesn't end a long run. The second stop in a row always goes through, so Claude can still finish, or ask a
question it truly needs answered."""
import json, os, re, sys

try:
    if json.load(sys.stdin).get("stop_hook_active"):
        sys.exit(0)  # already sent back once this turn: let it stop
except ValueError:
    pass
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "to-buy.tsv")) as f:
        left = sum(1 for l in f if len(p := l.rstrip("\n").split("\t")) > 2 and re.match(r"https?://\S+$", p[2]))
except OSError:
    sys.exit(0)
if left:
    print(json.dumps({"decision": "block", "reason":
        f"The Crate still lists {left} free song(s). If any is one you can still get, carry on with it. Songs "
        "waiting on me (a sign-in, a code, a check): leave their tabs open, tell me in one line, and check back on "
        "them now and then. If you're asking me something you can't go on without, or every song left is done, "
        "skipped or waiting on me, stop now with your short list."}))
