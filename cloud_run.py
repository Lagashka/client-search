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

if __name__ == "__main__":
    if not os.environ.get("BOT_TOKEN"):
        print("Нет секрета BOT_TOKEN: GitHub → Settings → Secrets and variables → Actions"); sys.exit(1)
    state = assemble_state()
    if state:
        os.environ["WEB_STATE_FILE"] = state
    elif not all(os.environ.get(k) for k in ("TG_API_ID", "TG_API_HASH", "TG_SESSION")):
        print("Нет секретов входа в Telegram (WEB_STATE_0… или TG_API_ID/TG_API_HASH/TG_SESSION)"); sys.exit(1)
    import autoclient
    autoclient.main()
