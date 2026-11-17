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
HOURS_HOT = (0, 24)     # 16.11 Егор: круглосуточно (с перерывами REST_*), лимиты в день остаются
HOT_DISCOVER_EVERY = 40 * 60    # как часто искать новые каналы с вакансиями (было 2 часа, 14.11 ускорено)
HOURS_COLD = (0, 24)    # холодные, компании, партнёры — тоже круглосуточно
REST_EVERY = (4, 7)     # после 4–7 отправок подряд — перерыв, как у живого человека
REST_FOR = (20 * 60, 45 * 60)
HOT_SCAN_EVERY = 12 * 60
REPLY_CHECK_EVERY = 60          # ответы проверяем каждую минуту: скорость ответа клиенту = деньги
AUTO_DELAY = (1800, 1860)        # автоответ уходит только через 30 минут и только если Егор за это время сам не ответил
HOLD_DELAY = (45, 120)           # режим hold_only: «секундочку, сейчас вернусь» через 1–2 мин, если Егор сам не ответил
HOLD_TEXTS = ["Секундочку, сейчас вернусь",
              "Секундочку, сейчас вернусь к вам",
              "Одну секундочку, сейчас вернусь",
              "Секундочку, сейчас отвечу"]
AUTO_HOURS = (0, 24)            # «Секундочку, сейчас вернусь» — в любое время (опоздавшее больше 15 мин не уходит)

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
HOT_MAX_AGE_H = 48      # откликаемся только на посты не старше N часов (было 36, 14.11 расширено)
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
                  r"анимац|нейро|креатор|tiktok|тикток|vfx|after effects|premiere|davinci|capcut", re.I)   # 16.11: без оператор/мобилограф/ugc — это съёмка
# Отсеиваем только то, что НЕ вакансия: резюме конкурентов, реклама сервисов, рефералки.
NOT_HOT = ["#резюме", "#помогу", "ищу работу", "ищу заказ", "ищу клиент", "возьму заказ", "беру заказ", "мои работы",
           "моё портфолио", "мое портфолио", "реферальн", "промокод", "бесплатный старт", "автомонтаж",
           "я видеомонтаж", "я — видеомонтаж", "я монтажер", "я монтажёр", "услуги монтаж", "стоимость рассчитывается",
           "предлагает услуги", "предлагаю услуги", "мои услуги", "обращайтесь ко мне", "курс по монтажу",
           "обучение монтажу", "научу монтировать"]
NOT_HOT_RX = re.compile("|".join(r"(?<![а-яёa-z])" + re.escape(x) for x in NOT_HOT), re.I)
HOT_QUERIES = ["ищу монтажера", "вакансии монтажер", "монтажер работа", "заказы видеомонтаж", "reels вакансии",
               "ищу рилсмейкера", "вакансии видео", "фриланс видеомонтаж", "вакансии контент мейкер",
               "ищу моушн дизайнера", "работа youtube монтаж", "ищу продюсера", "продюсер reels", "ищу сценариста", "сценарист рилс", "раскадровщик",
               "контент продюсер", "ролики под ключ",
               "ищу монтажёра рилс", "нужен видеомонтажер", "монтажер на проект", "монтажёр на постоянку",
               "вакансии smm", "ищу smm", "вакансии для креаторов",
               "вакансии шортс", "тикток вакансии", "вакансии клипмейкер", "монтаж подкастов", "ищу клипмейкера",
               "вакансии motion дизайнер", "ищу видеомейкера", "работа видеомонтажером удалённо", "заказы на монтаж",
               "биржа монтажеров", "чат монтажеров", "чат рилсмейкеров", "вакансии для видеомейкеров",
               # 15.11: расширение — креативные и digital-вакансии, где часто ищут видео
               "вакансии digital", "удаленная работа креатив", "креативные вакансии", "вакансии дизайн видео",
               "работа в smm удаленно", "фриланс заказы", "заказы фрилансерам", "вакансии маркетинг удаленно",
               "ищу монтажера для блога", "нужен монтажер youtube", "ищу видеомонтажера в команду",
               "монтаж для эксперта", "монтаж вебинаров", "нарезка видео вакансии", "ищу человека на монтаж",
               "вакансии продакшн", "работа в продакшене", "вакансии инфобизнес", "ищу ассистента продюсера",
               "вакансии для дизайнеров", "фриланс биржа телеграм", "удаленка вакансии", "remote вакансии креатив"]
HOT_RULES_VERSION = 4      # при смене правил — пересмотреть свежие посты заново
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

DEFAULTS = {"gap": 30, "limit_hot": 40, "limit_cold": 20, "limit_fu": 8, "hot_on": True, "cold_on": True, "fu_on": True,   # 16.11: дожимы — свой лимит, не съедают новые письма
            "biz_on": True, "partners_on": True, "niche_on": True, "yt_on": True, "limit_yt": 20, "mail_on": True,
            "yt_manual": True, "yt_mail_on": False, "limit_ytm": 10}
# 17.11 v3: yt_manual — каждое письмо бота 5 сначала тебе с кнопками «✅ Отправить / ❌ Пропустить»;
# yt_mail_on — эксперту без Telegram письмо на почту (с твоего адреса MAIL_USER, до limit_ytm в день), по умолчанию выключено
# 17.11: бот hh.ru (hh_api) удалён по решению Егора; бот 5 «YouTube» — свой лимит limit_yt, не съедает лимит холодных
_SC ={"m": None, "v": dict(DEFAULTS)}

def bot_key(item, kind):
    """Какой из трёх ботов (кнопка пульта) отвечает за письмо: 1 вакансии (hot_on), 2 компании (biz_on), 3 партнёры (partners_on);
    обычные холодные экспертам — cold_on."""
    v = item.get("variant")
    if v == "BIZ": return "biz_on"
    if v == "PARTNER": return "partners_on"
    if v == "NICHE": return "niche_on"
    if v == "YT": return "yt_on"
    return "hot_on" if kind == "hot" else "cold_on"

def pick_allowed(q, kind, s):
    """Первое письмо в очереди, чей бот включён, — переставить в начало (отправка берёт q[0])."""
    for i, x in enumerate(q):
        if s.get(bot_key(x, kind), True):
            if i: q.insert(0, q.pop(i))
            return q[0]
    return None

# ---- 16.11: честная очередь между ботами. Раньше холодные (боты 2–3, эксперты) шли только при пустой очереди
# вакансий — она не пустеет никогда, и боты 2–3 не написали ни одного письма. Теперь отправка идёт по кругу.
SLOTS = ("hot", "BIZ", "PARTNER", "NICHE", "YT", "cold", "fu")    # порядок круга: каждый бот получает свою очередь
SLOT_BOT = {"hot": "hot_on", "BIZ": "biz_on", "PARTNER": "partners_on", "NICHE": "niche_on", "YT": "yt_on", "cold": "cold_on", "fu": "fu_on"}
SLOT_NAME = {"hot": "1️⃣ Вакансии", "BIZ": "2️⃣ Компании", "PARTNER": "3️⃣ Партнёры", "NICHE": "4️⃣ Мастера", "YT": "5️⃣ YouTube",
             "cold": "❄️ Эксперты", "fu": "🔁 Дожимы"}

def count_sent(d, item, kind):
    """Счётчик дня после отправки: YouTube — свой (limit_yt), остальные холодные — общий cold (limit_cold)."""
    k = "yt" if slot_of(item, kind) == "YT" else kind
    d[k] = d.get(k, 0) + 1
HEALTH_IDLE_H = 24        # включённый бот столько часов без единой отправки — уведомление с причиной

def slot_of(item, kind):
    """Из какого бота письмо: вакансии (вся очередь hot_q), 2 компании, 3 партнёры, эксперты."""
    if kind == "hot": return "hot"
    v = item.get("variant")
    return v if v in ("BIZ", "PARTNER", "NICHE", "YT") else "cold"

def first_index(q, kind, s, slot):
    """Индекс первого письма нужного бота (бот включён), или None. Очередь не трогает."""
    for i, x in enumerate(q):
        if slot_of(x, kind) == slot and s.get(bot_key(x, kind), True): return i
    return None

def next_slot(avail, last):
    """Следующий по кругу бот после last, у которого есть что отправить."""
    order = list(SLOTS)
    if last in order:
        i = order.index(last) + 1; order = order[i:] + order[:i]
    return next((k for k in order if k in avail), None)

def plan_send(st, s, d, now, lim_hot, warm, hot_hours=True, cold_hours=True):
    """Что отправить сейчас: ("hot"|"cold", письмо из q[0]) / ("fu", ник) / None.
    Каждый бот со своей очередью — кандидат, выбор по кругу SLOTS после st["last_kind"]. Лимиты: вакансии lim_hot,
    компании+партнёры+эксперты limit_cold, дожимы limit_fu. В мягком режиме (warm) — только вакансии."""
    cand = {}                                    # slot → ("hot"/"cold", индекс) или ("fu", ник, касание)
    if (s.get("hot_on", True) or s.get("biz_on", True)) and hot_hours and d["hot"] < lim_hot:
        st["hot_q"] = [x for x in st["hot_q"] if now - x["found"] < 48 * 3600
                       and not safety.shoot_job((x.get("ctx") or "").split("\nБио автора")[0])]   # уже в очереди до 16.11
        i = first_index(st["hot_q"], "hot", s, "hot")
        if i is not None: cand["hot"] = ("hot", i)
    # 17.11 (Егор): боты 4 «Мастера» и 5 «YouTube» пишут сразу после снятия ограничения, мягкий режим их не держит;
    # остальные холодные ждут. У YouTube свой дневной лимит limit_yt, у остальных — общий limit_cold.
    if cold_hours and st["cold_q"]:
        for sl in (("NICHE", "YT") if warm else ("BIZ", "PARTNER", "NICHE", "YT", "cold")):
            if sl == "YT":
                if d.get("yt", 0) >= int(s.get("limit_yt", 20)): continue
            elif d["cold"] >= int(s.get("limit_cold", 20)): continue
            i = first_index(st["cold_q"], "cold", s, sl)
            if i is not None: cand[sl] = ("cold", i)
    if not warm and cold_hours:
        if s.get("fu_on", True) and d["fu"] < int(s.get("limit_fu", 8)):
            for u, e in st["sent"].items():
                h = FOLLOWUP_HOT_H if e.get("kind") == "hot" else FOLLOWUP_COLD_H
                age = now - e.get("ts", now)
                if not e.get("replied") and not e.get("fu") and e.get("peer") and h * 3600 < age < 7 * 86400:
                    cand["fu"] = ("fu", u, None); break
            if "fu" not in cand:                 # касания на 3-й и 7-й день тем, кому назвали цену, а он молчит
                for u, e in st["sent"].items():
                    tm = touch_due(e, now)
                    if tm: cand["fu"] = ("fu", u, tm); break
    sl = next_slot(cand, st.get("last_kind"))
    if not sl: return None
    st["last_kind"] = sl
    if sl == "fu":
        _, u, tm = cand["fu"]
        if tm: st["sent"][u]["_tm"] = tm
        return ("fu", u)
    kind, i = cand[sl]
    q = st["hot_q"] if kind == "hot" else st["cold_q"]
    if i: q.insert(0, q.pop(i))                  # отправка берёт q[0]
    return (kind, q[0])

def undone_leads(st, now, days=14):
    """Тёплые без ответа: клиент ответил (не отказ), последнее сообщение в переписке — его, не старше days дней.
    Свежее первым. Диалоги, где ты дописал сам (thread «me» после его ответа), не попадают."""
    out = []
    for u, e in (st.get("sent") or {}).items():
        if not e.get("replied") or e.get("outcome") == "no" or e.get("crm") == "refused" or e.get("closed"): continue
        th = [m for m in (e.get("thread") or []) if m.get("text") not in HOLD_TEXTS]   # «Секундочку» — не ответ
        if not th or th[-1].get("who") != "them": continue
        if e.get("human_ts", 0) > e.get("last_in_ts", 0): continue      # ты ответил сам после его последнего сообщения
        ts = e.get("last_in_ts") or e.get("ts", now)
        if now - ts > days * 86400: continue
        out.append({"u": u, "display": e.get("display", ""), "last": th[-1].get("text", ""), "ts": ts, "days": int((now - ts) // 86400)})
    return sorted(out, key=lambda r: -r["ts"])

def health_problems(st, s, now, mods, warm=False, limited=False):
    """[(slot, причина)] — включённые боты, которые HEALTH_IDLE_H часов ничего не отправили. mods: {"BIZ": ошибка_импорта|""}.
    Отсчёт идёт с момента, как бот замечен включённым (health[slot]["since"]), — первые сутки после запуска не тревожим."""
    out, H = [], st.setdefault("health", {})
    d = st.get("day") or {}
    for sl in SLOTS:
        if not s.get(SLOT_BOT[sl], True):
            H.pop(sl, None); continue
        h = H.setdefault(sl, {}); h.setdefault("since", now)
        if mods.get(sl):
            out.append((sl, f"модуль не загрузился: {mods[sl]}")); continue
        if now - max(h.get("sent", 0), h["since"]) < HEALTH_IDLE_H * 3600: continue
        if limited: why = "аккаунт на паузе после ограничения Telegram"
        elif warm and sl not in ("hot", "NICHE", "YT"): why = "мягкий режим после ограничения: холодные и дожимы ждут 3 дня"
        elif sl == "fu": why = "нет молчунов, которым пора напомнить" if not st.get("sent") else f"лимит дожимов {s.get('limit_fu')} в день или некому напоминать"
        else:
            q = st.get("hot_q" if sl == "hot" else "cold_q") or []
            n = len(q) if sl == "hot" else sum(1 for x in q if slot_of(x, "cold") == sl)
            lim, used = ((s.get("limit_hot"), d.get("hot", 0)) if sl == "hot" else (s.get("limit_yt"), d.get("yt", 0)) if sl == "YT"
                         else (s.get("limit_cold"), d.get("cold", 0)))
            if not n: why = "поиск ничего не находит" + (f" (последняя находка {datetime.datetime.fromtimestamp(h['found']):%d.%m %H:%M})" if h.get("found") else " — ни одной находки")
            elif used >= int(lim or 0): why = f"в очереди {n} писем, но дневной лимит ({lim}) исчерпан"
            else: why = f"в очереди {n} писем, но они не уходят — смотри лог («НЕ ПИШУ», «сбой», «пропуск»)"
        out.append((sl, why))
    return out

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
import crm, autoreply, guard, zlib, human, safety
try: import analyst                      # разбор воронки и советы по ответам (нейросеть Groq + правила)
except Exception: analyst = None
try: import mail_watch                   # почта: клиент ответил письмом → нейросеть разбирает, дожимы в Telegram стоп
except Exception: mail_watch = None
try:                                     # поиск бизнесов (hh.ru + 2ГИС): локально — соседняя папка «Поиск бизнеса», в облаке — рядом
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(BASE)), "Поиск бизнеса"))
    import bizhunt
    BIZ_ERR = ""
except Exception as _e:
    bizhunt = None; BIZ_ERR = f"{type(_e).__name__}: {str(_e)[:120]}"   # не молчим: сторож пришлёт это в Telegram
try:                                     # бот 3: партнёры (SMM, таргетологи, агентства) — «Поиск партнёров\partners.py», в облаке рядом
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(BASE)), "Поиск партнёров"))
    import partners
    PAR_ERR = ""
except Exception as _e:
    partners = None; PAR_ERR = f"{type(_e).__name__}: {str(_e)[:120]}"
try:                                     # бот 4: мастера (стройка/ремонт, авто, премиум-ремесло) — «Поиск мастеров\niches.py», в облаке рядом
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(BASE)), "Поиск мастеров"))
    import niches
    NIC_ERR = ""
except Exception as _e:
    niches = None; NIC_ERR = f"{type(_e).__name__}: {str(_e)[:120]}"
try:                                     # бот 5: YouTube-эксперты → Telegram (17.11) — «Поиск на YouTube\yt_hunt.py», в облаке рядом
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(BASE)), "Поиск на YouTube"))
    import yt_hunt
    YT_ERR = ""
except Exception as _e:
    yt_hunt = None; YT_ERR = f"{type(_e).__name__}: {str(_e)[:120]}"

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
    if NOT_HOT_RX.search(low): return False        # по границе слова: «требуетсЯ МОНТАЖЕР» ≠ «я монтажер» (до 16.11 такие вакансии терялись)
    if safety.shoot_job(low): return False          # 16.11: оператор/видеограф/мобилограф/«съёмка + монтаж» — Егор не снимает
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

    fmt = ("Reels и Shorts" if re.search(r"reels|рилс|shorts|шортс|вертикал|tiktok|тикток", low) else
           "ролики для YouTube" if re.search(r"youtube|ютуб|подкаст|интервью", low) else
           "моушн-графику" if re.search(r"моуш|motion|анимац|after effects", low) else "короткие ролики")

    # 16.11: короткое первое письмо — 2 строки: деталь из его вакансии → что делаю + работы → один вопрос.
    # Без «боли», без перечня услуг, без бесплатного теста: люди принимали длинные письма за рассылку и жаловались.
    def build(sp):
        seen = sp("увидел, что ищете монтажёра", "увидел вашу вакансию", "прочитал вашу вакансию")
        m1 = f"{_head(sp, fn)}, {seen}" + (", " + ", ".join(detail) if detail else "")
        who = sp(f"Монтирую {fmt} удалённо", f"Я как раз монтирую {fmt}, работаю удалённо", f"Делаю {fmt}, удалённо")
        if shoot: who += sp(", снимаете вы на телефон", ", съёмка с вашей стороны")
        works = sp("работы тут", "примеры тут", "мои работы") + " " + PORTFOLIO.replace("https://", "")
        if case: works += sp(", похожий по теме ", ", по вашей нише ") + CASE.replace("https://", "")
        if price: who += sp(", ролик от 3 000 ₽", ", монтаж ролика от 3 000 ₽")
        ask = (sp("с какого числа нужен первый ролик?", "когда нужен первый ролик?") if detail else
               sp("сколько роликов в месяц планируете?", "какой объём в месяц?", "вакансия ещё открыта?"))
        return f"{m1}\n\n{who}, {works}\n{ask[:1].upper() + ask[1:]}"
    for _ in range(12):                              # пересобираем, пока текст не пройдёт фильтр «пишет человек»
        t = human.humanize(autoreply.voicefy(unique("hot", build)), allow_link=True)
        if not human.looks_bot(t, allow_link=True): break
    return t

def followup_text(entry):
    fn = first_name(entry.get("display", ""))
    def build(sp):
        hi = sp("добрый день", "здравствуйте")
        lead = f"{fn}, {hi}" if fn else hi.capitalize()
        if entry["kind"] == "hot":
            return lead + ", " + sp("подскажите, вакансия ещё актуальна? Если да, сделаю тест к вечеру, окей?",
                                    "вакансия ещё открыта? Могу сегодня сделать тест на 10–15 секунд, а там решим вопрос",
                                    "уточню, поиск ещё актуален? Если да, покажу тест на вашем материале")
        if entry.get("variant") == "BIZ":                   # компании: без «вашего канала» и «серии под ваш канал»
            return lead + ", " + sp("вернусь к своему сообщению про ролики) если видео сейчас не в планах, напишите «нет», больше не побеспокою",
                                    "коротко напомню, предложение в силе, могу бесплатно расписать 3 идеи роликов под вашу компанию, а если не актуально, так и напишите",
                                    "пишу ещё раз, последний) если ролики понадобятся, буду на связи, а пока могу бесплатно накидать пару идей под вас")
        if entry.get("variant") == "PARTNER":
            return lead + ", " + sp("вернусь к своему сообщению про партнёрство) если видео у ваших клиентов сейчас не в задачах, напишите «нет», больше не побеспокою",
                                    "коротко напомню про партнёрство по видео: ролики под вашим брендом, ваша наценка 20%. Если не актуально, просто ответьте «нет»",
                                    "пишу ещё раз, последний) если появится клиент, которому нужны Reels или видеокреативы, подхвачу, тест сделаю бесплатно")
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
        about = None
        if topic and re.match(r"(как|почему|что|зачем|когда|сколько|где|можно ли)\b", topic, re.I):
            about = "про то, " + topic[:1].lower() + topic[1:]          # пост своими словами, а не цитатой
        if about:
            obs = sp(f"прочитал ваш пост {about}", f"зацепил ваш пост {about}", f"наткнулся на ваш пост {about}")
        elif topic and len(topic) <= 38:
            obs = sp(f"прочитал ваш пост «{topic}»", f"зацепил ваш пост «{topic}»", f"наткнулся на ваш пост «{topic}»")
        elif topic:
            obs = sp("прочитал ваш последний пост, зацепило", "почитал канал, особенно зашёл последний пост", "наткнулся на ваш канал, прочитал пару последних постов")
        else:
            obs = sp("зашёл на ваш канал, понравилась подача", "почитал ваш канал, сильная подача")
        m1 = f"{_head(sp, fn)}, {obs}"
        # 16.11: коротко — наблюдение → кто я → один вопрос. Без «боли», бесплатных предложений и перечня услуг.
        if share < 0.15: m1 += sp(", видео в канале почти нет", ", а видео у вас почти нет")
        who2 = sp("Я Егор, монтирую короткие ролики для экспертов, вы снимаете на телефон, остальное на мне",
                  "Я Егор, делаю короткие ролики для экспертов, от вас только снять на телефон")
        ask2 = {"A": sp("Видео сейчас в планах?", "Ролики сейчас в планах?"),
                "B": sp("Пробовали короткие ролики для канала?", "Думали про Reels для канала?"),
                "C": sp("Серия из 5 роликов 19 000 ₽, актуально сейчас?", "Серия из 5 роликов стоит 19 000 ₽, интересно?")}[variant]
        return f"{m1}\n\n{who2}. {ask2}"
    return human.humanize(autoreply.voicefy(unique(f"cold-{variant}", build)))

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
           f"(лимиты: холодных {S()['limit_cold']}, дожимов {S()['limit_fu']})\n\n"
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
            st["day"] = {"date": today(), "hot": 0, "cold": 0, "fu": 0, "yt": 0, "by": {}}
        return st["day"]

    tick_last = [0.0]

    def process_inbox():
        """Команды из бота: быстрые ответы клиентам и проверка аккаунта. Выполняются вне очереди и лимитов."""
        if not web: return
        if CLOUD and hasattr(web, "tick_bot") and time.time() - tick_last[0] > 5:     # кнопки не ждут конца обхода каналов
            tick_last[0] = time.time()
            try: web.tick_bot()
            except Exception: pass
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
            elif cmd.get("cmd") in ("yt_ok", "yt_no", "yt_edit", "yt_ok_all"):   # бот 5, ручной режим: твоё решение по письму
                keys = cmd.get("keys") or [cmd.get("key", "")]
                for key in keys:
                    it = (st.get("yt_wait") or {}).pop(key, None)
                    if not it:
                        if cmd["cmd"] != "yt_ok_all": notify("Это письмо уже обработано или устарело", silent=True)
                        continue
                    if cmd["cmd"] == "yt_no":
                        bad.add(it["username"].lower()); log(f"YouTube: пропущен по решению Егора: {it['username']}"); continue
                    if cmd["cmd"] == "yt_edit" and (cmd.get("text") or "").strip():
                        it["text"] = re.sub(r"\s*\n\s*\n\s*", "\n\n", cmd["text"].strip()); it["pain"] = it.get("pain") or {}
                        it["ab"] = (it.get("ab") or "?:") + ".edit"               # A/B: письма, исправленные Егором
                    if it.get("mail"):
                        st.setdefault("yt", {}).setdefault("mail_q", []).append(it); log(f"YouTube: одобрено письмо на почту {it['username']}")
                    else:
                        it["ok"] = True; st["cold_q"].insert(0, it); log(f"YouTube: одобрено письмо @{it['username']}")
                save()
            elif cmd.get("cmd") == "update":                    # «🔄 Обновить бота»: сохраниться и выйти, следующий запуск — свежий код
                st["restart_now"] = 1; save(); log("облако: перезапуск по кнопке «Обновить бота»")
            elif cmd.get("cmd") == "cleardraft":
                try:
                    s_, info = web.open_chat(cmd["to"], st["sent"].get(cmd["to"], {}).get("peer"))
                    if s_ == "ok": web.clear_input(); log("черновик очищен:", cmd["to"])
                except Exception as ex: log("не очистил черновик", cmd["to"], str(ex)[:80])

    def why_idle(s, d, limited):
        if limited: return f"⛔ пауза до {st['limited_until'][11:16]} (защита аккаунта)"
        parts = []
        off = [n for k, n in (("hot_on", "1 вакансии"), ("biz_on", "2 компании"), ("partners_on", "3 партнёры"), ("niche_on", "4 мастера"), ("yt_on", "5 YouTube")) if not s.get(k, True)]
        if off: parts.append("выключены боты: " + ", ".join(off))
        if not s["hot_on"]: pass
        elif not in_hours(HOURS_HOT): parts.append(f"вакансии: ночь, продолжу в {HOURS_HOT[0]}:00 МСК")
        elif d["hot"] >= s["limit_hot"]: parts.append("вакансии: дневной лимит исчерпан")
        elif not st["hot_q"]: parts.append("вакансии: жду новые")
        if not (s["cold_on"] or s["fu_on"]): parts.append("холодные выключены")
        elif not in_hours(HOURS_COLD): parts.append(f"холодные: с {HOURS_COLD[0]}:00 до {HOURS_COLD[1]}:00 МСК")
        elif d["cold"] >= int(s["limit_cold"]) and (not s["fu_on"] or d["fu"] >= int(s["limit_fu"])):
            parts.append("холодные и дожимы: дневной лимит исчерпан")
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
                if time.time() - T0 > CLOUD_RUN_LIMIT or st.pop("restart_now", None):
                    log("облако: завершение (плановое или «Обновить бота»), состояние сохраняется"); save(); break
                if not web.want():
                    live(phase="выключен кнопкой ⏹", why="нажми ▶️ Запустить", next_send=0)
                    time.sleep(3); continue

            # ---- 1. горячие вакансии
            if now >= next_hot and s["hot_on"]:             # бот 1 выключен кнопкой — каналы вакансий не читаем
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
                        if fm:
                            text = human.humanize(fm["text"], allow_link=True)
                            bot_why = human.looks_bot(text, allow_link=True)
                            if bot_why:                         # ИИ написал «как бот» — берём человеческий шаблон
                                log(f"ИИ-письмо похоже на бота ({bot_why}), беру шаблон: @{u}"); fm = None
                        if fm: pass
                        else:                                   # бесплатный режим: фильтр + боли по нише без ИИ
                            ok, why = autoreply.rule_fit(post["text"])
                            if not ok:
                                log(f"не наш профиль, пропускаю @{u}: {why}"); continue
                            text = compose_hot(post, c["title"] or chn, dn, bio)
                        st["hot_q"].append({"username": u, "display": dn, "post": link, "found": now, "uniq": 1,
                                            "ctx": (f"Вакансия в канале «{c['title'] or chn}»:\n{post['text'][:1500]}\n"
                                                    f"Био автора в Telegram: {bio or 'нет'}")[:2000],
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
                    if hits >= 2:        # было 3, 14.11 снижено: больше новых каналов
                        st["hot_channels"].append(chn)
                        log(f"НОВЫЙ канал с вакансиями: @{chn} ({hits} вакансий за неделю)")
                save()

            # ---- 1в. «снежный ком»: каналы, на которые ссылаются / из которых репостят известные каналы вакансий.
            # Только публичные страницы t.me/s — аккаунт Telegram не участвует, поэтому можно часто (раз в 10 мин).
            if now >= st.get("snow_ts", 0) + 10 * 60:
                st["snow_ts"] = now
                hl = hot_list()
                src = hl[st.get("snow_i", 0) % len(hl)]; st["snow_i"] = st.get("snow_i", 0) + 1
                c = parse_channel(src)
                if c:
                    known = {x.lower() for x in hl} | {x.lower() for x in st["hot_checked"]}
                    cand = set(re.findall(r'tgme_widget_message_forwarded_from_name"[^>]*href="https://t\.me/([A-Za-z][A-Za-z0-9_]{4,31})', c["html"]))
                    cand |= set(TME_RE.findall(c["desc"]))
                    for p in c["posts"]:
                        if not is_hot(p["text"]): cand |= set(p["links"])   # в вакансиях ссылки — это контакты людей, их не трогаем
                    new_ch = 0
                    for chn in [x for x in cand if x.lower() not in known and not x.lower().endswith("bot")][:8]:
                        st["hot_checked"].append(chn)
                        cc = parse_channel(chn); time.sleep(random.uniform(1, 2))
                        if not cc: continue
                        fresh = [p for p in cc["posts"] if p["when"] and (datetime.datetime.now(datetime.timezone.utc) - p["when"]).days <= 7]
                        hits = sum(1 for p in fresh if is_hot(p["text"]))
                        if hits >= 2:
                            st["hot_channels"].append(chn); new_ch += 1
                            log(f"НОВЫЙ канал с вакансиями (через @{src}): @{chn} ({hits} вакансий за неделю)")
                    st["hot_checked"] = st["hot_checked"][-5000:]
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
                        if crm.is_autoack(snippet):                                # шаблонный автоответ («ознакомимся, вернёмся»): не лид, молчим, ждём живого ответа
                            e["last_in"] = snippet; e["last_in_ts"] = time.time(); e["auto_ack"] = True
                            e.setdefault("thread", []).append({"who": "them", "text": snippet, "auto": True})
                            log(f"автоответ HR от @{u}: не считаю ответом, не отвечаю — «{snippet[:60]}»")
                            continue
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
                        if s.get("hold_only", True):
                            # 15.11: диалоги ведёт Егор. Бот только пишет первое сообщение, а на ответ — максимум одно
                            # «скоро вернусь» (если Егор сам не ответил за 10–15 мин). На вопросы бот не отвечает.
                            e["handoff"] = True; e.pop("pending", None)
                            if verdict == crm.ST_REFUSED:
                                notify(f"❌ Отказ: {e.get('display', '')} (@{u})\n«{snippet}»", buttons=link, silent=True)
                                continue
                            hold_note = ""
                            if first and not e.get("human") and not e.get("hold_sent") and in_hours(AUTO_HOURS) and not safety.soft_no(snippet):
                                hd = random.uniform(*HOLD_DELAY)
                                e["hold_sent"] = 1
                                e["pending"] = {"text": random.choice(HOLD_TEXTS), "due": now + hd, "src": "hold", "bye": 1}
                                hold_note = (f"\n\n⏳ Если не ответишь сам за {int(hd // 60)} мин, напишу «{e['pending']['text']}». "
                                             f"Больше бот в этом чате ничего не пишет.")
                            head = "✅ СОГЛАСИЛСЯ" if verdict == crm.ST_AGREED else "🔥 ОТВЕТИЛ"
                            adv, btns = "", reply_buttons(u)
                            pn = e.get("pain") or {}
                            if pn.get("pain"):                            # что нейросеть поняла о нём ещё до диалога
                                adv += f"\n\n🎯 Его боль: {pn['pain']}" + (f"\n✅ Что предложить: {pn['solution']}" if pn.get("solution") else "")
                            if e.get("variant") == "YT" and verdict != crm.ST_REFUSED:   # бот 5: готовый тест и мини-разбор
                                if e.get("best_url"):
                                    adv += f"\n\n🎬 Пробный Shorts: на ПК запусти «Сделать тест Shorts.bat» и вставь {e['best_url']}"
                                if e.get("audit"):
                                    adv += "\n\n📄 Мини-разбор (отправь вместе с тестом):\n" + e["audit"]
                            notify(f"{head} {e.get('display', '')} (@{u})\n«{snippet}»{adv}{hold_note}\n\n{kind}: {e.get('source', '')}",
                                   buttons=btns)                          # сначала сразу уведомление — нейросеть его не задерживает
                            if analyst and s.get("advice_on", True):      # потом нейросеть разбирает ответ и предлагает, что написать
                                live(phase=f"разбираю ответ @{u}")
                                a_ = analyst.reply_advice(e, snippet)
                                if a_:
                                    e["advice"] = a_["reply"]; e["advice_ts"] = time.time(); save()
                                    notify(f"🧠 Совет по @{u}" + (f"\n{a_['insight']}" if a_["insight"] else "") +
                                           f"\n\n💡 Можно ответить:\n«{a_['reply']}»",
                                           buttons=[[{"text": "📨 Отправить этот ответ", "callback_data": f"adv:{u}"}],
                                                    [{"text": "💬 Открыть чат", "url": f"https://t.me/{u}"}]], silent=True)
                            continue
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
                    if p.get("src") == "hold" and (now - p["due"] > 15 * 60 or e.get("human")):
                        log(f"«секундочку» @{u} не шлю: опоздало или ты уже ответил сам"); save(); continue   # «секундочку» через 8 часов — странно
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
                        if p.get("src") == "hold":             # 16.11: ты не ответил вовремя — громкое напоминание
                            notify(f"⏰ {e.get('display', '')} (@{u}) ждёт твоего ответа — я написал «{p['text']}».\n"
                                   "Ответь в ближайшие минуты: тёплый клиент остывает за час.",
                                   buttons=[[{"text": "💬 Открыть чат", "url": f"https://t.me/{u}"}]])
                    elif rr.startswith("skip:ответил сам"):
                        e["human"] = True; e["human_ts"] = time.time()                      # диалог взял Егор: бот в нём больше не пишет
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
            warm_raw = bool(st.get("warm_from")) and (datetime.datetime.now() - datetime.datetime.fromisoformat(st["warm_from"])).days < WARM_DAYS
            if st.get("warm_from") and not warm_raw: st.pop("warm_from", None)
            warm = warm_raw and not s.get("warm_off")     # 17.11: Егор может снять мягкий режим кнопкой в «⚙️ Ещё» (на свой риск)
            # 16.11 (Егор: «делай»): лимит холодных стоял на 0 — боты 2–3 молчали. Один раз, когда ограничение и мягкий режим
            # позади: 0 → 10 в день (не больше: жалобы на рассылку). Если Егор сам поставил своё число — не трогаем.
            if not warm and not (st["limited_until"] and st["limited_until"] > datetime.datetime.now().isoformat()) \
                    and int(s.get("limit_cold", 0)) == 0 and not st.get("cold10_done"):
                st["cold10_done"] = today(); jsave(SETTINGS, dict(jload(SETTINGS, {}), limit_cold=10)); s = S(); save()
                notify("❄️ Ограничение и мягкий режим позади: поставил холодных 10 в день (было 0), чтобы боты 2 и 3 начали писать. "
                       "Больше не ставлю: на длинные письма жаловались. Поменять — ⚙️ Настройки.", silent=True)
            # 17.11 (Егор): тест бота 5 — пишут только «Мастера». Один раз выключаем отклики на вакансии (1), компании (2),
            # партнёров (3), hh (4) и холодные экспертам; лимит холодных 10 в день (он же лимит мастеров). Вернуть — пульт.
            if not st.get("masters_only_done"):
                cur = jload(SETTINGS, {})
                cur.update(hot_on=False, biz_on=False, partners_on=False, cold_on=False, niche_on=True, yt_on=True)
                cur.pop("hhapi_on", None); cur.pop("limit_hhapi", None)
                cur.setdefault("limit_yt", 20)
                if int(cur.get("limit_cold", s.get("limit_cold", 0)) or 0) == 0: cur["limit_cold"] = 10
                jsave(SETTINGS, cur); s = S(); st["masters_only_done"] = today(); st["cold10_done"] = today(); save()
                notify("🧪 Тест ботов 4 и 5: пишут только «Мастера» (до 10 в день) и «YouTube» (до 20 в день), сразу после снятия "
                       "ограничения. Отклики на вакансии, компании, партнёры и холодные экспертам выключены — включить в пульте.", silent=True)
            # 17.11 вечер (Егор: «запусти всех ботов»): тест «только 4 и 5» окончен — один раз включаем все боты.
            # Мягкий режим после бана остаётся (компании, партнёры и холодные экспертам ждут его конца), снять — «⚙️ Ещё».
            if st.get("masters_only_done") and not st.get("all_on_1711"):
                cur = jload(SETTINGS, {})
                cur.update(hot_on=True, cold_on=True, biz_on=True, partners_on=True, niche_on=True, yt_on=True, fu_on=True,
                           advice_on=True, pain_on=True)
                jsave(SETTINGS, cur); s = S(); st["all_on_1711"] = today(); save()
                notify("🚀 Все боты включены: 1 вакансии + эксперты, 2 компании, 3 партнёры, 4 мастера, 5 YouTube, дожимы."
                       + ("\n🟡 Пока идёт мягкий режим после бана, пишут вакансии, мастера и YouTube, остальные подключатся после него."
                          if warm else ""), silent=True)
            lim_hot = min(int(s["limit_hot"]), WARM_HOT) if warm else int(s["limit_hot"])
            gap = lambda: max(WARM_GAP if warm else 10, int(s["gap"])) * random.uniform(1.0, 1.15)
            if now >= next_send and not limited:
                job = plan_send(st, s, d, now, lim_hot, warm, in_hours(HOURS_HOT), in_hours(HOURS_COLD))   # по кругу между ботами
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
                        fu_txt = touch_text(e, tm) if tm else (e.get("fu_alt") or autoreply.followup_message(e) or "")   # бот 5: другой факт о канале
                        if not tm and (not fu_txt or human.looks_bot(human.humanize(fu_txt))): fu_txt = followup_text(e)   # ИИ-дожим «как бот» → шаблон
                        fu_txt = human.humanize(fu_txt)
                        try: r = web.send_followup(item, e["peer"], fu_txt, known_out=e.get("n_out", 1))
                        except Limited: raise
                        except Exception as ex: r = "fail:" + str(ex).splitlines()[0][:100]
                        if r == "replied":
                            e["replied"] = datetime.datetime.now().isoformat(timespec="minutes"); log("уже ответил:", item)
                            if tm: e[tm] = "skip"
                        elif r == "sent":
                            add_out(e, getattr(web, "last_parts", 1) or 1); d["fu"] += 1; fails = 0
                            d.setdefault("by", {})["fu"] = d.get("by", {}).get("fu", 0) + 1
                            st.setdefault("health", {}).setdefault("fu", {})["sent"] = now
                            if tm: e[tm] = today(); e[tm + "_ts"] = time.time(); log(f"КАСАНИЕ {tm} отправлено: @{item}")
                            else: e["fu"] = today(); log(f"ДОЖИМ отправлен: @{item}")
                            next_send = time.time() + gap()
                        else:
                            if tm: e[tm] = "skip"
                            else: e["fu"] = "skip"
                            log("дожим пропущен:", item, r)
                            if "не одно наше" in r: e["human"] = True; e["human_ts"] = time.time()        # Егор дописал в чат сам: бот в нём больше не пишет
                        save()
                    else:
                        q = st["hot_q"] if kind == "hot" else st["cold_q"]
                        risk = "" if mine(item["username"]) else "контакт второй половины команды"
                        risk = risk or safety.pre_send(kind, item, st["sent"])   # свои, боты, дубли между ботами, мусор в тексте
                        risk = risk or guard.check_before_send(kind, item)   # последняя проверка: тот ли человек и не против ли он
                        if risk:
                            q.pop(0); bad.add(item["username"].lower())
                            log(f"НЕ ПИШУ @{item['username']}: {risk}"); save()
                            next_send = time.time() + 5
                            continue
                        if analyst and s.get("pain_on", True) and item.get("ctx") and "pain" not in item:
                            live(phase=f"ищу боль @{item['username']} (нейросеть)")   # до диалога: вакансия, канал, био → боль + решение
                            pn = analyst.lead_pain(item, kind)
                            item["pain"] = pn or {}
                            if pn:
                                item["text"] = analyst.inject(item["text"], pn["line"])
                                log(f"боль @{item['username']}: {pn['pain'][:120]}")
                        item["text"] = human.humanize(item["text"], allow_link=(kind == "hot"))   # последний фильтр «пишет человек»
                        bw = human.looks_bot(item["text"], allow_link=(kind == "hot"))
                        if bw: log(f"⚠️ письмо @{item['username']} всё ещё похоже на бота: {bw}")
                        hs = st.setdefault("text_hashes", [])
                        item["text"] = safety.vary(item["text"], set(hs))    # один и тот же текст двум людям — признак спама
                        if safety.JUNK.search(item["text"]) or len(item["text"]) < 60:   # нейросеть/фильтр испортили текст
                            q.pop(0); log(f"НЕ ПИШУ @{item['username']}: текст испорчен после обработки"); save(); continue
                        try: r, peer = web.send_new(item["username"], item["text"])
                        except Limited: raise
                        except Exception as ex: r, peer = "fail:" + str(ex).splitlines()[0][:100], None
                        if r == "sent":
                            q.pop(0); count_sent(d, item, kind); fails = 0
                            sl_ = slot_of(item, kind)                 # счёт по каждому боту + отметка для сторожа
                            d.setdefault("by", {})[sl_] = d.get("by", {}).get(sl_, 0) + 1
                            st.setdefault("health", {}).setdefault(sl_, {})["sent"] = now
                            st["text_hashes"] = (st.get("text_hashes", []) + [safety.text_hash(item["text"])])[-500:]
                            st["sent"][item["username"]] = {"kind": kind, "peer": peer, "ts": now, "date": today(),
                                "display": item["display"], "variant": item.get("variant"),
                                "source": item.get("post") or item.get("source"), "text": item["text"],
                                "pain": item.get("pain") or {},
                                "n_out": getattr(web, "last_parts", 1) or 1}
                            for k_ in ("fu_alt", "ab", "audit", "best_url", "plat"):     # бот 5: второе письмо, A/B, мини-разбор
                                if item.get(k_): st["sent"][item["username"]][k_] = item[k_]
                            crm_sync()
                            log(f"ОТПРАВЛЕНО [{'вакансия' if kind == 'hot' else 'холодное'}] @{item['username']} — сегодня: "
                                f"вакансии {d['hot']}/{s['limit_hot']}, холодные {d['cold']}/{s['limit_cold']}, "
                                f"YouTube {d.get('yt', 0)}/{s.get('limit_yt', 20)}, дожимы {d['fu']}/{s['limit_fu']}")
                            next_send = time.time() + gap()
                            st["burst"] = st.get("burst", 0) + 1
                            if st["burst"] >= st.setdefault("burst_max", random.randint(*REST_EVERY)):   # перерыв, как у человека
                                rest = random.uniform(*REST_FOR)
                                next_send = time.time() + rest; st["burst"] = 0; st["burst_max"] = random.randint(*REST_EVERY)
                                log(f"перерыв {int(rest // 60)} мин после серии сообщений")
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

            # ---- 3a. сторож (16.11): включённый бот сутки без единой отправки — уведомление с причиной, раз в день на бота
            if now - st.get("health_ts", 0) > 30 * 60:
                st["health_ts"] = now
                try:
                    probs = health_problems(st, s, now, {"BIZ": "" if bizhunt else BIZ_ERR or "не найден",
                                                         "PARTNER": "" if partners else PAR_ERR or "не найден",
                                                         "NICHE": "" if niches else NIC_ERR or "не найден",
                                                         "YT": "" if yt_hunt else YT_ERR or "не найден"}, warm, limited)
                    hn = st.setdefault("health_notified", {})
                    fresh = [(sl_, w_) for sl_, w_ in probs if hn.get(sl_) != today()]
                    if fresh:
                        for sl_, _ in fresh: hn[sl_] = today()
                        notify("🩺 Сторож ботов: за сутки ни одного письма от\n" +
                               "\n".join(f"• {SLOT_NAME[sl_]} — {w_}" for sl_, w_ in fresh) +
                               "\n\nОстальные боты работают. Выключить бота — 🤖 Боты.", silent=True)
                    for sl_, w_ in probs: log(f"сторож: {SLOT_NAME[sl_]} — {w_}")
                    save()
                except Exception as ex: log("сторож: сбой", str(ex)[:100])

            # ---- 3a2. утренняя сводка «Не дожаты» (16.11): ответили, а последнее слово за ними — раз в день после 10:00 МСК
            if msk_now().hour >= 10 and st.get("undone_day") != today():
                st["undone_day"] = today()
                try:
                    rows = undone_leads(st, now)
                    if rows:
                        notify(f"🔥 Не дожаты: {len(rows)} — ответили тебе, а ты им ещё нет\n\n" +
                               "\n".join(f"• {r['display']} (@{r['u']}), {r['days']} дн. назад: «{r['last'][:90]}»" for r in rows[:10]) +
                               "\n\nКаждому: его задача → цена → вопрос «да или нет».",
                               buttons=[[{"text": f"💬 {r['display'][:24] or r['u']}", "url": f"https://t.me/{r['u']}"}] for r in rows[:6]])
                    save()
                except Exception as ex: log("сводка «не дожаты»: сбой", str(ex)[:100])

            # ---- 3b. бизнесы из «Поиск бизнеса\bizhunt.py» (hh.ru + 2ГИС) — готовые письма в общую холодную очередь
            st["cold_q"] = [x for x in st["cold_q"] if now - x.get("found", now) < 7 * 86400]   # письмо недельной давности уже не к месту
            nq = lambda v: sum(1 for x in st["cold_q"] + st["hot_q"] if x.get("variant") == v)   # у каждого бота свой потолок очереди
            if s.get("biz_on", True) and bizhunt and now - st.get("biz_ts", 0) > 15 * 60 and nq("BIZ") < 15:
                st["biz_ts"] = now
                live(phase="ищу бизнесы (hh.ru / 2ГИС)")
                try:
                    skip = lambda u: u.lower() in contacted or u.lower() in bad or not mine(u)
                    tgs = getattr(web, "search_channels", None) if web else None   # поиск каналов компаний из 2ГИС
                    for item in bizhunt.tg_step(st.setdefault("biz", {}), skip=skip, max_prepare=3, tg_search=tgs):
                        # контакт из текста вакансии («пишите в тг») = отклик на вакансию: лимит вакансий (40), а не холодных
                        (st["hot_q"] if item.get("invited") else st["cold_q"]).insert(0, item)
                        contacted.add(item["username"].lower())
                        st.setdefault("health", {}).setdefault("BIZ", {})["found"] = now
                        log(f"бизнес в очередь Telegram: @{item['username']} ({item.get('display', '')}) ← {item.get('source', '')}")
                except Exception as e:
                    log("поиск бизнеса не удался:", str(e)[:120])
                save()
            # ---- 3c. бот 3 «партнёры»: SMM-специалисты, таргетологи, агентства → партнёрский оффер (15% / под их брендом)
            if s.get("partners_on", True) and partners and now - st.get("partners_ts", 0) > 15 * 60 and nq("PARTNER") < 15:
                st["partners_ts"] = now
                live(phase="ищу партнёров (SMM, таргетологи)")
                try:
                    skip = lambda u: u.lower() in contacted or u.lower() in bad or not mine(u)
                    tgs = getattr(web, "search_channels", None) if web else None
                    for item in partners.partner_step(st.setdefault("partners", {}), skip=skip, tg_search=tgs, parse=parse_channel):
                        st["cold_q"].insert(min(1, len(st["cold_q"])), item)      # вперемешку с бизнесами, а не за ними
                        contacted.add(item["username"].lower())
                        st.setdefault("health", {}).setdefault("PARTNER", {})["found"] = now
                        log(f"партнёр в очередь Telegram: @{item['username']} ({item.get('display', '')}) ← {item.get('source', '')}")
                except Exception as e:
                    log("поиск партнёров не удался:", str(e)[:120])
                save()
            # ---- 3c-bis. бот 5 «мастера»: стройка/ремонт, авто, премиум-ремесло → короткое письмо под нишу (17.11)
            if s.get("niche_on", True) and niches and now - st.get("niches_ts", 0) > 15 * 60 and nq("NICHE") < 15:
                st["niches_ts"] = now
                live(phase="ищу мастеров (стройка, авто, ремесло)")
                try:
                    skip = lambda u: u.lower() in contacted or u.lower() in bad or not mine(u)
                    def _nsearch(q):
                        f = set()
                        if web:
                            try: f |= web.search_channels(q)
                            except Exception as e: log("поиск мастеров в Telegram не удался:", str(e)[:80])
                        if len(f) < 3: f |= search_engines(q)
                        return f
                    for item in niches.niche_step(st.setdefault("niches", {}), skip=skip, tg_search=_nsearch, parse=parse_channel):
                        st["cold_q"].insert(min(1, len(st["cold_q"])), item)
                        contacted.add(item["username"].lower())
                        st.setdefault("health", {}).setdefault("NICHE", {})["found"] = now
                        log(f"мастер в очередь Telegram: @{item['username']} ({item.get('display', '')}) ← {item.get('source', '')}")
                except Exception as e:
                    log("поиск мастеров не удался:", str(e)[:120])
                save()
            # ---- 3c-ter. бот 5 «YouTube»: эксперты с живыми каналами → письмо в Telegram, только у кого есть Telegram (17.11)
            yw = st.setdefault("yt_wait", {})
            for k_ in [k for k, v in yw.items() if now - v.get("found", now) > 3 * 86400]: yw.pop(k_)     # без ответа 3 дня — забыть
            if s.get("yt_on", True) and yt_hunt and now - st.get("yt_ts", 0) > 15 * 60 and nq("YT") + len(yw) < 25 and len(yw) < 12:
                st["yt_ts"] = now
                live(phase="ищу экспертов на YouTube и RuTube")
                try:
                    skip = lambda u: u.lower() in contacted or u.lower() in bad or not mine(u) or u.lower() in st.get("sent_mail", {})
                    for item in yt_hunt.yt_step(st.setdefault("yt", {}), skip=skip):
                        contacted.add(item["username"].lower())
                        st.setdefault("health", {}).setdefault("YT", {})["found"] = now
                        if item.get("mail") and not s.get("yt_mail_on", False):
                            log(f"YouTube: у эксперта только почта, а письма на почту выключены — пропускаю ({item.get('source', '')})"); continue
                        if s.get("yt_manual", True):          # п. 19: сначала тебе, отправка — только по кнопке
                            key = format(zlib.crc32(item["username"].lower().encode()), "x")
                            yw[key] = item
                            pn = item.get("pain") or {}
                            notify(f"🎥 5️⃣ {item.get('plat', 'YouTube')}: нашёл эксперта (балл {item.get('score', 0)})\n"
                                   f"{item.get('display', '')} {'📧 ' + item['mail'] if item.get('mail') else '@' + item['username']}\n"
                                   f"{item.get('source', '')}\n🎯 {pn.get('pain', '')}\n\n✉️ Письмо:\n{item['text']}\n\n"
                                   f"🔁 Через 2 дня, если промолчит:\n{item.get('fu_alt', '')}",
                                   buttons=[[{"text": "✅ Отправить", "callback_data": f"yt:ok:{key}"},
                                             {"text": "❌ Пропустить", "callback_data": f"yt:no:{key}"}],
                                            [{"text": "📺 Открыть канал", "url": item.get("source") or "https://youtube.com"}]])
                        elif item.get("mail"):
                            st["yt"].setdefault("mail_q", []).append(item)
                        else:
                            st["cold_q"].insert(min(1, len(st["cold_q"])), item)
                        log(f"YouTube-эксперт найден: {item['username']} ({item.get('display', '')}) ← {item.get('source', '')}"
                            f"{' — жду твоего решения' if s.get('yt_manual', True) else ''}")
                except Exception as e:
                    log("поиск на YouTube не удался:", str(e)[:120])
                save()
            # ---- 3c-quater. бот 5: письма на почту экспертам без Telegram (только если включено и почта подключена)
            mq = (st.get("yt") or {}).get("mail_q") or []
            if (mq and yt_hunt and s.get("yt_mail_on", False) and in_hours(HOURS_COLD) and not limited
                    and d.get("ytm", 0) < int(s.get("limit_ytm", 10)) and now - st.get("ytm_ts", 0) > 20 * 60):
                it = mq.pop(0); st["ytm_ts"] = now
                try: r = yt_hunt.send_mail(it["mail"], "Shorts для вашего канала", yt_hunt.mail_body(it))
                except Exception as ex: r = "fail:" + str(ex)[:80]
                if r == "sent":
                    d["ytm"] = d.get("ytm", 0) + 1
                    st.setdefault("sent_mail", {})[it["mail"].lower()] = {"ts": now, "date": today(), "source": it.get("source"),
                                                                           "ab": it.get("ab"), "display": it.get("display")}
                    log(f"ОТПРАВЛЕНО [почта, YouTube] {it['mail']} — сегодня {d['ytm']}/{s.get('limit_ytm', 10)}")
                else:
                    log(f"письмо на почту не ушло ({it['mail']}): {r}")
                save()
            # ---- 3d. почта (раз в 10 мин)
            if mail_watch and s.get("mail_on", True) and mail_watch.configured():
                try: mail_watch.step(st, notify, log, crm)
                except Exception as e: log("почта: сбой", str(e)[:120])
            biz_file = os.path.join(BASE, "biz_tg.json")
            if s["cold_on"] and os.path.exists(biz_file):
                try:
                    biz = jload(biz_file, [])
                    os.remove(biz_file)
                    for item in biz:
                        ul = item.get("username", "").lower()
                        if not ul or ul in contacted or ul in bad or not mine(ul): continue
                        st["cold_q"].insert(0, item); contacted.add(ul)
                        log(f"бизнес в очередь Telegram: @{item['username']} ({item.get('display', '')})")
                    save()
                except Exception as e:
                    log("biz_tg.json не прочитан:", str(e)[:80])

            # ---- 4. поиск холодных — в паузах между отправками
            if s["cold_on"] and sum(1 for x in st["cold_q"] if x.get("variant") not in ("BIZ", "PARTNER", "NICHE", "YT")) < 30:
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
                                    txt = autoreply.cold_message(ch, dn, niche, v)   # ИИ изучил канал → письмо лично ему
                                    if txt:
                                        txt = human.humanize(re.sub(r"[^\n]*(https?://|t\.me/)\S*[^\n]*", "", txt))   # без ссылок незнакомому
                                        if human.looks_bot(txt): log("ИИ-письмо похоже на бота:", human.looks_bot(txt)); txt = None
                                    txt = txt or compose_cold(ch, dn, niche, v)
                                    st.setdefault("health", {}).setdefault("cold", {})["found"] = now
                                    st["cold_q"].append({"username": u, "display": dn, "variant": v, "niche": niche, "uniq": 1,
                                                         "source": f"https://t.me/{name}",
                                                         "ctx": (f"Канал эксперта «{ch['title']}», {ch['subs']} подписчиков, средние просмотры {ch['avg_views']}, "
                                                                 f"постов с видео {int(100 * ch['videos'] / max(ch['n_posts'], 1))}%\nОписание: {ch['desc'][:400]}\n"
                                                                 "Последние посты:\n" + "\n".join("- " + p[:250] for p in ch["posts"][-5:]))[:2000],
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
                            limit_cold=min(int(s["limit_cold"]), 10), limit_fu=min(int(s["limit_fu"]), 5))
                if safe != s:
                    jsave(SETTINGS, safe)
                    msg += (f"\n\n🛡 Включил безопасный режим: пауза {safe['gap']} с, лимиты {safe['limit_hot']}/"
                            f"{safe['limit_cold']}, дожимов {safe['limit_fu']} в день. Повторное ограничение обычно дольше, а потом — навсегда. "
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
