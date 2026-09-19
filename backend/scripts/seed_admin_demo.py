"""Fill the Firestore *emulator* with realistic synthetic data for the operator
dashboard: users, ledgers, sessions + messages, traces, rollups_daily,
refunds, support tickets, app_errors and config_flags.

    gcloud emulators firestore start --host-port=localhost:8080
    export FIRESTORE_EMULATOR_HOST=localhost:8080 GOOGLE_CLOUD_PROJECT=udhyath-dev
    export ADMIN_EMAILS=you@example.com JWT_SECRET=dev
    python backend/scripts/seed_admin_demo.py --days 30 --users 80
    uvicorn app.main:app --app-dir backend    # then open /admin

The script refuses to run without FIRESTORE_EMULATOR_HOST so it can never
write to a real project. It prints a dev admin token you can paste into the
dashboard's sign-in screen when Firebase web config is not set.
`seed(client, ...)` is importable (the tests and the local preview use it with
an in-memory fake).
"""

import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

USD_TO_INR = 90
FLASH = "gemini-2.5-flash"
OPUS = "claude-opus-4-5"
PRICE = {FLASH: (0.30, 2.50), OPUS: (5.00, 25.00)}  # USD per 1M tokens in/out
IST = timezone(timedelta(hours=5, minutes=30))
LANGS = ["te", "hi", "ta", "kn", "ml"]
LANG_W = [40, 25, 15, 12, 8]
NAMES = ["Ravi", "Lakshmi", "Suresh", "Anitha", "Arjun", "Priya", "Kiran", "Meena",
         "Venkat", "Divya", "Rahul", "Kavya", "Srinivas", "Padma", "Gopal", "Latha"]
INTENTS = {
    "career": ["current_dasha", "tenth_house", "transits"],
    "marriage": ["seventh_house", "navamsa", "current_dasha"],
    "health": ["sixth_house", "transits"],
    "finance": ["second_house", "eleventh_house", "current_dasha"],
    "education": ["fourth_house", "fifth_house"],
}
QUESTIONS = {
    "te": ["నా ఉద్యోగంలో ఎప్పుడు పదోన్నతి వస్తుంది?", "నా వివాహం ఎప్పుడు జరుగుతుంది?",
           "ఈ సంవత్సరం ఆర్థిక పరిస్థితి ఎలా ఉంటుంది?"],
    "hi": ["मेरी नौकरी में प्रमोशन कब होगा?", "मेरी शादी कब होगी?", "इस साल धन की स्थिति कैसी रहेगी?"],
    "ta": ["எனக்கு வேலையில் பதவி உயர்வு எப்போது?", "என் திருமணம் எப்போது நடக்கும்?"],
    "kn": ["ನನಗೆ ಉದ್ಯೋಗದಲ್ಲಿ ಬಡ್ತಿ ಯಾವಾಗ?", "ನನ್ನ ಮದುವೆ ಯಾವಾಗ?"],
    "ml": ["എനിക്ക് ജോലിയിൽ സ്ഥാനക്കയറ്റം എപ്പോൾ?", "എന്റെ വിവാഹം എപ്പോൾ?"],
}
ANSWERS = {
    "te": "మీ జాతకంలో ప్రస్తుతం గురు మహాదశ నడుస్తోంది. దశమ స్థానంపై శని దృష్టి ఉన్నందున వచ్చే ఆరు నెలల్లో మార్పు సూచన ఉంది.",
    "hi": "आपकी कुंडली में अभी गुरु की महादशा चल रही है। दशम भाव पर शनि की दृष्टि से अगले छह महीनों में बदलाव के संकेत हैं।",
    "ta": "உங்கள் ஜாதகத்தில் தற்போது குரு மகாதசை நடக்கிறது. அடுத்த ஆறு மாதங்களில் மாற்றம் தெரிகிறது.",
    "kn": "ನಿಮ್ಮ ಜಾತಕದಲ್ಲಿ ಈಗ ಗುರು ಮಹಾದಶೆ ನಡೆಯುತ್ತಿದೆ. ಮುಂದಿನ ಆರು ತಿಂಗಳಲ್ಲಿ ಬದಲಾವಣೆ ಕಾಣುತ್ತದೆ.",
    "ml": "നിങ്ങളുടെ ജാതകത്തിൽ ഇപ്പോൾ ഗുരു മഹാദശയാണ്. അടുത്ത ആറ് മാസത്തിൽ മാറ്റം കാണുന്നു.",
}


def cost_units(model, tin, tout):
    pin, pout = PRICE[model]
    return int(round((tin * pin + tout * pout) / 1e6 * USD_TO_INR * 100))


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def day_key(dt):
    return dt.astimezone(IST).strftime("%Y-%m-%d")


def make_trace(rnd, uid, sid, lang, mode, at, kind="query", ceiling=500):
    status = rnd.choices(["ok", "refused", "clarify", "error"], [90, 3, 4, 3])[0]
    intent = rnd.choice(list(INTENTS))
    tools = INTENTS[intent]
    stages = []
    pin, pout = rnd.randint(700, 1100), rnd.randint(100, 220)
    stages.append({"name": "plan", "model": FLASH, "in_tok": pin, "out_tok": pout,
                   "cost_units": cost_units(FLASH, pin, pout),
                   "latency_ms": rnd.randint(450, 1100),
                   "detail": {"intent": intent if status != "refused" else "off_topic",
                              "tools": tools if status == "ok" else []}})
    err = None
    if status in ("ok", "error"):
        tool_errors = []
        if status == "error" and rnd.random() < 0.5:
            tool_errors = ["%s: ephemeris lookup failed" % tools[0]]
        stages.append({"name": "tools", "latency_ms": rnd.randint(40, 200),
                       "detail": {"tools": tools, "errors": tool_errors}})
        bin_, bout = rnd.randint(3000, 7000), rnd.randint(700, 1500)
        stages.append({"name": "brief", "model": FLASH, "in_tok": bin_, "out_tok": bout,
                       "cost_units": cost_units(FLASH, bin_, bout),
                       "latency_ms": rnd.randint(1100, 2600)})
        if status == "error":
            err = rnd.choice(["Anthropic API 529 overloaded_error on claude-opus-4-5",
                              "DeadlineExceeded: reason stage timed out after 60s",
                              tool_errors[0] if tool_errors else "brief JSON parse error"])
        else:
            rin = rnd.randint(2800, 4800)
            cap = 350 if mode == "voice" else 1400
            rout = int(min(cap, rnd.lognormvariate(6.35, 0.45)))
            if kind == "report_chapter":
                rin, rout = rnd.randint(5000, 8000), rnd.randint(2500, 4000)
            cache = rnd.choice([0, 0, rnd.randint(1000, 2500)])
            c = cost_units(OPUS, rin - cache, rout) + int(cache * 0.5 / 1e6 * USD_TO_INR * 100)
            stages.append({"name": "reason", "model": OPUS, "in_tok": rin,
                           "cache_read_tok": cache, "out_tok": rout, "cost_units": c,
                           "latency_ms": rnd.randint(2000, 6500)})
            if mode == "voice" and rnd.random() < 0.3:  # cloud speech fallback
                stages.append({"name": "stt", "model": "google-stt-v2",
                               "units": rnd.randint(8, 25), "cost_units": rnd.randint(4, 12)})
                stages.append({"name": "tts", "model": "google-tts-wavenet",
                               "units": rnd.randint(300, 900), "cost_units": rnd.randint(6, 20)})
    total = sum(s.get("cost_units", 0) for s in stages)
    if status == "ok" and kind == "query" and total > ceiling:
        status = "over_ceiling"
    charged = 1000 if status in ("ok", "over_ceiling") and kind == "query" else 0
    tid = uuid.uuid4().hex[:20]
    return {
        "trace_id": tid, "uid": uid, "session_id": sid, "lang": lang, "mode": mode,
        "kind": kind, "status": status, "question_chars": rnd.randint(30, 220),
        "created_at": iso(at), "latency_ms": sum(s.get("latency_ms", 0) for s in stages),
        "stages": stages, "cost_units": total, "charged_units": charged, "error": err,
    }


def seed(db, days=30, users=80, seed_value=7, now=None):
    rnd = random.Random(seed_value)
    now = now or datetime.now(timezone.utc)
    rollups = {}

    def bump(day, key, v=1):
        r = rollups.setdefault(day, {"by_lang": {}})
        if key.startswith("by_lang."):
            k = key.split(".", 1)[1]
            r["by_lang"][k] = r["by_lang"].get(k, 0) + v
        else:
            r[key] = r.get(key, 0) + v

    counts = {"users": 0, "traces": 0, "sessions": 0}
    for i in range(users):
        uid = "demo_%03d" % i
        lang = rnd.choices(LANGS, LANG_W)[0]
        created = now - timedelta(days=rnd.uniform(0, days), hours=rnd.uniform(0, 3))
        name = rnd.choice(NAMES)
        phone = "+9198%08d" % rnd.randint(0, 99999999)
        email = "%s%d@example.com" % (name.lower(), i) if rnd.random() < 0.4 else ""
        user = {"uid": uid, "phone": phone, "email": email, "name": name, "lang": lang,
                "role": "astrologer" if rnd.random() < 0.1 else "user", "balance_units": 0,
                "plan": "free", "created_at": iso(created),
                "device_hashes": [uuid.uuid4().hex[:16]], "trial_claimed": True,
                "fcm_tokens": ["fcm-demo-%d" % i], "notif_prefs": {"daily": True}}
        bump(day_key(created), "signups")
        uref = db.collection("users").document(uid)
        ledger = []
        balance = 0

        def add_ledger(typ, delta, at, ref=""):
            nonlocal balance
            balance += delta
            ledger.append({"type": typ, "delta_units": delta, "balance_after": balance,
                           "ref": ref, "created_at": iso(at)})

        add_ledger("trial", 1000, created, "trial")
        n_sessions = rnd.randint(1, 4)
        for _ in range(n_sessions):
            s_at = created + timedelta(hours=rnd.uniform(0.1, max(0.2, (now - created).total_seconds() / 3600 - 0.1)))
            if s_at > now:
                s_at = now - timedelta(minutes=rnd.randint(1, 50))
            mode = "voice" if rnd.random() < 0.3 else "text"
            if balance < 1000:
                amt = rnd.choice([10000, 20000, 50000])
                add_ledger("topup", amt, s_at - timedelta(minutes=2), "pay_%s" % uuid.uuid4().hex[:10])
                bump(day_key(s_at), "topups_units", amt)
                db.collection("payments").document("pay_" + uuid.uuid4().hex[:12]).set(
                    {"uid": uid, "provider": rnd.choice(["play", "razorpay"]),
                     "amount_units": amt, "status": "captured", "created_at": iso(s_at)})
            sref = db.collection("sessions").document()
            n_q = rnd.randint(1, 5)
            messages = []
            t_at = s_at
            q_count = 0
            for _q in range(n_q):
                t_at = t_at + timedelta(minutes=rnd.uniform(0.5, 6))
                if t_at > now:
                    break
                tr = make_trace(rnd, uid, sref.id, lang, mode, t_at)
                db.collection("traces").document(tr["trace_id"]).set(tr)
                counts["traces"] += 1
                d = day_key(t_at)
                q = rnd.choice(QUESTIONS[lang])
                messages.append({"role": "user", "text": q, "charged_units": 0,
                                 "trace_id": tr["trace_id"], "created_at": iso(t_at)})
                reply = {"ok": ANSWERS[lang], "over_ceiling": ANSWERS[lang],
                         "refused": "(refused) I can only help with astrology questions.",
                         "clarify": "(clarify) Which profile should I use?",
                         "error": "(error) Something went wrong, you were not charged."}[tr["status"]]
                messages.append({"role": "assistant", "text": reply,
                                 "charged_units": tr["charged_units"],
                                 "trace_id": tr["trace_id"],
                                 "created_at": iso(t_at + timedelta(milliseconds=tr["latency_ms"]))})
                if tr["charged_units"]:
                    q_count += 1
                    add_ledger("query", -tr["charged_units"], t_at, tr["trace_id"])
                    bump(d, "queries")
                    bump(d, "revenue_units", tr["charged_units"])
                    bump(d, "by_lang." + lang)
                    if mode == "voice":
                        bump(d, "voice_queries")
                bump(d, "cost_units", tr["cost_units"])
                if tr["status"] == "over_ceiling":
                    bump(d, "over_ceiling")
                elif tr["status"] == "error":
                    bump(d, "errors")
                elif tr["status"] == "refused":
                    bump(d, "refusals")
            sref.set({"uid": uid, "profile_id": "self", "lang": lang, "mode": mode,
                      "created_at": iso(s_at), "summary": "", "query_count": q_count})
            counts["sessions"] += 1
            for m in messages:
                sref.collection("messages").document().set(m)

        # Occasional report purchase (Rs 1050, several Opus chapters).
        if rnd.random() < 0.08 and balance >= 1050:
            r_at = created + (now - created) * rnd.random()
            add_ledger("report", -1050, r_at, "report_demo_%d" % i)
            bump(day_key(r_at), "reports")
            bump(day_key(r_at), "revenue_units", 1050)
            for ch in range(6):
                tr = make_trace(rnd, uid, "", lang, "text", r_at + timedelta(minutes=ch),
                                kind="report_chapter")
                tr["status"] = "ok" if tr["status"] != "error" else "error"
                db.collection("traces").document(tr["trace_id"]).set(tr)
                bump(day_key(r_at), "cost_units", tr["cost_units"])
                counts["traces"] += 1

        if rnd.random() < 0.12 and ledger:
            q_entries = [l for l in ledger if l["type"] == "query"]
            if q_entries:
                l = rnd.choice(q_entries)
                st = rnd.choice(["requested", "requested", "approved", "rejected"])
                db.collection("refunds").document().set(
                    {"uid": uid, "ref": l["ref"], "amount_units": 1000,
                     "reason": rnd.choice(["Answer was in the wrong language",
                                           "App crashed before the answer",
                                           "Answer did not address my question"]),
                     "status": st, "created_at": l["created_at"],
                     "decided_by": "ops@example.com" if st != "requested" else None})
        if rnd.random() < 0.1:
            db.collection("support_tickets").document().set(
                {"uid": uid, "category": rnd.choice(["payment", "answer", "app", "account"]),
                 "message": rnd.choice(["Paid Rs 100 but balance not updated",
                                        "Voice mode is not working on my phone",
                                        "How do I add my wife's birth details?"]),
                 "status": rnd.choice(["open", "open", "resolved"]), "replies": [],
                 "created_at": iso(created + timedelta(hours=1))})

        user["balance_units"] = balance
        uref.set(user)
        for l in ledger:
            uref.collection("ledger").document().set(l)
        uref.collection("profiles").document().set(
            {"name": name, "relation": "self", "time_known": True, "gender": "",
             "birth": {"date": "1990-%02d-%02d" % (rnd.randint(1, 12), rnd.randint(1, 28)),
                       "time": "06:30", "tz": 5.5, "lat": 17.385, "lon": 78.4867,
                       "place": "Hyderabad"}, "created_at": iso(created)})
        counts["users"] += 1

    for d, r in rollups.items():
        db.collection("rollups_daily").document(d).set(r)
    for k in range(6):
        at = now - timedelta(hours=rnd.uniform(0, 72))
        db.collection("app_errors").document().set(
            {"path": rnd.choice(["/api/sessions/x/ask", "/api/wallet/play/verify", "/api/daily"]),
             "method": "POST", "uid": "demo_%03d" % rnd.randint(0, users - 1),
             "error_type": rnd.choice(["KeyError", "TimeoutError", "ValueError"]),
             "message": "synthetic demo error %d" % k,
             "traceback": "Traceback (most recent call last):\n  File \"app.py\", line 1\nKeyError: 'lat'",
             "status": 500, "created_at": iso(at)})
    db.collection("config_flags").document("global").set(
        {"voice_cloud_enabled": True, "opus_enabled": True, "query_price_units": 1000,
         "cost_ceiling_units": 500, "maintenance_message": ""}, merge=True)
    counts["rollup_days"] = len(rollups)
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--users", type=int, default=80)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--admin-email", default="")
    args = ap.parse_args()
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        sys.exit("Refusing to seed: FIRESTORE_EMULATOR_HOST is not set (emulator only).")
    from app import store
    counts = seed(store.fs(), args.days, args.users, args.seed)
    print("Seeded:", counts)
    email = args.admin_email or next(iter(sorted(store.ADMIN_EMAILS)), "")
    if email:
        print("Dev admin token (paste on /admin sign-in):")
        print(store.issue_token("admin-demo", admin_email=email))
    else:
        print("Set ADMIN_EMAILS to get a dev admin token printed here.")


if __name__ == "__main__":
    main()
