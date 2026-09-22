"""Manual live check (needs both servers + API key): replay the "in uk" report.

    .venv/Scripts/python.exe tests/live_in_uk.py
"""
import json
import time
import urllib.request

URL = "http://localhost:3000/api/chat/stream"


def say(message, sid=None):
    body = {"message": message, **({"session_id": sid} if sid else {})}
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    toks, slots, done = [], None, None
    with urllib.request.urlopen(req, timeout=180) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace")
            if not line.startswith("data: "):
                continue
            d = json.loads(line[6:])
            if "text" in d and len(d) == 1:
                toks.append(d["text"])
            elif "filled" in d:
                slots = d
            elif "session_id" in d and "diagnostics_unlocked" in d:
                done = d
    return "".join(toks).strip(), slots, done


sid, last = None, None
for message in ["I am Unaiza from Pakistan", "bachelors, cgpa 3.5 out of 4", "in uk"]:
    text, slots, done = say(message, sid)
    sid = done["session_id"] if done else sid
    last = slots or last
    print(f"\nUSER : {message}\nVERA : {text[:180]}")
    if slots:
        s = slots["slots"]
        print(f"  field_of_study={s.get('field_of_study')!r}  target={s.get('target_country')!r}")
    time.sleep(14)

field = last["slots"].get("field_of_study") if last else None
print("\nPASS" if field is None or "uk" not in str(field).lower() else f"\nFAIL: field={field!r}")
