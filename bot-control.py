# ПУЛЬТ В TELEGRAM: управление поиском клиентов через бота @pepeclodai715bot.
#
# Работает в фоне на компьютере (без окна, стоит в автозагрузке) и слушает бота. Команды — ТОЛЬКО от Егора.
# Кнопки внизу:  ▶️ Запустить · ⏹ Остановить · 📊 Статус · 💬 Ответы · 📤 Отправленные · ⚙️ Настройки · 📝 Лог · ♻️ Перезапуск
# Под сообщениями: 🔄 Обновить (обновляет то же сообщение), в уведомлениях об ответах — быстрые ответы клиенту.
# Сам: перезапускает упавший поиск, будит зависший (сторож), присылает итог дня в 21:00.
import os, re, sys, json, time, datetime, subprocess, urllib.request, urllib.error, uuid

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(BASE))
BOTFILE = os.path.join(ROOT, ".telegram-bot.txt")
CFG = os.path.join(BASE, "bot-control.json")
MYLOCK = os.path.join(BASE, "bot-control.lock")
SEARCH_LOCK = os.path.join(BASE, "running.lock")
STATE = os.path.join(BASE, "state.json")
SETTINGS = os.path.join(BASE, "settings.json")
INBOX = os.path.join(BASE, "inbox")
LIVE = os.path.join(BASE, "live.json")
LOGF = os.path.join(BASE, "log.txt")
CLOG = os.path.join(BASE, "bot-control.log")
OWNER = 5787402361
PY = sys.executable.replace("pythonw.exe", "python.exe")
NO_WINDOW = 0x08000000
REPORT_HOUR = 21          # итог дня — в 21:00 по времени компьютера
WATCHDOG_MIN = 20         # нет признаков жизни столько минут — перезапуск поиска
DEFAULTS = {"gap": 30, "limit_hot": 40, "limit_cold": 20, "hot_on": True, "cold_on": True, "fu_on": True}

B_START, B_STOP = "▶️ Запустить", "⏹ Остановить"
B_STATUS, B_REPLIES, B_SENT = "📊 Статус", "💬 Ответы", "📤 Отправленные"
B_SETTINGS, B_LOG, B_RESTART = "⚙️ Настройки", "📝 Лог", "♻️ Перезапуск"
KEYBOARD = {"keyboard": [[{"text": B_START}, {"text": B_STOP}],
                         [{"text": B_STATUS}, {"text": B_REPLIES}, {"text": B_SENT}],
                         [{"text": B_SETTINGS}, {"text": B_LOG}, {"text": B_RESTART}]],
            "resize_keyboard": True, "is_persistent": True}

# Быстрые ответы клиенту — по прайсу 2.0 и «скрипту как ответить 2.0» Егора
QR = {
    "price": ("💰 Прайс",
              "Мои цены (прайс на ноябрь):\n\n"
              "Короткие ролики (Reels, Shorts, TikTok до 90 сек):\n"
              "• Базовый — 3 000 ₽: склейка, цвет, простые субтитры, 2 круга правок\n"
              "• Стандарт — 5 000 ₽: + звук, музыка, динамичные субтитры, SFX, акценты внимания\n"
              "• Премиум — 8 000 ₽: + моушен-дизайн и инфографика, 3 круга правок, сдача за 24 часа\n\n"
              "Длинные (YouTube, VK): 1–5 мин — от 5 000 ₽, 5–15 мин — от 10 000 ₽.\n"
              "Пакеты на месяц: 5 роликов — 12 000 ₽, 10 роликов — 40 000 ₽ (выгода 20%).\n\n"
              "Работаю по договору, с чеком самозанятого, предоплата 50%. Какой формат вам ближе?"),
    "works": ("🎬 Примеры",
              "Мои работы: https://t.me/zakulisy715 — там ролики для экспертов, разборы и закулисье монтажа.\n"
              "Свежий кейс — Reels для эксперта по ипотеке: https://t.me/zakulisy715/45\n\n"
              "Пришлёте 2–3 ролика, которые вам нравятся? Так я сразу попаду в нужный стиль."),
    "brief": ("📋 Что нужно",
              "Чтобы начать, нужно совсем немного:\n"
              "1) исходники видео (можно с телефона)\n"
              "2) 2–3 примера роликов, которые нравятся\n"
              "3) пара слов о цели ролика и площадке\n\n"
              "Дальше согласуем ТЗ и сроки, подписываем договор, предоплата 50% — и через 1–2 дня у вас готовый ролик."),
    "call": ("📞 Созвон",
             "Давайте созвонимся на 10–15 минут: обсудим задачу, сроки и формат — так быстрее, чем в переписке. "
             "Когда вам удобно сегодня или завтра?"),
    "test": ("🧪 Тест",
             "Могу сделать тестовый фрагмент на 10–15 секунд по вашему исходнику, чтобы вы оценили стиль до оплаты. "
             "Пришлите материал — сделаю в течение дня."),
}

# ---------------------------------------------------------------- служебное
def clog(*a):
    try:
        with open(CLOG, "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now().strftime("%d.%m %H:%M:%S ") + " ".join(map(str, a)) + "\n")
    except Exception: pass

def jload(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return d

def jsave(p, data):
    with open(p + ".tmp", "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)

def settings():
    s = dict(DEFAULTS); s.update(jload(SETTINGS, {})); return s

TOKEN = os.environ.get("BOT_TOKEN") or \
    re.search(r"\d{6,}:[A-Za-z0-9_-]{30,}", open(BOTFILE, encoding="utf-8").read()).group(0)

def api(method, http_timeout=30, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", data=json.dumps(params).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=http_timeout) as r:
        return json.loads(r.read())

def say(text, markup=None, silent=False):
    try: api("sendMessage", chat_id=OWNER, text=text[:4000], reply_markup=markup or KEYBOARD,
             disable_web_page_preview=True, disable_notification=silent)
    except Exception as e: clog("не отправил:", e)

def edit(mid, text, markup):
    try: api("editMessageText", chat_id=OWNER, message_id=mid, text=text[:4000], reply_markup=markup,
             disable_web_page_preview=True)
    except urllib.error.HTTPError as e:
        if e.code != 400: clog("edit:", e)       # 400 = «текст не изменился» — это нормально
    except Exception as e: clog("edit:", e)

def answer(cq, text=""):
    try: api("answerCallbackQuery", callback_query_id=cq["id"], text=text[:190])
    except Exception: pass

def to_inbox(cmd):
    os.makedirs(INBOX, exist_ok=True)
    p = os.path.join(INBOX, f"{time.time():.3f}-{uuid.uuid4().hex[:6]}.json")
    jsave(p, dict(cmd, ts=time.time()))

def pid_alive(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             creationflags=NO_WINDOW).stdout
        return str(pid) in out
    except Exception:
        return False

def search_pid():
    try:
        pid = int(open(SEARCH_LOCK).read().strip())
        return pid if pid_alive(pid) else None
    except Exception:
        return None

def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)

def ago(ts):
    m = int((time.time() - ts) // 60)
    return f"{m} мин" if m < 60 else f"{m // 60} ч {m % 60} мин"

# ---------------------------------------------------------------- управление процессом поиска
class Ctl:
    def __init__(self):
        self.cfg = jload(CFG, {})
        self.cfg.setdefault("offset", 0); self.cfg.setdefault("want", False)
        self.proc = None
        self.started = None
        self.crashes = []

    def save(self): jsave(CFG, self.cfg)

    def running(self):
        if self.proc and self.proc.poll() is None: return True
        return search_pid() is not None

    def start(self):
        if self.running(): return False
        err = open(os.path.join(BASE, "autoclient-errors.txt"), "a")
        self.proc = subprocess.Popen([PY, os.path.join(BASE, "autoclient.py")], cwd=BASE, creationflags=NO_WINDOW,
                                     stdout=subprocess.DEVNULL, stderr=err,
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.started = time.time()
        clog("поиск запущен, pid", self.proc.pid)
        return True

    def stop(self):
        stopped = False
        if self.proc and self.proc.poll() is None:
            kill_tree(self.proc.pid); stopped = True
        pid = search_pid()
        if pid:
            kill_tree(pid); stopped = True
        try: os.remove(SEARCH_LOCK)
        except Exception: pass
        self.proc = None; self.started = None
        clog("поиск остановлен")
        return stopped

    def supervise(self):
        if not self.cfg["want"]: return
        if self.running():
            if self.started is None: self.started = time.time()     # запущен прошлым экземпляром пульта
            # сторож: процесс жив, но давно не подаёт признаков жизни — перезапускаем
            lv = jload(LIVE, {})
            last = max(lv.get("ts", 0), os.path.getmtime(LOGF) if os.path.exists(LOGF) else 0)
            up = time.time() - (self.started or 0)
            if self.started and up > WATCHDOG_MIN * 60 and time.time() - last > WATCHDOG_MIN * 60:
                clog("сторож: нет активности", ago(last), "— перезапуск")
                self.stop(); time.sleep(5); self.start()
                say(f"🐶 Поиск завис (нет активности {WATCHDOG_MIN}+ мин) — перезапустил сам.", silent=True)
            return
        code = self.proc.returncode if self.proc else None
        if code == 3: return                       # уже работает экземпляр из .bat
        now = time.time()
        self.crashes = [t for t in self.crashes if now - t < 1800] + [now]
        if len(self.crashes) > 5:
            self.cfg["want"] = False; self.save()
            say("⚠️ Поиск падает раз за разом, я его выключил. Глянь 📝 Лог и напиши Claude, что там.")
            return
        clog("поиск завершился (код", code, ") — перезапуск")
        time.sleep(15)
        self.start()

# ---------------------------------------------------------------- тексты экранов
def refresh_kb(what, extra=None):
    rows = [[{"text": "🔄 Обновить", "callback_data": f"refresh:{what}"}]]
    return {"inline_keyboard": (extra or []) + rows}

def stamp():
    return f"\n\n🕐 обновлено {datetime.datetime.now():%H:%M:%S}"

def fmt_status(ctl):
    st, s, lv = jload(STATE, {}), settings(), jload(LIVE, {})
    d = st.get("day", {})
    sent = st.get("sent", {})
    today = d.get("date", "")
    replied = [e for e in sent.values() if e.get("replied")]
    rep_today = [e for e in replied if (e.get("replied") or "")[:10] == datetime.date.today().isoformat()]
    run = ctl.running()
    head = "🟢 Поиск РАБОТАЕТ" + (f" (уже {ago(ctl.started)})" if run and ctl.started else "") if run else "🔴 Поиск ВЫКЛЮЧЕН"
    lines = [head]
    if run and time.time() - lv.get("ts", 0) < 300:
        lines.append(f"Сейчас: {lv.get('phase', '—')}")
        ns = lv.get("next_send", 0)
        if ns and ns > time.time():
            lines.append(f"Следующее сообщение через {int(ns - time.time())} с")
        elif lv.get("why"):
            lines.append(f"Отправка: {lv['why']}")
    lim = st.get("limited_until", "")
    if lim and lim > datetime.datetime.now().isoformat():
        lines.append(f"⛔ Отправка на паузе до {lim[11:16]} {lim[8:10]}.{lim[5:7]} (защита аккаунта), поиск идёт")
    lines += [f"\nСегодня ({today[8:10]}.{today[5:7]}):" if today else "\nСегодня:",
              f"• откликов на вакансии: {d.get('hot', 0)} из {s['limit_hot']}",
              f"• холодных: {d.get('cold', 0)}, дожимов: {d.get('fu', 0)} (лимит {s['limit_cold']})",
              f"• ответили: {len(rep_today)} (🔥 {sum(1 for e in rep_today if e.get('outcome') != 'no')}, "
              f"❌ {sum(1 for e in rep_today if e.get('outcome') == 'no')})",
              f"\nОчередь: вакансий {len(st.get('hot_q', []))}, холодных {len(st.get('cold_q', []))}",
              f"Всего: отправлено {len(sent)}, ответили {len(replied)}"
              + (f" ({100 * len(replied) // len(sent)}%)" if sent else ""),
              f"⏱ Пауза между сообщениями: {s['gap']} с"]
    return "\n".join(lines)

def fmt_replies():
    st = jload(STATE, {})
    rows = sorted(((e["replied"], u, e) for u, e in st.get("sent", {}).items() if e.get("replied")), reverse=True)
    if not rows: return "Пока никто не ответил. Как только ответят — пришлю сразу 🔥", []
    out, kb = ["Последние ответы:"], []
    for when, u, e in rows[:10]:
        mark = "❌" if e.get("outcome") == "no" else "🔥"
        done = f" · ты ответил: {', '.join(x['what'] for x in e.get('my', []))}" if e.get("my") else ""
        out.append(f"{mark} {when[8:10]}.{when[5:7]} {when[11:16]} — {e.get('display', '')} (@{u}){done}")
        if e.get("outcome") != "no" and len(kb) < 5:
            kb.append([{"text": f"💬 {e.get('display', u)[:25]}", "url": f"https://t.me/{u}"}])
    return "\n".join(out), kb

def fmt_sent():
    st = jload(STATE, {})
    rows = sorted(st.get("sent", {}).items(), key=lambda x: x[1].get("ts", 0), reverse=True)[:10]
    if not rows: return "Ещё ничего не отправлено."
    out = ["Последние отправленные:"]
    for u, e in rows:
        t = datetime.datetime.fromtimestamp(e.get("ts", 0)).strftime("%H:%M")
        kind = "вакансия" if e.get("kind") == "hot" else "холодное"
        mark = " ✅ ответил" if e.get("replied") else ""
        out.append(f"• {t} {kind} → {e.get('display', '')} (@{u}){mark}\n  {e.get('source', '')}")
    return "\n".join(out)

def fmt_log():
    try: lines = open(LOGF, encoding="utf-8").read().strip().splitlines()
    except Exception: return "Лог пуст."
    lines = [l for l in lines if re.match(r"\d\d\.\d\d \d", l)][-15:]
    return "Последние 15 событий:\n\n" + "\n".join(l[:170] for l in lines)

def render(what, ctl):
    if what == "status": return fmt_status(ctl) + stamp(), refresh_kb("status")
    if what == "replies":
        text, kb = fmt_replies(); return text + stamp(), refresh_kb("replies", kb)
    if what == "sent": return fmt_sent() + stamp(), refresh_kb("sent")
    if what == "log": return fmt_log() + stamp(), refresh_kb("log")
    return "?", None

GAPS, HOTS, COLDS = [30, 60, 90, 180, 300], [25, 40, 60, 100], [0, 10, 20, 40]

def render_settings():
    s = settings()
    mark = lambda cur, v: f"• {v} •" if cur == v else str(v)
    onoff = lambda k: "✅" if s[k] else "❌"
    text = ("⚙️ Настройки — меняются сразу, без перезапуска\n\n"
            f"⏱ Пауза между сообщениями: {s['gap']} с\n"
            f"📈 Откликов на вакансии в день: {s['limit_hot']}\n"
            f"❄️ Холодных + дожимов в день: {s['limit_cold']}\n"
            f"Вакансии {onoff('hot_on')} · Холодные {onoff('cold_on')} · Дожимы {onoff('fu_on')}\n\n"
            "⚠️ Чем чаще и больше сообщений незнакомым, тем выше риск, что Telegram ограничит аккаунт.")
    kb = [[{"text": "⏱ пауза, сек:", "callback_data": "noop"}],
          [{"text": mark(s["gap"], g), "callback_data": f"set:gap:{g}"} for g in GAPS],
          [{"text": "📈 вакансий в день:", "callback_data": "noop"}],
          [{"text": mark(s["limit_hot"], v), "callback_data": f"set:limit_hot:{v}"} for v in HOTS],
          [{"text": "❄️ холодных в день:", "callback_data": "noop"}],
          [{"text": mark(s["limit_cold"], v), "callback_data": f"set:limit_cold:{v}"} for v in COLDS],
          [{"text": f"Вакансии {onoff('hot_on')}", "callback_data": "tog:hot_on"},
           {"text": f"Холодные {onoff('cold_on')}", "callback_data": "tog:cold_on"},
           {"text": f"Дожимы {onoff('fu_on')}", "callback_data": "tog:fu_on"}],
          [{"text": "🛡 Проверить аккаунт (@SpamBot)", "callback_data": "spamcheck"}]]
    return text, {"inline_keyboard": kb}

HELP = ("Пульт поиска клиентов 🎬\n\n"
        f"{B_START} / {B_STOP} — включить / выключить поиск\n"
        f"{B_STATUS} — что происходит прямо сейчас и итоги дня\n"
        f"{B_REPLIES} — кто ответил, со ссылками на чаты\n"
        f"{B_SENT} — кому и по какой вакансии написал\n"
        f"{B_SETTINGS} — пауза между сообщениями, лимиты, что включено\n"
        f"{B_LOG} — последние события · {B_RESTART} — перезапустить поиск\n\n"
        "🔄 Обновить под сообщением — освежает его на месте.\n"
        "Когда клиент ответит — пришлю 🔥 с кнопками быстрого ответа: прайс, примеры, созвон, тест или свой текст.")

# ---------------------------------------------------------------- обработка команд
def handle_text(ctl, text):
    t = (text or "").strip()
    low = t.lower()
    pend = ctl.cfg.get("pending")
    if low in ("/cancel", "отмена"):
        ctl.cfg.pop("pending", None); ctl.save(); say("Ок, отменил."); return
    buttons = {B_START.lower(), B_STOP.lower(), B_STATUS.lower(), B_REPLIES.lower(), B_SENT.lower(),
               B_SETTINGS.lower(), B_LOG.lower(), B_RESTART.lower()}
    if pend and low not in buttons and not low.startswith("/") and time.time() < pend.get("until", 0):
        to_inbox({"cmd": "send", "to": pend["to"], "text": t, "label": "✍️ Твой ответ"})
        ctl.cfg.pop("pending", None); ctl.save()
        say(f"📨 Отправляю @{pend['to']}…" + ("" if ctl.running() else "\nПоиск выключен — уйдёт сразу после ▶️ Запустить."))
        return
    if low in ("/start", "/help", "помощь", "меню"):
        say(HELP)
    elif low in (B_START.lower(), "/go", "/run", "запустить", "старт"):
        ctl.cfg["want"] = True; ctl.crashes = []; ctl.save()
        if ctl.start(): say("▶️ Запускаю поиск. Через минуту нажми 📊 Статус — увидишь, чем он занят.")
        else: say("Поиск уже работает 🟢")
    elif low in (B_STOP.lower(), "/stop", "стоп", "остановить"):
        ctl.cfg["want"] = False; ctl.save()
        say("⏹ Поиск остановлен." if ctl.stop() else "Поиск и так был выключен.")
    elif low in (B_RESTART.lower(), "/restart", "перезапуск"):
        ctl.cfg["want"] = True; ctl.save()
        ctl.stop(); time.sleep(3); ctl.start()
        say("♻️ Перезапустил поиск — через минуту он снова в работе.")
    elif low in (B_STATUS.lower(), "/status", "статус"):
        say(*render("status", ctl))
    elif low in (B_REPLIES.lower(), "/replies", "ответы"):
        say(*render("replies", ctl))
    elif low in (B_SENT.lower(), "/sent", "отправленные"):
        say(*render("sent", ctl))
    elif low in (B_LOG.lower(), "/log", "лог"):
        say(*render("log", ctl))
    elif low in (B_SETTINGS.lower(), "/settings", "настройки"):
        say(*render_settings())
    else:
        say("Не понял. Нажми кнопку внизу 👇")

def handle_callback(ctl, cq):
    data = cq.get("data", "")
    mid = (cq.get("message") or {}).get("message_id")
    if data.startswith("refresh:"):
        text, kb = render(data.split(":", 1)[1], ctl)
        edit(mid, text, kb); answer(cq, "Обновлено ✅")
    elif data.startswith("set:"):
        _, key, val = data.split(":")
        s = settings(); s[key] = int(val); jsave(SETTINGS, s)
        edit(mid, *render_settings()); answer(cq, "Сохранено — действует сразу")
    elif data.startswith("tog:"):
        key = data.split(":")[1]
        s = settings(); s[key] = not s[key]; jsave(SETTINGS, s)
        edit(mid, *render_settings()); answer(cq, "Сохранено")
    elif data == "spamcheck":
        to_inbox({"cmd": "spamcheck"})
        answer(cq, "Проверяю — ответ придёт через минуту" if ctl.running() else "Поиск выключен — проверю после запуска")
    elif data.startswith("qr:"):
        _, kind, u = data.split(":", 2)
        if kind == "own":
            ctl.cfg["pending"] = {"to": u, "until": time.time() + 900}; ctl.save()
            answer(cq)
            say(f"✍️ Напиши ответ для @{u} одним сообщением — отправлю от твоего имени.\nПередумал — /cancel",
                markup={"force_reply": True, "input_field_placeholder": f"Ответ для @{u}"})
        elif kind in QR:
            label, text = QR[kind]
            to_inbox({"cmd": "send", "to": u, "text": text, "label": label})
            answer(cq, f"{label}: отправляю…" if ctl.running() else "Поиск выключен — отправлю после ▶️ Запустить")
    else:
        answer(cq)

def evening_report(ctl):
    st, s = jload(STATE, {}), settings()
    d = st.get("day", {})
    sent = st.get("sent", {})
    today = datetime.date.today().isoformat()
    rep = [e for e in sent.values() if (e.get("replied") or "")[:10] == today]
    hot = [e for e in rep if e.get("outcome") != "no"]
    allrep = sum(1 for e in sent.values() if e.get("replied"))
    text = (f"📊 Итог дня {datetime.date.today():%d.%m}\n\n"
            f"Отправлено: откликов на вакансии {d.get('hot', 0)}, холодных {d.get('cold', 0)}, дожимов {d.get('fu', 0)}\n"
            f"Ответили сегодня: {len(rep)} (🔥 {len(hot)}, ❌ {len(rep) - len(hot)})\n"
            f"За всё время: отправлено {len(sent)}, ответили {allrep}"
            + (f" ({100 * allrep // len(sent)}%)" if sent else "") +
            f"\nВ очереди на завтра: вакансий {len(st.get('hot_q', []))}, холодных {len(st.get('cold_q', []))}\n\n"
            + ("🔥 Проверь, что ответил всем заинтересованным: " + ", ".join(
                   f"@{u}" for u, e in sent.items()
                   if (e.get('replied') or '')[:10] == today and e.get('outcome') != 'no')[:300]
               if hot else "Поиск продолжается и ночью: заказы собираются, отправка — по расписанию."))
    say(text, markup=refresh_kb("status"))

def process_update(ctl, u):
    """Одно обновление от Telegram: нажатие кнопки или сообщение. Общее для пульта на ПК и для облака."""
    ctl.cfg["offset"] = u["update_id"] + 1; ctl.save()
    if "callback_query" in u:
        cq = u["callback_query"]
        if (cq.get("from") or {}).get("id") != OWNER: answer(cq, "Нет доступа"); return
        clog("кнопка:", cq.get("data"))
        handle_callback(ctl, cq)
        return
    m = u.get("message") or {}
    if (m.get("from") or {}).get("id") != OWNER: return              # чужим не подчиняемся
    if time.time() - m.get("date", 0) > 600: return                 # старые нажатия (пульт был выключен)
    clog("команда:", (m.get("text") or "")[:60])
    handle_text(ctl, m.get("text"))

def take_lock():
    try:
        pid = int(open(MYLOCK).read().strip())
        if pid != os.getpid() and pid_alive(pid): return False
    except Exception: pass
    with open(MYLOCK, "w") as f: f.write(str(os.getpid()))
    return True

def main():
    if not take_lock():
        clog("пульт уже запущен — выхожу"); return
    if not os.path.exists(SETTINGS): jsave(SETTINGS, DEFAULTS)
    os.makedirs(INBOX, exist_ok=True)
    ctl = Ctl()
    clog("пульт запущен")
    try: api("setMyCommands", commands=[{"command": "start", "description": "Меню пульта"},
                                         {"command": "status", "description": "Статус поиска"},
                                         {"command": "settings", "description": "Настройки"},
                                         {"command": "stop", "description": "Остановить поиск"}])
    except Exception: pass
    note = ""
    if not ctl.cfg.get("v3"):
        ctl.cfg["v3"] = True; ctl.save()
        note = ("\n\n🆕 Что нового: ⚙️ Настройки (пауза, лимиты, вкл/выкл — прямо отсюда), 📤 Отправленные, "
                "♻️ Перезапуск, 🔄 Обновить под сообщениями. Когда клиент ответит — под уведомлением будут "
                "кнопки быстрого ответа: прайс, примеры, что нужно, созвон, тест или свой текст.")
    if ctl.cfg.get("want") and not ctl.running():
        ctl.start(); say("🔄 Пульт запущен — продолжаю поиск клиентов." + note)
    else:
        say("🤖 Пульт на связи. " + ("Поиск работает 🟢" if ctl.running() else "Поиск выключен — нажми ▶️ Запустить.") + note)
    while True:
        try:
            r = api("getUpdates", http_timeout=40, offset=ctl.cfg["offset"], timeout=25,
                    allowed_updates=["message", "callback_query"])
            for u in r.get("result", []):
                process_update(ctl, u)
        except Exception as e:
            clog("ошибка связи:", str(e)[:120]); time.sleep(5)
        try: ctl.supervise()
        except Exception as e: clog("ошибка надзора:", e)
        try:
            now = datetime.datetime.now()
            if now.hour == REPORT_HOUR and ctl.cfg.get("report_date") != now.date().isoformat():
                ctl.cfg["report_date"] = now.date().isoformat(); ctl.save()
                evening_report(ctl)
        except Exception as e: clog("отчёт:", e)

if __name__ == "__main__":
    main()
