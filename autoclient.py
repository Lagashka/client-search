# АВТОПОИСК КЛИЕНТОВ v2 — видеомонтаж, Telegram.
#
#   python autoclient.py             боевой режим, работает без остановки
#   python autoclient.py --dry       ничего не отправляет, тексты пишет в outbox.md (проверка)
#   python autoclient.py --selftest  отправляет 3 образца сообщений в твоё «Избранное» и выходит
#   python autoclient.py --show      то же, что боевой, но с видимым окном браузера (для отладки)
#
# Что делает (по приоритету):
#   1. ГОРЯЧИЕ: каждые ~12 минут читает каналы с вакансиями монтажёров, находит свежие посты «ищу монтажёра»
#      и откликается автору персональным сообщением под его задачу. Человек уже ищет монтажёра —
#      конверсия в разы выше, чем у холодных сообщений.
#   2. ОТВЕТЫ: каждые ~15 минут смотрит список чатов. Если кто-то ответил — бот @pepeclodai715bot
#      пишет тебе в личку. Отвечай быстро: первые минуты решают.
#   3. ДОЖИМ: если человек молчит (вакансия — 24 ч, холодный — 48 ч) — одно короткое напоминание. Больше не пишет.
#   4. ХОЛОДНЫЕ: ищет каналы экспертов (ипотека, недвижимость, юристы, психологи…), считает реальные цифры
#      (просмотры/подписчики, доля видео) и пишет владельцу: наблюдение → боль → решение + кейс → лёгкий шаг.
#      Варианты призыва A/B/C тестируются сами: скрипт считает, на какой отвечают чаще, и шлёт его чаще.
#
# Защита аккаунта: дневные лимиты, рабочие часы по Москве, паузы 4–10 мин между сообщениями,
# ежедневная проверка @SpamBot; при признаках ограничения отправка встаёт на 20 ч (поиск продолжается).
import os, re, sys, json, time, random, html, datetime, traceback
import urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
TG = os.path.dirname(BASE)
ROOT = os.path.dirname(TG)
STATE = os.path.join(BASE, "state.json")
LOGF = os.path.join(BASE, "log.txt")
OUTBOX = os.path.join(BASE, "outbox.md")
STATUS = os.path.join(BASE, "СТАТУС.md")
REPLIES = os.path.join(BASE, "ОТВЕТЫ.md")
QR = os.path.join(BASE, "qr.png")
PROFILE = os.path.join(BASE, "profile")
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
SETTINGS = os.path.join(BASE, "settings.json")   # меняется из бота (⚙️ Настройки), читается на лету
INBOX = os.path.join(BASE, "inbox")              # команды из бота: быстрые ответы клиентам, проверка аккаунта
LIVE = os.path.join(BASE, "live.json")           # что скрипт делает прямо сейчас (для 📊 Статус и сторожа)
DRY = "--dry" in sys.argv
SELFTEST = "--selftest" in sys.argv
SHOW = "--show" in sys.argv
CLOUD = os.environ.get("CLOUD") == "1"   # запуск на сервере GitHub (через cloud_run.py): без браузера, через Telethon
CLOUD_RUN_LIMIT = 5.75 * 3600            # GitHub даёт задаче до 6 ч — заканчиваем чуть раньше и сохраняем состояние
if DRY: STATE = os.path.join(BASE, "state-dry.json")

# ======================= НАСТРОЙКИ =======================
MY_NAME = "Егор"
MY_ID = 5787402361                     # твой Telegram id (уведомления от бота + самотест)
MY_USERNAME = "chernyshev_edit"
PORTFOLIO = "https://t.me/zakulisy715"
CASE = "https://t.me/zakulisy715/53"   # ролик «Ипотека» — кейс для финансов/недвижимости/юристов

# Пауза между сообщениями и дневные лимиты — в settings.json (меняются из бота: ⚙️ Настройки).
# По умолчанию: пауза 30 с (просьба Егора), 40 откликов на вакансии и 20 холодных+дожимов в сутки — см. DEFAULTS.
HOURS_HOT = (7, 23)     # часы по Москве для откликов на вакансии
HOT_DISCOVER_EVERY = 2 * 3600   # как часто искать новые каналы с вакансиями
HOURS_COLD = (10, 20)   # часы по Москве для холодных
HOT_SCAN_EVERY = 12 * 60
REPLY_CHECK_EVERY = 60          # ответы проверяем каждую минуту: скорость ответа клиенту = деньги
AUTO_DELAY = (1800, 1860)        # автоответ уходит только через 30 минут и только если Егор за это время сам не ответил
AUTO_HOURS = (8, 23)            # автоответы — днём по Москве; ночные сообщения получат ответ утром

SPLIT_ON = True                  # письмо уходит несколькими сообщениями, как пишет сам Егор
PART_PAUSE = (5, 10)             # пауза между сообщениями одного письма, секунды
MAX_PARTS = 4

def split_parts(text):
    """Абзацы (пустая строка) = отдельные сообщения; не больше MAX_PARTS, остаток сливается в последнее."""
    parts = [x.strip() for x in re.split(r"\n\s*\n", text or "") if x.strip()]
    if len(parts) > MAX_PARTS: parts = parts[:MAX_PARTS - 1] + ["\n".join(parts[MAX_PARTS - 1:])]
    return parts or [text or ""]

def _legacy_out(e):
    return 1 + (1 if e.get("fu") and e.get("fu") != "skip" else 0) + sum(1 for m in e.get("thread", []) if m.get("who") == "me")

def bot_out(e):
    """Сколько исходящих сообщений в чате отправил сам бот (письмо уходит несколькими) + быстрые ответы из пульта."""
    return (e["n_out"] if "n_out" in e else _legacy_out(e)) + len(e.get("my", []))

def add_out(e, parts):
    """Записать, что бот отправил ещё N сообщений. Вызывать до изменения e['fu'] и e['thread']."""
    e["n_out"] = (e["n_out"] if "n_out" in e else _legacy_out(e)) + max(int(parts or 1), 1)
WARM_DAYS, WARM_HOT, WARM_GAP = 3, 100, 180  # после ограничения: 3 дня без холодных и дожимов; откликов на вакансии (Егор 09.11) не меньше 40 в день, лимит как в настройках, пауза от 3 мин
HOT_MAX_AGE_H = 36      # откликаемся только на посты не старше N часов
FOLLOWUP_HOT_H = 24
FOLLOWUP_COLD_H = 48
SUBS_RANGE = (300, 60000)
FRESH_DAYS = 21
CTA_VARIANTS = ["A", "B", "C"]   # A — бесплатно 3 идеи роликов, B — бесплатно 15 сек монтажа, C — цена + дефицит

HOT_CHANNELS = ["editors_video", "vakansii_reelsmaker", "SearchEditorr", "reelsmaker_tinder", "GetJob_videoedit",
                "montage_free", "reelsmakervacancy", "Panteon_WORK", "Content_Jobss", "allvideomakers", "nimb_job",
                "reelsclubdi", "montage_job", "ECvacancy", "montazh_geo", "freelancer_rabota_doma", "Fm_ReelsMaker",
                "motiondisgnfreelanc"]

NICHES = {
    "finance": ["ипотек", "кредит", "брокер", "финанс", "инвест", "страхов", "налог", "бухгалт", "вычет"],
    "realty":  ["недвижим", "риелтор", "риэлтор", "квартир", "новостройк", "застройщик", "аренд"],
    "law":     ["юрист", "адвокат", "банкрот", "долгов", "долги ", "списани", "правов", "юридич", "исков"],
    "expert":  ["психолог", "коуч", "нутрициолог", "фитнес", "тренер", "косметолог", "стоматолог", "врач",
                "маркетолог", "таргет", "smm", "наставник", "дизайн интерьер", "дизайнер интерьер", "эксперт"],
}
QUERIES = [
    "ипотечный брокер", "кредитный брокер", "финансовый советник", "налоговый консультант", "бухгалтер блог",
    "риелтор", "эксперт по недвижимости", "агент недвижимости", "юрист банкротство", "банкротство физических лиц",
    "списание долгов", "адвокат блог", "семейный юрист", "психолог блог", "нутрициолог", "фитнес тренер блог",
    "косметолог блог", "стоматолог блог", "дизайнер интерьера", "наставник", "ипотека Новосибирск",
    "недвижимость Новосибирск", "юрист Москва", "психолог Москва", "риелтор Москва", "ипотека Москва",
    "риелтор Санкт-Петербург", "юрист Екатеринбург", "недвижимость Казань", "ипотека Краснодар",
]
SEEDS = ["broker_Aleksey", "rakuta_nedvizhka", "rusipoteka", "pravonadom1", "careerinlaw", "dvinsky_invest"]
STOP_TITLE = re.compile(r"суд\b|судеб|арбитраж|новост|news|министер|администрац|госуслуг|мвд|полиц|прокурат|вестник|"
                        r"журнал|газет|медиа|дайджест|подборк|каталог|\bчат\b|вакан|работа\b|монтаж|рилсмейк|видеограф|"
                        r"продакшн|production|официальн|районн|типичн|барахолк|объявлен|форум", re.I)
FIRST_PERSON = re.compile(r"(?<![а-яё])(я|мне|меня|мой|моя|мои|моих|моим|ко мне|расскажу|помогаю|помогу)(?![а-яё])", re.I)
SELLS = re.compile(r"консультац|запис|услуг|клиент|обращ|напиши|пишите|заявк|разбор|диагностик|сопровожд", re.I)
CONTACT_HINTS = ["связ", "вопрос", "консультац", "запис", "пишите", "писать", "автор", "лс", "личк", "директ",
                 "обращ", "заявк", "менеджер", "контакт"]
JUNK_NAMES = {"joinchat", "share", "addstickers", "addemoji", "proxy", "socks", "iv", "s", "c", "contact", "login",
              "setlanguage", "boost", "addlist", "invoice", "durov", "telegram", "username", "spambot", "botfather"}

HIRE = re.compile(r"(?<![а-яё])(ищу|ищем|ищет|ищут|нужен|нужна|нужны|нужно|надо|требуется|требуются|в поиске|"
                  r"вакансия|набираем|приглашаем|открыт набор|кто может|кто сделает|кто смонтирует|заказ|задача|"
                  r"в команду|на постоянку|на проект)(?![а-яё])", re.I)
ROLE = re.compile(r"монтаж|рилс|reels|shorts|шортс|клип|моуш|motion|видео|youtube|ютуб|контент|сторис|stories|"
                  r"анимац|нейро|креатор|ugc|мобилограф|оператор|tiktok|тикток|vfx|after effects|premiere|davinci|capcut", re.I)
# Отсеиваем только то, что НЕ вакансия: резюме конкурентов, реклама сервисов, рефералки.
NOT_HOT = ["#резюме", "#помогу", "ищу работу", "ищу заказ", "ищу клиент", "возьму заказ", "беру заказ", "мои работы",
           "моё портфолио", "мое портфолио", "реферальн", "промокод", "бесплатный старт", "автомонтаж",
           "я видеомонтаж", "я — видеомонтаж", "я монтажер", "я монтажёр", "услуги монтаж", "стоимость рассчитывается",
           "предлагает услуги", "предлагаю услуги", "мои услуги", "обращайтесь ко мне", "курс по монтажу",
           "обучение монтажу", "научу монтировать"]
HOT_QUERIES = ["ищу монтажера", "вакансии монтажер", "монтажер работа", "заказы видеомонтаж", "reels вакансии",
               "ищу рилсмейкера", "вакансии видео", "фриланс видеомонтаж", "ищу видеографа", "вакансии контент мейкер",
               "ищу моушн дизайнера", "работа youtube монтаж", "ищу продюсера", "продюсер reels", "ищу сценариста", "сценарист рилс", "раскадровщик",
               "контент продюсер", "ролики под ключ"]
HOT_RULES_VERSION = 3       # при смене правил — пересмотреть свежие посты заново
JUNK_LINE = re.compile(r"взята из|в бот|вакансия v\d|предварительная оценка|приемлем|источник|контакт|"
                       r"^ищут видеомонтаж|^ищут монтаж", re.I)
GREETING = re.compile(r"^(всем )?(привет\w*|здравствуйте|добрый (день|вечер)|доброе утро|hello|hi)[!,.\s)]*", re.I)

NAMES = {x.replace("ё", "е") for x in """александр алексей анатолий андрей антон аркадий арсений артём артем борис
вадим валентин валерий василий виктор виталий владимир владислав всеволод вячеслав геннадий георгий глеб григорий
давид даниил данил денис дмитрий евгений егор иван игорь илья кирилл константин лев леонид максим марк матвей михаил
никита николай олег павел пётр петр роман руслан сергей станислав степан тимофей тимур фёдор федор эдуард юрий
ярослав рустам ильдар азат марат александра алина алла алёна алена альбина анастасия ангелина анна антонина арина
валентина валерия вера вероника виктория галина дарья диана евгения екатерина елена елизавета жанна зарина злата
инна ирина карина кира кристина ксения лариса лидия любовь людмила маргарита марина мария милана надежда наталья
наталия нина оксана олеся ольга полина регина светлана снежана софия софья таисия тамара татьяна ульяна эвелина
юлия яна ярослава эльвира лилия гульнара айгуль венера василиса алиса майя мила""".split()}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# ======================= служебное =======================
def log(*a):
    line = datetime.datetime.now().strftime("%d.%m %H:%M:%S ") + " ".join(str(x) for x in a)
    if not CLOUD:            # в облаке логи публичного репозитория видны всем — пишем только в файл
        try: print(line, flush=True)
        except Exception: print(line.encode("ascii", "replace").decode(), flush=True)
    try:
        with open(LOGF, "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass

def jload(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return d

def jsave(p, data):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)

DEFAULTS = {"gap": 30, "limit_hot": 40, "limit_cold": 20, "hot_on": True, "cold_on": True, "fu_on": True}
_SC = {"m": None, "v": dict(DEFAULTS)}

def S():
    """Настройки из settings.json (их меняет бот). Перечитываются, как только файл изменился."""
    try:
        m = os.path.getmtime(SETTINGS)
        if m != _SC["m"]:
            v = dict(DEFAULTS); v.update(jload(SETTINGS, {})); _SC.update(m=m, v=v)
    except OSError:
        pass
    return _SC["v"]

_LIVE = {"t": 0}
def live(**kw):
    """Пишет live.json: чем занят скрипт. Без аргументов — только отметка «жив» (не чаще раза в 10 с)."""
    changed = any(_LIVE.get(k) != v for k, v in kw.items())
    if not changed and time.time() - _LIVE["t"] < 10: return
    _LIVE.update(kw); _LIVE["t"] = _LIVE["ts"] = time.time(); _LIVE["pid"] = os.getpid()
    try: jsave(LIVE, {k: v for k, v in _LIVE.items() if k != "t"})
    except Exception: pass

def msk_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)

def today():
    return msk_now().date().isoformat()

def in_hours(rng):
    return rng[0] <= msk_now().hour < rng[1]

def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(60)
            elif e.code in (404, 410): return ""
            else: time.sleep(3 + i * 5)
        except Exception:
            time.sleep(3 + i * 5)
    return ""

def clean(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()

EMOJI_RE = re.compile("[\U00010000-\U0010ffff​‌⁠⁉‼™ℹ←-⇿"
                      "⌀-⏿■-➿⤀-⯿️‍•]")

def cut(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(",.:;—-") + "…"

def fmt_num(n):
    if n < 1000: return str(max(10, round(n, -1)))   # 331 → 330: «около 330 просмотров»
    if n >= 10000: return f"{round(n / 1000)} тыс."
    if n >= 1000: return f"{n / 1000:.1f}".replace(".0", "").replace(".", ",") + " тыс."
    return str(n)

def first_name(display):
    w = [x for x in re.split(r"[\s|_,.\-]+", EMOJI_RE.sub(" ", display or "").strip()) if x]
    if w and w[0].lower().replace("ё", "е") in NAMES:
        return w[0][0].upper() + w[0][1:].lower()
    return ""

def parse_count(s):
    s = s.replace(" ", "").replace("\xa0", "").upper()
    m = re.match(r"([\d.,]+)([KM]?)", s)
    if not m: return 0
    v = float(m.group(1).replace(",", "."))
    return int(v * (1000 if m.group(2) == "K" else 1000000 if m.group(2) == "M" else 1))

# ======================= уведомления тебе (бот) =======================
_BOT = None
def notify(text, buttons=None, silent=False):
    """Сообщение тебе от бота. buttons — inline-кнопки, silent — без звука (для неважного)."""
    global _BOT
    log("УВЕДОМЛЕНИЕ:", text.replace("\n", " / ")[:200])
    if DRY: return
    try:
        if _BOT is None:
            _BOT = os.environ.get("BOT_TOKEN", "")
            if not _BOT:
                m = re.search(r"\d{6,}:[A-Za-z0-9_-]{30,}", open(BOTFILE, encoding="utf-8").read())
                _BOT = m.group(0) if m else ""
        if not _BOT: return
        payload = {"chat_id": MY_ID, "text": text[:4000], "disable_web_page_preview": True, "disable_notification": silent}
        if buttons: payload["reply_markup"] = {"inline_keyboard": buttons}
        req = urllib.request.Request(f"https://api.telegram.org/bot{_BOT}/sendMessage", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        log("бот не отправил уведомление:", str(e)[:80])

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crm, autoreply, guard, zlib

# Команда из двух аккаунтов (Егор и Саша) делит контакты пополам, чтобы один человек не получил два письма.
# CONTACTS_PART = "0" или "1" (у Егора в облаке "0", у Саши "1"); пусто — пишем всем.
CONTACTS_PART = os.environ.get("CONTACTS_PART", "").strip()
def mine(u):
    return CONTACTS_PART not in ("0", "1") or zlib.crc32(u.lower().encode()) % 2 == int(CONTACTS_PART)

def bot_token():
    global _BOT
    if not _BOT:
        _BOT = os.environ.get("BOT_TOKEN", "")
        if not _BOT:
            try:
                m = re.search(r"\d{6,}:[A-Za-z0-9_-]{30,}", open(BOTFILE, encoding="utf-8").read()); _BOT = m.group(0) if m else ""
            except Exception: _BOT = ""
    return _BOT

NEG_REPLY = re.compile(r"не актуальн|неактуальн|не нужн|не интерес|не надо|не требуется|уже наш(ли|ёл|ел)|уже выбрал|"
                       r"уже есть монтаж|нет,? спасибо|спасибо,? (но )?нет|спасибо,? не|отказ|вакансия закрыта|"
                       r"набор закрыт|не пишите|не беспокойте|спам", re.I)

def link0(u):
    return [[{"text": "💬 Открыть чат", "url": f"https://t.me/{u}"}]]

def reply_buttons(u):
    return [[{"text": "💬 Открыть чат", "url": f"https://t.me/{u}"}],
            [{"text": "💰 Прайс", "callback_data": f"qr:price:{u}"}, {"text": "🎬 Примеры", "callback_data": f"qr:works:{u}"}],
            [{"text": "📋 Что нужно", "callback_data": f"qr:brief:{u}"}, {"text": "📞 Созвон", "callback_data": f"qr:call:{u}"}],
            [{"text": "🧪 Тест", "callback_data": f"qr:test:{u}"}, {"text": "✍️ Свой ответ", "callback_data": f"qr:own:{u}"}]]

# ======================= кого уже трогали =======================
def already_contacted_external():
    names = set()
    try:
        names |= {m.lower() for m in re.findall(r"@(\w{4,})", open(os.path.join(ROOT, "Telegram-канал", "лиды-радар.md"), encoding="utf-8").read())}
    except Exception: pass
    for p in [os.path.join(TG, "sent-log.json"), os.path.join(TG, "tgweb", "sent-log-web.json")]:
        names |= {x.get("username", "").lower() for x in jload(p, [])}
    try:
        src = open(os.path.join(TG, "tgweb", "tgweb-рассылка.py"), encoding="utf-8").read()
        m = re.search(r"SKIP\s*=\s*\{(.*?)\}", src, re.S)
        if m: names |= {x.lower() for x in re.findall(r'"(\w+)"', m.group(1))}
    except Exception: pass
    names.discard("")
    return names

def user_page(u):
    """@u — живой человек? Возвращает отображаемое имя или None (канал/группа/бот/нет такого)."""
    if u.lower().endswith("bot"): return None
    h = fetch(f"https://t.me/{u}")
    m = re.search(r'tgme_page_title[^>]*>\s*<span[^>]*>(.*?)</span>', h, re.S)
    if not m: return None
    extra = clean((re.search(r'tgme_page_extra[^>]*>(.*?)</div>', h, re.S) or [None, ""])[1]).lower()
    if any(w in extra for w in ("subscriber", "member", "подписч", "участник", "online")): return None
    USER_BIO[u.lower()] = clean((re.search(r'tgme_page_description[^>]*>(.*?)</div>', h, re.S) or [None, ""])[1])[:400]
    return clean(m.group(1))

USER_BIO = {}     # био автора вакансии (с той же страницы t.me/u) — для подстройки письма

# ======================= разбор публичной страницы канала =======================
TME_RE = re.compile(r"t\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_/])")

def parse_channel(name):
    h = fetch(f"https://t.me/s/{name}")
    if "tgme_channel_info" not in h: return None
    title = clean((re.search(r'tgme_channel_info_header_title[^>]*>(.*?)</div>', h, re.S) or [None, ""])[1])
    desc = clean((re.search(r'tgme_channel_info_description[^>]*>(.*?)</div>', h, re.S) or [None, ""])[1])
    subs = 0
    for val, typ in re.findall(r'counter_value">([^<]+)</span>\s*<span class="counter_type">([^<]+)<', h):
        if "subscriber" in typ or "подписч" in typ: subs = parse_count(val)
    posts = []
    for b in re.split(r'<div class="tgme_widget_message_wrap', h)[1:]:
        pid = re.search(r'data-post="([^"]+)"', b)
        dt = re.search(r'<time datetime="([^"]+)"', b)
        m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
        raw = m.group(1) if m else ""
        when = None
        if dt:
            try: when = datetime.datetime.fromisoformat(dt.group(1).replace("Z", "+00:00"))
            except Exception: pass
        v = re.search(r'tgme_widget_message_views">([^<]+)<', b)
        btns = [(html.unescape(u), clean(t)) for u, t in re.findall(r'tgme_widget_message_inline_button[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)]
        posts.append({"id": pid.group(1) if pid else "", "text": clean(raw), "when": when, "buttons": btns,
                      "links": re.findall(r'href="(?:https?:)?//t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/?(?:\?[^"]*)?"', raw),
                      "views": parse_count(v.group(1)) if v else 0,
                      "video": ("message_video_player" in b) or ("roundvideo" in b)})
    return {"name": name, "title": title, "desc": desc, "subs": subs, "posts": posts, "html": h}

# ======================= 1. ГОРЯЧИЕ: вакансии =======================
def is_hot(text):
    low = text.lower()
    if any(x in low for x in NOT_HOT): return False
    return bool(HIRE.search(low[:800])) and bool(ROLE.search(low))

def hot_contacts(post, channel):
    out = []
    for u in post["links"] + guard.tg_handles(post["text"]):      # без ников из ссылок Threads/Instagram и т. п.
        ul = u.lower()
        if ul == channel.lower() or ul in JUNK_NAMES or ul.endswith("bot") or ul in [x.lower() for x in out]: continue
        out.append(u)
    return out

def hot_task(text):
    """Строка, которая лучше всего описывает задачу: сначала «ищу + монтаж», потом просто про монтаж."""
    lines = []
    for line in text.split("\n"):
        l = EMOJI_RE.sub("", line)
        if re.fullmatch(r"(\s*[•\-]?\s*#\S+)+\s*", l): continue          # строка из одних хэштегов
        l = re.sub(r"\s+", " ", l.replace("#", "")).strip(" -—:•*|❗!🔥")
        l = GREETING.sub("", l).strip()
        if l: l = l[0].upper() + l[1:]
        if len(l) < 15 or JUNK_LINE.search(l): continue
        if l.isupper(): l = l.capitalize()
        lines.append(l)
    for test in (lambda l: HIRE.search(l) and ROLE.search(l), lambda l: ROLE.search(l), lambda l: HIRE.search(l)):
        for l in lines:
            if test(l): return cut(l, 110).rstrip(".!;:, ")
    return ""

# ---------- уникальность: каждая фраза в нескольких формулировках, комбинации не повторяются ----------
USED_SKELETONS = set()      # загружается из state.json в main()

class Spin:
    def __init__(self): self.key = []
    def __call__(self, *opts):
        i = random.randrange(len(opts)); self.key.append(i); return opts[i]
    def shuffle(self, items):
        order = list(range(len(items))); random.shuffle(order); self.key.append(tuple(order))
        return [items[i] for i in order]

def unique(kind, build):
    """Собирает текст, пока не получится ещё не использованное сочетание формулировок (до 60 попыток)."""
    for _ in range(60):
        sp = Spin(); text = build(sp)
        sig = kind + ":" + repr(sp.key)
        if sig not in USED_SKELETONS: break
    USED_SKELETONS.add(sig)
    return text

def hi_line(sp, fn):
    if fn:
        return sp(f"Здравствуйте, {fn}!", f"{fn}, здравствуйте!", f"Добрый день, {fn}!", f"{fn}, добрый день!",
                  f"Приветствую, {fn}!")
    return sp("Здравствуйте!", "Добрый день!", "Приветствую!", "Здравствуйте.")

def hot_fit(sp, text):
    low = text.lower()
    skills = []
    if re.search(r"reels|рилс|shorts|шортс|вертикал|tiktok|тикток|говорящ", low):
        skills.append(sp("Вертикальные ролики — моя основная специализация: хук в первые секунды, динамичные субтитры, моушен-графика, звук.",
                         "Основное, чем занимаюсь, — Reels и Shorts: цепляющее начало, живые субтитры, графика и саунд-дизайн.",
                         "Короткие вертикальные ролики делаю каждый день: сильный хук, темп, субтитры, звук, моушен.",
                         "Специализируюсь на вертикальном формате — от хука в первые 2 секунды до субтитров и звука."))
    if re.search(r"youtube|ютуб|длинн|подкаст|интервью", low):
        skills.append(sp("Длинные видео тоже делаю: структура, B-roll, графика, субтитры, чистый звук.",
                         "С длинным форматом работаю: держу структуру, добавляю B-roll, графику, чищу звук.",
                         "Для YouTube собираю ролики так, чтобы досматривали: темп, вставки, графика, звук."))
    if re.search(r"моуш|motion|анимац|after effects|(?<!суб)титр|инфограф|пэкшот", low):
        skills.append(sp("Моушен-графику делаю в After Effects: титры, инфографика, анимация логотипа.",
                         "В After Effects делаю анимированные титры, инфографику и пэкшоты.",
                         "Моушен — моя сильная сторона: титры, графика, анимация логотипа в After Effects."))
    if re.search(r"нейро|(?<![а-яё])ии(?![а-яё])|(?<![a-z])ai(?![a-z])|сгенерир|генерац", low):
        skills.append(sp("С AI-материалом работаю: собираю сгенерированные шоты в цельный ролик, ритм, звук, титры.",
                         "AI-шоты собираю в цельное видео: ритм, переходы, звук, титры.",
                         "Сгенерированный материал тоже монтирую — свожу в единый стиль, добавляю звук и титры."))
    if not skills:
        skills.append(sp("Делаю динамичный монтаж для экспертов и бизнеса: субтитры, графика, звук, цвет.",
                         "Монтирую видео для экспертов и брендов: темп, субтитры, графика, цвет, звук.",
                         "Собираю ролики под задачу клиента: склейка, цвет, звук, субтитры, графика."))
    case = bool(re.search(r"ипотек|недвиж|финанс|кредит|юрист|банкрот|эксперт|инвест|бизнес", low))
    return " ".join(skills[:2]), case

def _lc(s):
    return (s[:1].lower() + s[1:]) if s else s

def _head(sp, fn):
    hi = sp("здравствуйте", "добрый день")
    return f"{fn}, {hi}" if fn else hi.capitalize()

def compose_hot(post, ch_title, display, bio=""):
    """Первое письмо по вакансии голосом Егора: 3 коротких сообщения (абзаца), без цитат вакансии и схемы «боль–решение–ссылка»."""
    fn = first_name(display)
    low = post["text"].lower()
    price = re.search(r"цен|стоимост|бюджет|ставк|оплат|сколько", low)
    shoot = re.search(r"съёмк|съемк|снимать|сниму|оператор|мобилограф|ugc|на камеру|в кадре", low)
    vol = re.search(r"(\d{1,3})\s*(?:роликов|видео|рилс\w*|reels)", low)
    detail = []
    if vol: detail.append(vol.group(1) + " роликов" + (" в месяц" if "месяц" in low else ""))
    if "постоянн" in low: detail.append("на постоянную работу")
    case = bool(re.search(r"ипотек|недвиж|финанс|кредит|юрист|банкрот|инвест", low))

    def build(sp):
        pain = autoreply.pain_for(sp, post["text"], bio)
        seen = sp("увидел вашу вакансию", "прочитал вашу вакансию", "увидел, что вы ищете монтажёра")
        m1 = f"{_head(sp, fn)}, {seen}" + (", " + ", ".join(detail) if detail else "")
        if pain:
            understand, mine = pain[0].rstrip("."), pain[1].rstrip(".")
        else:
            understand = sp("Знаю, как это бывает: ролик нужен, а монтаж съедает всё остальное время",
                            "Понимаю, когда монтаж тянется, страдает и выпуск, и всё остальное")
            mine = sp("Делаю по ТЗ, держу один стиль и сдаю короткий ролик за 1–2 дня",
                      "Работаю по ТЗ, в одном стиле и в срок, короткий ролик за 1–2 дня")
        m2 = f"{understand}. {mine}"
        extra = sp("Я не только монтирую, а продюсирую ролики под ключ: стратегия, сценарии, раскадровка и монтаж, можно взять весь цикл или только монтаж",
                   "Продюсирую ролики под ключ, не только монтаж: сценарии, раскадровка, хук и звук, а если нужен один монтаж, беру его отдельно",
                   "Веду проект под ключ, как продюсер: сценарии, раскадровка, монтаж, можно взять весь цикл или только монтаж",
                   "Беру ролики под ключ как продюсер: стратегия, сценарии, раскадровка и монтаж, а если нужен только монтаж, делаю его одним")
        if shoot: extra += ". " + sp("Съёмку не беру, снимаете вы на телефон, остальное беру на себя",
                                     "Снимаете вы на телефон, а сценарий, раскадровку и монтаж беру на себя")
        offer = sp("Могу бесплатно сделать 10–15 секунд из вашего материала за сутки, глянете уровень, а там решим вопрос",
                   "Предлагаю так, сделаю тест на 10–15 секунд бесплатно, за сутки после исходника, а там сами глянете, подходит или нет",
                   "Могу для начала бесплатно смонтировать 10–15 секунд за сутки, а там уже сами глянете, нужно вам такое или нет")
        ask = sp("Какой формат у вас сейчас?", "К какому числу нужен первый ролик?", "Скинете исходник?")
        lines = [f"{offer}. {extra}. {ask}"]
        if price: lines.append("По цене: серия из 5 роликов под ключ 19 000 ₽, отдельный монтаж от 3 000 ₽")
        lines.append(f"Работы здесь: {PORTFOLIO}" + (f", похожий пример: {CASE}" if case else ""))
        return "\n\n".join([m1, m2, "\n".join(lines)])
    return autoreply.voicefy(unique("hot", build))

def followup_text(entry):
    fn = first_name(entry.get("display", ""))
    def build(sp):
        hi = sp("добрый день", "здравствуйте")
        lead = f"{fn}, {hi}" if fn else hi.capitalize()
        if entry["kind"] == "hot":
            return lead + ", " + sp("подскажите, вакансия ещё актуальна? Если да, сделаю тест к вечеру, окей?",
                                    "вакансия ещё открыта? Могу сегодня сделать тест на 10–15 секунд, а там решим вопрос",
                                    "уточню, поиск ещё актуален? Если да, покажу тест на вашем материале")
        return lead + ", " + sp("вернусь к своему сообщению, если тема не ваша, напишите «нет», больше не побеспокою) а если интересно, пришлю схему серии роликов под ваш канал",
                                "не хочу быть навязчивым, поэтому коротко: если видео сейчас не в планах, просто ответьте «нет», а если в планах, покажу схему серии под вашу тему",
                                "пишу ещё раз, последний) предложение в силе, могу бесплатно показать, как ваш пост выглядел бы роликом, а если не актуально, так и напишите")
    return autoreply.voicefy(unique("fu-" + entry["kind"], build))

TOUCH3_D, TOUCH7_D = 3, 4      # касания после названной цены: через 3 дня, потом ещё через 4 (на 7-й день)

def touch_due(e, now):
    """'t3' / 't7' / None: пора ли коснуться того, кому уже назвали цену, а он молчит. Только тем, с кем диалог ведёт бот."""
    pts = e.get("price_ts")
    if not pts or not e.get("peer") or e.get("human") or e.get("handoff") or e.get("bye"): return None
    if e.get("crm") in ("agreed", "refused"): return None
    if e.get("last_in_ts", 0) > pts: return None                # после цены он что-то написал: ведём по ответам
    if not e.get("t3"):
        return "t3" if now - pts >= TOUCH3_D * 86400 and now - pts < 10 * 86400 else None
    if e.get("t3") == "skip" or e.get("t7"): return None
    return "t7" if now - e.get("t3_ts", now) >= TOUCH7_D * 86400 else None

def touch_text(entry, which):
    fn = first_name(entry.get("display", ""))
    def build(sp):
        hi = sp("добрый день", "здравствуйте")
        lead = f"{fn}, {hi}" if fn else hi.capitalize()
        if which == "t3":
            return lead + ", " + sp("вернусь по вашему проекту: могу до оплаты прислать карту серии на одну страницу за 24 часа, не подойдёт, платить ничего не нужно. Набросать?",
                                    "по вашему проекту предложение в силе: до оплаты пришлю карту серии (5 тем и золотая кнопка) за 24 часа, не подойдёт, ничего не должны. Присылать?")
        return lead + ", " + sp("последний раз побеспокою) если сейчас не актуально, так и напишите, закрою вопрос, а если актуально, держу за вами место ещё пару дней. Да или нет?",
                                "пишу в последний раз, чтобы не надоедать: если тема не ваша, ответьте «нет», и я закрою вопрос, если ваша, место за вами ещё на пару дней. Да или нет?")
    return autoreply.voicefy(unique("touch-" + which, build))

def niche_of(title, desc, body):
    t1 = (title + " " + desc).lower(); t2 = body.lower()
    best, score = None, 0
    for n, kws in NICHES.items():
        s = sum(t1.count(k) for k in kws) * 3 + sum(t2.count(k) for k in kws)
        if s > score: best, score = n, s
    return best if score >= 4 else None

def analyze_channel(name):
    c = parse_channel(name)
    if not c: return None
    ps = c["posts"]
    views = [p["views"] for p in ps if p["views"]]
    vs = sorted(views)[len(views) // 5: len(views) - len(views) // 5] or views    # без выбросов
    dates = [p["when"] for p in ps if p["when"]]
    c.update(posts=[p["text"] for p in ps if p["text"]], videos=sum(1 for p in ps if p["video"]),
             n_posts=max(len(ps), 1), last=max(dates) if dates else None,
             avg_views=int(sum(vs) / len(vs)) if vs else 0,
             links=set(TME_RE.findall(c.pop("html"))) | set(re.findall(r'@([A-Za-z][A-Za-z0-9_]{4,31})', " ".join(p["text"] for p in ps))))
    return c

def is_expert_channel(ch):
    if STOP_TITLE.search(ch["title"]) or STOP_TITLE.search(ch["desc"][:120]): return False
    txt = " ".join(ch["posts"]) + " " + ch["desc"]
    return len(FIRST_PERSON.findall(txt)) >= 4 and bool(SELLS.search(txt))

def find_contacts(ch):
    out = []
    ad = lambda ctx: "реклам" in ctx
    for m in re.finditer(r"(?:@|t\.me/)([A-Za-z][A-Za-z0-9_]{4,31})", ch["desc"]):
        ctx = ch["desc"][max(0, m.start() - 40):m.start()].lower()
        if not ad(ctx): out.append(m.group(1))
    for p in ch["posts"]:
        for m in re.finditer(r"@([A-Za-z][A-Za-z0-9_]{4,31})", p):
            ctx = p[max(0, m.start() - 60):m.start()].lower()
            if any(k in ctx for k in CONTACT_HINTS) and not ad(ctx): out.append(m.group(1))
    res, seen = [], set()
    for u in out:
        ul = u.lower()
        if ul in seen or ul == ch["name"].lower() or ul.endswith("bot") or ul in JUNK_NAMES: continue
        seen.add(ul); res.append(u)
    return res

AD_MARKERS = ("реклама", "erid", "подборк", "папк", "подпишись", "подписывайтесь", "розыгрыш", "конкурс", "скидк",
              "промокод", "партнёр", "партнер", "сохраняй", "эфир", "pinned", "закрепил")

def topic_of(posts):
    for p in reversed(posts):
        low = p.lower()
        if any(m in low for m in AD_MARKERS): continue
        t = re.sub(r"https?://\S+|#\w+|@\w+", "", EMOJI_RE.sub("", p)).strip()
        first = re.split(r"\n|(?<=[.!?])\s+(?=[А-ЯЁA-Z])", t)[0].strip(" -—:«»\"*.!?")
        if len(first.split()) >= 4 and 20 <= len(first) <= 200 and not re.search(r"\d{2}\.\d{2}\.\d{4}|№", first):
            return cut(first, 80)
    return None

def compose_cold(ch, display, niche, variant):
    """Холодное письмо голосом Егора: 3 коротких сообщения (наблюдение, понимаю проблему, лёгкое предложение)."""
    fn = first_name(display)
    topic = topic_of(ch["posts"])
    share = ch["videos"] / ch["n_posts"]
    er = ch["avg_views"] / ch["subs"] if ch["subs"] else 1
    head = (ch["title"] + " " + ch["desc"]).lower()
    case_fits = any(k in head for n in ("finance", "realty", "law") for k in NICHES[n])
    low_reach = ch["subs"] >= 500 and ch["avg_views"] and er < 0.15
    subs, views = fmt_num(ch["subs"]), fmt_num(ch["avg_views"])

    def build(sp):
        if topic:
            obs = sp(f"прочитал ваш пост «{topic}»", f"зацепил ваш пост «{topic}»", f"наткнулся на ваш пост «{topic}»")
        else:
            obs = sp("зашёл на ваш канал, понравилась подача", "почитал ваш канал, сильная подача")
        m1 = f"{_head(sp, fn)}, {obs}"
        if share < 0.15:
            pain = sp("смотрите, видео у вас почти нет, а новых людей сейчас в основном приводят короткие ролики в Reels и Shorts, текст видят в основном те, кто уже подписан",
                      "заметил, что видео в канале почти нет, а новая аудитория сейчас приходит как раз через короткие ролики, посты читают в основном свои",
                      "вижу, что видео почти нет, а рекомендации Reels и Shorts как раз показывают ролики тем, кто про вас ещё не знает")
        else:
            pain = sp("вижу, что видео вы уже снимаете, а монтаж на каждый ролик забирает часы, которые вам дороже потратить на клиентов",
                      "у вас уже есть видео, и по факту монтаж каждого ролика забирает часы, которые лучше отдавать клиентам")
        if low_reach:
            pain += sp(f", да и при {subs} подписчиках посты набирают около {views} просмотров, остальные их просто не видят",
                       f", плюс подписчиков {subs}, а просмотров у постов около {views}, большая часть аудитории их не видит")
        pain = pain[0].upper() + pain[1:]
        who = sp("Я Егор, продюсирую для экспертов ролики под ключ (стратегия, сценарии, раскадровка, монтаж)",
                 "Я Егор, веду ролики для экспертов под ключ как продюсер (стратегия, сценарии, раскадровка, монтаж)")
        offer = {"A": sp("Предлагаю так, бесплатно набросаю схему серии из 5 роликов под ваш канал, а вы глянете, подходит или нет. Скинуть?",
                         "Могу бесплатно расписать серию из 5 роликов по вашим темам, а там уже сами глянете, нужно вам такое или нет. Скинуть?"),
                 "B": sp("Могу бесплатно смонтировать 15 секунд из вашего видео за сутки, а там сами глянете, нужно вам такое или нет. Скинете исходник?",
                         "Предлагаю так, бесплатно сделаю 15 секунд из вашего видео за сутки, сравните сами) пришлёте любой исходник?"),
                 "C": sp("Серия из 5 роликов под ключ стоит 19 000 ₽, беру не больше 5 клиентов в месяц, сейчас есть место. Обсудим?",
                         "Серия из 5 роликов под ключ, 19 000 ₽, постоянных клиентов беру не больше пяти, сейчас есть окно. Интересно?")}[variant]
        proof = f"Пример по ипотеке: {CASE}" if case_fits else f"Работы здесь: {PORTFOLIO}"
        return "\n\n".join([m1, pain, f"{who}. {offer}\n{proof}"])
    return autoreply.voicefy(unique(f"cold-{variant}", build))

def pick_variant(st):
    """A/B/C: пока мало данных — поровну, потом 80% лучшему по доле ответов."""
    stats = {v: [0, 0] for v in CTA_VARIANTS}
    for e in list(st["sent"].values()) + st["cold_q"]:
        if e.get("variant") in stats:
            stats[e["variant"]][0] += 1
            if e.get("replied"): stats[e["variant"]][1] += 1
    if min(s[0] for s in stats.values()) < 15 or random.random() < 0.2:
        return min(CTA_VARIANTS, key=lambda v: stats[v][0] + random.random())
    return max(CTA_VARIANTS, key=lambda v: (stats[v][1] + 1) / (stats[v][0] + 2))

def search_engines(q):
    found = set()
    qq = urllib.parse.quote("site:t.me " + q)
    for url in (f"https://html.duckduckgo.com/html/?q={qq}", f"https://www.bing.com/search?q={qq}&count=50"):
        h = urllib.parse.unquote(fetch(url))
        for n in TME_RE.findall(h):
            if n.lower() not in JUNK_NAMES: found.add(n)
        time.sleep(random.uniform(2, 5))
    return found

# ======================= Telegram Web =======================
class Limited(Exception): pass

class Web:
    INPUT = "div.input-message-input[contenteditable='true']:not(.input-field-input-fake)"
    SEARCH = "#column-left input.input-search-input"

    def __init__(self):
        self.pw = self.ctx = self.page = self.browser = None

    def start(self):
        from playwright.sync_api import sync_playwright
        self.close()
        self.pw = sync_playwright().start()
        state_file = os.environ.get("WEB_STATE_FILE")
        if CLOUD and state_file and os.path.exists(state_file):
            # облако: чистый браузер + сессия Telegram Web из секретов GitHub (без папки профиля)
            self.browser = self.pw.chromium.launch(headless=True)
            self.ctx = self.browser.new_context(storage_state=state_file, viewport={"width": 1280, "height": 1000},
                                                locale="en-US")
            self.page = self.ctx.new_page()
        else:
            self.ctx = self.pw.chromium.launch_persistent_context(PROFILE, headless=not SHOW, viewport={"width": 1280, "height": 1000})
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.goto("https://web.telegram.org/k/", timeout=90000)
        self.wait_login()
        time.sleep(3)

    def close(self):
        for x in (self.ctx, self.browser):
            try:
                if x: x.close()
            except Exception: pass
        try:
            if self.pw: self.pw.stop()
        except Exception: pass
        self.ctx = self.pw = self.page = self.browser = None

    def logged(self):
        p = self.page
        try:
            auth = p.locator("#auth-pages")
            if auth.count() and auth.first.is_visible(): return False
            main = p.locator("#main-columns")
            return main.count() > 0 and main.first.is_visible()
        except Exception:
            return False

    def wait_login(self):
        for _ in range(25):
            if self.logged(): break
            time.sleep(1)
        if self.logged():
            log("Telegram Web: вход есть"); return
        if CLOUD:           # в облаке показать QR некому: сессию надо перенести заново
            notify("⚠️ Облако: Telegram не принял сохранённый вход (сессию отозвали или она устарела). "
                   "Запусти на ПК «2 Перенести вход в облако.bat» ещё раз — отправка до тех пор остановлена.")
            raise SystemExit(2)
        qr_html = os.path.join(BASE, "qr.html")
        with open(qr_html, "w", encoding="utf-8") as f:
            f.write('<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="4"></head>'
                    '<body style="margin:0;background:#888;text-align:center;font:20px sans-serif">'
                    '<p>Telegram на телефоне: Настройки → Устройства → Подключить устройство. Страница обновляется сама.</p>'
                    '<img src="qr.png" style="max-height:85vh"></body></html>')
        log("НУЖЕН ВХОД: открылся qr.html — отсканируй QR телефоном (Настройки → Устройства → Подключить устройство)")
        notify("⚠️ Скрипт поиска клиентов просит вход в Telegram Web: на компьютере открыт QR-код (qr.html).")
        try: os.startfile(qr_html)
        except Exception: pass
        said_pw = False
        while not self.logged():
            live(phase="жду вход в Telegram Web по QR-коду")
            try:
                self.page.screenshot(path=QR + ".tmp.png"); os.replace(QR + ".tmp.png", QR)
            except Exception: pass
            try:
                pwf = self.page.locator("#auth-pages input[type='password']")
                if pwf.count() and pwf.first.is_visible() and not said_pw:
                    log("QR принят, Telegram просит облачный пароль: закрой окно и запусти «ВХОД (с окном).bat»")
                    said_pw = True
            except Exception: pass
            time.sleep(4)
        log("Telegram Web: вход выполнен")
        for f in (QR, qr_html):
            try: os.remove(f)
            except Exception: pass

    def home(self):
        for _ in range(3):
            self.page.keyboard.press("Escape"); time.sleep(0.4)

    def find_row(self, username, peer_id=None):
        p = self.page
        self.home()
        inp = p.locator(self.SEARCH).first
        inp.click(); inp.fill(""); time.sleep(0.3)
        inp.type("@" + username, delay=35)
        rows = p.locator("#search-container .chatlist-chat")
        for _ in range(24):
            time.sleep(0.5)
            for k in range(min(rows.count(), 10)):
                r = rows.nth(k)
                try:
                    pid = r.get_attribute("data-peer-id") or ""
                    txt = r.inner_text()
                except Exception: continue
                if peer_id and pid == str(peer_id): return r, pid
                if username.lower() in [x.lower() for x in re.findall(r"@([A-Za-z0-9_]+)", txt)]:
                    return r, pid
        return None, "не найден в поиске"

    def open_chat(self, username, peer_id=None):
        """→ ('ok', peer_id) | ('skip', причина) | ('retry', причина)"""
        p = self.page
        row, pid = self.find_row(username, peer_id)
        if row is None: return "skip", pid
        if not pid or pid.startswith("-"): return "skip", "это канал/группа, не человек"
        row.click()
        for _ in range(20):
            time.sleep(0.5)
            try:
                t = p.locator(".chat-info .peer-title:visible").first
                if t.count() and t.get_attribute("data-peer-id") == pid: break
            except Exception: pass
        else:
            return "retry", "чат не открылся"
        for _ in range(16):                      # ждём историю или заглушку пустого чата
            time.sleep(0.5)
            if p.locator(".bubbles .bubble:visible, .bubbles .empty-bubble-placeholder:visible").count(): break
        time.sleep(1.5)
        return "ok", pid

    def bubbles(self):
        p = self.page
        return (p.locator(".bubbles .bubble.is-out:visible").count(),
                p.locator(".bubbles .bubble.is-in:visible").count())

    def flood_popup(self):
        try:
            for t in self.page.locator(".popup:visible, .toast:visible").all_inner_texts():
                if re.search(r"mutual contact|взаимн|PEER_FLOOD|too many|слишком мног|limited|ограничен", t, re.I):
                    return True
        except Exception: pass
        return False

    def premium_only(self):
        try:
            txt = self.page.locator(".chat-input:visible, .chat-input-wrapper:visible").all_inner_texts()
            return bool(re.search(r"only premium users can message|только пользователи.*premium|premium.*могут писать",
                                  " ".join(txt), re.I))
        except Exception:
            return False

    def paid_only(self):
        """Платные сообщения: Telegram просит звёзды за сообщение этому человеку."""
        try:
            txt = " ".join(self.page.locator(".chat-input:visible, .chat-input-wrapper:visible, .bubbles .empty-bubble-placeholder:visible")
                           .all_inner_texts())
            return bool(re.search(r"(\d+\s*)?(звёзд|звезд|stars?)\b.{0,40}(сообщ|message)|(сообщ|message).{0,40}(звёзд|звезд|stars?)\b|⭐",
                                  txt, re.I))
        except Exception:
            return False

    def last_out(self):
        try:
            return self.page.evaluate("""() => { const b = [...document.querySelectorAll('.bubbles .bubble.is-out')].pop();
                return b ? {mid: b.dataset.mid || '', text: (b.innerText || '').replace(/\\s+/g, ' '), cls: b.className}
                         : {mid: '', text: '', cls: ''} }""")
        except Exception:
            return {"mid": "", "text": "", "cls": ""}

    def last_is_out(self):
        """True, если последнее сообщение в открытом чате наше (Егор ответил сам или бот уже писал)."""
        try:
            return bool(self.page.evaluate("""() => { const l = [...document.querySelectorAll('.bubbles .bubble.is-in, .bubbles .bubble.is-out')].pop();
                return !!(l && l.classList.contains('is-out')); }"""))
        except Exception:
            return False

    def clear_input(self):
        """Стереть текст в поле ввода, чтобы неотправленное сообщение не осталось черновиком в чате."""
        p = self.page
        try:
            box = p.locator(f"{self.INPUT}:visible").first
            if box.count() and (box.inner_text() or "").strip():
                box.evaluate("e => e.focus()")
                p.keyboard.press("Control+A"); p.keyboard.press("Backspace"); time.sleep(0.5)
        except Exception: pass

    def type_and_send(self, text, split=False):
        """split=True: письмо уходит несколькими сообщениями (абзацы), между ними пауза 5–10 с. Результат первого сообщения решает,
        считается ли письмо отправленным; число ушедших сообщений — в self.last_parts."""
        parts = split_parts(text) if (split and SPLIT_ON) else [text]
        self.last_parts = 0
        for i, part in enumerate(parts):
            if i: time.sleep(random.uniform(*PART_PAUSE))
            r = self._type_and_send(part)
            if r != "sent":
                self.clear_input()
                if i == 0: return r
                log(f"часть {i + 1} из {len(parts)} не ушла: {r}")
                return "sent"
            self.last_parts += 1
        return "sent"

    def _type_and_send(self, text):
        p = self.page
        if p.locator(f"{self.INPUT}:visible").count() == 0 or self.premium_only():
            return "skip:нельзя написать (закрыта личка / пишут только Premium)"
        if self.paid_only():
            return "skip:человек берёт звёзды за сообщения от незнакомых — значит, не ждёт их"
        before = self.last_out()["mid"]
        probe = re.sub(r"\s+", " ", EMOJI_RE.sub("", text))[:18]
        box = p.locator(f"{self.INPUT}:visible").first
        try: box.click(timeout=5000)
        except Exception:                      # поле перекрыто (плашка/подсказка) — ставим курсор напрямую
            try: p.screenshot(path=os.path.join(BASE, "перекрыто-поле.png"))
            except Exception: pass
            box.evaluate("e => { e.focus(); const r = document.createRange(); r.selectNodeContents(e); r.collapse(false); "
                         "const s = getSelection(); s.removeAllRanges(); s.addRange(r); }")
        p.keyboard.press("Control+A"); p.keyboard.press("Backspace"); time.sleep(0.3)   # убрать старый черновик
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line: p.keyboard.insert_text(line)
            if i < len(lines) - 1: p.keyboard.press("Shift+Enter")
        time.sleep(0.8)
        p.keyboard.press("Enter")
        for _ in range(30):
            time.sleep(0.5)
            if self.flood_popup(): raise Limited("Telegram ограничил сообщения незнакомым")
            lo = self.last_out()
            if lo["mid"] != before and probe in lo["text"]:
                for _ in range(16):            # ждём, пока уйдёт «часики» (is-sending)
                    if "is-sending" not in lo["cls"]: break
                    time.sleep(0.5); lo = self.last_out()
                time.sleep(1.5)
                if self.flood_popup(): raise Limited("Telegram ограничил сообщения незнакомым")
                if "is-error" in lo["cls"] or "is-sending" in lo["cls"]:
                    if self.premium_only() or "premium" in p.locator("body").inner_text()[-3000:].lower():
                        return "skip:пишут только Premium"
                    return "fail:сообщение не ушло"
                # Telegram может отклонить сообщение уже после появления пузыря: пузырь исчезает,
                # а текст возвращается в поле ввода черновиком. Ждём и проверяем ещё раз.
                time.sleep(3)
                if self.flood_popup(): raise Limited("Telegram ограничил сообщения незнакомым")
                after = self.last_out()
                if probe not in after["text"] or "is-error" in after["cls"] or (probe[:12] and probe[:12] in self.input_text()):
                    return "fail:Telegram не принял сообщение (остался черновик)"
                return "sent"
        return "fail:отправка не подтвердилась"

    def input_text(self):
        try:
            box = self.page.locator(f"{self.INPUT}:visible").first
            return re.sub(r"\s+", " ", EMOJI_RE.sub("", box.inner_text() or "")) if box.count() else ""
        except Exception:
            return ""

    def send_new(self, username, text):
        st, info = self.open_chat(username)
        if st != "ok": return f"{st}:{info}", None
        out, inn = self.bubbles()
        if out or inn: return "skip:переписка уже была", info
        return self.type_and_send(text, split=True), info

    def send_reply(self, username, peer_id, text, auto=False, known_out=None):
        """Ответ в уже идущей переписке. auto=True — автоответ: бот пишет, только если Егор в этом чате не писал вообще:
        последнее сообщение от клиента и исходящих не больше, чем отправил сам бот (known_out)."""
        st, info = self.open_chat(username, peer_id)
        if st != "ok": return f"{st}:{info}"
        if auto:
            if self.last_is_out(): return "skip:ответил сам"
            if known_out is not None and self.bubbles()[0] > known_out: return "skip:ответил сам"
        return self.type_and_send(text, split=auto)

    def send_followup(self, username, peer_id, text, known_out=1):
        st, info = self.open_chat(username, peer_id)
        if st != "ok": return f"{st}:{info}"
        out, inn = self.bubbles()
        if inn: return "replied"
        if out != known_out: return "skip:в чате не одно наше сообщение"      # known_out: сколько сообщений ушло в первом письме
        return self.type_and_send(text, split=True)

    def search_channels(self, q):
        p = self.page
        self.home()
        inp = p.locator(self.SEARCH).first
        inp.click(); inp.fill(""); inp.type(q, delay=30); time.sleep(5)
        names = set()
        rows = p.locator("#search-container .chatlist-chat")
        for k in range(min(rows.count(), 30)):
            try:
                if (rows.nth(k).get_attribute("data-peer-id") or "").startswith("-"):
                    names |= set(re.findall(r"@([A-Za-z][A-Za-z0-9_]{4,31})", rows.nth(k).inner_text()))
            except Exception: pass
        self.home()
        return names

    def scan_replies(self, peers):
        """peers: {peer_id: username} → {peer_id: текст последнего входящего}.
        Черновики («Draft: …» / «Черновик: …») — это НЕ ответ клиента, а наше неотправленное сообщение:
        такие чаты складываются в self.drafts."""
        p = self.page
        self.home()
        found = {}
        self.drafts = set()
        for _ in range(20):                       # ждём, пока список чатов прогрузится
            if p.locator("#folders-container .chatlist-chat").count() >= 5: break
            time.sleep(0.5)
        for _ in range(5):
            try:
                rows = p.evaluate("""() => [...document.querySelectorAll('#folders-container .chatlist-chat')].map(e => ({
                    peer: e.dataset.peerId || '',
                    st: (e.querySelector('.sending-status') || {}).className || '',
                    unread: !!e.querySelector('.dialog-subtitle-badge-unread.is-visible'),
                    sub: (e.querySelector('.row-subtitle, .dialog-subtitle') || {}).innerText || ''}))""")
            except Exception:
                rows = []
            for info in rows:
                if info["peer"] not in peers: continue
                sub = re.sub(r"\s+", " ", info["sub"]).strip()
                if re.match(r"^(draft|черновик)\s*:", sub, re.I):
                    self.drafts.add(info["peer"]); continue
                if "hide" in info["st"] or info["unread"]:
                    found[info["peer"]] = sub[:200]
            try:
                p.locator("#folders-container .chatlist").first.evaluate(
                    "e => { const s = e.closest('.scrollable') || e.parentElement; s.scrollTop += 2500 }")
            except Exception: break
            time.sleep(1.5)
        try:
            p.locator("#folders-container .chatlist").first.evaluate(
                "e => { const s = e.closest('.scrollable') || e.parentElement; s.scrollTop = 0 }")
        except Exception: pass
        return found

    def spambot_ok(self):
        """True — ограничений нет, False — есть, None — не понял."""
        p = self.page
        self.spam_text = ""
        st, info = self.open_chat("SpamBot")
        if st != "ok": return None
        last_in = lambda: p.evaluate("""() => { const b = [...document.querySelectorAll('.bubbles .bubble.is-in')].pop();
                                       return b ? [b.dataset.mid || '', b.innerText || ''] : ['', ''] }""")
        before = last_in()[0]
        start = p.locator(".chat-input button:visible").filter(has_text=re.compile(r"start|запустить", re.I))
        if start.count(): start.first.click()
        elif p.locator(f"{self.INPUT}:visible").count():
            p.locator(f"{self.INPUT}:visible").first.click()
            p.keyboard.insert_text("/start"); p.keyboard.press("Enter")
        mid, last = before, ""
        for _ in range(30):                      # ждём НОВЫЙ ответ бота (счётчик пузырей ненадёжен)
            time.sleep(0.5)
            mid, last = last_in()
            if mid != before: break
        time.sleep(1)
        last = last_in()[1] or last
        self.spam_text = re.sub(r"\s+", " ", last).strip()
        self.home()
        if re.search(r"free as a bird|no limits|свободен от|нет ограничений|не ограничен", last, re.I): return True
        if re.search(r"limited|ограничен|annoying|жалоб|к сожалению|unfortunately|пожаловал", last, re.I): return False
        return None

# ======================= отчёты =======================
def variant_stats(st):
    out = {}
    for e in st["sent"].values():
        k = "вакансии" if e["kind"] == "hot" else f"холодные-{e.get('variant')}"
        s = out.setdefault(k, [0, 0]); s[0] += 1
        if e.get("replied"): s[1] += 1
    return out

def write_status(st, d, limited):
    rows = "\n".join(f"| {k} | {n} | {r} | {100 * r // n if n else 0}% |" for k, (n, r) in sorted(variant_stats(st).items()))
    replies = [f"- {e['replied']} @{u} ({e.get('display', '')}) — {e.get('source', '')}"
               for u, e in st["sent"].items() if e.get("replied")]
    txt = (f"# Статус поиска клиентов\n\nОбновлено: {datetime.datetime.now():%d.%m %H:%M}"
           f"{'  ⛔ отправка на паузе до ' + st['limited_until'][:16] if limited else ''}\n\n"
           f"**Сегодня:** откликов на вакансии {d['hot']}/{S()['limit_hot']}, холодных {d['cold']}, дожимов {d['fu']} "
           f"(лимит холодных+дожимов {S()['limit_cold']})\n\n"
           f"**В очереди:** вакансий {len(st['hot_q'])}, холодных {len(st['cold_q'])}\n\n"
           f"## Кто отвечает\n| тип | отправлено | ответили | % |\n|---|---|---|---|\n{rows}\n\n"
           f"## Ответили ({len(replies)})\n" + "\n".join(replies[-30:]) + "\n")
    try:
        with open(STATUS, "w", encoding="utf-8") as f: f.write(txt)
    except Exception: pass

# ======================= главный цикл =======================
LOCK = os.path.join(BASE, "running.lock")

def take_lock():
    """Не даём запустить второй экземпляр (два браузера на одном профиле ломают друг друга)."""
    try:
        pid = int(open(LOCK).read().strip())
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        if str(pid) in out and pid != os.getpid():
            return False
    except Exception:
        pass
    with open(LOCK, "w") as f: f.write(str(os.getpid()))
    return True

def main():
    if not DRY and not CLOUD and not take_lock():
        log("Скрипт уже запущен в другом окне — второй экземпляр не нужен."); sys.exit(3)
    st = jload(STATE, {})
    for k, d in (("seen", []), ("frontier", []), ("contacted", []), ("bad", []), ("qi", 0), ("hot_seen", []),
                 ("sent", {}), ("hot_q", []), ("cold_q", []), ("day", {}), ("limited_until", ""), ("spam_check", ""),
                 ("hot_channels", []), ("hot_checked", []), ("hqi", 0), ("notified", []), ("hot_rules", 1)):
        st.setdefault(k, d)
    seen, contacted, bad = set(st["seen"]), set(st["contacted"]), set(st["bad"])
    hot_seen = set(st["hot_seen"])
    if st["hot_rules"] != HOT_RULES_VERSION:     # правила откликов изменились — свежие посты смотрим заново
        st["notified"] = sorted(set(st["notified"]) | hot_seen)[-4000:]
        hot_seen = set(); st["hot_rules"] = HOT_RULES_VERSION
    notified = set(st["notified"])
    hot_list = lambda: list(dict.fromkeys(HOT_CHANNELS + st["hot_channels"]))
    USED_SKELETONS.update(st.get("skeletons", []))

    # очередь, собранная старыми шаблонами, — пересобираем в уникальные тексты
    pages = {}
    for item in st["hot_q"]:
        if item.get("uniq"): continue
        try:
            chn, pid = item["post"].rsplit("/", 2)[-2:]
            if chn not in pages: pages[chn] = parse_channel(chn); time.sleep(1)
            post = next(p for p in (pages[chn] or {}).get("posts", []) if p["id"] == f"{chn}/{pid}")
            item["text"] = compose_hot(post, pages[chn]["title"] or chn, item["display"]); item["uniq"] = 1
        except Exception: pass
    for item in st["cold_q"]:
        if item.get("uniq"): continue
        try:
            ch = analyze_channel(item["source"].rsplit("/", 1)[-1]); time.sleep(1)
            if ch:
                item["text"] = compose_cold(ch, item["display"], item["niche"], item["variant"]); item["uniq"] = 1
        except Exception: pass
    # разовый перенос старых ответов в CRM: статус по тексту ответа из ОТВЕТЫ.md
    try:
        for line in open(REPLIES, encoding="utf-8"):
            m = re.match(r"- \S+ @(\w+) .*?«(.*)»", line)
            if m and m.group(1) in st["sent"]:
                e = st["sent"][m.group(1)]
                if e.get("replied") and not e.get("crm"):
                    v = crm.classify(m.group(2)); crm.mark(e, v, m.group(2)); e["last_in"] = m.group(2)
                    e["outcome"] = "no" if v == crm.ST_REFUSED else "hot"
    except Exception: pass
    frontier = list(st["frontier"])
    contacted |= already_contacted_external()
    contacted |= {u.lower() for u in st["sent"]}

    def save():
        st.update(seen=sorted(seen), frontier=frontier[-5000:], contacted=sorted(contacted), bad=sorted(bad),
                  hot_seen=sorted(hot_seen)[-6000:], notified=sorted(notified)[-4000:],
                  skeletons=list(USED_SKELETONS)[-30000:])
        jsave(STATE, st)

    def crm_sync():
        """База лидов обновляется в момент события: файлы + «живое табло» в боте."""
        try:
            crm.write_files(st, BASE)
            if not DRY: crm.push_board(st, bot_token(), MY_ID)
        except Exception as ex: log("crm:", str(ex)[:80])

    def day():
        if st["day"].get("date") != today():          # итог дня присылает пульт в 21:00, тут только обнуляем
            st["day"] = {"date": today(), "hot": 0, "cold": 0, "fu": 0}
        return st["day"]

    def process_inbox():
        """Команды из бота: быстрые ответы клиентам и проверка аккаунта. Выполняются вне очереди и лимитов."""
        if not web: return
        try: files = sorted(f for f in os.listdir(INBOX) if f.endswith(".json"))
        except FileNotFoundError: return
        for fn in files:
            p = os.path.join(INBOX, fn); cmd = jload(p, None)
            try: os.remove(p)
            except Exception: pass
            if not cmd: continue
            if time.time() - cmd.get("ts", time.time()) > 3 * 3600:      # пролежало дольше 3 ч — не шлём невпопад
                notify(f"⌛ Не отправил устаревшую команду ({cmd.get('label') or cmd.get('cmd')}"
                       f"{' для @' + cmd['to'] if cmd.get('to') else ''}): поиск был выключен больше 3 часов.", silent=True)
                continue
            if cmd.get("cmd") == "send":
                u = cmd["to"]; e = st["sent"].get(u, {}); label = cmd.get("label", "Сообщение")
                live(phase=f"отвечаю клиенту @{u}")
                try: r = web.send_reply(u, e.get("peer") or cmd.get("peer"), cmd["text"])
                except Exception as ex: r = "fail:" + str(ex).splitlines()[0][:100]
                if r == "sent":
                    if u in st["sent"]:
                        e.setdefault("my", []).append({"t": datetime.datetime.now().isoformat(timespec="minutes"), "what": label})
                        crm.note_offer(e, cmd.get("text", ""))      # быстрый ответ с ценой тоже запускает касания 3-го и 7-го дня
                    log(f"ОТВЕТ клиенту @{u}: {label}")
                    notify(f"✅ {label} → {e.get('display') or u} (@{u}) отправлено", silent=True)
                else:
                    notify(f"⚠️ Не смог отправить «{label}» @{u}: {r}\nНапиши вручную: https://t.me/{u}")
                save()
            elif cmd.get("cmd") == "spamcheck":
                live(phase="проверяю аккаунт через @SpamBot")
                try: ok = web.spambot_ok()
                except Exception: ok = None
                txt = getattr(web, "spam_text", "")
                notify({True: "🛡 @SpamBot: ограничений на аккаунте нет ✅",
                        False: "🛡 @SpamBot: на аккаунте ЕСТЬ ограничение ⛔",
                        None: "🛡 Не разобрал ответ @SpamBot — загляни в него вручную: https://t.me/SpamBot"}[ok]
                       + (f"\n\nОн пишет: «{cut(txt, 700)}»" if txt and ok is not True else ""))
            elif cmd.get("cmd") == "cleardraft":
                try:
                    s_, info = web.open_chat(cmd["to"], st["sent"].get(cmd["to"], {}).get("peer"))
                    if s_ == "ok": web.clear_input(); log("черновик очищен:", cmd["to"])
                except Exception as ex: log("не очистил черновик", cmd["to"], str(ex)[:80])

    def why_idle(s, d, limited):
        if limited: return f"⛔ пауза до {st['limited_until'][11:16]} (защита аккаунта)"
        parts = []
        if not s["hot_on"]: parts.append("вакансии выключены")
        elif not in_hours(HOURS_HOT): parts.append(f"вакансии: ночь, продолжу в {HOURS_HOT[0]}:00 МСК")
        elif d["hot"] >= s["limit_hot"]: parts.append("вакансии: дневной лимит исчерпан")
        elif not st["hot_q"]: parts.append("вакансии: жду новые")
        if not (s["cold_on"] or s["fu_on"]): parts.append("холодные выключены")
        elif not in_hours(HOURS_COLD): parts.append(f"холодные: с {HOURS_COLD[0]}:00 до {HOURS_COLD[1]}:00 МСК")
        elif d["cold"] + d["fu"] >= s["limit_cold"]: parts.append("холодные: дневной лимит исчерпан")
        elif not st["cold_q"]: parts.append("холодные: подбираю экспертов")
        return "; ".join(parts) or "готов отправлять"

    web = None
    def web_up():
        nonlocal web
        if DRY: return None
        if web is None or web.page is None:
            if not CLOUD:
                web = Web()
            elif os.environ.get("WEB_STATE_FILE"):          # основной облачный режим: Telegram Web в Chromium
                cloud_tg = __import__("cloud_tg")
                web = type("WebCloud", (Web, cloud_tg.BotLink), {})()
                web.init_bot()
            else:                                           # запасной: Telethon (нужны api_id/api_hash)
                web = __import__("cloud_tg").TgCloud(Limited)
            while True:
                try: web.start(); break
                except Exception as e:
                    log("браузер не запустился:", str(e)[:100], "— повтор через 60 c"); web.close(); time.sleep(60)
        return web

    def web_reset():
        try: web.close()
        except Exception: pass
        time.sleep(5); web_up()

    if SELFTEST:
        w = web_up()
        ch = {"title": "Ипотека без нервов", "desc": "Ипотечный брокер, консультации", "posts": ["Как получить семейную ипотеку, если вы самозанятый: 5 шагов"],
              "videos": 0, "n_posts": 20, "subs": 4200, "avg_views": 380}
        post = {"text": "#ищу монтажёра Reels для эксперта по недвижимости\nНужно 8 роликов в месяц, говорящая голова, субтитры."}
        for t in (compose_hot(post, "Ищу монтажера/рилс-мейкера", "Анна Петрова"),
                  compose_cold(ch, "Алексей Иванов", "finance", "A"),
                  followup_text({"kind": "cold", "display": "Алексей"})):
            s, info = w.open_chat(MY_USERNAME, MY_ID)
            log("самотест: открыть «Избранное» →", s, info)
            if s == "ok": log("самотест: отправка →", w.type_and_send(t))
            time.sleep(2)
        notify("✅ Самотест: 3 образца сообщений (вакансия, холодное, дожим) лежат у тебя в «Избранном».")
        w.close(); return

    log("СТАРТ v2", "(проверка, без отправки)" if DRY else "(боевой режим)", "| уже писали:", len(contacted),
        "| каналов с вакансиями:", len(HOT_CHANNELS))
    if not DRY:
        print("=" * 64 + "\n  ПОИСК КЛИЕНТОВ работает. Окно можно свернуть, но НЕ закрывать.\n"
              "  Остановить — закрыть окно. Ответы клиентов пришлёт бот @pepeclodai715bot.\n"
              "  Статус: auto\\СТАТУС.md    Все ответы: auto\\ОТВЕТЫ.md\n" + "=" * 64, flush=True)
        web_up()
        log("браузер готов, начинаю работу")
        if CLOUD: notify("☁️ Поиск клиентов работает в облаке GitHub — компьютер можно выключать.", silent=True)

    next_hot = 0; next_replies = time.time() + 120; next_send = 0; next_status = 0; fails = 0
    T0 = time.time()
    next_hot_disc = time.time() + 600
    next_crm = 0

    while True:
        try:
            now = time.time()
            d = day()
            s = S()
            live()
            if now >= next_crm: crm_sync(); next_crm = now + 600       # «молчит >48ч» и прочие статусы по времени
            process_inbox()
            if CLOUD:
                web.tick_bot()                              # кнопки пульта обрабатываются здесь же
                if time.time() - T0 > CLOUD_RUN_LIMIT:
                    log("облако: плановое завершение, состояние сохраняется"); break
                if not web.want():
                    live(phase="выключен кнопкой ⏹", why="нажми ▶️ Запустить", next_send=0)
                    time.sleep(3); continue

            # ---- 1. горячие вакансии
            if now >= next_hot:
                next_hot = now + HOT_SCAN_EVERY
                new, manual = 0, []
                live(phase="проверяю каналы с вакансиями")
                for chn in hot_list():
                    c = parse_channel(chn)
                    process_inbox(); live()
                    time.sleep(random.uniform(1, 2.5))
                    if not c: continue
                    for post in c["posts"]:
                        if not post["id"] or post["id"] in hot_seen: continue
                        hot_seen.add(post["id"])
                        if not post["when"] or (datetime.datetime.now(datetime.timezone.utc) - post["when"]).total_seconds() > HOT_MAX_AGE_H * 3600:
                            continue
                        if not is_hot(post["text"]): continue
                        why = guard.no_dm(post["text"]) or guard.apply_by_button(post["text"], post.get("buttons"))
                        if why: log(f"пропуск вакансии {post['id']}: {why}"); continue
                        allc = hot_contacts(post, chn)
                        cands = [u for u in allc if u.lower() not in contacted and u.lower() not in bad and mine(u)
                                 and not guard.contact_problem(post["text"], u, post["links"])]
                        target = None
                        for u in cands:
                            dn = user_page(u); time.sleep(random.uniform(0.8, 1.8))
                            if dn: target = (u, dn); break
                            bad.add(u.lower())
                        link = f"https://t.me/{post['id']}"
                        if not target:
                            if not allc and post["id"] not in notified:
                                notified.add(post["id"])
                                manual.append(f"• {cut(hot_task(post['text']) or post['text'], 90)}\n  {link}")
                            continue
                        u, dn = target
                        bio = USER_BIO.get(u.lower(), "")
                        why = guard.no_dm(bio)
                        if why:
                            bad.add(u.lower()); log(f"пропуск @{u}: в био {why}"); continue
                        fm = autoreply.first_message(post["text"], u, dn, bio) if autoreply.llm_on() else None
                        if fm and not fm["fit"]:
                            log(f"не наш профиль, пропускаю @{u}: {fm['reason']}"); continue
                        if fm: text = fm["text"]
                        else:                                   # бесплатный режим: фильтр + боли по нише без ИИ
                            ok, why = autoreply.rule_fit(post["text"])
                            if not ok:
                                log(f"не наш профиль, пропускаю @{u}: {why}"); continue
                            text = compose_hot(post, c["title"] or chn, dn, bio)
                        st["hot_q"].append({"username": u, "display": dn, "post": link, "found": now, "uniq": 1,
                                            "text": text})
                        contacted.add(u.lower()); new += 1
                        log(f"ВАКАНСИЯ: @{u} ({dn}) ← {link}")
                save()
                log(f"вакансии проверены ({len(hot_list())} каналов): +{new} в очередь (всего {len(st['hot_q'])})")
                if manual:      # вакансии без контакта в Telegram не присылаем ни Егору, ни кому-то ещё: просто пропускаем
                    log(f"вакансий без контакта в Telegram пропущено: {len(manual)}")

            # ---- 1б. поиск НОВЫХ каналов с вакансиями (раз в 2 часа, один запрос)
            if web and now >= next_hot_disc:
                next_hot_disc = now + HOT_DISCOVER_EVERY
                q = HOT_QUERIES[st["hqi"] % len(HOT_QUERIES)]; st["hqi"] += 1
                try: found = web.search_channels(q)
                except Exception as e: found = set(); log("поиск каналов вакансий не удался:", str(e)[:80])
                known = {x.lower() for x in hot_list()} | {x.lower() for x in st["hot_checked"]}
                for chn in found:
                    if chn.lower() in known: continue
                    st["hot_checked"].append(chn)
                    c = parse_channel(chn); time.sleep(random.uniform(1, 2.5))
                    if not c: continue
                    fresh = [p for p in c["posts"] if p["when"] and
                             (datetime.datetime.now(datetime.timezone.utc) - p["when"]).days <= 7]
                    hits = sum(1 for p in fresh if is_hot(p["text"]))
                    if hits >= 3:
                        st["hot_channels"].append(chn)
                        log(f"НОВЫЙ канал с вакансиями: @{chn} ({hits} вакансий за неделю)")
                save()

            # ---- 2. ответы
            if web and now >= next_replies:
                next_replies = now + REPLY_CHECK_EVERY
                # следим и за теми, кто уже ответил, но диалог ещё ведёт бот (auto_n) и не передан Егору
                peers = {e["peer"]: u for u, e in st["sent"].items() if e.get("peer")
                         and e.get("crm") != crm.ST_REFUSED and not e.get("handoff")      # согласившихся ведём до оплаты
                         and (not e.get("replied") or e.get("auto_n") or e.get("pending"))}
                if peers:
                    live(phase="проверяю, кто ответил")
                    try: got = web.scan_replies(peers)
                    except Exception as e: got = {}; log("проверка ответов не удалась:", str(e)[:80])
                    # черновик вместо отправленного сообщения: Telegram его не принял — убираем из базы и чистим поле
                    for pid in getattr(web, "drafts", set()):
                        u = peers[pid]; e = st["sent"].get(u) or {}
                        if e.get("replied") or e.get("thread"): continue           # в живом диалоге черновик не трогаем
                        try:
                            if web.open_chat(u, pid)[0] == "ok" and not web.bubbles()[0]: web.clear_input()
                        except Exception: pass
                        st["sent"].pop(u, None); bad.add(u.lower())
                        log(f"НЕ ДОШЛО @{u}: в чате остался черновик, Telegram не принял сообщение — убрал из базы")
                        notify(f"⚠️ Сообщение @{u} не дошло (Telegram его не принял, остался черновик). Убрал черновик и вычеркнул из базы.",
                               silent=True)
                    if getattr(web, "drafts", None): save()
                    for pid, snippet in got.items():
                        u = peers[pid]; e = st["sent"][u]
                        if snippet and snippet == e.get("last_in"): continue      # это сообщение уже обработано
                        first = not e.get("replied")
                        if first: e["replied"] = datetime.datetime.now().isoformat(timespec="minutes")
                        e["last_in"] = snippet; e["last_in_ts"] = time.time()
                        e.setdefault("thread", []).append({"who": "them", "text": snippet})
                        kind = "вакансия" if e["kind"] == "hot" else f"холодное, вариант {e.get('variant')}"
                        verdict = crm.classify(snippet)
                        if verdict != crm.ST_REFUSED and crm.is_junk(snippet):          # не лид: без денег / «читайте бота» / дубль
                            e["junk"] = True; e["handoff"] = True; e.pop("pending", None)
                            crm.mark(e, crm.ST_REPLIED, snippet)
                            notify(f"🗑 Не лид (без оплаты или дубль): {e.get('display', '')} (@{u})\n«{snippet[:200]}»", buttons=link0(u), silent=True)
                            continue
                        crm.mark(e, verdict, snippet)
                        e["outcome"] = "no" if verdict == crm.ST_REFUSED else "hot"
                        link = [[{"text": "💬 Открыть чат", "url": f"https://t.me/{u}"}]]
                        with open(REPLIES, "a", encoding="utf-8") as f:
                            f.write(f"- {e['replied']} @{u} ({e.get('display', '')}) — {kind} — {crm.LABEL[verdict]} — «{snippet}» — https://t.me/{u}\n")
                        autoon = s.get("autoreply", True)
                        delay = random.uniform(*AUTO_DELAY)               # отвечаем не мгновенно — как живой человек
                        if verdict == crm.ST_REFUSED:
                            e.pop("pending", None)
                            if autoon and not e.get("bye") and not e.get("human"):               # вежливо закрываем — дверь остаётся открытой
                                e["bye"] = 1; e["pending"] = {"text": autoreply.goodbye(), "due": now + delay, "bye": 1}
                            notify(f"❌ Отказ: {e.get('display', '')} (@{u})\n«{snippet}»", buttons=link, silent=True)
                            continue
                        auto = None
                        if autoon and not e.get("human") and e.get("auto_n", 0) < autoreply.max_auto():
                            live(phase=f"готовлю ответ @{u}")
                            auto = autoreply.generate(e, snippet, verdict)
                        if auto:
                            e["pending"] = {"text": auto["text"], "due": now + delay, "src": auto.get("src", "")}
                            if auto["handoff"] or e.get("auto_n", 0) + 1 >= autoreply.max_auto(): e["handoff"] = True
                        else:
                            e.pop("pending", None)
                        # согласие: если ИИ сам дал реквизиты (pay.txt), диалог ведёт дальше до скрина оплаты
                        if verdict == crm.ST_AGREED and not (auto and auto.get("src") != "rules" and autoreply.pay_info()):
                            e["handoff"] = True
                        when = f"через {int(delay // 60) or 1} мин, если ты не ответишь сам" + ("" if in_hours(AUTO_HOURS) else f", утром после {AUTO_HOURS[0]}:00 МСК")
                        if verdict == crm.ST_AGREED or e.get("handoff") or not auto:
                            if e.get("handoff") or not auto: e["handoff"] = True
                            head = "✅ СОГЛАСИЛСЯ" if verdict == crm.ST_AGREED else "🔥 ОТВЕТИЛ"
                            extra = (f"\n\n🤖 Отвечу {when}: «{auto['text'][:300]}»\nДальше веди сам: {auto['reason']}" if auto else
                                     "\n\n🤖 Тут нужен ты: вопрос нестандартный, сам не отвечаю.")
                            notify(f"{head} {e.get('display', '')} (@{u})\n«{snippet}»{extra}\n\n{kind}: {e.get('source', '')}\n\n"
                                   f"Быстрый ответ — кнопками ниже:", buttons=reply_buttons(u))
                        else:
                            notify(f"🤖 Веду диалог с {e.get('display', '')} (@{u})\nКлиент: «{snippet[:200]}»\n"
                                   f"Отвечу {when}: «{auto['text'][:300]}»", buttons=link, silent=True)
                    save(); crm_sync()

            # ---- 2б. отложенные автоответы (по одному за проход, только днём по Москве)
            if web and in_hours(AUTO_HOURS):
                for u, e in list(st["sent"].items()):
                    p = e.get("pending")
                    if not p or now < p["due"]: continue
                    e.pop("pending", None)
                    known = bot_out(e)
                    try: rr = web.send_reply(u, e.get("peer"), p["text"], auto=True, known_out=known)
                    except Limited: raise
                    except Exception as ex: rr = "fail:" + str(ex)[:60]
                    if rr == "sent":
                        if not p.get("bye"): e["auto_n"] = e.get("auto_n", 0) + 1
                        add_out(e, getattr(web, "last_parts", 1) or 1)
                        e.setdefault("thread", []).append({"who": "me", "text": p["text"]})
                        crm.note_offer(e, p["text"])                  # цена названа / закрывающий вопрос задан (для касаний и CRM)
                        log(f"АВТООТВЕТ @{u} [{p.get('src') or 'прощание'}]: {p['text'][:80]}")
                    elif rr.startswith("skip:ответил сам"):
                        e["human"] = True                      # диалог взял Егор: бот в нём больше не пишет
                        log(f"автоответ @{u} отменён: в чате уже ответили сами")
                    else:
                        log(f"автоответ @{u} не ушёл: {rr}")
                        notify(f"⚠️ Не смог отправить автоответ @{u} — ответь сам:\n«{p['text'][:300]}»",
                               buttons=[[{"text": "💬 Открыть чат", "url": f"https://t.me/{u}"}]])
                    save(); crm_sync()
                    break

            # ---- 3. отправка: одно сообщение за раз, потом пауза
            limited = bool(st["limited_until"]) and st["limited_until"] > datetime.datetime.now().isoformat()
            if not limited and st["limited_until"]:                # ограничение только что истекло:
                st["limited_until"] = ""; st["spam_check"] = ""    # перед первым сообщением — снова спросить @SpamBot
                st.setdefault("warm_from", datetime.datetime.now().isoformat()); save()
            # 3 дня после ограничения — мягкий разгон: мало откликов, длинные паузы, без холодных и дожимов
            warm = bool(st.get("warm_from")) and (datetime.datetime.now() - datetime.datetime.fromisoformat(st["warm_from"])).days < WARM_DAYS
            if st.get("warm_from") and not warm: st.pop("warm_from", None)
            lim_hot = min(int(s["limit_hot"]), WARM_HOT) if warm else int(s["limit_hot"])
            gap = lambda: max(WARM_GAP if warm else 10, int(s["gap"])) * random.uniform(1.0, 1.15)
            if now >= next_send and not limited:
                job = None
                if s["hot_on"] and in_hours(HOURS_HOT) and d["hot"] < lim_hot:
                    st["hot_q"] = [x for x in st["hot_q"] if now - x["found"] < 48 * 3600]
                    if st["hot_q"]: job = ("hot", st["hot_q"][0])
                if not job and not warm and in_hours(HOURS_COLD) and d["cold"] + d["fu"] < s["limit_cold"]:
                    if s["fu_on"]:
                        for u, e in st["sent"].items():
                            h = FOLLOWUP_HOT_H if e["kind"] == "hot" else FOLLOWUP_COLD_H
                            age = now - e.get("ts", now)
                            if not e.get("replied") and not e.get("fu") and e.get("peer") and h * 3600 < age < 7 * 86400:
                                job = ("fu", u); break
                        if not job:                                    # касания на 3-й и 7-й день тем, кому назвали цену, а он молчит
                            for u, e in st["sent"].items():
                                tm = touch_due(e, now)
                                if tm: e["_tm"] = tm; job = ("fu", u); break
                    if not job and s["cold_on"] and st["cold_q"]: job = ("cold", st["cold_q"][0])
                if not job: live(phase="жду", why=why_idle(s, d, limited), next_send=0)
                else: live(phase=f"пишу @{job[1] if job[0] == 'fu' else job[1]['username']}")

                if job and DRY:
                    kind, item = job
                    if kind != "fu":
                        with open(OUTBOX, "a", encoding="utf-8") as f:
                            f.write(f"### [{'ВАКАНСИЯ' if kind == 'hot' else 'ХОЛОДНОЕ ' + item['variant']}] "
                                    f"@{item['username']} ({item['display']}) ← {item.get('post') or item.get('source')}\n"
                                    f"{item['text']}\n\n")
                        st["hot_q" if kind == "hot" else "cold_q"].pop(0)
                        d[kind] += 1; log(f"черновик [{kind}]: @{item['username']}")
                    save(); job = None

                if job:
                    kind, item = job
                    if st["spam_check"] != today():
                        ok = web.spambot_ok(); st["spam_check"] = today(); save()
                        log("@SpamBot:", {True: "ограничений нет", False: "ЕСТЬ ОГРАНИЧЕНИЕ", None: "ответ не распознан"}[ok])
                        if ok is False: raise Limited("@SpamBot сообщает об ограничении аккаунта")
                    if kind == "fu":
                        e = st["sent"][item]
                        tm = e.pop("_tm", None)                        # t3 / t7 — касание после цены; иначе обычный дожим
                        try: r = web.send_followup(item, e["peer"], touch_text(e, tm) if tm else (autoreply.followup_message(e) or followup_text(e)), known_out=e.get("n_out", 1))
                        except Limited: raise
                        except Exception as ex: r = "fail:" + str(ex).splitlines()[0][:100]
                        if r == "replied":
                            e["replied"] = datetime.datetime.now().isoformat(timespec="minutes"); log("уже ответил:", item)
                            if tm: e[tm] = "skip"
                        elif r == "sent":
                            add_out(e, getattr(web, "last_parts", 1) or 1); d["fu"] += 1; fails = 0
                            if tm: e[tm] = today(); e[tm + "_ts"] = time.time(); log(f"КАСАНИЕ {tm} отправлено: @{item}")
                            else: e["fu"] = today(); log(f"ДОЖИМ отправлен: @{item}")
                            next_send = time.time() + gap()
                        else:
                            if tm: e[tm] = "skip"
                            else: e["fu"] = "skip"
                            log("дожим пропущен:", item, r)
                            if "не одно наше" in r: e["human"] = True        # Егор дописал в чат сам: бот в нём больше не пишет
                        save()
                    else:
                        q = st["hot_q"] if kind == "hot" else st["cold_q"]
                        risk = "" if mine(item["username"]) else "контакт второй половины команды"
                        risk = risk or guard.check_before_send(kind, item)   # последняя проверка: тот ли человек и не против ли он
                        if risk:
                            q.pop(0); bad.add(item["username"].lower())
                            log(f"НЕ ПИШУ @{item['username']}: {risk}"); save()
                            next_send = time.time() + 5
                            continue
                        try: r, peer = web.send_new(item["username"], item["text"])
                        except Limited: raise
                        except Exception as ex: r, peer = "fail:" + str(ex).splitlines()[0][:100], None
                        if r == "sent":
                            q.pop(0); d[kind] += 1; fails = 0
                            st["sent"][item["username"]] = {"kind": kind, "peer": peer, "ts": now, "date": today(),
                                "display": item["display"], "variant": item.get("variant"),
                                "source": item.get("post") or item.get("source"), "text": item["text"],
                                "n_out": getattr(web, "last_parts", 1) or 1}
                            crm_sync()
                            log(f"ОТПРАВЛЕНО [{'вакансия' if kind == 'hot' else 'холодное'}] @{item['username']} — сегодня: "
                                f"вакансии {d['hot']}/{s['limit_hot']}, холодные+дожимы {d['cold'] + d['fu']}/{s['limit_cold']}")
                            next_send = time.time() + gap()
                        elif r.startswith("retry"):
                            q.pop(0); item["tries"] = item.get("tries", 0) + 1
                            if item["tries"] < 3: q.append(item)
                            log("чат не открылся:", item["username"], "попытка", item["tries"]); web_reset()
                        elif r.startswith("skip"):
                            q.pop(0); bad.add(item["username"].lower()); log("пропуск", item["username"], "—", r[5:])
                        else:
                            fails += 1; log("сбой", item["username"], "—", r, f"({fails} подряд)")
                            try: web.page.screenshot(path=os.path.join(BASE, f"сбой-{item['username']}.png"))
                            except Exception: pass
                            q.pop(0); item["tries"] = item.get("tries", 0) + 1
                            if item["tries"] < 2: q.append(item)
                            else: bad.add(item["username"].lower()); log("убираю из очереди после 2 сбоев:", item["username"])
                            if fails >= 3:
                                ok = web.spambot_ok()
                                log("3 сбоя подряд — @SpamBot:", {True: "ограничений нет", False: "ЕСТЬ ОГРАНИЧЕНИЕ", None: "не понял"}[ok])
                                if ok is False: raise Limited("@SpamBot: Telegram ограничил аккаунт")
                                if ok is None: raise Limited("3 сбоя отправки подряд")
                                fails = 0
                            web_reset()
                        save()

            if limited:
                live(phase="жду", why=why_idle(s, d, limited), next_send=0)
            elif time.time() < next_send:
                live(why="пауза между сообщениями", next_send=next_send)

            # ---- 4. поиск холодных — в паузах между отправками
            if s["cold_on"] and len(st["cold_q"]) < 30:
                if not frontier:
                    if not st.get("seeded"):
                        frontier.extend(s for s in SEEDS if s.lower() not in seen); st["seeded"] = True
                    else:
                        q = QUERIES[st["qi"] % len(QUERIES)]; st["qi"] += 1
                        live(phase=f"ищу экспертов: «{q}»")
                        found = set()
                        if web:
                            try: found |= web.search_channels(q)
                            except Exception as e: log("поиск в Telegram не удался:", str(e)[:80])
                        if len(found) < 3: found |= search_engines(q)
                        new = [n for n in found if n.lower() not in seen and n.lower() not in JUNK_NAMES]
                        frontier.extend(new); log(f"поиск «{q}»: новых каналов {len(new)}")
                    save()
                else:
                    name = frontier.pop(0)
                    if name.lower() not in seen:
                        seen.add(name.lower())
                        live(phase=f"изучаю канал @{name}")
                        ch = analyze_channel(name); time.sleep(random.uniform(1.5, 3))
                        if ch:
                            niche = niche_of(ch["title"], ch["desc"], " ".join(ch["posts"][-10:]))
                            if niche:   # снежный ком: каналы, на которые ссылается профильный канал
                                fl = {x.lower() for x in frontier}
                                for n in list(ch["links"])[:40]:
                                    nl = n.lower()
                                    if nl not in seen and nl not in JUNK_NAMES and nl not in fl and not nl.endswith("bot"):
                                        frontier.append(n); fl.add(nl)
                            fresh = ch["last"] and (datetime.datetime.now(datetime.timezone.utc) - ch["last"]).days <= FRESH_DAYS
                            if niche and fresh and SUBS_RANGE[0] <= ch["subs"] <= SUBS_RANGE[1] and is_expert_channel(ch):
                                for u in find_contacts(ch):
                                    ul = u.lower()
                                    if ul in contacted or ul in bad or not mine(u): continue
                                    dn = user_page(u); time.sleep(random.uniform(1, 2))
                                    if dn is None: bad.add(ul); continue
                                    v = pick_variant(st)
                                    live(phase=f"пишу письмо для @{u}")
                                    txt = autoreply.cold_message(ch, dn, niche, v) or compose_cold(ch, dn, niche, v)   # ИИ изучил канал → письмо лично ему
                                    st["cold_q"].append({"username": u, "display": dn, "variant": v, "niche": niche, "uniq": 1,
                                                         "source": f"https://t.me/{name}",
                                                         "text": txt})
                                    contacted.add(ul)
                                    log(f"холодный лид: @{u} ({dn}) ← @{name}, {ch['subs']} подп., {niche}, вариант {v}")
                                    break
                        save()
            else:
                live(phase="жду")
                time.sleep(5)

            if now >= next_status:
                next_status = now + 300; write_status(st, d, limited)
            time.sleep(2)

        except Limited as e:
            txt = getattr(web, "spam_text", "") if web else ""
            until = guard.spam_until(txt)                          # точная дата из ответа @SpamBot, если она есть
            if not until or until < datetime.datetime.now() + datetime.timedelta(hours=1):
                until = datetime.datetime.now() + datetime.timedelta(hours=20)
            st["limited_until"] = max(st.get("limited_until") or "", until.isoformat())
            st["warm_from"] = st["limited_until"]                  # после снятия — 3 дня мягкого разгона
            fails = 0; save()
            log("СТОП ОТПРАВКИ до", st["limited_until"][:16], "—", e)
            msg = (f"⛔ {e}. Новых сообщений незнакомым не шлю до {st['limited_until'][8:10]}.{st['limited_until'][5:7]} "
                   f"{st['limited_until'][11:16]} — поиск заказов продолжается, ответы клиентам и быстрые ответы работают.\n"
                   f"После снятия 3 дня разгоняюсь мягко: до {WARM_HOT} откликов в день, без холодных и дожимов.")
            if "SpamBot" in str(e) or re.search(r"к сожалению|ограничен|limited", txt, re.I):
                s = S()
                safe = dict(s, gap=max(int(s["gap"]), 180), limit_hot=min(int(s["limit_hot"]), 25),
                            limit_cold=min(int(s["limit_cold"]), 10))
                if safe != s:
                    jsave(SETTINGS, safe)
                    msg += (f"\n\n🛡 Включил безопасный режим: пауза {safe['gap']} с, лимиты {safe['limit_hot']}/"
                            f"{safe['limit_cold']} в день. Повторное ограничение обычно дольше, а потом — навсегда. "
                            "Вернуть быстрее можно в ⚙️ Настройках.")
                if txt: msg += f"\n\n@SpamBot пишет: «{cut(txt, 600)}»"
            notify(msg)
            if web: web_reset()
        except KeyboardInterrupt:
            log("остановлено вручную"); break
        except Exception as e:
            log("ошибка (идём дальше):", str(e)[:200]); log(traceback.format_exc().splitlines()[-1])
            time.sleep(10)
            if web and re.search(r"closed|target|crash|disconnected", str(e), re.I): web_reset()
    save()
    if web: web.close()

if __name__ == "__main__":
    main()
