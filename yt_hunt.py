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
           "пластический хирург", "трихолог", "остеопат", "репетитор", "эксперт по маркетплейсам"]
TOPICS = [(r"ипотек", "про ипотеку"), (r"кредит", "про кредиты"), (r"недвижим|риелт|риэлт|квартир|новостройк|(?<![а-яё])жк(?![а-яё])", "про недвижимость"),
          (r"банкрот|долг", "про банкротство"), (r"юрист|адвокат|правов|закон|(?<![а-яё])суд", "про право"), (r"психолог|психотерап", "про психологию"),
          (r"нутрицио|диетолог|питани", "про питание"), (r"косметолог|кож[аиу]|уход", "про уход"), (r"стоматолог|зуб", "про зубы"),
          (r"налог|бухгалт", "про налоги"), (r"инвест|финанс", "про финансы"), (r"интерьер", "про интерьеры"), (r"фитнес|трениров", "про тренировки"),
          (r"логопед|речь|речев", "про речь"), (r"гинеколог|беремен", "про женское здоровье"), (r"хирург|пластик", "про пластику"),
          (r"трихолог|волос", "про волосы"), (r"остеопат|осанк|спин[аеуы]", "про здоровье спины"), (r"врач|здоровь|лечени", "про здоровье"),
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

NS = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/"}
def videos(cid):
    """Последние видео из RSS: [{title, when (UTC), desc}] — свежие первыми."""
    root = ET.fromstring(get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
    out = []
    for e in root.findall("a:entry", NS):
        try: when = datetime.datetime.fromisoformat(e.findtext("a:published", "", NS))
        except ValueError: continue
        out.append({"title": e.findtext("a:title", "", NS), "when": when,
                    "desc": e.findtext("m:group/m:description", "", NS) or "", "shorts": "/shorts/" in (e.find("a:link", NS).get("href", "") if e.find("a:link", NS) is not None else "")})
    return sorted(out, key=lambda v: v["when"], reverse=True)

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
    """Как пишет Егор с телефона: со строчной после приветствия, на запятых, без точки в конце, одна деталь, один вопрос."""
    R = random.choice
    cap = lambda s: s[:1].upper() + s[1:]
    fn = B.first_name(c.get("who", ""))
    hi = f"{fn}, {R(['добрый день', 'здравствуйте'])}" if fn else R(["Добрый день", "Здравствуйте"])
    vt = short_title(c.get("video", ""))
    vtp = topic(c.get("video", ""))
    tp = topic(c.get("title", "") + " " + c.get("desc", ""))
    if vt:
        a = R([f"{hi}, посмотрел ваше видео «{vt}» на YouTube", f"{hi}, наткнулся на ваш YouTube, посмотрел ролик «{vt}»"])
    elif vtp:
        a = R([f"{hi}, посмотрел ваше видео {vtp} на YouTube", f"{hi}, наткнулся на ваш YouTube, посмотрел ролик {vtp}"])
    elif tp:
        a = R([f"{hi}, наткнулся на ваш YouTube-канал {tp}", f"{hi}, посмотрел ваш YouTube {tp}, хорошо объясняете"])
    else:
        a = f"{hi}, наткнулся на ваш YouTube-канал, посмотрел пару видео"
    b = "Я Егор, " + R(["монтирую видео для экспертов, длинные для YouTube и Shorts из них",
                        "монтирую ролики для экспертов, и длинные видео, и нарезку в Shorts"])
    ask = R(["Монтаж сейчас сами делаете?", "Кто у вас сейчас монтирует?", "Shorts из длинных видео нарезаете?"] if not c.get("has_shorts")
            else ["Монтаж сейчас сами делаете?", "Кто у вас сейчас монтирует?"])
    text = f"{a}\n{cap(b)}. {ask}"
    try:
        import human
        text = human.humanize(text)
    except Exception:
        pass
    return text

def item_of(c):
    return {"username": c["username"], "invited": False, "found": time.time(), "post": "", "display": c.get("who") or c.get("title") or "",
            "variant": "YT", "niche": "youtube-эксперт", "uniq": 1, "source": c["source"],
            "pain": {},      # первое письмо = 2 строки, без «боли»
            "ctx": (f"YouTube-канал эксперта: {c.get('title') or ''}\nПодписчиков: {c.get('subs', '')}\n"
                    f"Последнее видео: {c.get('video', '')}\nОписание: {c.get('desc', '')}")[:2000],
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
    if not handles: return None
    now = datetime.datetime.now(datetime.timezone.utc)
    if not vids or (now - vids[0]["when"]).days > FRESH_DAYS: return None
    if not is_expert(ch["title"], ab["desc"], vids): return None
    # канал по экспертной теме: тема в названии/описании или хотя бы в 2 из 10 последних видео (не влоги и ASMR)
    if not topic(ch["title"] + " " + ab["desc"]) and sum(1 for v in vids[:10] if topic(v["title"])) < 2: return None
    u = resolve_person(handles, skip)
    if not u: return None
    # в письмо — только видео по теме: короткое название в кавычках, иначе «видео про …»; не по теме — не цитируем
    on = [v for v in vids if not v["shorts"] and topic(v["title"])] or [v for v in vids if topic(v["title"])]
    long_v = next((v for v in on if short_title(v["title"])), on[0] if on else {"title": ""})
    return {"username": u, "title": ch["title"], "subs": subs, "desc": ab["desc"][:400], "video": long_v["title"],
            "has_shorts": any(v["shorts"] for v in vids), "source": f"https://www.youtube.com/channel/{ch['id']}",
            "who": (B.TG_INFO.get(u.lower()) or {}).get("title", "")}

def yt_step(ys, skip=lambda u: False, max_new=3, max_check=8):
    """Один шаг (autoclient зовёт раз в 15 мин): поиск по очередному запросу → проверить до max_check каналов → до max_new писем.
    ys — st["yt"] в state.json основного бота."""
    for k, v in (("frontier", []), ("seen", []), ("qi", 0), ("pending", [])):
        ys.setdefault(k, v)
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
    pend = {c["username"].lower(): c for c in ys["pending"] + cands}
    out = []
    for ul, c in list(pend.items()):
        if len(out) >= max_new: break
        del pend[ul]
        if skip(c["username"]): continue
        c["text"] = template(c)
        out.append(item_of(c))
        log(f"эксперт @{c['username']} ← {c['source']} ({c['subs']} подп.)")
    ys["pending"] = list(pend.values())[:30]
    return out

if __name__ == "__main__":        # локальная проверка без отправки: python yt_hunt.py [шагов]
    ys = {}
    for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 2):
        for it in yt_step(ys):
            print("\n=== @" + it["username"], it["source"], "\n" + it["text"])
    print("\nпроверено каналов:", len(ys.get("seen", [])), "в запасе:", len(ys.get("frontier", [])))
