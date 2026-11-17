# -*- coding: utf-8 -*-
"""Бот 5 «YouTube» (17.11): эксперты с живыми YouTube-каналами → письмо в Telegram (только тем, у кого есть Telegram).

Без ключа API: страница поиска YouTube (фильтр «каналы») → страница «О канале» (описание + ссылки) → RSS последних видео.
Работает внутри основного бота (autoclient.py, облако GitHub Actions), как niches/partners:
    yt_hunt.yt_step(st["yt"], skip) → готовые письма (variant "YT") → общая холодная очередь (свой лимит limit_yt, @SpamBot, guard, дожим).

Письмо: 2 сообщения (какое видео посмотрел → кто я + ОДИН вопрос), без ссылок, цен и бесплатного.
"""
import os, re, sys, json, time, random, datetime, urllib.request, urllib.parse
from xml.etree import ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(os.path.dirname(BASE), "Поиск бизнеса"), BASE):
    if p not in sys.path: sys.path.append(p)
import bizhunt as B          # log, tg_kind, TG_INFO, first_name

def log(*a): B.log("youtube:", *a)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SP_CHANNELS = "EgIQAg=="        # фильтр поиска YouTube: только каналы

# эксперты, которые уже снимают: им нужен монтаж длинных видео и нарезка Shorts
QUERIES = ["ипотечный брокер", "риелтор", "юрист банкротство", "психолог", "нутрициолог", "косметолог", "финансовый консультант",
           "налоговый консультант", "стоматолог", "семейный юрист", "эксперт по недвижимости", "дизайнер интерьера", "фитнес тренер",
           "бухгалтер для бизнеса", "инвестиции для начинающих", "кредитный брокер", "агент недвижимости Москва", "психотерапевт",
           "врач диетолог", "юрист по недвижимости", "адвокат", "риелтор Санкт-Петербург", "коуч", "логопед", "гинеколог блог",
           "пластический хирург", "трихолог", "остеопат", "репетитор", "эксперт по маркетплейсам",
           "ипотека 2026", "купить квартиру советы", "новостройки обзор риелтор", "банкротство физических лиц юрист",
           "развод раздел имущества юрист", "психолог отношения", "семейный психолог", "налоги ИП", "бухгалтер ИП",
           "диетолог похудение", "эндокринолог", "кардиолог", "детский психолог", "финансовая грамотность",
           "недвижимость Дубай риелтор", "загородная недвижимость", "юрист ДТП", "автоюрист", "трудовой юрист", "наследство юрист"]
TOPICS = [(r"ипоте[кч]", "про ипотеку"), (r"кредит", "про кредиты"), (r"недвижим|риелт|риэлт|квартир|новостройк|(?<![а-яё])жк(?![а-яё])", "про недвижимость"),
          (r"банкрот|долг", "про банкротство"), (r"юрист|адвокат|правов|закон|(?<![а-яё])суд|(?<![а-яё])дтп|наследств|развод", "про право"), (r"психолог|психотерап", "про психологию"),
          (r"нутрицио|диетолог|питани", "про питание"), (r"косметолог|кож[аиу]|уход", "про уход"), (r"стоматолог|зуб", "про зубы"),
          (r"налог|бухгалт", "про налоги"), (r"инвест|финанс", "про финансы"), (r"интерьер", "про интерьеры"), (r"фитнес|трениров", "про тренировки"),
          (r"логопед|речь|речев", "про речь"), (r"гинеколог|беремен", "про женское здоровье"), (r"хирург|пластик", "про пластику"),
          (r"трихолог|волос", "про волосы"), (r"остеопат|осанк|спин[аеуы]", "про здоровье спины"), (r"врач|здоровь|лечени|кардиолог|эндокрин|невролог", "про здоровье"),
          (r"репетитор|егэ|огэ", "про подготовку к экзаменам"), (r"маркетплейс|wildberries|ozon|вб\b", "про маркетплейсы"),
          (r"коуч|цели|мышлени", "про мышление")]

SUBS = (200, 100000)
FRESH_DAYS = 30
STOP_TITLE = re.compile(r"новост|news|tv\b|тв\b|канал о|министер|администрац|вестник|журнал|медиа|подкаст студи|"
                        r"монтаж|видеомонтаж|рилсмейк|видеограф|продакшн|production|"
                        r"курс|школа|академи|обучени|университет|колледж|клиника|центр\b|агентств|компани|ооо|холдинг", re.I)
COMPETITOR = re.compile(r"монтаж[её]р|видеомонтаж|рилсмейкер|мобилограф|видеограф|моушн|motion|smm", re.I)
SELLS = re.compile(r"консультац|запис|услуг|клиент|обращ|напиши|пишите|заявк|помогу|помогаю|разбор|сопровожд|стоимост|прайс|связ", re.I)
FIRST_PERSON = re.compile(r"(?<![а-яё])(я|мне|меня|мой|моя|мои|помогаю|помогу|расскажу|рассказываю|работаю)(?![а-яё])", re.I)
TG_RX = re.compile(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_/])|(?<![\w.@])@([A-Za-z][A-Za-z0-9_]{4,31})(?![\w.])")
JUNK = {"joinchat", "share", "addstickers", "proxy", "iv", "contact", "telegram", "durov", "username", "gmail", "mail", "yandex"}

# ---------------------------------------------------------------- сеть
def get(url, timeout=25):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9", "Cookie": "SOCS=CAI; CONSENT=YES+"})
    return urllib.request.urlopen(r, timeout=timeout).read().decode("utf-8", "replace")

def initial_data(html):
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html or "", re.S)
    try: return json.loads(m.group(1)) if m else None
    except Exception: return None

def walk(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key: yield v
            yield from walk(v, key)
    elif isinstance(o, list):
        for v in o: yield from walk(v, key)

def _txt(x):
    if isinstance(x, str): return x
    if isinstance(x, dict): return x.get("simpleText") or x.get("content") or "".join(r.get("text", "") for r in x.get("runs", []))
    return ""

def parse_count(s):
    """«4,82 тыс. подписчиков» → 4820, «1,2 млн» → 1200000, «135 подписчиков» → 135; не число → None."""
    s = (s or "").replace(" ", " ").replace(" ", " ").lower()
    m = re.search(r"(\d[\d ]*(?:[.,]\d+)?)\s*(тыс|млн|k|m)?", s)
    if not m: return None
    n = float(m.group(1).replace(" ", "").replace(",", "."))
    mul = {"тыс": 1e3, "k": 1e3, "млн": 1e6, "m": 1e6}.get(m.group(2) or "", 1)
    return int(n * mul)

def search(q):
    """Каналы из поиска YouTube: [{id, title, subs, snippet}]."""
    h = get("https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": q, "sp": SP_CHANNELS, "hl": "ru", "gl": "RU"}))
    out = []
    for c in walk(initial_data(h), "channelRenderer"):
        cid = c.get("channelId")
        if not cid: continue
        # YouTube местами кладёт число подписчиков в videoCountText, а в subscriberCountText — @ник
        cnt = next((t for t in (_txt(c.get("subscriberCountText")), _txt(c.get("videoCountText"))) if "подпис" in t.lower()), "")
        out.append({"id": cid, "title": _txt(c.get("title")), "subs": parse_count(cnt), "snippet": _txt(c.get("descriptionSnippet"))})
    return out

def about(cid):
    """Страница «О канале»: описание, ссылки (как показаны: «t.me/xxx»), подписчики."""
    vm = next(walk(initial_data(get(f"https://www.youtube.com/channel/{cid}/about?hl=ru")), "aboutChannelViewModel"), None)
    if not vm: return None
    links = [_txt((l.get("channelExternalLinkViewModel") or {}).get("link")) for l in vm.get("links", [])]
    return {"desc": vm.get("description") or "", "links": [x for x in links if x], "subs": parse_count(vm.get("subscriberCountText"))}

NS = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/", "yt": "http://www.youtube.com/xml/schemas/2015"}
def videos(cid):
    """Последние 15 видео из RSS: [{id, title, when (UTC), desc, shorts, views}] — свежие первыми."""
    root = ET.fromstring(get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
    out = []
    for e in root.findall("a:entry", NS):
        try: when = datetime.datetime.fromisoformat(e.findtext("a:published", "", NS))
        except ValueError: continue
        st_ = e.find("m:group/m:community/m:statistics", NS)
        link = e.find("a:link", NS)
        out.append({"id": e.findtext("yt:videoId", "", NS), "title": e.findtext("a:title", "", NS), "when": when,
                    "desc": e.findtext("m:group/m:description", "", NS) or "",
                    "shorts": "/shorts/" in (link.get("href", "") if link is not None else ""),
                    "views": int(st_.get("views", 0)) if st_ is not None and (st_.get("views") or "").isdigit() else None})
    return sorted(out, key=lambda v: v["when"], reverse=True)

VIEWS_RX = re.compile(r"(\d[\d  ]*(?:[.,]\d+)?\s*(?:тыс\w*\.?|млн\w*\.?)?)\s*просмотр", re.I)
def shorts_tab(cid):
    """Вкладка Shorts: просмотры последних Shorts (до ~48; сколько их вообще есть). [] — Shorts на канале нет."""
    d = initial_data(get(f"https://www.youtube.com/channel/{cid}/shorts?hl=ru"))
    out = []
    for s in walk(d, "shortsLockupViewModel"):
        m = list(VIEWS_RX.finditer(s.get("accessibilityText") or ""))
        if m: out.append(parse_count(m[-1].group(1)))
    return [v for v in out if v is not None]

def heatmap(vid):
    """График «самые пересматриваемые» (100 точек 0..1) и длина видео в секундах. YouTube показывает его только
    у видео с большим числом просмотров — у небольших экспертов чаще всего нет → (None, длина)."""
    w = get(f"https://www.youtube.com/watch?v={vid}&hl=ru")
    ln = re.search(r'"lengthSeconds":"(\d+)"', w)
    ln = int(ln.group(1)) if ln else 0
    for m in walk(initial_data(w), "macroMarkersListEntity"):
        ml = m.get("markersList") or {}
        if ml.get("markerType") == "MARKER_TYPE_HEATMAP" and len(ml.get("markers") or []) >= 20:
            return [float(x.get("intensityScoreNormalized") or 0) for x in ml["markers"]], ln
    return None, ln

def heat_points(h, length):
    """Из графика пересмотров: самый пересматриваемый момент (сек) и где зрители начинают проматывать (сек).
    Начало и конец не считаем: в начале график всегда высокий, в конце всегда падает."""
    if not h or length < 60: return None
    n = len(h); a, b = max(1, n // 20), n - n // 10
    sm = [sum(h[max(0, i - 1):i + 2]) / len(h[max(0, i - 1):i + 2]) for i in range(n)]      # сгладить шум
    peak = max(range(a, b), key=lambda i: sm[i])
    base = sum(sm[a:b]) / (b - a)
    drop = next((i for i in range(a, b) if sm[i] < 0.5 * sm[a]), None)
    return {"peak": int(peak * length / n), "peak_x": round(sm[peak] / base, 1) if base else 0,
            "drop": int(drop * length / n) if drop is not None else None}

def mmss(sec): return f"{sec // 60}:{sec % 60:02d}"

def num(n):
    """4720 → «4,7 тыс.», 343 → «340», 12 → «12»: как человек округляет на глаз."""
    if n >= 1000:
        s = f"{n / 1000:.1f}".rstrip("0").rstrip(".") if n < 10000 else str(round(n / 1000))
        return s.replace(".", ",") + " тыс."
    return str(round(n, -1)) if n >= 100 else str(n)

def median(xs):
    xs = sorted(xs); k = len(xs)
    return 0 if not k else (xs[k // 2] if k % 2 else (xs[k // 2 - 1] + xs[k // 2]) / 2)

ALIVE_DAYS, ALIVE_MIN = 14, 3          # живой канал: последнее видео ≤14 дней назад и ≥3 видео за 60 дней

def analyze(vids, subs, sh_views, now=None, on_topic=lambda v: True):
    """Разбор канала по открытым цифрам → боль, которую видно со стороны, или None (тогда не пишем).
    Настоящее удержание видно только владельцу в YouTube Studio, поэтому смотрим то, что видит любой зритель:
    есть ли Shorts, сколько они набирают против длинных и подписчиков, не просели ли просмотры.
    vids — RSS (свежие первыми), sh_views — просмотры с вкладки Shorts. Возвращает {kind, ...цифры} или {"skip": причина}."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age = lambda v: (now - v["when"]).days
    if not vids or age(vids[0]) > ALIVE_DAYS: return {"skip": "мёртвый канал"}
    if sum(1 for v in vids if age(v) <= 60) < ALIVE_MIN: return {"skip": "редко выходят видео"}
    ripe = [v for v in vids if age(v) >= 3 and v.get("views") is not None]        # свежим 1–2 дня ещё рано судить
    longs = [v for v in ripe if not v["shorts"]]
    shorts = [v for v in ripe if v["shorts"]]
    ml = median([v["views"] for v in longs]); ms = median([v["views"] for v in shorts] or sh_views[:10])
    best = max([v for v in longs if on_topic(v)], key=lambda v: v["views"], default=None)    # лучшее — только по теме эксперта
    r = {"subs": subs, "med_long": int(ml), "med_short": int(ms), "n_long": len(longs), "n_short": len(shorts) or len(sh_views)}
    if best and ml and best["views"] >= 2 * ml and best["views"] >= 300:
        r["best"] = {"id": best["id"], "title": best["title"], "views": best["views"], "x": round(best["views"] / ml, 1)}
    recent_sh = [v for v in vids if v["shorts"] and age(v) <= 30]
    # 1) длинные выходят, а Shorts нет — самое очевидное: нарезка из того, что уже снято
    if len(longs) >= 3 and not recent_sh:
        return dict(r, kind="no_shorts", never=not sh_views)
    # 2) Shorts есть, но не работают: вдвое хуже длинных или меньше 5% подписчиков
    if (len(shorts) >= 3 or len(sh_views) >= 5) and ms < 2000 and ((ml and ms < 0.5 * ml) or (subs and ms < 0.05 * subs)):
        return dict(r, kind="weak_shorts")
    # 3) просмотры просели: последние 3 вдвое ниже прежних
    for grp in (shorts, longs):
        if len(grp) >= 6:
            new, old = median([v["views"] for v in grp[:3]]), median([v["views"] for v in grp[3:]])
            if old >= 200 and new < 0.5 * old:
                return dict(r, kind="drop", new=int(new), old=int(old), of="shorts" if grp is shorts else "long")
    return {"skip": "с роликами и так всё нормально"}

# ---------------------------------------------------------------- отбор
def tg_handles(*texts):
    """Ники Telegram из ссылок и текста (по порядку, без повторов и ботов)."""
    out = []
    for t in texts:
        for m in TG_RX.finditer(t or ""):
            u = m.group(1) or m.group(2)
            if m.group(2) and not re.search(r"(?i)t\.me|телеграм|telegram|tg\b|тг\b", (t or "")[max(0, m.start() - 40):m.start()]) \
                    and not re.search(r"(?i)телеграм|telegram", t or ""):
                continue        # «@ник» без упоминания Telegram рядом — скорее Instagram
            if u.lower() in JUNK or u.lower().endswith("bot") or u.lower() in [x.lower() for x in out]: continue
            out.append(u)
    return out

def is_expert(title, desc, vids):
    """Живой эксперт сам за себя: не новости/школа/клиника/монтажёр, говорит от первого лица или продаёт консультации."""
    if STOP_TITLE.search(title or "") or COMPETITOR.search(title or ""): return False
    txt = (desc or "") + " " + " ".join(v["title"] for v in vids[:10])
    return bool(SELLS.search(txt)) or len(FIRST_PERSON.findall(txt)) >= 2

def resolve_person(handles, skip):
    """Первый ник, которому можно написать в личку. Если ссылка ведёт на канал — ищем ник владельца в его описании."""
    tried = 0
    for u in handles:
        if tried >= 4: break
        if skip(u): continue
        tried += 1
        k = B.tg_kind(u); time.sleep(0.5)
        if k == "person": return u
        if k == "channel":
            desc = (B.TG_INFO.get(u.lower()) or {}).get("desc", "")
            for o in tg_handles(desc.replace("@", " t.me/")):
                if o.lower() == u.lower() or skip(o): continue
                if B.tg_kind(o) == "person": return o
                time.sleep(0.5)
    return ""

def topic(text):
    for rx, w in TOPICS:
        if re.search(rx, text or "", re.I): return w
    return ""

def short_title(t):
    """Название видео для письма: без хэштегов, эмодзи и КАПСА, короче 40 знаков (длинные цитаты human.py вырезает —
    человек их не цитирует; тогда в письме «видео про …»); плохое — пусто."""
    t = re.sub(r"#\S+", "", t or "")
    t = re.sub(r"[^\w\s.,:;!?\"'()\-–—%₽]", "", t).strip(" -–—|.,!?")
    t = re.sub(r"\s+", " ", t).replace('"', "")
    if len(t) < 10 or len(t) >= 40 or sum(ch.isupper() for ch in t) > 0.5 * sum(ch.isalpha() for ch in t): return ""
    return t

def template(c):
    """3 сообщения, как пишет Егор с телефона: 1) что увидел на канале (боль цифрами со стороны),
    2) кто я и как это исправляется, 3) золотая кнопка: пробный Shorts на 15 с из их же видео + ОДИН вопрос.
    Без ссылок, цен, «бесплатно» и восклицаний. c["an"] — результат analyze()."""
    R = random.choice
    an = c.get("an") or {}
    fn = B.first_name(c.get("who", ""))
    hi = f"{fn}, {R(['добрый день', 'здравствуйте'])}" if fn else R(["Добрый день", "Здравствуйте"])
    tp = topic(c.get("title", "") + " " + c.get("desc", ""))
    yt = f"ваш YouTube {tp}".strip() if tp else "ваш YouTube"
    look = R([f"посмотрел {yt}", f"наткнулся на {yt}, посмотрел несколько роликов"])
    k = an.get("kind")
    if k == "no_shorts":
        a = f"{hi}, {look}, длинные видео выходят регулярно, а " + ("Shorts на канале нет совсем" if an.get("never")
                                                                   else "Shorts за последний месяц ни одного")
        fix = R(["из одного длинного видео обычно получается 3-5 коротких, и они приводят на канал новых людей, которых длинные сами не соберут",
                 "короткие сейчас главный источник новых зрителей, а у вас для них уже всё снято, нужно только вырезать и смонтировать"])
    elif k == "weak_shorts":
        if an.get("med_long") and an["med_short"] < 0.5 * an["med_long"]:
            a = f"{hi}, {look}, Shorts у вас набирают около {num(an['med_short'])} просмотров, а длинные видео около {num(an['med_long'])}"
        else:
            a = f"{hi}, {look}, Shorts набирают около {num(an['med_short'])} просмотров при {num(an['subs'])} подписчиках"
        fix = R(["обычно короткие теряют зрителя в первые 1-2 секунды, когда нет цепляющего начала, это исправляется монтажом, переснимать ничего не нужно",
                 "чаще всего короткий ролик теряет зрителя на первых секундах и на паузах, это лечится монтажом, а не новой съёмкой"])
    elif k == "drop":
        what = "последние Shorts" if an.get("of") == "shorts" else "последние ролики"
        a = f"{hi}, {look}, {what} набирают около {num(an['new'])} просмотров, а до этого было около {num(an['old'])}"
        fix = R(["часто дело не в теме, а в первых секундах и темпе, это исправляется монтажом",
                 "обычно просадка из-за начала и темпа, а не из-за темы, и это исправляется монтажом"])
    else:
        a = f"{hi}, {look}"
        fix = "из длинных видео можно делать короткие, и они приводят на канал новых людей"
    b = f"Я Егор, монтирую Shorts для экспертов, {fix}"
    best, ht = an.get("best") or {}, an.get("heat") or {}
    bt = short_title(best.get("title", "")) or short_title(c.get("video", ""))
    if ht.get("peak") and bt:
        b += f". У видео «{bt}» самый пересматриваемый момент на {mmss(ht['peak'])}, с него бы и начал"
    elif best and short_title(best.get("title", "")):
        x = round(best["x"])
        b += f". Начал бы с видео «{bt}», оно набрало {num(best['views'])}, это в {x} {'раз' if x >= 5 else 'раза'} больше обычного"
    src = f"из видео «{bt}»" if bt else ("из вашего видео " + topic(c.get("video", ""))).strip() if topic(c.get("video", "")) else "из одного вашего видео"
    if k == "weak_shorts":
        btn = R([f"Могу переделать один ваш Shorts или сделать новый на 15 секунд {src}, чтобы сравнили. Прислать?",
                 f"Могу сделать пробный Shorts на 15 секунд {src}, сравните со своими. Прислать?"])
    else:
        btn = R([f"Могу сделать пробный Shorts на 15 секунд {src}, посмотрите, как это выглядит у вас на канале. Прислать?",
                 f"Могу сделать пробный Shorts на 15 секунд {src}, без обязательств, просто посмотрите. Прислать?"])
    text = f"{a}\n{b}\n{btn}"
    try:
        import human
        text = human.humanize(text)
    except Exception:
        pass
    return text

PAIN_TXT = {"no_shorts": ("длинные видео выходят, а Shorts нет: теряет новых зрителей", "нарезка Shorts из его длинных видео, начать с пробного на 15 с"),
            "weak_shorts": ("Shorts набирают мало (теряют зрителя в первые секунды)", "переделать начало и темп Shorts, пробный на 15 с для сравнения"),
            "drop": ("просмотры последних роликов просели вдвое", "монтаж начала и темпа, пробный Shorts на 15 с")}

def item_of(c):
    an = c.get("an") or {}
    pn = PAIN_TXT.get(an.get("kind"))
    facts = (f"Shorts медиана {an.get('med_short')}, длинные медиана {an.get('med_long')}, подписчиков {an.get('subs')}"
             + (f", лучшее видео «{an['best']['title']}» {an['best']['views']} (в {an['best']['x']} раза выше обычного)" if an.get("best") else "")
             + (f", самый пересматриваемый момент {mmss(an['heat']['peak'])}" if (an.get("heat") or {}).get("peak") else "")) if an else ""
    return {"username": c["username"], "invited": False, "found": time.time(), "post": "", "display": c.get("who") or c.get("title") or "",
            "variant": "YT", "niche": "youtube-эксперт", "uniq": 1, "source": c["source"],
            # боль уже в письме (по цифрам канала) — нейросеть свою не дописывает; Егор увидит её в уведомлении об ответе
            "pain": {"pain": f"{pn[0]} ({facts})"[:300], "solution": pn[1]} if pn else {},
            "ctx": (f"YouTube-канал эксперта: {c.get('title') or ''}\nПодписчиков: {c.get('subs', '')}\n"
                    f"Разбор канала: {facts}\nВидео: {c.get('video', '')}\nОписание: {c.get('desc', '')}")[:2000],
            "text": re.sub(r"\s*\n\s*", "\n\n", c["text"].strip())}

def check_channel(ch, skip):
    """Канал из поиска → кандидат или None (с причиной в логе)."""
    if ch["subs"] is not None and not (SUBS[0] <= ch["subs"] <= SUBS[1]): return None
    if STOP_TITLE.search(ch["title"]) or COMPETITOR.search(ch["title"]): return None
    ab = about(ch["id"]); time.sleep(random.uniform(1, 2))
    if not ab: return None
    subs = ab["subs"] or ch["subs"] or 0
    if not (SUBS[0] <= subs <= SUBS[1]): return None
    handles = tg_handles(" ".join(ab["links"]), ab["desc"])
    vids = []
    try: vids = videos(ch["id"]); time.sleep(random.uniform(0.5, 1.5))
    except Exception: pass
    if not handles:      # в описании канала нет — ищем в описаниях свежих видео
        handles = tg_handles(*[v["desc"] for v in vids[:3]])
    if not handles: return why("нет Telegram")
    if not vids: return why("мёртвый канал")
    if not is_expert(ch["title"], ab["desc"], vids): return why("не эксперт")
    # канал по экспертной теме: тема в названии/описании или хотя бы в 2 из 10 последних видео (не влоги и ASMR)
    if not topic(ch["title"] + " " + ab["desc"]) and sum(1 for v in vids[:10] if topic(v["title"])) < 2: return why("не по теме")
    # разбор: пишем только если со стороны видно, что нужен монтаж коротких (без боли — не пишем)
    sh = []
    try: sh = shorts_tab(ch["id"]); time.sleep(random.uniform(0.5, 1.5))
    except Exception: pass
    an = analyze(vids, subs, sh, on_topic=lambda v: bool(topic(v["title"])))
    if an.get("skip"): return why(an["skip"])
    if an.get("best"):                     # у лучшего видео — график «самые пересматриваемые», если YouTube его показывает
        try:
            h, ln = heatmap(an["best"]["id"]); time.sleep(random.uniform(0.5, 1.5))
            hp = heat_points(h, ln)
            if hp: an["heat"] = hp
        except Exception: pass
    u = resolve_person(handles, skip)
    if not u: return why("Telegram не личный")
    # в письмо — только видео по теме: короткое название в кавычках, иначе «видео про …»; не по теме — не цитируем
    on = [v for v in vids if not v["shorts"] and topic(v["title"])] or [v for v in vids if topic(v["title"])]
    long_v = next((v for v in on if short_title(v["title"])), on[0] if on else {"title": ""})
    WHY[an["kind"]] = WHY.get(an["kind"], 0) + 1
    return {"username": u, "title": ch["title"], "subs": subs, "desc": ab["desc"][:400], "video": long_v["title"], "an": an,
            "has_shorts": any(v["shorts"] for v in vids) or bool(sh), "source": f"https://www.youtube.com/channel/{ch['id']}",
            "who": (B.TG_INFO.get(u.lower()) or {}).get("title", "")}

WHY = {}          # счёт причин за шаг (без имён) → st["yt"]["why"] → DIAG
def why(r):
    WHY[r] = WHY.get(r, 0) + 1
    return None

def yt_step(ys, skip=lambda u: False, max_new=3, max_check=10):
    """Один шаг (autoclient зовёт раз в 15 мин): поиск по очередному запросу → проверить до max_check каналов → до max_new писем.
    ys — st["yt"] в state.json основного бота."""
    for k, v in (("frontier", []), ("seen", []), ("qi", 0), ("pending", []), ("why", {})):
        ys.setdefault(k, v)
    ys["pending"] = [c for c in ys["pending"] if c.get("an")]       # кандидаты старой версии (без разбора) не пишем
    WHY.clear()
    seen = set(ys["seen"])
    if len(ys["frontier"]) < max_check:
        q = QUERIES[ys["qi"] % len(QUERIES)]; ys["qi"] += 1
        try:
            found = [c for c in search(q) if c["id"] not in seen and c["id"] not in {x["id"] for x in ys["frontier"]}]
            ys["frontier"] += found; log(f"поиск «{q}»: новых каналов {len(found)}")
        except Exception as e:
            log("поиск не удался:", str(e)[:80])
    cands = []
    for _ in range(max_check):
        if not ys["frontier"] or len(cands) >= max_new: break
        ch = ys["frontier"].pop(0)
        if ch["id"] in seen: continue
        seen.add(ch["id"])
        try:
            c = check_channel(ch, skip)
            if c: cands.append(c)
        except Exception as e:
            log("канал не проверился:", str(e)[:80])
    ys["seen"] = list(seen)[-10000:]; ys["frontier"] = ys["frontier"][:200]
    for k, v in WHY.items(): ys["why"][k] = ys["why"].get(k, 0) + v
    pend = {c["username"].lower(): c for c in ys["pending"] + cands}
    out = []
    for ul, c in list(pend.items()):
        if len(out) >= max_new: break
        del pend[ul]
        if skip(c["username"]): continue
        c["text"] = template(c)
        out.append(item_of(c))
        log(f"эксперт @{c['username']} ← {c['source']} ({c['subs']} подп., боль: {c['an'].get('kind')})")
    ys["pending"] = list(pend.values())[:30]
    return out

if __name__ == "__main__":        # локальная проверка без отправки: python yt_hunt.py [шагов]
    ys = {}
    for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 2):
        for it in yt_step(ys):
            print("\n=== @" + it["username"], it["source"], "\n" + it["text"])
    print("\nпроверено каналов:", len(ys.get("seen", [])), "в запасе:", len(ys.get("frontier", [])), "\nпричины:", ys.get("why"))
