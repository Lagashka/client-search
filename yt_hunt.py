# -*- coding: utf-8 -*-
"""Бот 5 «YouTube» (17.11, v3): эксперты с живыми каналами на YouTube и RuTube → письмо в Telegram (или на почту, если Telegram нет).

Без ключей API: поиск YouTube (фильтр «каналы») → «О канале» (описание, ссылки) → RSS последних видео → вкладка Shorts
→ разбор канала по открытым цифрам (analyze) → письмо: боль цифрами → как исправляется → золотая кнопка (пробный Shorts 15 с).
RuTube: открытый API поиска и профиля (rt_*), тот же разбор.

Что видно со стороны (настоящее удержание видно только владельцу в YouTube Studio):
  • живой ли канал; есть ли Shorts; сколько они набирают против длинных, подписчиков и коллег по теме; длина Shorts;
  • просели ли просмотры; лучшее видео по теме; график «самые пересматриваемые» (YouTube даёт его только популярным видео);
  • вопросы зрителей в комментариях; есть ли у канала монтажёр (подпись «монтаж: @…» — таким не пишем).
Работает внутри autoclient.py (облако GitHub Actions): yt_step(st["yt"], skip) → письма variant "YT".
"""
import os, re, sys, json, time, random, datetime, zlib, urllib.request, urllib.parse
from xml.etree import ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(os.path.dirname(BASE), "Поиск бизнеса"), BASE):
    if p not in sys.path: sys.path.append(p)
import bizhunt as B          # log, tg_kind, TG_INFO, first_name

def log(*a): B.log("youtube:", *a)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SP_CHANNELS = "EgIQAg=="        # фильтр поиска YouTube: только каналы
UTC = datetime.timezone.utc
MSK = datetime.timezone(datetime.timedelta(hours=3))

# эксперты, которые уже снимают: им нужен монтаж Shorts
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
          (r"банкрот|долг", "про банкротство"), (r"юрист|адвокат|правов|закон|(?<![а-яё])суд|(?<![а-яё])дтп|наследств|развод", "про право"),
          (r"психолог|психотерап", "про психологию"),
          (r"нутрицио|диетолог|питани", "про питание"), (r"косметолог|кож[аиу]|уход", "про уход"), (r"стоматолог|зуб", "про зубы"),
          (r"налог|бухгалт", "про налоги"), (r"инвест|финанс", "про финансы"), (r"интерьер", "про интерьеры"), (r"фитнес|трениров", "про тренировки"),
          (r"логопед|речь|речев", "про речь"), (r"гинеколог|беремен", "про женское здоровье"), (r"хирург|пластик", "про пластику"),
          (r"трихолог|волос", "про волосы"), (r"остеопат|осанк|спин[аеуы]", "про здоровье спины"),
          (r"врач|здоровь|лечени|кардиолог|эндокрин|невролог", "про здоровье"),
          (r"репетитор|егэ|огэ", "про подготовку к экзаменам"), (r"маркетплейс|wildberries|ozon|вб\b", "про маркетплейсы"),
          (r"коуч|цели|мышлени", "про мышление")]

# идея Shorts под нишу (п. 7) — для второго письма и мини-разбора; без обещаний результата
NICHE_IDEAS = {"про недвижимость": "рум-тур на 20 секунд, цена и главный плюс квартиры в первой же секунде",
               "про ипотеку": "один вопрос клиента и ответ с цифрами за 20 секунд, например как снизить платёж",
               "про кредиты": "одна ошибка заёмщика и сколько она стоит в рублях, за 20 секунд",
               "про банкротство": "короткий ответ на вопрос «можно ли списать долги, если…», да или нет и почему",
               "про право": "одна частая ошибка и как её избежать, за 20-30 секунд с субтитрами",
               "про психологию": "одна ситуация из жизни и одна фраза-вывод, такие ролики хорошо пересылают",
               "про питание": "миф и правда о продукте за 15 секунд",
               "про налоги": "одна дата или штраф, о котором мало кто знает, за 20 секунд",
               "про финансы": "одна цифра и вывод из неё за 20 секунд",
               "про интерьеры": "было и стало за 10 секунд с одной главной идеей",
               "про тренировки": "одна ошибка в упражнении и как правильно, за 15 секунд"}
IDEA_DEFAULT = "один вопрос клиента и короткий ответ на него, за 20-30 секунд"
# только темы, где новость общая для всей страны (не местный ЖК); заголовок обязан содержать корень темы
NEWS_Q = {"про ипотеку": ("ипотека", r"ипотек"), "про кредиты": ("кредиты", r"кредит"), "про банкротство": ("банкротство физлиц", r"банкрот"),
          "про налоги": ("налоги ИП", r"налог|ндфл|ндс"), "про финансы": ("ключевая ставка", r"ставк"), "про маркетплейсы": ("маркетплейсы", r"маркетплейс|wildberries|ozon")}
NEWS_STOP = re.compile(r"погиб|теракт|войн|удар|дрон|бпла|убий|смерт|сво\b|фронт|обстрел|арест|задерж|пожар|авари", re.I)

SUBS = (200, 100000)
STOP_TITLE = re.compile(r"новост|news|tv\b|тв\b|канал о|министер|администрац|вестник|журнал|медиа|подкаст студи|"
                        r"монтаж|видеомонтаж|рилсмейк|видеограф|продакшн|production|"
                        r"курс|школа|академи|обучени|университет|колледж|клиника|центр\b|агентств|компани|ооо|холдинг", re.I)
COMPETITOR = re.compile(r"монтаж[её]р|видеомонтаж|рилсмейкер|мобилограф|видеограф|моушн|motion|smm", re.I)
SELLS = re.compile(r"консультац|запис|услуг|клиент|обращ|напиши|пишите|заявк|помогу|помогаю|разбор|сопровожд|стоимост|прайс|связ", re.I)
FIRST_PERSON = re.compile(r"(?<![а-яё])(я|мне|меня|мой|моя|мои|помогаю|помогу|расскажу|рассказываю|работаю)(?![а-яё])", re.I)
TG_RX = re.compile(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_/])|(?<![\w.@])@([A-Za-z][A-Za-z0-9_]{4,31})(?![\w.])")
JUNK = {"joinchat", "share", "addstickers", "proxy", "iv", "contact", "telegram", "durov", "username", "gmail", "mail", "yandex"}
# п. 13: у канала уже есть монтажёр — подпись в описании видео
EDITOR_RX = re.compile(r"(?i:монтаж|монтажер|монтажёр|видеомонтаж|editor|edited by|edit by|режисс[её]р монтажа)\s*(?:[:\-–—]\s*(?:@|https?://|t\.me|[А-ЯЁA-Z][а-яёa-z]+)|\s(?:@|t\.me/))")
EMAIL_RX = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{2,40}@[A-Za-z0-9.-]{2,40}\.[A-Za-z]{2,10})(?![\w.])")
EMAIL_JUNK = re.compile(r"noreply|no-reply|example|support@|info@youtube|press@|@youtube|@google|\.(png|jpg|gif)$", re.I)

# ---------------------------------------------------------------- сеть
def get(url, timeout=25, data=None, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9", "Cookie": "SOCS=CAI; CONSENT=YES+"}
    h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h)
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

VIEWS_RX = re.compile(r"(\d[\d   ]*(?:[.,]\d+)?\s*(?:тыс\w*\.?|млн\w*\.?)?)\s*просмотр", re.I)
def shorts_tab(cid):
    """Вкладка Shorts: [(id, просмотры)] последних Shorts (до ~48). [] — Shorts на канале нет."""
    d = initial_data(get(f"https://www.youtube.com/channel/{cid}/shorts?hl=ru"))
    out = []
    for s in walk(d, "shortsLockupViewModel"):
        m = list(VIEWS_RX.finditer(s.get("accessibilityText") or ""))
        v = parse_count(m[-1].group(1)) if m else None
        if v is not None: out.append((s.get("entityId", "").replace("shorts-shelf-item-", ""), v))
    return out

def watch(vid):
    """Страница видео: (html, ytInitialData, длина в секундах)."""
    w = get(f"https://www.youtube.com/watch?v={vid}&hl=ru")
    ln = re.search(r'"lengthSeconds":"(\d+)"', w)
    return w, initial_data(w), int(ln.group(1)) if ln else 0

def heatmap_of(d):
    """График «самые пересматриваемые» (100 точек 0..1) из ytInitialData; YouTube даёт его только популярным видео → None."""
    for m in walk(d, "macroMarkersListEntity"):
        ml = m.get("markersList") or {}
        if ml.get("markerType") == "MARKER_TYPE_HEATMAP" and len(ml.get("markers") or []) >= 20:
            return [float(x.get("intensityScoreNormalized") or 0) for x in ml["markers"]]
    return None

def heatmap(vid):
    w, d, ln = watch(vid)
    return heatmap_of(d), ln

def comments_of(w, d, n=40):
    """Первые комментарии под видео (внутренний запрос YouTube, без ключа). [] если закрыты/не вышло."""
    tok = None
    for isr in walk(d, "itemSectionRenderer"):
        if isr.get("sectionIdentifier") == "comment-item-section":
            tok = next(walk(isr, "token"), None)
    if not tok: return []
    ver = (re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', w) or [None, "2.20261116.00.00"])[1]
    body = json.dumps({"context": {"client": {"clientName": "WEB", "clientVersion": ver, "hl": "ru"}}, "continuation": tok}).encode()
    j = json.loads(get("https://www.youtube.com/youtubei/v1/next?prettyPrint=false", data=body, headers={"Content-Type": "application/json"}))
    return [((p.get("properties") or {}).get("content") or {}).get("content", "") for p in walk(j, "commentEntityPayload")][:n]

def questions(cs):
    """Вопросы зрителей из комментариев (п. 5): короткие, с «?», без ссылок и телефонов — темы для Shorts."""
    out = []
    for c in cs:
        if re.search(r"(?i)пишите в коммент|делитесь|подписывайтесь|ставьте лайк|звоните", c or ""): continue   # комментарий автора
        for q in re.findall(r"[^.!?\n]{8,120}\?", c or ""):
            q = re.sub(r"\s+", " ", q).strip(" ,-")
            q = re.sub(r"[^\w\s,?%-]", "", q).strip()
            q = re.sub(r"\s+,", ",", q)
            if re.search(r"http|t\.me|\d{6,}|@", q) or len(q) < 12 or len(q.split()) < 4: continue
            if re.search(r"(?i)(?<![а-яё])(вам|вас|ваш\w*)(?![а-яё])|возникает вопрос|как думаете|кто (знает|согласен)", q): continue   # вопрос зрителям, а не эксперту
            if not re.search(r"(?i)^(а |и )?(как|можно|что|сколько|когда|где|почему|зачем|какой|какая|какие|ли |если|нужно|стоит|есть ли|реально)|\s(ли|можно)\s", q): continue
            if q.lower() not in [x.lower() for x in out]: out.append(q[:1].upper() + q[1:])
    return out

def heat_points(h, length):
    """Из графика пересмотров: самый пересматриваемый момент (сек) и где зрители начинают проматывать (сек).
    Начало и конец не считаем: в начале график всегда высокий, в конце всегда падает."""
    if not h or length < 60: return None
    n = len(h); a, b = max(1, n // 20), n - n // 10
    sm = [sum(h[max(0, i - 1):i + 2]) / len(h[max(0, i - 1):i + 2]) for i in range(n)]
    peak = max(range(a, b), key=lambda i: sm[i])
    base = sum(sm[a:b]) / (b - a)
    drop = next((i for i in range(a, b) if sm[i] < 0.5 * sm[a]), None)
    return {"peak": int(peak * length / n), "peak_x": round(sm[peak] / base, 1) if base else 0,
            "drop": int(drop * length / n) if drop is not None else None}

def news_hook(topic_, cache):
    """Повод из новостей ниши за 3 дня (п. 15): короткий заголовок (<40 знаков, без трагедий) или "". Раз в день на тему."""
    q, must = NEWS_Q.get(topic_) or (None, None)
    if not q: return ""
    day = datetime.date.today().isoformat()
    if (cache.get(topic_) or {}).get("d") == day: return cache[topic_]["t"]
    t = ""
    try:
        root = ET.fromstring(get("https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:3d", "hl": "ru", "gl": "RU", "ceid": "RU:ru"})))
        for it in root.iter("item"):
            h = re.split(r"\s+[-–—]\s+", it.findtext("title") or "")[0].strip(" .")
            if 12 <= len(h) < 40 and re.search(must, h, re.I) and not NEWS_STOP.search(h) and sum(ch.isupper() for ch in h) < 0.4 * len(h) and "«" not in h:
                t = h; break
    except Exception: pass
    cache[topic_] = {"d": day, "t": t}
    return t

def cases():
    """Реальные кейсы Егора по темам (п. 20) — файл «Кейсы.json» рядом; пусто, пока нет настоящих цифр."""
    try:
        j = json.load(open(os.path.join(BASE, "Кейсы.json"), encoding="utf-8"))
        return {k: v.strip() for k, v in j.items() if not k.startswith("_") and isinstance(v, str) and v.strip()}
    except Exception: return {}

# ---------------------------------------------------------------- RuTube (п. 12): открытый API
def rt_search(q):
    j = json.loads(get("https://rutube.ru/api/search/video/?" + urllib.parse.urlencode({"query": q})))
    out, seen = [], set()
    for v in j.get("results") or []:
        a = v.get("author") or {}
        if a.get("id") and a["id"] not in seen:
            seen.add(a["id"]); out.append({"id": f"rt:{a['id']}", "title": a.get("name") or "", "subs": None, "snippet": ""})
    return out

def rt_profile(aid):
    p = json.loads(get(f"https://rutube.ru/api/profile/user/{aid}/"))
    return {"desc": p.get("description") or "", "links": [], "subs": p.get("subscribers_count")}

def rt_videos(aid):
    j = json.loads(get(f"https://rutube.ru/api/video/person/{aid}/?page=1"))
    out = []
    for v in j.get("results") or []:
        try: when = datetime.datetime.fromisoformat((v.get("publication_ts") or v.get("created_ts"))[:19]).replace(tzinfo=MSK)
        except Exception: continue
        out.append({"id": v.get("id"), "title": v.get("title") or "", "when": when, "desc": v.get("description") or "",
                    "shorts": (v.get("duration") or 999) <= 90, "views": v.get("hits"), "len": v.get("duration") or 0})
    return sorted(out, key=lambda v: v["when"], reverse=True)

# ---------------------------------------------------------------- разбор
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
    """Разбор канала по открытым цифрам → боль, которую видно со стороны, или {"skip": причина} (тогда не пишем).
    vids — последние видео (свежие первыми), sh_views — просмотры с вкладки Shorts."""
    now = now or datetime.datetime.now(UTC)
    age = lambda v: (now - v["when"]).days
    if not vids or age(vids[0]) > ALIVE_DAYS: return {"skip": "мёртвый канал"}
    if sum(1 for v in vids if age(v) <= 60) < ALIVE_MIN: return {"skip": "редко выходят видео"}
    ripe = [v for v in vids if age(v) >= 3 and v.get("views") is not None]        # свежим 1–2 дня ещё рано судить
    longs = [v for v in ripe if not v["shorts"]]
    shorts = [v for v in ripe if v["shorts"]]
    ml = median([v["views"] for v in longs]); ms = median([v["views"] for v in shorts] or sh_views[:10])
    best = max([v for v in longs if on_topic(v)], key=lambda v: v["views"], default=None)
    r = {"subs": subs, "med_long": int(ml), "med_short": int(ms), "n_long": len(longs), "n_short": len(shorts) or len(sh_views),
         "n_long_30": sum(1 for v in vids if not v["shorts"] and age(v) <= 30)}
    if best and ml and best["views"] >= 2 * ml and best["views"] >= 300:
        r["best"] = {"id": best["id"], "title": best["title"], "views": best["views"], "x": round(best["views"] / ml, 1)}
    fr = vids[0]
    if age(fr) <= 2 and on_topic(fr) and short_title(fr["title"]):            # п. 10: повод — свежее видео
        r["fresh"] = {"title": fr["title"], "days": age(fr)}
    recent_sh = [v for v in vids if v["shorts"] and age(v) <= 30]
    if len(longs) >= 3 and not recent_sh:
        return dict(r, kind="no_shorts", never=not sh_views)
    if (len(shorts) >= 3 or len(sh_views) >= 5) and ms < 2000 and ((ml and ms < 0.5 * ml) or (subs and ms < 0.05 * subs)):
        return dict(r, kind="weak_shorts")
    for grp in (shorts, longs):
        if len(grp) >= 6:
            new, old = median([v["views"] for v in grp[:3]]), median([v["views"] for v in grp[3:]])
            if old >= 200 and new < 0.5 * old:
                return dict(r, kind="drop", new=int(new), old=int(old), of="shorts" if grp is shorts else "long")
    return dict(r, skip="с роликами и так всё нормально")

def score(c):
    """Приоритет лида (п. 11): сила боли + повод + продаёт услуги + размер канала. Выше — пишем раньше."""
    an = c.get("an") or {}
    s = {"no_shorts": 3, "weak_shorts": 2, "drop": 2}.get(an.get("kind"), 0)
    s += bool(an.get("best")) + bool(an.get("heat")) + 1.5 * bool(an.get("fresh")) + bool(an.get("bench")) + bool(an.get("questions"))
    s += bool(SELLS.search(c.get("desc", ""))) + (1000 <= (c.get("subs") or 0) <= 30000)
    return round(s, 1)

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

def emails(*texts):
    """Почта из описания канала и видео (п. 9) — если Telegram нет."""
    out = []
    for t in texts:
        for m in EMAIL_RX.finditer(t or ""):
            e = m.group(1).strip(".").lower()
            if not EMAIL_JUNK.search(e) and e not in out: out.append(e)
    return out

def has_editor(vids):
    """У канала уже есть монтажёр: подпись в описаниях последних видео (п. 13)."""
    return any(EDITOR_RX.search(v.get("desc") or "") for v in vids[:8])

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
    """Название видео для письма: без хэштегов, эмодзи и КАПСА, короче 40 знаков (длинные цитаты human.py вырезает); плохое — пусто."""
    t = re.sub(r"#\S+", "", t or "")
    t = re.sub(r"[^\w\s.,:;!?\"'()\-–—%₽]", "", t).strip(" -–—|.,!?")
    t = re.sub(r"\s+", " ", t).replace('"', "")
    if len(t) < 10 or len(t) >= 40 or sum(ch.isupper() for ch in t) > 0.5 * sum(ch.isalpha() for ch in t): return ""
    return t

# ---------------------------------------------------------------- письма
def _hi(c, R):
    fn = B.first_name(c.get("who", ""))
    return f"{fn}, {R(['добрый день', 'здравствуйте'])}" if fn else R(["Добрый день", "Здравствуйте"])

def template(c):
    """3 сообщения, как пишет Егор с телефона: 1) что увидел на канале (боль цифрами со стороны),
    2) кто я и как это исправляется (беру видео на себя, 17.11), 3) золотая кнопка: разбор канала и 3 идеи Shorts из их же видео + ОДИН вопрос.
    Без ссылок, цен, «бесплатно» и восклицаний. c["an"] — результат analyze(). Выбранные варианты → c["ab"] (A/B, п. 17)."""
    ab = []
    def R(opts, name=None):
        i = random.randrange(len(opts))
        if name: ab.append(f"{name}{i}")
        return opts[i]
    an = c.get("an") or {}
    plat = c.get("plat") or "YouTube"
    hi = _hi(c, R)
    tp = topic(c.get("title", "") + " " + c.get("desc", ""))
    yt = f"ваш {plat} {tp}".strip() if tp else f"ваш {plat}"
    fr = an.get("fresh")
    if fr:
        look = f"посмотрел ваше {'вчерашнее' if fr['days'] <= 1 else 'свежее'} видео «{short_title(fr['title'])}»"; ab.append("fresh")
    else:
        look = R([f"посмотрел {yt}", f"наткнулся на {yt}, посмотрел несколько роликов"], "o")
    k = an.get("kind")
    if k == "no_shorts":
        a = f"{hi}, {look}, длинные видео выходят регулярно, а " + ("Shorts на канале нет совсем" if an.get("never")
                                                                   else "Shorts за последний месяц ни одного")
        n = an.get("n_long_30") or 0
        fix = R(([f"за месяц у вас вышло {n} длинных, из них получилось бы {3 * n}-{5 * n} коротких, и они приводят на канал новых людей"] if n >= 2 else [])
                + ["из одного длинного видео обычно получается 3-5 коротких, и они приводят на канал новых людей, которых длинные сами не соберут",
                   "короткие сейчас главный источник новых зрителей, а у вас для них уже всё снято, нужно только вырезать и смонтировать"], "f")
    elif k == "weak_shorts":
        if an.get("bench"):
            a = f"{hi}, {look}, Shorts у вас набирают около {num(an['med_short'])} просмотров, а у коллег в вашей теме около {num(an['bench'])}"
        elif an.get("med_long") and an["med_short"] < 0.5 * an["med_long"]:
            a = f"{hi}, {look}, Shorts у вас набирают около {num(an['med_short'])} просмотров, а длинные видео около {num(an['med_long'])}"
        else:
            a = f"{hi}, {look}, Shorts набирают около {num(an['med_short'])} просмотров при {num(an['subs'])} подписчиках"
        if (an.get("sh_len") or 0) >= 45:
            fix = f"ваши Shorts идут около {an['sh_len']} секунд, а досматривают обычно 20-30, лишнее режется монтажом, переснимать ничего не нужно"
            ab.append("flen")
        else:
            fix = R(["обычно короткие теряют зрителя в первые 1-2 секунды, когда нет цепляющего начала, это исправляется монтажом, переснимать ничего не нужно",
                     "чаще всего короткий ролик теряет зрителя на первых секундах и на паузах, это лечится монтажом, а не новой съёмкой"], "f")
    elif k == "drop":
        what = "последние Shorts" if an.get("of") == "shorts" else "последние ролики"
        a = f"{hi}, {look}, {what} набирают около {num(an['new'])} просмотров, а до этого было около {num(an['old'])}"
        fix = R(["часто дело не в теме, а в первых секундах и темпе, это исправляется монтажом",
                 "обычно просадка из-за начала и темпа, а не из-за темы, и это исправляется монтажом"], "f")
    else:
        a = f"{hi}, {look}"
        fix = "из длинных видео можно делать короткие, и они приводят на канал новых людей"
    b = f"Я Егор, беру видео на себя, чтобы оно выходило без вашего участия. {fix[:1].upper() + fix[1:]}"      # 17.11 «Видео без владельца»
    best, ht = an.get("best") or {}, an.get("heat") or {}
    bt = short_title(best.get("title", "")) or short_title(c.get("video", ""))
    if ht.get("peak") and bt:
        b += f". У видео «{bt}» самый пересматриваемый момент на {mmss(ht['peak'])}, с него бы и начал"; ab.append("heat")
    elif best and short_title(best.get("title", "")):
        x = round(best["x"])
        b += f". Начал бы с видео «{bt}», оно набрало {num(best['views'])}, это в {x} {'раз' if x >= 5 else 'раза'} больше обычного"; ab.append("best")
    src = f"из видео «{bt}»" if bt else ("из вашего видео " + topic(c.get("video", ""))).strip() if topic(c.get("video", "")) else "из одного вашего видео"
    # 17.11: золотая кнопка = мини-разбор канала + 3 идеи Shorts из их же видео (audit_text их и формирует), снимать им ничего не нужно
    if k == "weak_shorts":
        btn = R([f"Могу прислать разбор канала и 3 идеи, как переделать Shorts {src}, переснимать ничего не нужно. Прислать?",
                 f"Могу прислать разбор канала и 3 идеи Shorts {src}, снимать ничего не придётся. Прислать?"], "b")
    else:
        btn = R([f"Могу прислать разбор канала и 3 идеи Shorts {src}, снимать ничего не придётся. Прислать?",
                 f"Могу показать на примере {src}, как Shorts выходили бы без вашего участия: разбор канала и 3 идеи. Прислать?"], "b")
    c["ab"] = (k or "?") + ":" + ".".join(ab)
    return _human(f"{a}\n{b}\n{btn}")

def _human(t):
    try:
        import human
        return human.humanize(t)
    except Exception:
        return t

def followup(c):
    """Второе письмо через 2 дня (п. 14): ДРУГОЙ факт, не повтор первого. По силе: реальный кейс → вопрос зрителей →
    повод из новостей → идея под нишу. Одна строка, один вопрос, можно ответить «нет»."""
    R = random.choice
    an = c.get("an") or {}
    hi = _hi(c, R)
    tp = topic(c.get("title", "") + " " + c.get("desc", ""))
    cs = cases().get(tp)
    q = next((x for x in an.get("questions") or [] if len(x) < 38), "")
    nw = an.get("news") or ""
    no = R(["Если не актуально, просто напишите «нет»", "Если не ваша тема, напишите «нет», больше не побеспокою"])
    if cs:
        t = f"{hi}, коротко покажу, что получается, {cs}. Прислать вам разбор и 3 идеи Shorts? {no}"
    elif q:
        t = f"{hi}, ещё заметил, под вашим видео зрители спрашивают «{q.rstrip('?')}», ответ на такой вопрос за 20 секунд получается сильным Shorts, снимать вам ничего не нужно. Прислать 3 идеи под такие вопросы? {no}"
    elif nw:
        t = f"{hi}, кстати, сейчас все обсуждают «{nw}», по вашей теме из этого вышел бы актуальный Shorts на этой неделе. Прислать 3 идеи? {no}"
    else:
        t = f"{hi}, ещё идея под вашу тему, {NICHE_IDEAS.get(tp, IDEA_DEFAULT)}. Прислать 3 таких идеи под ваш канал? {no}"
    return _human(t)

PAIN_TXT = {"no_shorts": ("длинные видео выходят, а Shorts нет: теряет новых зрителей", "нарезка Shorts из его длинных видео"),
            "weak_shorts": ("Shorts набирают мало (теряют зрителя в первые секунды)", "переделать начало и темп Shorts"),
            "drop": ("просмотры последних роликов просели вдвое", "монтаж начала и темпа")}
LADDER = " → разбор канала и 3 идеи → Старт 19 000 ₽ (задания, обучение, серия из 5 Shorts) → месяц 50 000 ₽"     # п. 16; 17.11: идея «Видео без владельца», ниже 19 000 не опускаемся

def facts_of(an):
    if not an: return ""
    return (f"Shorts медиана {an.get('med_short')}, длинные медиана {an.get('med_long')}, подписчиков {an.get('subs')}"
            + (f", у коллег по теме Shorts ~{an['bench']}" if an.get("bench") else "")
            + (f", Shorts по ~{an['sh_len']} с" if an.get("sh_len") else "")
            + (f", лучшее видео «{an['best']['title']}» {an['best']['views']} (в {an['best']['x']} раза выше обычного)" if an.get("best") else "")
            + (f", самый пересматриваемый момент {mmss(an['heat']['peak'])}" if (an.get("heat") or {}).get("peak") else ""))

def audit_text(c):
    """Мини-разбор канала (п. 8): Егор отправляет его после «да», вместе с пробным Shorts."""
    an = c.get("an") or {}
    tp = topic(c.get("title", "") + " " + c.get("desc", ""))
    pn = PAIN_TXT.get(an.get("kind"), ("", ""))
    themes = [x.rstrip("?") + "?" for x in (an.get("questions") or [])[:3]]
    if an.get("best"): themes.append(f"ещё 2-3 коротких из видео «{an['best']['title']}», тема уже доказала, что заходит")
    themes.append(NICHE_IDEAS.get(tp, IDEA_DEFAULT))
    lines = [f"Мини-разбор канала «{c.get('title', '')}»", "",
             "Что видно со стороны:",
             f"• Shorts набирают около {num(an.get('med_short') or 0)}, длинные около {num(an.get('med_long') or 0)}, подписчиков {num(an.get('subs') or 0)}"]
    if an.get("bench"): lines.append(f"• у коллег в вашей теме Shorts набирают около {num(an['bench'])}")
    if an.get("n_long_30"): lines.append(f"• за месяц вышло {an['n_long_30']} длинных видео, это материал на {3 * an['n_long_30']}-{5 * an['n_long_30']} Shorts")
    if an.get("sh_len"): lines.append(f"• Shorts идут около {an['sh_len']} секунд")
    if (an.get("heat") or {}).get("peak"): lines.append(f"• у видео «{an['best']['title']}» самый пересматриваемый момент на {mmss(an['heat']['peak'])}")
    lines += ["", f"Где теряются зрители: {pn[0]}", f"Что сделать: {pn[1]}, сильное начало в первую секунду, субтитры, темп без пауз", "",
              "Темы для Shorts:"] + [f"{i + 1}. {t}" for i, t in enumerate(themes[:5])]
    return "\n".join(lines)[:1500]

def item_of(c):
    an = c.get("an") or {}
    pn = PAIN_TXT.get(an.get("kind"))
    facts = facts_of(an)
    return {"username": c["username"], "invited": False, "found": time.time(), "post": "", "display": c.get("who") or c.get("title") or "",
            "variant": "YT", "niche": "youtube-эксперт", "uniq": 1, "source": c["source"], "plat": c.get("plat") or "YouTube",
            # боль уже в письме (по цифрам канала) — нейросеть свою не дописывает; Егор увидит её в уведомлении об ответе
            "pain": {"pain": f"{pn[0]} ({facts})"[:300], "solution": (pn[1] + LADDER)[:300]} if pn else {},
            "ctx": (f"{c.get('plat') or 'YouTube'}-канал эксперта: {c.get('title') or ''}\nПодписчиков: {c.get('subs', '')}\n"
                    f"Разбор канала: {facts}\nВидео: {c.get('video', '')}\nОписание: {c.get('desc', '')}")[:2000],
            "text": re.sub(r"\s*\n\s*", "\n\n", c["text"].strip()),
            "fu_alt": c.get("fu_alt") or "", "ab": c.get("ab") or "", "audit": c.get("audit") or "", "score": c.get("score", 0),
            "best_url": (f"https://www.youtube.com/watch?v={an['best']['id']}" if an.get("best") and c.get("plat", "YouTube") == "YouTube" else ""),
            "mail": c.get("mail") or ""}

# ---------------------------------------------------------------- проверка канала
WHY = {}          # счёт причин за шаг (без имён) → st["yt"]["why"] → DIAG
def why(r):
    WHY[r] = WHY.get(r, 0) + 1
    return None

def check_channel(ch, skip, ys=None):
    """Канал из поиска (YouTube или RuTube «rt:id») → кандидат или None (причина — в WHY)."""
    ys = ys if ys is not None else {}
    rt = ch["id"].startswith("rt:")
    if ch["subs"] is not None and not (SUBS[0] <= ch["subs"] <= SUBS[1]): return why("подписчиков мало или много")
    if STOP_TITLE.search(ch["title"]) or COMPETITOR.search(ch["title"]): return why("не эксперт")
    ab = rt_profile(ch["id"][3:]) if rt else about(ch["id"]); time.sleep(random.uniform(1, 2))
    if not ab: return why("канал не открылся")
    subs = ab["subs"] or ch["subs"] or 0
    if not (SUBS[0] <= subs <= SUBS[1]): return why("подписчиков мало или много")
    handles = tg_handles(" ".join(ab["links"]), ab["desc"])
    vids = []
    try: vids = rt_videos(ch["id"][3:]) if rt else videos(ch["id"]); time.sleep(random.uniform(0.5, 1.5))
    except Exception: pass
    if not handles: handles = tg_handles(*[v["desc"] for v in vids[:3]])
    mails = [] if handles else emails(ab["desc"], *[v["desc"] for v in vids[:3]])
    if not handles and not mails: return why("нет Telegram и почты")
    if not vids: return why("мёртвый канал")
    if not is_expert(ch["title"], ab["desc"], vids): return why("не эксперт")
    if not topic(ch["title"] + " " + ab["desc"]) and sum(1 for v in vids[:10] if topic(v["title"])) < 2: return why("не по теме")
    if has_editor(vids): return why("уже есть монтажёр")
    sh = []
    if rt: sh = [(v["id"], v["views"]) for v in vids if v["shorts"] and v.get("views") is not None]
    else:
        try: sh = shorts_tab(ch["id"]); time.sleep(random.uniform(0.5, 1.5))
        except Exception: pass
    an = analyze(vids, subs, [v for _, v in sh], on_topic=lambda v: bool(topic(v["title"])))
    tp = topic(ch["title"] + " " + ab["desc"]) or next((topic(v["title"]) for v in vids if topic(v["title"])), "")
    bench = ys.setdefault("bench", {}).setdefault(tp or "?", [])          # п. 4: медиана Shorts у коллег по теме
    bm = median(bench) if len(bench) >= 5 else 0
    if an.get("med_short"): bench.append(an["med_short"]); del bench[:-60]
    if an.get("skip"): return why(an["skip"])
    if bm and an.get("med_short") is not None and bm >= 3 * max(an["med_short"], 1) and bm >= 500: an["bench"] = int(bm)
    if not rt:
        if sh and an["kind"] != "no_shorts":                                 # п. 2: длина Shorts (2 последних)
            lens = []
            for sid, _ in sh[:2]:
                try: lens.append(watch(sid)[2]); time.sleep(random.uniform(0.5, 1))
                except Exception: pass
            if lens: an["sh_len"] = int(median(lens))
        vid = (an.get("best") or {}).get("id") or next((v["id"] for v in vids if not v["shorts"] and topic(v["title"])), None)
        if vid:                                                              # график пересмотров + вопросы зрителей (п. 5)
            try:
                w, d, ln = watch(vid); time.sleep(random.uniform(0.5, 1.5))
                if an.get("best"):
                    hp = heat_points(heatmap_of(d), ln)
                    if hp: an["heat"] = hp
                qs = questions(comments_of(w, d))
                if qs: an["questions"] = qs[:5]
            except Exception: pass
    if tp: an["news"] = news_hook(tp, ys.setdefault("news", {}))
    u = resolve_person(handles, skip) if handles else ""
    mail = ""
    if not u:
        mail = next((m for m in mails if not skip(m)), "")
        if not mail: return why("Telegram не личный")
    on = [v for v in vids if not v["shorts"] and topic(v["title"])] or [v for v in vids if topic(v["title"])]
    long_v = next((v for v in on if short_title(v["title"])), on[0] if on else {"title": ""})
    WHY[an["kind"]] = WHY.get(an["kind"], 0) + 1
    if mail: WHY["почта вместо Telegram"] = WHY.get("почта вместо Telegram", 0) + 1
    src = f"https://rutube.ru/channel/{ch['id'][3:]}/" if rt else f"https://www.youtube.com/channel/{ch['id']}"
    return {"username": u or mail, "mail": mail, "title": ch["title"], "subs": subs, "desc": ab["desc"][:400], "video": long_v["title"],
            "an": an, "plat": "RuTube" if rt else "YouTube", "has_shorts": any(v["shorts"] for v in vids) or bool(sh), "source": src,
            "who": (B.TG_INFO.get(u.lower()) or {}).get("title", "") if u else ""}

def yt_step(ys, skip=lambda u: False, max_new=3, max_check=10):
    """Один шаг (autoclient зовёт раз в 15 мин): поиск по очередному запросу (YouTube, каждый 3-й — RuTube) →
    проверить до max_check каналов → до max_new писем (лучшие по score первыми). ys — st["yt"] в state.json основного бота."""
    for k, v in (("frontier", []), ("seen", []), ("qi", 0), ("pending", []), ("why", {})):
        ys.setdefault(k, v)
    ys["pending"] = [c for c in ys["pending"] if c.get("an")]       # кандидаты старой версии (без разбора) не пишем
    WHY.clear()
    seen = set(ys["seen"])
    if len(ys["frontier"]) < max_check:
        i = ys["qi"]; ys["qi"] += 1
        q = QUERIES[(i // 1) % len(QUERIES)]
        rt = i % 3 == 2
        try:
            found = [c for c in (rt_search(q) if rt else search(q)) if c["id"] not in seen and c["id"] not in {x["id"] for x in ys["frontier"]}]
            ys["frontier"] += found; log(f"поиск {'RuTube' if rt else 'YouTube'} «{q}»: новых каналов {len(found)}")
        except Exception as e:
            log("поиск не удался:", str(e)[:80])
    cands = []
    for _ in range(max_check):
        if not ys["frontier"] or len(cands) >= max_new: break
        ch = ys["frontier"].pop(0)
        if ch["id"] in seen: continue
        seen.add(ch["id"])
        try:
            c = check_channel(ch, skip, ys)
            if c: cands.append(c)
        except Exception as e:
            log("канал не проверился:", str(e)[:80])
    ys["seen"] = list(seen)[-10000:]; ys["frontier"] = ys["frontier"][:200]
    for k, v in WHY.items(): ys["why"][k] = ys["why"].get(k, 0) + v
    for c in cands: c["score"] = score(c)
    pend = sorted({c["username"].lower(): c for c in ys["pending"] + cands}.values(), key=lambda c: -c.get("score", 0))
    out, keep = [], []
    for c in pend:
        if len(out) >= max_new or skip(c["username"]): keep.append(c); continue
        c["text"] = template(c)
        c["fu_alt"] = followup(c)
        c["audit"] = audit_text(c)
        out.append(item_of(c))
        log(f"эксперт {'📧 ' if c.get('mail') else '@'}{c['username']} ← {c['source']} ({c['subs']} подп., боль: {c['an'].get('kind')}, балл {c.get('score')})")
    ys["pending"] = [c for c in keep if not skip(c["username"])][:30]
    return out

# ---------------------------------------------------------------- почта (п. 9): только если Егор включил «📧 YouTube на почту»
def smtp_host(user):
    d = user.split("@")[-1].lower()
    return os.environ.get("MAIL_SMTP") or {"gmail.com": "smtp.gmail.com", "yandex.ru": "smtp.yandex.ru", "ya.ru": "smtp.yandex.ru",
            "mail.ru": "smtp.mail.ru", "bk.ru": "smtp.mail.ru", "inbox.ru": "smtp.mail.ru", "list.ru": "smtp.mail.ru"}.get(d, "smtp." + d)

def mail_body(item):
    """Письмо на почту = тот же текст + подпись (на почте без подписи выглядит как спам)."""
    return item["text"] + "\n\nЕгор, монтаж Shorts для экспертов"

def send_mail(to, subject, body):
    import smtplib
    from email.mime.text import MIMEText
    user, pw = os.environ.get("MAIL_USER", ""), os.environ.get("MAIL_PASS", "")
    if not (user and pw): return "skip:почта не подключена"
    msg = MIMEText(body, "plain", "utf-8"); msg["Subject"] = subject; msg["From"] = f"Егор <{user}>"; msg["To"] = to
    with smtplib.SMTP_SSL(smtp_host(user), 465, timeout=30) as s:
        s.login(user, pw); s.sendmail(user, [to], msg.as_string())
    return "sent"

if __name__ == "__main__":        # локальная проверка без отправки: python yt_hunt.py [шагов]
    ys = {}
    for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 2):
        for it in yt_step(ys):
            print("\n=== " + it["username"], it["source"], "балл", it["score"], it["ab"], "\n" + it["text"],
                  "\n--- дожим:\n" + it["fu_alt"], "\n--- разбор:\n" + it["audit"])
    print("\nпроверено каналов:", len(ys.get("seen", [])), "в запасе:", len(ys.get("frontier", [])), "\nпричины:", ys.get("why"))
