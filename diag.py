# -*- coding: utf-8 -*-
"""Сводка облачного запуска ТОЛЬКО цифрами (лог Actions публичный — без ников, имён, компаний, текстов).
Шаг «Stats» в workflow: python diag.py → строки DIAG/EVENTS/WHY в логе запуска."""
import json, re, os, sys, datetime, collections
HERE = os.path.dirname(os.path.abspath(__file__))

def jl(p, d):
    try: return json.load(open(os.path.join(HERE, p), encoding="utf-8"))
    except Exception: return d

st, s = jl("state.json", {}), jl("settings.json", {})
today = datetime.date.today().strftime("%d.%m")
try: lines = [l for l in open(os.path.join(HERE, "log.txt"), encoding="utf-8") if l.startswith(today)]
except Exception: lines = []

def clean(l):   # строка лога → шаблон события без имён и цифр
    l = l[15:]
    l = re.sub(r"@\w+|https?://\S+|«[^»]*»|\([^)]*\)|\b[A-Za-z_][A-Za-z0-9_]{4,}\b", "*", l)
    l = re.sub(r"\d+", "#", l)
    return l.split(":")[0][:60].strip() if ":" in l[:70] else l[:60].strip()

ev = collections.Counter(clean(l) for l in lines)

def _yts(st):
    try:
        sys.path.insert(0, HERE); import yt_stats
        return yt_stats.report(st.get("sent") or {})
    except Exception as e: return str(e)[:80]
q = collections.Counter((x.get("variant") or "hot") for x in st.get("hot_q", []))
cq = collections.Counter((x.get("variant") or "?") for x in st.get("cold_q", []))
day = st.get("day", {})
print("DIAG", json.dumps({
    "today": day, "limited_until": st.get("limited_until") or "", "warm_from": st.get("warm_from") or "",
    "hot_q": dict(q), "cold_q": dict(cq),
    "settings": {k: s.get(k) for k in ("hot_on", "cold_on", "fu_on", "biz_on", "partners_on", "niche_on", "yt_on", "mail_on", "limit_hot", "limit_cold", "limit_yt", "limit_fu", "gap", "hold_only")},
    "want": jl("bot-control.json", {}).get("want"),
    "biz_companies": dict(collections.Counter(c.get("status") for c in ((st.get("biz") or {}).get("companies") or {}).values())),
    "partners": {k: len((st.get("partners") or {}).get(k) or []) for k in ("frontier", "boards", "pending", "seen")},
    "youtube": dict({k: len((st.get("yt") or {}).get(k) or []) for k in ("frontier", "pending", "seen")},
                    why=(st.get("yt") or {}).get("why") or {},      # причины отсева и найденные боли — только счёт
                    wait=len(st.get("yt_wait") or {}), mail_q=len((st.get("yt") or {}).get("mail_q") or []),
                    sent_mail=len(st.get("sent_mail") or {}), stats=_yts(st)),
    "mail": {"connected": bool((st.get("mail") or {}).get("init"))},
    "last_kind": st.get("last_kind"),
    "health_h_ago": {k: {f: round((datetime.datetime.now().timestamp() - v[f]) / 3600, 1) for f in ("sent", "found", "since") if v.get(f)}
                     for k, v in (st.get("health") or {}).items()},
    "diag": re.sub(r"@\w+", "*", str(st.get("diag", "")))[:200]}, ensure_ascii=False))
print("EVENTS", json.dumps(dict(ev.most_common(40)), ensure_ascii=False))
