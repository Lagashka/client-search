# Запуск поиска клиентов в облаке (GitHub Actions). Локально не нужен — на ПК работает autoclient.py.
import os, sys
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

for k in ("TG_API_ID", "TG_API_HASH", "TG_SESSION", "BOT_TOKEN"):
    if not os.environ.get(k):
        print(f"Нет секрета {k}: GitHub → Settings → Secrets and variables → Actions"); sys.exit(1)

import autoclient
autoclient.main()
