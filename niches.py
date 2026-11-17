# -*- coding: utf-8 -*-
"""Бот 5 «Мастера»: владельцы Telegram-каналов в трёх направлениях по сильным работам Егора (17.11):
  build — строительство и ремонт (Стяжка-Про), auto — авто (BMW M3), craft — премиум-ремесло (ателье, кожа, мебель; OHRA).

Работает внутри основного бота (autoclient.py, облако GitHub Actions), как partners:
    niches.niche_step(st["niches"], skip, tg_search=<поиск каналов>, parse=parse_channel)
→ список готовых писем (variant "NICHE") → общая холодная очередь autoclient (лимиты, часы, @SpamBot, guard, дожим).

Письмо: 2 сообщения (наблюдение про его канал → кто я под его нишу + ОДИН вопрос), без ссылок, цен и бесплатных предложений.
Пример работы (Стяжка / M3 / OHRA) показываем только ПОСЛЕ ответа, в диалоге. Все три работы тестовые, не «кейсы клиентов».
"""
import os, re, sys, time, random, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(os.path.dirname(BASE), "Поиск бизнеса"), BASE):
    if p not in sys.path: sys.path.append(p)
import bizhunt as B          # log, tg_kind, TG_INFO, first_name, RU_NAMES

def log(*a): B.log("мастера:", *a)

# --- три направления: признаки в канале, поисковые запросы, как представиться, о чём пост (одна живая деталь)
NICHES = {
    "build": {
        "kw": re.compile(r"ремонт|стяжк|строительств|строим(?![а-яё])|отделк|прораб|фундамент|каркасн|бан[яию](?![а-яё])|кровл|штукатур|плиточ|"
                         r"дом[а-я]* под ключ|тепл\w+ пол|черновая", re.I),
        "queries": ["ремонт квартир блог", "стяжка пола", "строительство домов блог", "прораб блог", "каркасные дома строительство",
                    "отделка квартир под ключ", "ремонт Москва прораб", "бани под ключ", "фундамент строительство эксперт"],
        "pitch": ["беру видео для строителей и мастеров ремонта на себя: ваши мастера снимают работу по минуте в день, монтаж и публикация на мне",
                  "делаю так, чтобы ролики для строительного канала выходили без вашего участия, мастера снимают по минуте в день, остальное на мне"],
        "topics": [(r"стяжк", "про стяжку"), (r"фундамент", "про фундаменты"), (r"бан[яию](?![а-яё])", "про бани"), (r"каркасн", "про каркасные дома"),
                   (r"кровл", "про кровлю"), (r"штукатур|плиточ|отделк", "про отделку"), (r"ремонт", "про ремонт"), (r"строительств|строим", "про строительство")],
    },
    "auto": {
        "kw": re.compile(r"автомобил|автосервис|автоподбор|автоблог|автоэксперт|(?<![а-яё])авто(?![а-яё])|детейлинг|тюнинг|спорткар|двигател|"
                         r"шиномонтаж|кузов|bmw|мотор", re.I),
        "queries": ["детейлинг", "автоподбор", "тюнинг авто", "автосервис блог", "авто эксперт", "спорткары блог", "ремонт двигателей блог"],
        "pitch": ["беру видео для автобизнеса на себя: мастера снимают работу по минуте в день, монтаж под музыку и публикация на мне",
                  "делаю ролики для автосервисов и детейлинга без вашего участия, мастера снимают процесс по минуте в день, остальное на мне"],
        "topics": [(r"детейлинг|полировк", "про детейлинг"), (r"тюнинг", "про тюнинг"), (r"подбор", "про подбор авто"),
                   (r"спорткар|bmw|мотор|двигател", "про моторы и спорткары"), (r"автосервис|ремонт", "про автосервис")],
    },
    "craft": {
        "kw": re.compile(r"ателье|пошив|кожаны|изделия из кожи|кожевен|мебел\w* на заказ|ювелир|столярн|ручной работы|мастерск", re.I),
        "queries": ["ателье пошив", "индивидуальный пошив", "кожаные изделия", "мебель на заказ", "мастерская ручной работы", "ювелир мастер"],
        "pitch": ["беру видео для мастерских и ателье на себя: вы снимаете процесс по минуте в день, монтаж и публикация на мне",
                  "делаю так, чтобы ремесло в мастерской и ателье выглядело дорого, вы снимаете по минуте в день, остальное на мне"],
        "topics": [(r"кож", "про изделия из кожи"), (r"пошив|ателье", "про пошив"), (r"мебел", "про мебель"), (r"ювелир", "про украшения"),
                   (r"столярн", "про работу с деревом")],
    },
}
QUERIES = [q for grp in zip(*(v["queries"] for v in NICHES.values())) for q in grp] + \
          [q for v in NICHES.values() for q in v["queries"][min(len(w["queries"]) for w in NICHES.values()):]]   # по кругу между направлениями

FRESH_DAYS = 21
SUBS = (300, 60000)
FIRST_PERSON = re.compile(r"(?<![а-яё])(я|мне|меня|мой|моя|мои|моих|моим|ко мне|расскажу|помогаю|помогу|делаем|делаю|строим|строю|наш|мы)(?![а-яё])", re.I)
SELLS = re.compile(r"консультац|запис|услуг|клиент|обращ|напиши|пишите|заявк|заказ|стоимост|прайс|расч[её]т|под ключ", re.I)
STOP_TITLE = re.compile(r"суд\b|новост|news|министер|администрац|вестник|журнал|газет|медиа|дайджест|подборк|каталог|\bчат\b|вакан|работа\b|"
                        r"монтаж|рилсмейк|видеограф|продакшн|production|барахолк|объявлен|форум|куплю|продам|биржа|маркетплейс|"
                        r"курс|школа|академи|обучени", re.I)
SCHOOL = re.compile(r"курс|школа|академи|обучени|обучаю|марафон|интенсив|наставничеств|университет|колледж", re.I)
COMPETITOR = re.compile(r"монтаж[её]р|видеомонтаж|рилсмейкер|reelsmaker|мобилограф|видеограф|моушн|motion", re.I)
AD_NEAR = re.compile(r"(реклам\w*|\bads\b|прайс на рекламу|размещени\w*)[^@]{0,25}$", re.I)

B.RU_NAMES |= set("""артур давид марк даниил данил данила богдан ринат рустам тигран арина алёна ульяна милена""".split())

def _no_dm(text):
    try:
        import guard
        return guard.no_dm(text)
    except Exception:
        return ""

def owner_handles(desc, channel):
    """Ники из описания канала; менеджер по рекламе — последним (он не владелец)."""
    out = []
    for m in re.finditer(r"@([A-Za-z][A-Za-z0-9_]{4,31})|t\.me/([A-Za-z][A-Za-z0-9_]{4,31})", desc or ""):
        u = m.group(1) or m.group(2)
        if u.lower() == channel.lower() or u in [x for x, _ in out] or u.lower().endswith("bot"): continue
        out.append((u, bool(AD_NEAR.search(desc[max(0, m.start() - 40):m.start()]))))
    return [u for u, ad in sorted(out, key=lambda x: x[1])]

CONTACT_HINTS = ("связ", "вопрос", "консультац", "запис", "пишите", "писать", "заказ", "заявк", "менеджер", "контакт", "директ", "личк", "лс", "мастер", "обращ")

def post_handles(ch, channel):
    """Ники из постов рядом со словами «заказ / запись / пишите» (свежие посты первыми) — когда в описании контакта нет."""
    out = []
    for p in reversed(ch.get("posts", [])):
        t = p.get("text", "")
        for m in re.finditer(r"@([A-Za-z][A-Za-z0-9_]{4,31})", t):
            ctx = t[max(0, m.start() - 60):m.start()].lower()
            u = m.group(1)
            if not any(k in ctx for k in CONTACT_HINTS) or "реклам" in ctx or AD_NEAR.search(ctx): continue
            if u.lower() == channel.lower() or u.lower().endswith("bot") or u in out: continue
            out.append(u)
    return out

def _fresh(posts, days):
    now = datetime.datetime.now(datetime.timezone.utc)
    return [p for p in posts if p.get("when") and (now - p["when"]).days <= days]

def _person(u, skip):
    if not u or skip(u) or u.lower().endswith("bot"): return False
    k = B.tg_kind(u); time.sleep(0.5)
    return k == "person"

def niche_of(ch):
    """build|auto|craft или '' — по названию/описанию (вес 3) и последним постам (вес 1); порог 4, как у основного бота."""
    head = f"{ch.get('title', '')} {ch.get('desc', '')}"
    body = " ".join(p.get("text", "") for p in ch.get("posts", [])[-10:])
    best, score = "", 0
    for n, v in NICHES.items():
        s = 3 * len(v["kw"].findall(head)) + len(v["kw"].findall(body))
        if s > score: best, score = n, s
    return best if score >= 4 else ""

def is_master(ch):
    """Живой мастер/владелец, а не новости, чат, курс или конкурент-монтажёр: пишет от первого лица и принимает заказы."""
    if STOP_TITLE.search(ch.get("title", "")) or COMPETITOR.search(ch.get("title", "")): return False
    if len(SCHOOL.findall(ch.get("desc", ""))) >= 2: return False
    txt = " ".join(p.get("text", "") for p in ch.get("posts", [])) + " " + ch.get("desc", "")
    return len(FIRST_PERSON.findall(txt)) >= 3 and bool(SELLS.search(txt))

# ---------------------------------------------------------------- сообщение
def topic(niche, text):
    for rx, w in NICHES[niche]["topics"]:
        if re.search(rx, text or "", re.I): return w
    return ""

def template(c):
    """Как пишет Егор с телефона: со строчной после приветствия, на запятых, без точки в конце, одна деталь, один вопрос."""
    R = random.choice
    cap = lambda s: s[:1].upper() + s[1:]
    fn = B.first_name(c.get("who", ""))
    hi = f"{fn}, {R(['добрый день', 'здравствуйте'])}" if fn else R(["Добрый день", "Здравствуйте"])
    tp = topic(c["niche"], (c.get("snippet") or "") + " " + (c.get("title") or ""))
    if tp:
        a = R([f"{hi}, наткнулся на ваш канал {tp}", f"{hi}, посмотрел ваш канал, вы пишете {tp}", f"{hi}, полистал ваш канал, особенно {tp}"])
    else:
        a = R([f"{hi}, наткнулся на ваш канал, понравилось, как показываете работу", f"{hi}, посмотрел ваш канал, сильная подача"])
    if c.get("video_share", 1) < 0.15 and R([0, 1]): a += ", видео у вас почти нет"
    b = "Я Егор, " + R(NICHES[c["niche"]]["pitch"])
    ask = R(["Видео сейчас снимаете, заявки с него приходят?", "Видео сейчас отнимает у вас время?", "Видео сейчас в планах?"])
    text = f"{a}\n{cap(b)}. {ask}"
    try:
        import human
        text = human.humanize(text)
    except Exception:
        pass
    return text

def item_of(c):
    return {"username": c["username"], "invited": False, "found": time.time(), "post": "", "display": c.get("who") or c.get("title") or "",
            "variant": "NICHE", "niche": "мастера-" + c["niche"], "uniq": 1, "source": c["source"],
            "pain": {},      # 16.11: первое письмо = 2 строки; «боль до диалога» (analyst.inject) добавила бы третью
            "ctx": (f"Направление: {c['niche']} (Telegram-канал мастера)\nКанал: {c.get('title') or ''}\n"
                    f"Подписчиков: {c.get('subs', '')}\nТекст: {c.get('snippet', '')}")[:2000],
            "text": re.sub(r"\s*\n\s*", "\n\n", c["text"].strip())}

# ---------------------------------------------------------------- поиск
def check_channel(name, ch, ns, skip):
    """Канал → кандидат (контакт владельца), ссылки профильного канала → снежный ком."""
    niche = niche_of(ch)
    if not niche: return []
    fr = ns["frontier"]; known = set(ns["seen"]) | {x.lower() for x in fr}
    for n in re.findall(r"t\.me/([A-Za-z][A-Za-z0-9_]{4,31})", ch.get("desc", "")) + [l for p in ch["posts"][-10:] for l in p.get("links", [])][:20]:
        if n.lower() not in known and not n.lower().endswith("bot"): fr.append(n); known.add(n.lower())
    for n in re.findall(r"@([A-Za-z][A-Za-z0-9_]{4,31})", ch.get("desc", "") + " " + " ".join(p.get("text", "") for p in ch["posts"][-10:]))[:25]:
        if n.lower() not in known and not n.lower().endswith("bot"): fr.append(n); known.add(n.lower())   # упомянутые каналы и люди
    if not is_master(ch) or _no_dm(ch.get("desc", "")): return []
    if not (SUBS[0] <= (ch.get("subs") or 0) <= SUBS[1]) or not _fresh(ch["posts"], FRESH_DAYS): return []
    handles = owner_handles(ch.get("desc", ""), name)
    handles += [u for u in post_handles(ch, name) if u not in handles]
    for u in handles[:4]:
        if _person(u, skip):
            last = next((p["text"] for p in reversed(ch["posts"]) if len(p.get("text", "")) > 60), "")
            vids = sum(1 for p in ch["posts"] if p.get("video"))
            return [{"username": u, "niche": niche, "title": ch.get("title") or name, "subs": ch.get("subs"),
                     "snippet": (ch.get("desc", "") + " | " + last)[:500], "source": f"https://t.me/{name}",
                     "video_share": vids / max(len(ch["posts"]), 1), "who": (B.TG_INFO.get(u.lower()) or {}).get("title", "")}]
    return []

def niche_step(ns, skip=lambda u: False, tg_search=None, parse=None, max_new=2, max_check=6):
    """Один шаг (autoclient зовёт раз в 15 мин): проверить до max_check каналов, вернуть до max_new писем.
    ns — st["niches"] в state.json основного бота. parse(name) — autoclient.parse_channel (t.me/s)."""
    if not parse: return []
    for k, v in (("frontier", []), ("seen", []), ("qi", 0), ("pending", [])):
        ns.setdefault(k, v)
    seen = set(ns["seen"])
    cands = []
    if not ns["frontier"] and tg_search:
        q = QUERIES[ns["qi"] % len(QUERIES)]; ns["qi"] += 1
        try:
            found = [n for n in tg_search(q) if n.lower() not in seen]
            ns["frontier"] += found; log(f"поиск «{q}»: новых каналов {len(found)}")
        except Exception as e:
            log("поиск не удался:", str(e)[:80])
    for _ in range(max_check):
        if not ns["frontier"] or len(cands) >= max_new: break
        n = ns["frontier"].pop(0)
        if n.lower() in seen: continue
        seen.add(n.lower())
        ch = parse(n); time.sleep(random.uniform(1, 2))
        if ch: cands += check_channel(n, ch, ns, skip)
    ns["seen"] = list(seen)[-8000:]; ns["frontier"] = ns["frontier"][:300]
    pend = {c["username"].lower(): c for c in ns["pending"] + cands}
    out = []
    for ul, c in list(pend.items()):
        if len(out) >= max_new: break
        del pend[ul]
        if skip(c["username"]): continue
        c["text"] = template(c)
        out.append(item_of(c))
        log(f"мастер @{c['username']} ({c['niche']}) ← {c['source']}")
    ns["pending"] = list(pend.values())[:30]
    return out

if __name__ == "__main__":        # локальная проверка без отправки: поиск через DuckDuckGo/Bing + шаблоны
    sys.path.insert(0, os.path.join(os.path.dirname(BASE), "Автопоиск клиентов (telegram)", "auto"))
    import autoclient
    ns = {}
    for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 3):
        for it in niche_step(ns, tg_search=autoclient.search_engines, parse=autoclient.parse_channel):
            print("\n=== @" + it["username"], it["niche"], it["source"], "\n" + it["text"])
    print("\nseen:", len(ns.get("seen", [])), "pending:", len(ns.get("pending", [])))
