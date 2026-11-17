# ПУЛЬТ В TELEGRAM: управление поиском клиентов через бота @pepeclodai715bot.
#
# Работает в фоне на компьютере (без окна, стоит в автозагрузке) и слушает бота. Команды — ТОЛЬКО от Егора.
# Кнопки внизу:  ▶️ Запустить · ⏹ Остановить · 📊 Статус · 💬 Ответы · 📤 Отправленные · ⚙️ Настройки · 📝 Лог · ♻️ Перезапуск
# Под сообщениями: 🔄 Обновить (обновляет то же сообщение), в уведомлениях об ответах — быстрые ответы клиенту.
# Сам: перезапускает упавший поиск, будит зависший (сторож), присылает итог дня в 21:00.
import os, re, sys, json, time, datetime, subprocess, urllib.request, urllib.error, uuid

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(BASE))
def _find_botfile():
    """Токен бота: ищется рядом с папкой и в «05 Доступы и служебное» (после наведения порядка 05.11)."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        for cand in (os.path.join(d, ".telegram-bot.txt"), os.path.join(d, "05 Доступы и служебное", ".telegram-bot.txt")):
            if os.path.exists(cand):
                return cand
        d = os.path.dirname(d)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".telegram-bot.txt")
BOTFILE = _find_botfile()
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
DEFAULTS = {"gap": 30, "limit_hot": 40, "limit_cold": 20, "limit_fu": 8, "hot_on": True, "cold_on": True, "fu_on": True, "autoreply": True,
            "biz_on": True, "partners_on": True, "niche_on": True, "yt_on": True, "limit_yt": 20, "mail_on": True,
            "yt_manual": True, "yt_mail_on": False, "limit_ytm": 10}

B_START, B_STOP = "▶️ Запустить", "⏹ Остановить"
B_STATUS, B_REPLIES, B_SENT = "📊 Статус", "💬 Ответы", "📤 Отправленные"
B_SETTINGS, B_LOG, B_RESTART = "⚙️ Настройки", "📝 Лог", "♻️ Перезапуск"
B_BASE = "🗂 База лидов"
B_BOTS = "🤖 Боты 1–5"
B_ANALYZE = "🧠 Разбор"
B_ALL = "🚀 Запустить все боты"
BOTS = [("hot_on", "1️⃣ Вакансии", "отклики на вакансии в Telegram-каналах"),
        ("cold_on", "1️⃣ ❄️ Эксперты", "холодные письма экспертам с Telegram-каналами (часть бота 1)"),
        ("biz_on", "2️⃣ Компании", "бизнесы с hh.ru и 2ГИС → личное сообщение"),
        ("partners_on", "3️⃣ Партнёры", "SMM-специалисты, таргетологи, агентства → партнёрство"),
        ("niche_on", "4️⃣ Мастера", "владельцы каналов: стройка и ремонт, авто, премиум-ремесло → короткое письмо"),
        ("yt_on", "5️⃣ YouTube", "эксперты с живыми YouTube-каналами → письмо в Telegram (только у кого он есть)"),
        ("mail_on", "📧 Почта", "видит письма клиентов, останавливает дожимы ответившим"),
        ("fu_on", "🔁 Дожимы", "одно напоминание тем, кто молчит")]
# настройки бота 5 — не боты, кнопки «включить/выключить все» их не трогают
YT_OPTS = [("yt_manual", "5️⃣ ✋ Ручной режим", "каждое письмо YouTube сначала тебе: ✅ Отправить / ❌ Пропустить"),
           ("yt_mail_on", "5️⃣ 📧 На почту", "эксперту без Telegram — письмо на почту с твоего адреса (до 10 в день)")]
# 17.11 пульт v4: 5 кнопок вместо 12. Старые названия кнопок тоже понимаются (у кого осталась старая клавиатура).
B_HOME, B_LEADS, B_APPROVE, B_MORE = "🏠 Главная", "🔥 Клиенты", "📥 Одобрить", "⚙️ Ещё"
KEYBOARD = {"keyboard": [[{"text": B_HOME}, {"text": B_LEADS}],
                         [{"text": B_APPROVE}, {"text": B_BOTS}, {"text": B_MORE}]],
            "resize_keyboard": True, "is_persistent": True}

# Быстрые ответы клиенту — по прайсу 2.0 и «скрипту как ответить 2.0» Егора
QR = {
    "price": ("💰 Прайс",
              "Мои цены (прайс 3.0):\n\n"
              "Видео без владельца:\n"
              "• Старт — 19 000 ₽: разбор бизнеса, обучение вашей команды, карточка правил съёмки, задания на 2 недели и серия из 5 роликов (сценарии, монтаж, субтитры, звук, обложки)\n"
              "• Видеоотдел на месяц — 50 000 ₽: задания на каждый день, 10 роликов, публикация, отчёт и план на следующий месяц (подключается после «Старта»)\n"
              "• Сценарный пакет без монтажа — 7 000 ₽\n\n"
              "Только монтаж: ролик до 90 сек — 3 000 / 5 000 / 8 000 ₽ (базовый / со звуком и SFX / с моушеном и сдачей за 24 ч).\n\n"
              "Работаю по договору, с чеком самозанятого, предоплата 50%. Расскажете, откуда у вас сейчас приходят клиенты?"),
    "works": ("🎬 Примеры",
              "Мои работы: https://t.me/zakulisy715 — там ролики для экспертов, разборы и закулисье монтажа.\n"
              "Свежий кейс — Reels для эксперта по ипотеке: https://t.me/zakulisy715/53\n\n"
              "Пришлёте 2–3 ролика, которые вам нравятся? Так я сразу попаду в нужный стиль."),
    "brief": ("📋 Что нужно",
              "Чтобы начать, нужно совсем немного:\n"
              "1) созвон на 40 минут: кто ваш клиент, что продаёт лучше всего, что нельзя показывать\n"
              "2) один человек из команды, который будет получать задания (связной), и тот, кому нравится говорить в камеру\n"
              "3) ссылка на ваши соцсети или сайт\n\n"
              "Дальше обучаю команду, подписываем договор, предоплата 50% — и в первую неделю у вас первые ролики."),
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
              f"• холодных: {d.get('cold', 0)} из {s['limit_cold']}, YouTube: {d.get('yt', 0)} из {s.get('limit_yt', 20)}, "
              f"дожимов: {d.get('fu', 0)} из {s['limit_fu']}",
              "• по ботам: " + " · ".join(f"{n} {(d.get('by') or {}).get(k, 0)}" for k, n in
                                          (("hot", "1️⃣"), ("cold", "❄️"), ("BIZ", "2️⃣"), ("PARTNER", "3️⃣"), ("NICHE", "4️⃣"), ("YT", "5️⃣"), ("fu", "🔁"))),
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

# ---------------------------------------------------------------- пульт v4: главная, клиенты, одобрение
BOT_ROWS = [(("hot_on", "1️⃣ Вакансии", "hot", "limit_hot"), ("cold_on", "❄️ Эксперты", "cold", None)),
            (("biz_on", "2️⃣ Компании", "BIZ", None), ("partners_on", "3️⃣ Партнёры", "PARTNER", None)),
            (("niche_on", "4️⃣ Мастера", "NICHE", None), ("yt_on", "5️⃣ YouTube", "YT", "limit_yt")),
            (("fu_on", "🔁 Дожимы", "fu", "limit_fu"),)]

def waiting(ctl, st=None):
    """Письма бота 5, которые ждут твоего решения (без уже нажатых)."""
    st = st or jload(STATE, {})
    done = set(ctl.cfg.get("yt_handled") or [])
    return [(k, v) for k, v in sorted((st.get("yt_wait") or {}).items(), key=lambda x: -x[1].get("score", 0)) if k not in done]

def hot_leads(st, days=14):
    """Клиенты, которые ответили и ждут твоего ответа: последнее сообщение — его, не отказ, ты после него не писал."""
    out, now = [], time.time()
    for u, e in (st.get("sent") or {}).items():
        if not e.get("replied") or e.get("outcome") == "no" or e.get("crm") == "refused" or e.get("closed") or e.get("junk"): continue
        th = [m for m in (e.get("thread") or []) if not m.get("auto")]
        if th and th[-1].get("who") != "them": continue
        if e.get("human_ts", 0) > e.get("last_in_ts", 0): continue
        ts = e.get("last_in_ts") or e.get("ts", now)
        if now - ts > days * 86400: continue
        out.append((ts, u, e))
    return sorted(out, reverse=True)

def fmt_home(ctl):
    st, s, lv = jload(STATE, {}), settings(), jload(LIVE, {})
    d, by = st.get("day", {}), (st.get("day", {}).get("by") or {})
    now_iso = datetime.datetime.now().isoformat()
    lim = st.get("limited_until") or ""
    if not ctl.running(): head = "🔴 Выключен — нажми 🚀 Включить всё"
    elif lim > now_iso: head = f"⛔ Пауза до {lim[11:16]} {lim[8:10]}.{lim[5:7]} (защита аккаунта), поиск идёт"
    else: head = "🟢 Работает" + (f" · {lv.get('phase')}" if time.time() - lv.get("ts", 0) < 300 and lv.get("phase") else "")
    wf = st.get("warm_from")
    if wf and not s.get("warm_off"):
        try:
            end = datetime.datetime.fromisoformat(wf) + datetime.timedelta(days=3)
            if end > datetime.datetime.now():
                head += f"\n🟡 Мягкий режим до {end:%d.%m %H:%M}: после бана пишут вакансии, мастера и YouTube, остальные ждут"
        except Exception: pass
    sent_today = sum(by.values()) if by else d.get("hot", 0) + d.get("cold", 0) + d.get("fu", 0)
    rep = [e for e in (st.get("sent") or {}).values() if (e.get("replied") or "")[:10] == datetime.date.today().isoformat()]
    lines = [head, "", f"📤 Сегодня отправлено {sent_today} · ответили {len(rep)} (🔥 {sum(1 for e in rep if e.get('outcome') != 'no')})", ""]
    for row in BOT_ROWS:
        cells = []
        for key, name, slot, limk in row:
            n = by.get(slot, 0)
            cells.append(f"{name} {'✅' if s.get(key, True) else '❌'} {n}" + (f"/{s.get(limk)}" if limk else ""))
        lines.append(" · ".join(cells))
    w, hl = len(waiting(ctl, st)), len(hot_leads(st))
    lines += ["", f"📥 Ждут одобрения: {w}" + (" — нажми, чтобы отправить" if w else ""),
              f"🔥 Клиенты ждут ответа: {hl}" + (" — ответь сейчас, пока тёплые" if hl else "")]
    kb = [[{"text": "🚀 Включить всё", "callback_data": "go:all"}, {"text": "⏸ Пауза" if ctl.running() else "▶️ Запустить",
                                                                   "callback_data": "go:pause" if ctl.running() else "go:resume"}],
          [{"text": f"📥 Одобрить ({w})", "callback_data": "nav:approve"}, {"text": f"🔥 Клиенты ({hl})", "callback_data": "nav:leads"}]]
    return "\n".join(lines), kb

def fmt_leads(ctl):
    rows = hot_leads(jload(STATE, {}))
    if not rows: return "🔥 Сейчас никто не ждёт ответа. Как только клиент ответит — пришлю сразу.", []
    out, kb = [f"🔥 Ждут твоего ответа: {len(rows)} (свежие сверху)"], []
    for ts, u, e in rows[:6]:
        h = int((time.time() - ts) // 3600)
        out.append(f"\n• {e.get('display') or u} (@{u}) · {h} ч назад\n  «{(e.get('last_in') or '')[:120]}»")
        nm = (e.get("display") or u)[:14]
        kb.append([{"text": f"💬 {nm}", "url": f"https://t.me/{u}"}, {"text": "💰", "callback_data": f"qr:price:{u}"},
                   {"text": "🧪", "callback_data": f"qr:test:{u}"}, {"text": "✍️", "callback_data": f"qr:own:{u}"}])
    out.append("\n💬 чат · 💰 прайс · 🧪 тест · ✍️ свой ответ")
    return "\n".join(out), kb

def fmt_card(ctl):
    """Одно письмо на одобрение (лучшее по баллу первым) — кнопки меняют это же сообщение на следующее."""
    w = waiting(ctl)
    if not w: return "📥 Одобрять нечего — все письма разобраны ✅\nНовые придут, как только бот найдёт экспертов.", []
    k, it = w[0]
    pn = (it.get("pain") or {}).get("pain", "")
    to = ("📧 " + it["mail"]) if it.get("mail") else "@" + it["username"]
    text = (f"📥 1 из {len(w)} · 🎥 {it.get('plat', 'YouTube')} · балл {it.get('score', 0)}\n{it.get('display', '')} {to}\n"
            f"{it.get('source', '')}\n🎯 {pn}\n\n✉️ Письмо:\n{it.get('text', '')}\n\n🔁 Через 2 дня, если промолчит:\n{it.get('fu_alt', '')}")
    kb = [[{"text": "✅ Отправить", "callback_data": f"yc:ok:{k}"}, {"text": "✏️ Изменить", "callback_data": f"yc:ed:{k}"},
           {"text": "❌ Пропустить", "callback_data": f"yc:no:{k}"}],
          [{"text": f"✅ Отправить все ({len(w)})", "callback_data": "yc:all:x"}]]
    if it.get("source"): kb.append([{"text": "📺 Открыть канал", "url": it["source"]}])
    return text, kb

def handled(ctl, *keys):
    ctl.cfg["yt_handled"] = ((ctl.cfg.get("yt_handled") or []) + list(keys))[-300:]; ctl.save()

def fmt_more(ctl):
    s = settings()
    return ("⚙️ Ещё — всё остальное", [
        [{"text": "⚙️ Лимиты и пауза", "callback_data": "m:settings"}, {"text": "📝 Лог", "callback_data": "m:log"}],
        [{"text": "📤 Отправленные", "callback_data": "m:sent"}, {"text": "🗂 База лидов", "callback_data": "m:base"}],
        [{"text": "🧠 Разбор нейросетью", "callback_data": "m:analyze"}, {"text": "🛡 Проверить аккаунт", "callback_data": "spamcheck"}],
        [{"text": "🔄 Обновить бота (свежий код)", "callback_data": "m:update"}],
        [{"text": ("🟡 Мягкий режим после бана: ВКЛ" if not s.get("warm_off") else "⚠️ Мягкий режим: ВЫКЛ (риск бана)"),
          "callback_data": "m:warm"}]])

def render(what, ctl):
    if what == "home":
        t, kb = fmt_home(ctl); return t + stamp(), refresh_kb("home", kb)
    if what == "leads":
        t, kb = fmt_leads(ctl); return t + stamp(), refresh_kb("leads", kb)
    if what == "approve":
        t, kb = fmt_card(ctl); return t, {"inline_keyboard": kb + [[{"text": "🔄 Обновить", "callback_data": "refresh:approve"}]]}
    if what == "status": return fmt_status(ctl) + stamp(), refresh_kb("status")
    if what == "replies":
        text, kb = fmt_replies(); return text + stamp(), refresh_kb("replies", kb)
    if what == "sent": return fmt_sent() + stamp(), refresh_kb("sent")
    if what == "log": return fmt_log() + stamp(), refresh_kb("log")
    return "?", None

GAPS, HOTS, COLDS, FUS = [30, 60, 90, 180, 300], [25, 40, 60, 100], [0, 10, 20, 40], [0, 5, 8, 15]
YTS = [0, 10, 20, 30]

def render_settings():
    s = settings()
    mark = lambda cur, v: f"• {v} •" if cur == v else str(v)
    onoff = lambda k: "✅" if s[k] else "❌"
    text = ("⚙️ Настройки — меняются сразу, без перезапуска\n\n"
            f"⏱ Пауза между сообщениями: {s['gap']} с\n"
            f"📈 Откликов на вакансии в день: {s['limit_hot']}\n"
            f"❄️ Новых холодных (эксперты, компании, партнёры, мастера) в день: {s['limit_cold']}\n"
            f"5️⃣ Писем с YouTube в день (отдельный лимит): {s.get('limit_yt', 20)}\n"
            f"🔁 Дожимов и касаний в день: {s['limit_fu']}\n"
            f"Вакансии {onoff('hot_on')} · Холодные {onoff('cold_on')} · Дожимы {onoff('fu_on')}\n\n"
            "⚠️ Чем чаще и больше сообщений незнакомым, тем выше риск, что Telegram ограничит аккаунт.")
    kb = [[{"text": "⏱ пауза, сек:", "callback_data": "noop"}],
          [{"text": mark(s["gap"], g), "callback_data": f"set:gap:{g}"} for g in GAPS],
          [{"text": "📈 вакансий в день:", "callback_data": "noop"}],
          [{"text": mark(s["limit_hot"], v), "callback_data": f"set:limit_hot:{v}"} for v in HOTS],
          [{"text": "❄️ холодных в день:", "callback_data": "noop"}],
          [{"text": mark(s["limit_cold"], v), "callback_data": f"set:limit_cold:{v}"} for v in COLDS],
          [{"text": "5️⃣ YouTube в день:", "callback_data": "noop"}],
          [{"text": mark(s.get("limit_yt", 20), v), "callback_data": f"set:limit_yt:{v}"} for v in YTS],
          [{"text": "🔁 дожимов в день:", "callback_data": "noop"}],
          [{"text": mark(s["limit_fu"], v), "callback_data": f"set:limit_fu:{v}"} for v in FUS],
          [{"text": f"Вакансии {onoff('hot_on')}", "callback_data": "tog:hot_on"},
           {"text": f"Холодные {onoff('cold_on')}", "callback_data": "tog:cold_on"},
           {"text": f"Дожимы {onoff('fu_on')}", "callback_data": "tog:fu_on"}],
          [{"text": f"🤖 Автоответы клиентам {onoff('autoreply')}", "callback_data": "tog:autoreply"}],
          [{"text": "🛡 Проверить аккаунт (@SpamBot)", "callback_data": "spamcheck"}]]
    return text, {"inline_keyboard": kb}

def render_bots():
    s = settings()
    on = lambda k: s.get(k, DEFAULTS.get(k, True))
    lines = [f"{'🟢' if on(k) else '⚪️'} {name} — {about}" for k, name, about in BOTS + YT_OPTS]
    text = ("🤖 Боты — нажми, чтобы включить или выключить. Действует сразу, в облаке.\n\n" + "\n".join(lines) +
            f"\n\nЛимиты в день: вакансии {s['limit_hot']}, эксперты+компании+партнёры+мастера {s['limit_cold']}, "
            f"YouTube {s.get('limit_yt', 20)}, дожимы {s['limit_fu']} (меняются в ⚙️ Настройки).\n"
            "На ответ клиента бот пишет только «Секундочку, сейчас вернусь», дальше ведёшь ты.")
    kb = [[{"text": f"{name} {'✅' if on(k) else '❌'}", "callback_data": f"bot:{k}"}] for k, name, _ in BOTS + YT_OPTS]
    kb.append([{"text": "✅ Включить все", "callback_data": "bot:all_on"}, {"text": "⏸ Выключить все", "callback_data": "bot:all_off"}])
    return text, {"inline_keyboard": kb}

def run_analysis(ctl, days=7, intro=""):
    """🧠 Разбор: цифры по ботам + нейросеть ищет узкие места и предлагает решения; действия — кнопками."""
    try:
        sys.path.insert(0, BASE)
        import analyst
        try: logt = open(LOGF, encoding="utf-8").read()[-400000:]
        except Exception: logt = ""
        text, acts = analyst.report(jload(STATE, {}), logt, settings(), days)
        try:
            import yt_stats
            yts = yt_stats.text(jload(STATE, {}).get("sent") or {})
            if yts: text += "\n\n" + yts
        except Exception: pass
    except Exception as e:
        clog("разбор:", e); say("Разбор не получился: " + str(e)[:150]); return
    ctl.cfg["an_actions"] = acts; ctl.save()
    kb = [[{"text": "✅ " + a["label"], "callback_data": f"an:{i}"}] for i, a in enumerate(acts)]
    kb.append([{"text": "🔄 Разобрать заново", "callback_data": "an:again"}])
    say(intro + text, markup={"inline_keyboard": kb})

HELP = ("Пульт поиска клиентов 🎬\n\n"
        f"{B_HOME} — всё на одном экране: что делает бот, сколько отправлено, кто ждёт тебя; 🚀 Включить всё / ⏸ Пауза\n"
        f"{B_LEADS} — клиенты, которые ответили и ждут тебя: чат, прайс, тест, свой ответ в одно касание\n"
        f"{B_APPROVE} — письма YouTube по одному: ✅ отправить, ✏️ изменить, ❌ пропустить, или отправить все\n"
        f"{B_MORE} — лимиты, лог, база, разбор, проверка аккаунта, обновить бота\n\n"
        f"{B_ALL} — одной кнопкой включить все боты и нейросеть и запустить поиск\n"
        f"{B_BOTS} — включить/выключить бота 1 (вакансии и эксперты), 2 (компании), 3 (партнёры), 4 (мастера), 5 (YouTube)\n"
        f"{B_ANALYZE} — нейросеть разбирает цифры всех ботов и предлагает, что поменять (применяется кнопкой)\n"
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
    buttons = {B_START.lower(), B_STOP.lower(), B_STATUS.lower(), B_REPLIES.lower(), B_SENT.lower(), B_BASE.lower(),
               B_SETTINGS.lower(), B_LOG.lower(), B_RESTART.lower(), B_BOTS.lower(), B_ANALYZE.lower(), B_ALL.lower(),
               B_HOME.lower(), B_LEADS.lower(), B_APPROVE.lower(), B_MORE.lower()}
    if pend and pend.get("yt_edit") and low not in buttons and not low.startswith("/") and time.time() < pend.get("until", 0):
        to_inbox({"cmd": "yt_edit", "key": pend["yt_edit"], "text": t})       # исправленный текст письма → сразу в отправку
        handled(ctl, pend["yt_edit"]); ctl.cfg.pop("pending", None); ctl.save()
        say("✏️ Сохранил твой текст и поставил письмо в отправку ✅", silent=True)
        say(*render("approve", ctl))
        return
    if pend and pend.get("to") and low not in buttons and not low.startswith("/") and time.time() < pend.get("until", 0):
        to_inbox({"cmd": "send", "to": pend["to"], "text": t, "label": "✍️ Твой ответ"})
        ctl.cfg.pop("pending", None); ctl.save()
        say(f"📨 Отправляю @{pend['to']}…" + ("" if ctl.running() else "\nПоиск выключен — уйдёт сразу после ▶️ Запустить."))
        return
    if low in ("/start", "/help", "помощь", "меню"):
        say(HELP); say(*render("home", ctl))
    elif low in (B_HOME.lower(), "/home", "главная"):
        say(*render("home", ctl))
    elif low in (B_LEADS.lower(), "/leads", "клиенты"):
        say(*render("leads", ctl))
    elif low in (B_APPROVE.lower(), "/approve", "одобрить"):
        say(*render("approve", ctl))
    elif low in (B_MORE.lower(), "/more", "ещё", "еще"):
        t_, kb_ = fmt_more(ctl); say(t_, {"inline_keyboard": kb_})
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
    elif low in (B_BASE.lower(), "/base", "база"):
        send_crm(csv_too=False)
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
    elif low in (B_BOTS.lower(), "/bots", "боты"):
        say(*render_bots())
    elif low in (B_ALL.lower(), "/all", "запустить все", "все боты"):
        s = settings()
        for k, _, _ in BOTS: s[k] = True                 # 1 вакансии, 2 компании, 3 партнёры, эксперты, дожимы
        s["advice_on"] = True; s["pain_on"] = True       # нейросеть: боль до диалога и советы по ответам
        jsave(SETTINGS, s)
        ctl.cfg["want"] = True; ctl.crashes = []; ctl.save(); ctl.start()
        say("🚀 Все боты запущены разом: 1 вакансии, 2 компании, 3 партнёры, эксперты, дожимы.\n"
            "🧠 Нейросеть включена: ищет боль каждого клиента до письма и подсказывает ответы.\n"
            "Через пару минут нажми 📊 Статус.")
        say(*render_bots())
    elif low in (B_ANALYZE.lower(), "/analyze", "разбор", "анализ"):
        say("🧠 Разбираю цифры всех ботов, до минуты…", silent=True)
        run_analysis(ctl)
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
    elif data.startswith("an:"):
        k = data.split(":")[1]
        if k == "again":
            answer(cq, "Разбираю заново…"); run_analysis(ctl); return
        acts = ctl.cfg.get("an_actions") or []
        if not k.isdigit() or int(k) >= len(acts): answer(cq, "Это предложение устарело, нажми 🧠 Разбор"); return
        a = acts[int(k)]
        s = settings(); s.update(a["set"]); jsave(SETTINGS, s)
        answer(cq, "Применил: " + a["label"])
        say("✅ Применил: " + a["label"] + "\n" + ", ".join(f"{x} = {v}" for x, v in a["set"].items()) +
            "\nВернуть можно в 🤖 Боты и ⚙️ Настройки.", silent=True)
    elif data.startswith("adv:"):
        u = data.split(":", 1)[1]
        e = (jload(STATE, {}).get("sent") or {}).get(u) or {}
        if not e.get("advice"): answer(cq, "Совет не найден, ответь сам"); return
        key = f"{u}:{int(e.get('advice_ts', 0))}"
        done = ctl.cfg.setdefault("adv_done", [])
        if key in done: answer(cq, "Этот ответ уже отправлен"); return              # двойное нажатие = два одинаковых сообщения
        if time.time() - e.get("advice_ts", time.time()) > 3 * 3600:
            answer(cq, "Совет устарел (больше 3 ч), диалог мог уйти дальше — ответь сам"); return
        if (e.get("last_in_ts") or 0) > (e.get("advice_ts") or 0) + 5:
            answer(cq, "Клиент уже написал ещё — совет не про то, ответь сам"); return
        done.append(key); ctl.cfg["adv_done"] = done[-300:]; ctl.save()
        to_inbox({"cmd": "send", "to": u, "text": e["advice"], "label": "🧠 Ответ по совету"})
        answer(cq, "Отправляю…" if ctl.running() else "Поиск выключен — уйдёт после ▶️ Запустить")
    elif data.startswith("bot:"):
        key = data.split(":")[1]
        s = settings()
        if key in ("all_on", "all_off"):
            for k, _, _ in BOTS: s[k] = key == "all_on"
        elif key in {k for k, _, _ in BOTS + YT_OPTS}:
            s[key] = not s.get(key, DEFAULTS.get(key, True))
        jsave(SETTINGS, s)
        edit(mid, *render_bots())
        name = next((n for k, n, _ in BOTS + YT_OPTS if k == key), "")
        answer(cq, ("Все боты включены" if key == "all_on" else "Все боты выключены") if key.startswith("all_") else
               f"{name}: {'включён' if s[key] else 'выключен'}")
    elif data == "crm:csv":
        answer(cq, "Отправляю файл"); send_crm(csv_too=True)
    elif data == "spamcheck":
        to_inbox({"cmd": "spamcheck"})
        answer(cq, "Проверяю — ответ придёт через минуту" if ctl.running() else "Поиск выключен — проверю после запуска")
    elif data.startswith("go:"):                                   # главная: включить всё / пауза / запуск
        act = data[3:]
        if act == "all":
            s = settings()
            for k, _, _ in BOTS: s[k] = True
            s["advice_on"] = True; s["pain_on"] = True; jsave(SETTINGS, s)
            ctl.cfg["want"] = True; ctl.crashes = []; ctl.save(); ctl.start()
            answer(cq, "🚀 Все боты включены")
        elif act == "pause":
            ctl.cfg["want"] = False; ctl.save(); ctl.stop(); answer(cq, "⏸ На паузе — письма не уходят")
        else:
            ctl.cfg["want"] = True; ctl.crashes = []; ctl.save(); ctl.start(); answer(cq, "▶️ Запущено")
        edit(mid, *render("home", ctl))
    elif data.startswith("nav:"):
        answer(cq); say(*render(data[4:], ctl))
    elif data.startswith("yc:"):                                   # карточка одобрения: действие → следующая карточка
        _, act, key = data.split(":", 2)
        if act == "all":
            ks = [k for k, _ in waiting(ctl)]
            to_inbox({"cmd": "yt_ok_all", "keys": ks}); handled(ctl, *ks)
            answer(cq, f"✅ Отправлю все {len(ks)} по очереди, с паузами")
        elif act == "ed":
            ctl.cfg["pending"] = {"yt_edit": key, "until": time.time() + 900}; ctl.save(); answer(cq)
            it = dict(waiting(ctl)).get(key) or {}
            say("✏️ Пришли исправленный текст письма одним сообщением (абзацы — через пустую строку). Передумал — /cancel\n\n"
                "Сейчас:\n" + it.get("text", ""), markup={"force_reply": True, "input_field_placeholder": "Текст письма"})
            return
        else:
            to_inbox({"cmd": "yt_ok" if act == "ok" else "yt_no", "key": key}); handled(ctl, key)
            answer(cq, "✅ В отправку" if act == "ok" else "❌ Пропущено")
        edit(mid, *render("approve", ctl))
    elif data.startswith("m:"):                                    # меню «Ещё»
        act = data[2:]; answer(cq)
        if act == "settings": say(*render_settings())
        elif act == "log": say(*render("log", ctl))
        elif act == "sent": say(*render("sent", ctl))
        elif act == "base": send_crm(csv_too=False)
        elif act == "analyze": say("🧠 Разбираю цифры всех ботов, до минуты…", silent=True); run_analysis(ctl)
        elif act == "update":
            to_inbox({"cmd": "update"})
            say("🔄 Перезапускаюсь на свежем коде: сохраню всё и уйду, новый запуск поднимется сам через 3–10 минут. "
                "Очереди, база и настройки сохраняются.")
        elif act == "warm":
            s = settings(); s["warm_off"] = not s.get("warm_off", False); jsave(SETTINGS, s)
            say("⚠️ Мягкий режим выключен: все боты пишут в полную силу сразу. Аккаунт недавно был в ограничении — "
                "если @SpamBot снова ограничит, бот сам встанет на паузу." if s["warm_off"] else
                "🟡 Мягкий режим включён: 3 дня после бана пишут только вакансии, мастера и YouTube.", silent=True)
            t_, kb_ = fmt_more(ctl); edit(mid, t_, {"inline_keyboard": kb_})
    elif data.startswith("yt:"):                                   # бот 5, ручной режим: решение по письму
        _, act, key = data.split(":", 2)
        handled(ctl, key)
        to_inbox({"cmd": "yt_ok" if act == "ok" else "yt_no", "key": key})
        answer(cq, ("✅ Отправлю по очереди" if act == "ok" else "❌ Пропускаю") if ctl.running() else "Поиск выключен — решение применю после запуска")
        try: api("editMessageReplyMarkup", chat_id=OWNER, message_id=mid,
                 reply_markup={"inline_keyboard": [[{"text": "✅ Одобрено" if act == "ok" else "❌ Пропущено", "callback_data": "noop"}]]})
        except Exception: pass
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

def send_crm(csv_too=False):
    """Свежая сводка по базе лидов; csv_too — приложить таблицу файлом."""
    try:
        sys.path.insert(0, BASE)
        import crm
        st = jload(STATE, {}); st.setdefault("sent", {})
        crm.write_files(st, BASE)
        say(crm.board_text(st), markup={"inline_keyboard": [[{"text": "📋 Выгрузить базу (CSV)", "callback_data": "crm:csv"}]]})
        if csv_too:
            path = os.path.join(BASE, "leads.csv"); bd = uuid.uuid4().hex
            body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{OWNER}\r\n"
                    f"--{bd}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"leads.csv\"\r\n"
                    f"Content-Type: text/csv\r\n\r\n").encode() + open(path, "rb").read() + f"\r\n--{bd}--\r\n".encode()
            urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={bd}"}), timeout=30).read()
    except Exception as e:
        clog("crm:", e); say("Не получилось собрать базу: " + str(e)[:150])

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
    try:                                                           # бот 5: какая боль и какой вариант письма работают, почему отказывают
        sys.path.insert(0, BASE)
        import yt_stats
        yts = yt_stats.text(sent)
        if yts: text += "\n\n" + yts
    except Exception as e: clog("yt_stats:", e)
    say(text, markup=refresh_kb("status"))
    if settings().get("advice_on", True):
        run_analysis(ctl, intro="Вечерний разбор\n\n")             # каждый вечер нейросеть сама ищет узкие места

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

REMINDERS = [
    {"id": "cloud-start-2026-11-05", "at": "2026-11-05T15:00:00+03:00",
     "text": ("⏰ 15:00 — пора запускать облако, ограничение аккаунта уже снято.\n\n"
              "1️⃣ Запусти 02 Клиенты и продажи\\Автопоиск клиентов (telegram)\\cloud\\2 Перенести вход в облако.bat и отсканируй QR "
              "(Telegram → Настройки → Устройства → Подключить устройство). Попросит облачный пароль — введи в окне браузера.\n"
              "2️⃣ Дождись слова «Готово», затем запусти 02 Клиенты и продажи\\Автопоиск клиентов (telegram)\\cloud\\Выключить локальный пульт.bat.\n"
              "3️⃣ Напиши Claude в новой сессии: «вход в облако перенесён» — он проверит первый облачный старт.\n\n"
              "Облако само стартует в 16:00 по Москве. Архив вчерашней работы: Cloud AI\\99 Архив\\Архив сессий\\2026-11-04…")},
]

def check_reminders(ctl):
    """Присылает напоминания в назначенное время (если ПК был выключен — при первом запуске пульта, с пометкой)."""
    done = ctl.cfg.setdefault("reminders_done", [])
    now = time.time()
    for r in REMINDERS:
        if r["id"] in done: continue
        at = datetime.datetime.fromisoformat(r["at"]).timestamp()
        if now < at: continue
        late = int((now - at) // 60)
        say(r["text"] + (f"\n\n(напоминание пришло с опозданием на {late} мин: компьютер был выключен)" if late > 30 else ""))
        done.append(r["id"]); ctl.save()

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
        try: check_reminders(ctl)
        except Exception as e: clog("напоминание:", e)

if __name__ == "__main__":
    main()
