# -*- coding: utf-8 -*-
"""Тесты пульта v4 (17.11) без Telegram: главная, клиенты, одобрение писем YouTube, «Ещё», команды в основной бот.
Запуск: python tests_pult.py"""
import os, sys, json, time, tempfile, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("BOT_TOKEN", "123456:" + "x" * 35)
spec = importlib.util.spec_from_file_location("bc", os.path.join(HERE, "bot-control.py"))
bc = importlib.util.module_from_spec(spec); spec.loader.exec_module(bc)

T = tempfile.mkdtemp()
for k in ("CFG", "STATE", "SETTINGS", "INBOX", "LIVE", "LOGF"):
    setattr(bc, k, os.path.join(T, k.lower() + ".json"))
calls = []
bc.api = lambda method, http_timeout=30, **p: calls.append((method, p)) or {"ok": True, "result": []}

ok = bad = 0
def check(name, cond):
    global ok, bad
    if cond: ok += 1; print("  ✓", name)
    else: bad += 1; print("  ✗ ПРОВАЛ:", name)

class C:                                   # как CloudCtl
    def __init__(self): self.cfg = {"offset": 0, "want": True}; self.crashes = []; self.on = True; self.started = time.time()
    def save(self): pass
    def running(self): return self.on
    def start(self): self.on = True; return True
    def stop(self): self.on = False; return True
ctl = C()
now = time.time()
item = lambda u, sc: {"username": u, "display": u.title(), "text": "Добрый день\n\nЯ Егор\n\nПрислать?", "fu_alt": "дожим", "score": sc,
                      "pain": {"pain": "нет Shorts"}, "source": "https://www.youtube.com/channel/X", "found": now, "plat": "YouTube"}
st = {"day": {"date": "2026-11-17", "hot": 3, "cold": 1, "fu": 0, "yt": 2, "by": {"hot": 3, "NICHE": 1, "YT": 2}},
      "yt_wait": {"k1": item("anna", 3), "k2": item("boris", 7)},
      "sent": {"ivan": {"replied": "2026-11-17T18:00", "outcome": "hot", "last_in": "Сколько стоит?", "last_in_ts": now - 3600,
                        "thread": [{"who": "them", "text": "Сколько стоит?"}], "display": "Иван"},
               "olga": {"replied": "2026-11-17T17:00", "outcome": "no", "last_in": "не надо", "last_in_ts": now},
               "petr": {"replied": "2026-11-17T16:00", "outcome": "hot", "last_in_ts": now - 7200, "thread": [{"who": "them"}, {"who": "me"}]}}}
json.dump(st, open(bc.STATE, "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"hot_on": False, "biz_on": False}, open(bc.SETTINGS, "w", encoding="utf-8"))

print("главная")
t, kb = bc.render("home", ctl)
check("статус, отправлено сегодня 6, ждут одобрения 2, клиенты 1", "🟢 Работает" in t and "отправлено 6" in t and "Ждут одобрения: 2" in t and "Клиенты ждут ответа: 1" in t)
check("боты с галочками и счётом: вакансии ❌ 3/40, YouTube ✅ 2/20", "1️⃣ Вакансии ❌ 3/40" in t and "5️⃣ YouTube ✅ 2/20" in t)
check("кнопки: Включить всё, Пауза, Одобрить (2), Клиенты (1), Обновить",
      [b["text"] for r in kb["inline_keyboard"] for b in r] == ["🚀 Включить всё", "⏸ Пауза", "📥 Одобрить (2)", "🔥 Клиенты (1)", "🔄 Обновить"])

print("клиенты")
t, kb = bc.render("leads", ctl)
check("только ждущие ответа: Иван (отказ Ольги и Пётр, которому ты ответил, — нет)", "Иван" in t and "olga" not in t and "petr" not in t)
check("кнопки ответа в одно касание: чат, прайс, тест, свой", [b.get("callback_data") or "url" for b in kb["inline_keyboard"][0]] == ["url", "qr:price:ivan", "qr:test:ivan", "qr:own:ivan"])

print("одобрение")
t, kb = bc.render("approve", ctl)
check("первым — лучший по баллу (boris 7)", "1 из 2" in t and "Boris" in t and "балл 7" in t)
cq = lambda data: {"id": "1", "data": data, "message": {"message_id": 5}, "from": {"id": bc.OWNER}}
bc.handle_callback(ctl, cq("yc:ok:k2"))
inbox = lambda: [json.load(open(os.path.join(bc.INBOX, f), encoding="utf-8")) for f in sorted(os.listdir(bc.INBOX))]
check("✅ → команда yt_ok в основной бот", inbox()[-1]["cmd"] == "yt_ok" and inbox()[-1]["key"] == "k2")
ed = [p for m, p in calls if m == "editMessageText"][-1]
check("карточка сразу сменилась на следующую (anna, 1 из 1)", "1 из 1" in ed["text"] and "Anna" in ed["text"])
bc.handle_callback(ctl, cq("yc:ed:k1"))
check("✏️ → ждёт текст", ctl.cfg.get("pending", {}).get("yt_edit") == "k1")
bc.handle_text(ctl, "Добрый день, мой текст\n\nПрислать?")
check("твой текст → yt_edit в основной бот, ожидание снято", inbox()[-1] == dict(inbox()[-1], cmd="yt_edit", key="k1") and "мой текст" in inbox()[-1]["text"] and not ctl.cfg.get("pending"))
t, kb = bc.render("approve", ctl)
check("после разбора: «одобрять нечего»", "Одобрять нечего" in t)
st["yt_wait"]["k3"] = item("vera", 1); st["yt_wait"]["k4"] = item("gleb", 2)
json.dump(st, open(bc.STATE, "w", encoding="utf-8"), ensure_ascii=False)
bc.handle_callback(ctl, cq("yc:all:x"))
check("✅ Отправить все → одна команда со всеми ключами", inbox()[-1]["cmd"] == "yt_ok_all" and sorted(inbox()[-1]["keys"]) == ["k3", "k4"])

print("главная: кнопки")
bc.handle_callback(ctl, cq("go:all"))
s = bc.settings()
check("🚀 Включить всё: все боты включены", all(s[k] for k, _, _ in bc.BOTS) and ctl.running())
check("ручной режим YouTube и почта не тронуты кнопкой «все»", s.get("yt_manual") is True and s.get("yt_mail_on") is False)
bc.handle_callback(ctl, cq("go:pause"))
check("⏸ Пауза", not ctl.running())
bc.handle_callback(ctl, cq("go:resume"))
check("▶️ Запустить", ctl.running())

print("Ещё")
bc.handle_callback(ctl, cq("m:update"))
check("🔄 Обновить бота → команда update", inbox()[-1]["cmd"] == "update")
bc.handle_callback(ctl, cq("m:warm"))
check("мягкий режим снимается и возвращается", bc.settings().get("warm_off") is True)
bc.handle_callback(ctl, cq("m:warm"))
check("…и возвращается", bc.settings().get("warm_off") is False)

print("клавиатура и старые кнопки")
check("внизу 5 кнопок", sum(len(r) for r in bc.KEYBOARD["keyboard"]) == 5)
n = len(calls); bc.handle_text(ctl, "📊 Статус")
check("старая кнопка «📊 Статус» тоже работает", len(calls) > n and "Сегодня" in calls[-1][1].get("text", ""))
n = len(calls); bc.handle_text(ctl, "🏠 Главная")
check("🏠 Главная", "Ждут одобрения" in calls[-1][1].get("text", ""))

print(f"\nИтого: {ok} прошло, {bad} провалено")
sys.exit(1 if bad else 0)
