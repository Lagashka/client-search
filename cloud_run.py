# Запуск поиска клиентов в облаке (GitHub Actions). Локально не нужен — на ПК работает autoclient.py.
import os, sys, base64, gzip
os.environ["CLOUD"] = "1"
sys.argv = [sys.argv[0]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# лог переживает перезапуски (кэш GitHub) — не даём ему расти бесконечно
LOG = os.path.join(HERE, "log.txt")
try:
    if os.path.getsize(LOG) > 2_000_000:
        with open(LOG, "rb") as f: f.seek(-1_000_000, 2); tail = f.read()
        with open(LOG, "wb") as f: f.write(tail[tail.find(b"\n") + 1:])
except OSError:
    pass

def assemble_state(env=os.environ, out=os.path.join(HERE, "webstate.json")):
    """Сессия Telegram Web лежит в секретах кусками WEB_STATE_0..7 (base64 от gzip). Собираем в файл на время запуска."""
    parts = []
    for i in range(8):
        v = env.get(f"WEB_STATE_{i}", "").strip()
        if not v: break
        parts.append(v)
    if not parts: return None
    with open(out, "wb") as f: f.write(gzip.decompress(base64.b64decode("".join(parts))))
    return out

def merge_seed(env=os.environ, path=os.path.join(HERE, "state.json")):
    """База с ПК (секрет STATE_SEED, base64 от gzip JSON) подмешивается в облачное состояние один раз."""
    import json, hashlib
    raw = env.get("STATE_SEED", "").strip()
    if not raw: return
    sid = hashlib.sha1(raw.encode()).hexdigest()[:12]
    try: st = json.load(open(path, encoding="utf-8"))
    except Exception: st = {}
    if st.get("seed_id") == sid: return
    seed = json.loads(gzip.decompress(base64.b64decode(raw)))
    sent = st.setdefault("sent", {})
    for u, e in seed.get("sent", {}).items():
        if u not in sent or len(e.get("history", [])) > len(sent[u].get("history", [])): sent[u] = e
    for k in ("contacted", "bad", "seen", "hot_seen", "notified", "hot_channels"):
        st[k] = sorted(set(st.get(k, [])) | set(seed.get(k, [])))
    have = {x["username"].lower() for x in st.get("hot_q", [])}
    done = {u.lower() for u in sent} | {u.lower() for u in st.get("bad", [])}
    st["hot_q"] = [x for x in seed.get("hot_q", []) if x["username"].lower() not in done] + \
                  [x for x in st.get("hot_q", []) if x["username"].lower() not in done and x["username"].lower() not in
                   {y["username"].lower() for y in seed.get("hot_q", [])}]
    if not st.get("cold_q"): st["cold_q"] = [x for x in seed.get("cold_q", []) if x["username"].lower() not in done]
    st["limited_until"] = max(st.get("limited_until", "") or "", seed.get("limited_until", "") or "")
    st.setdefault("hot_rules", seed.get("hot_rules", 1))
    st["seed_id"] = sid
    with open(path, "w", encoding="utf-8") as f: json.dump(st, f, ensure_ascii=False, indent=1)
    print(f"База с ПК подмешана: лидов {len(sent)}, в очереди {len(st['hot_q'])}")

if __name__ == "__main__":
    try: merge_seed()
    except Exception as ex: print("seed:", ex)
    if not os.environ.get("BOT_TOKEN"):
        print("Нет секрета BOT_TOKEN: GitHub → Settings → Secrets and variables → Actions"); sys.exit(1)
    state = assemble_state()
    if state:
        os.environ["WEB_STATE_FILE"] = state
    elif not all(os.environ.get(k) for k in ("TG_API_ID", "TG_API_HASH", "TG_SESSION")):
        print("Нет секретов входа в Telegram (WEB_STATE_0… или TG_API_ID/TG_API_HASH/TG_SESSION)"); sys.exit(1)
    import autoclient
    autoclient.main()
