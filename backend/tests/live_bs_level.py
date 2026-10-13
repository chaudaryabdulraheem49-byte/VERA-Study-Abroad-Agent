"""Manual live check (needs both servers + API key): "BS" must set only the level.

    .venv/Scripts/python.exe tests/live_bs_level.py
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
for message in ["I am Ahmad", "turkish", "BS"]:
    text, slots, done = say(message, sid)
    sid = done["session_id"] if done else sid
    last = slots or last
    print(f"\nUSER : {message}\nVERA : {text[:170]}")
    if slots:
        s = slots["slots"]
        print(f"  field_of_study={s.get('field_of_study')!r}  level={s.get('education_level')!r}")
    time.sleep(14)

s = last["slots"] if last else {}
ok = s.get("field_of_study") is None and s.get("education_level") == "bachelors"
print("\nPASS" if ok else f"\nFAIL: field={s.get('field_of_study')!r} level={s.get('education_level')!r}")
