# -*- coding: utf-8 -*-
"""ПОИСК БИЗНЕСА — сам находит компании, которые готовы вкладываться в соцсети, и сам пишет им первое предложение.

    python bizhunt.py            боевой режим: ищет, пишет письма, отправляет (если включено в config.json), ловит ответы
    python bizhunt.py --dry      только ищет и пишет письма в ЧЕРНОВИКИ.md, ничего не отправляет
    python bizhunt.py --once     один круг и выход (удобно для проверки)
    python bizhunt.py --test-mail  отправляет одно тестовое письмо самому себе (проверка почты)

Источники:
  1. hh.ru — компании, которые ищут SMM-менеджера / маркетолога / мобилографа. Раз ищут, бюджет на соцсети есть.
  2. 2ГИС — компании по нишам и крупным городам (нужен ключ API в config.json → "gis_key").
Обогащение: сайт компании → почта, Telegram, ВК, Instagram, YouTube.
Письмо: персональное, через ИИ (Groq/бесплатный), с проверкой autoreply._sane; при сбое ИИ — шаблон.
Отправка: почта (SMTP отдельного ящика) и Telegram (через очередь auto/biz_tg.json → autoclient).
Ответы: IMAP раз в 10 минут → уведомление Егору в бота.
"""
import os, re, sys, json, time, random, html, datetime, smtplib, imaplib, email, csv, traceback
import urllib.request, urllib.parse, urllib.error
from email.message import EmailMessage
from email.utils import make_msgid, formataddr, parseaddr
from email.header import decode_header

BASE = os.path.dirname(os.path.abspath(__file__))
SALES = os.path.dirname(BASE)
AUTO = os.path.join(SALES, "Автопоиск клиентов (telegram)", "auto")
sys.path.insert(0, AUTO)

CFG_FILE = os.path.join(BASE, "config.json")
STATE_FILE = os.path.join(BASE, "state.json")
LOGF = os.path.join(BASE, "log.txt")
DRAFTS = os.path.join(BASE, "ЧЕРНОВИКИ.md")
LEADS_CSV = os.path.join(BASE, "ЛИДЫ.csv")
TG_QUEUE = os.path.join(AUTO, "biz_tg.json")

DRY = "--dry" in sys.argv
ONCE = "--once" in sys.argv
TEST_MAIL = "--test-mail" in sys.argv

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
PORTFOLIO = "https://t.me/zakulisy715"
MY_TG = "@chernyshev_edit"
MY_ID = 5787402361

DEFAULT_CFG = {
    "_help": "send_email / send_tg = true включают автоотправку. Пароль почты — пароль ПРИЛОЖЕНИЯ (Яндекс ID → Безопасность → Пароли приложений).",
    "send_email": False,
    "send_tg": False,
    "gis_key": "",
    "groq_api_key": "",
    "smtp": {"host": "smtp.yandex.ru", "port": 465, "user": "", "password": "", "from_name": "Егор | ролики для бизнеса"},
    "imap": {"host": "imap.yandex.ru", "port": 993},
    "limits": {"email_per_day": 30, "tg_per_day": 8, "gap_min": [4, 9], "hours_msk": [9, 19],
               "followup_days": 3, "letters_per_cycle": 6, "min_reviews_2gis": 15},
    "cities": ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань", "Нижний Новгород", "Краснодар",
               "Самара", "Ростов-на-Дону", "Уфа", "Красноярск", "Пермь", "Воронеж", "Тюмень", "Челябинск", "Омск"],
    "gis_queries": ["стоматология", "косметология", "агентство недвижимости", "застройщик", "ремонт квартир",
                    "кухни на заказ", "мебель на заказ", "автосервис", "детейлинг", "фитнес-клуб",
                    "медицинский центр", "салон красоты", "натяжные потолки", "окна пвх"],
    "hh_queries": ["SMM-менеджер", "SMM специалист", "маркетолог", "контент-менеджер", "мобилограф", "рилсмейкер",
                   "специалист по продвижению в социальных сетях"],
    "hh_every_hours": 3,
}

# ---------------------------------------------------------------- утилиты
def log(*a):
    line = datetime.datetime.now().strftime("%d.%m %H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
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

def load_cfg():
    cfg = jload(CFG_FILE, None)
    if cfg is None:
        jsave(CFG_FILE, DEFAULT_CFG); cfg = json.loads(json.dumps(DEFAULT_CFG))
        log("создан config.json — заполни почту и ключ 2ГИС")
    for k, v in DEFAULT_CFG.items():                      # новые поля из DEFAULT подмешиваем, не трогая заполненные
        if k not in cfg: cfg[k] = v
        elif isinstance(v, dict):
            for kk, vv in v.items(): cfg[k].setdefault(kk, vv)
    if cfg.get("groq_api_key"): os.environ.setdefault("GROQ_API_KEY", cfg["groq_api_key"])
    return cfg

def msk_now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))

def today():
    return msk_now().strftime("%Y-%m-%d")

def fetch(url, timeout=20, headers=None, raw=False):
    h = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}
    if headers: h.update(headers)
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)
        b = r.read(3_000_000)
        return b if raw else b.decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception as e:
        return None

def clean(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t\xa0]+", " ", html.unescape(s)).strip()

def domain_of(url):
    try:
        d = urllib.parse.urlparse(url if "//" in url else "http://" + url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception: return ""

_BOT = [None]
def notify(text):
    log("УВЕДОМЛЕНИЕ:", text.replace("\n", " / ")[:200])
    if DRY: return
    try:
        if _BOT[0] is None:
            d = BASE; tok = ""
            for _ in range(5):
                for cand in (os.path.join(d, ".telegram-bot.txt"), os.path.join(d, "05 Доступы и служебное", ".telegram-bot.txt")):
                    if os.path.exists(cand):
                        m = re.search(r"\d{6,}:[A-Za-z0-9_-]{30,}", open(cand, encoding="utf-8").read()); tok = m.group(0) if m else ""
                        break
                if tok: break
                d = os.path.dirname(d)
            _BOT[0] = os.environ.get("BOT_TOKEN") or tok
        if not _BOT[0]: return
        body = json.dumps({"chat_id": MY_ID, "text": text[:4000], "disable_web_page_preview": True}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{_BOT[0]}/sendMessage", data=body,
                               headers={"Content-Type": "application/json"}), timeout=20).read()
    except Exception as e:
        log("бот не отправил уведомление:", str(e)[:80])

# ---------------------------------------------------------------- 1. hh.ru
AGENCY = re.compile(r"кадров|рекрут|recruit|staff|персонал|аутстафф|hr[- ]?агентств", re.I)
ROLE_OK = re.compile(r"smm|смм|маркет|контент|content|мобилограф|рилс|reels|shorts|видео|video|продвижен|соц\.?\s?сет|social|"
                     r"таргет|бренд|brand|pr[- ]|пиар|креатив|сторис|tiktok|ютуб|youtube", re.I)
ROLE_HOT = re.compile(r"мобилограф|рилс|reels|shorts|видео|video|монтаж|сторис|tiktok|ютуб|youtube|контент-?мейкер", re.I)
FIO = re.compile(r"^[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+(вич|вна|ична|кызы|оглы)$")

def priority(c):
    """3 — ищут видео-человека прямо сейчас, 2 — ищут SMM/маркетолога, 1 — компания из 2ГИС."""
    if c.get("vacancy") and ROLE_HOT.search(c["vacancy"]): return 3
    if c.get("vacancy"): return 2
    return 1

def hh_search(query, page=0):
    """Вакансии за 3 дня по всей России с публичной страницы поиска hh.ru."""
    url = ("https://hh.ru/search/vacancy?" + urllib.parse.urlencode(
        {"text": query, "area": 113, "search_period": 3, "order_by": "publication_time", "page": page}))
    h = fetch(url, timeout=30)
    if not h: return []
    m = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>(.*?)</template>', h, re.S)
    if not m: return []
    try: data = json.loads(html.unescape(m.group(1)))
    except Exception: return []
    out = []
    for v in (data.get("vacancySearchResult") or {}).get("vacancies") or []:
        c = v.get("company") or {}
        comp = v.get("compensation") or {}
        if not c.get("id") or AGENCY.search(c.get("name", "")) or not ROLE_OK.search(v.get("name", "")): continue
        sal = ""
        if comp.get("from") or comp.get("to"):
            sal = f"{comp.get('from') or ''}–{comp.get('to') or ''} {comp.get('currencyCode', '')}".strip("– ")
        out.append({
            "key": f"hh:{c['id']}",
            "source": "hh", "name": c.get("visibleName") or c.get("name"), "city": (v.get("area") or {}).get("name", ""),
            "site": c.get("companySiteUrl") or "", "vacancy": v.get("name", ""), "salary": sal,
            "vacancy_url": (v.get("links") or {}).get("desktop", "").replace("belovo.hh.ru", "hh.ru"),
            "hh_employer": f"https://hh.ru/employer/{c['id']}", "niche": "", "query": query,
        })
    return out

def hh_employer_site(emp_url):
    h = fetch(emp_url, timeout=25)
    if not h: return ""
    m = re.search(r'"companySiteUrl"\s*:\s*"([^"]+)"', html.unescape(h)) or re.search(r'data-qa="sidebar-company-site"[^>]*href="([^"]+)"', h)
    return m.group(1) if m else ""

# ---------------------------------------------------------------- 2. 2ГИС (официальный Catalog API)
GIS = "https://catalog.api.2gis.com"

def gis_region(city, key, st):
    cache = st.setdefault("gis_regions", {})
    if city in cache: return cache[city]
    h = fetch(f"{GIS}/2.0/region/search?" + urllib.parse.urlencode({"q": city, "key": key}))
    rid = None
    try: rid = json.loads(h)["result"]["items"][0]["id"]
    except Exception: pass
    cache[city] = rid
    return rid

def gis_search(query, city, key, st, page=1, min_reviews=15):
    rid = gis_region(city, key, st)
    if not rid: return [], "регион не найден"
    params = {"q": query, "region_id": rid, "type": "branch", "page": page, "page_size": 10, "key": key,
              "fields": "items.contact_groups,items.rubrics,items.reviews,items.org,items.address"}
    h = fetch(f"{GIS}/3.0/items?" + urllib.parse.urlencode(params), timeout=25)
    if h is None: return [], "нет ответа"
    try: j = json.loads(h)
    except Exception: return [], "не JSON"
    code = (j.get("meta") or {}).get("code")
    if code != 200: return [], f"код {code}: {(j.get('meta') or {}).get('error', {}).get('message', '')}"
    out = []
    for it in (j.get("result") or {}).get("items") or []:
        rv = it.get("reviews") or {}
        cnt = rv.get("general_review_count") or rv.get("org_review_count") or 0
        if cnt < min_reviews: continue                      # мелочь без отзывов обычно без бюджета
        org = (it.get("org") or {}).get("id") or it.get("id")
        c = {"emails": [], "tg": [], "socials": {}, "site": ""}
        for g in it.get("contact_groups") or []:
            for x in g.get("contacts") or []:
                t, val, url = x.get("type"), x.get("value") or "", x.get("url") or ""
                if t == "email" and val: c["emails"].append(val.lower())
                elif t == "website": c["site"] = c["site"] or ("https://" + (x.get("text") or val).strip("/") if (x.get("text") or val) and "2gis" not in (x.get("text") or val) else url)
                elif t == "telegram": c["tg"].append(url or val)
                elif t in ("vkontakte", "instagram", "youtube", "whatsapp", "ok", "rutube", "dzen"):
                    c["socials"][t] = url or val
        out.append({
            "key": f"gis:{org}", "source": "2gis", "name": it.get("name", "").split(",")[0], "city": city,
            "site": c["site"], "emails": c["emails"], "tg_raw": c["tg"], "socials": c["socials"],
            "niche": query, "rating": rv.get("general_rating"), "reviews": cnt,
            "address": it.get("address_name") or "", "gis_url": f"https://2gis.ru/firm/{it.get('id', '').split('_')[0]}",
            "query": query,
        })
    return out, ""

# ---------------------------------------------------------------- 3. обогащение: сайт → почта, Telegram, соцсети
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,10}")
BAD_EMAIL = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$|example\.|sentry|wixpress|domain\.|email@|your@|name@|test@|@2x", re.I)
SOC = {"vk": r"https?://(?:m\.)?vk\.(?:com|ru)/[A-Za-z0-9_.]+", "instagram": r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.]+",
       "youtube": r"https?://(?:www\.)?youtube\.com/(?:@|c/|channel/)[A-Za-z0-9_\-]+", "rutube": r"https?://rutube\.ru/channel/\d+",
       "dzen": r"https?://dzen\.ru/[A-Za-z0-9_.]+", "whatsapp": r"https?://(?:wa\.me|api\.whatsapp\.com)/[^\s\"'<>]+"}
TME = re.compile(r"(?:https?:)?//t\.me/([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_/])")

TG_INFO = {}
def tg_kind(u):
    """'person' — можно писать в личку; 'channel'/'group' — это канал; 'bot'/None — не годится.
    Имя и описание страницы кладутся в TG_INFO[u] (имя — для обращения, описание канала — чтобы найти контакт владельца)."""
    if u.lower().endswith("bot"): return "bot"
    h = fetch(f"https://t.me/{u}", timeout=15)
    if not h or "tgme_page_title" not in h: return None
    title = clean((re.search(r'tgme_page_title[^>]*>(.*?)</div>', h, re.S) or [None, ""])[1])
    desc = clean((re.search(r'tgme_page_description[^>]*>(.*?)</div>', h, re.S) or [None, ""])[1])
    TG_INFO[u.lower()] = {"title": title, "desc": desc}
    extra = clean((re.search(r'tgme_page_extra[^>]*>(.*?)</div>', h, re.S) or [None, ""])[1]).lower()
    if "subscriber" in extra or "подписчик" in extra: return "channel"
    if "member" in extra or "участник" in extra: return "group"
    return "person"

def handles_in(text):
    """@ники и t.me-ссылки из текста — только те, что про Telegram (guard.tg_handles отсекает Instagram/TikTok)."""
    try:
        import guard
        hs = guard.tg_handles(text)
    except Exception:
        hs = re.findall(r"@([A-Za-z][A-Za-z0-9_]{4,31})", text or "")
    return list(dict.fromkeys(hs + TME.findall(text or "")))

def hh_vacancy_contacts(url):
    """Текст вакансии hh: Telegram-контакт работодателя («пишите в тг @...») и запрет писать в личку, если он есть."""
    h = fetch(url, timeout=25)
    if not h: return [], ""
    i = h.find('data-qa="vacancy-description"')
    text = clean(h[i:i + 20000]) if i >= 0 else ""
    try:
        import guard
        stop = guard.no_dm(text)
    except Exception:
        stop = ""
    return handles_in(text), stop

def enrich(c):
    site = c.get("site") or ""
    emails = set(c.get("emails") or []); tgs = set(); socials = dict(c.get("socials") or {})
    for raw in c.pop("tg_raw", []) or []:
        m = TME.search(raw) or re.match(r"@?([A-Za-z][A-Za-z0-9_]{4,31})$", raw.strip())
        if m: tgs.add(m.group(1))
    if site and not re.search(r"vk\.(com|ru)|instagram\.com|t\.me/", site):
        root = site if site.startswith("http") else "https://" + site
        pages = [root]
        h0 = fetch(root, timeout=20)
        if h0:
            for m in re.finditer(r'href="([^"]*(?:contact|kontakt|контакт|about|o-nas|o_nas)[^"]*)"', h0, re.I):
                pages.append(urllib.parse.urljoin(root, m.group(1)))
        for i, p in enumerate(dict.fromkeys(pages[:3])):
            h = h0 if i == 0 else fetch(p, timeout=20)
            if not h: continue
            hh = html.unescape(h)
            for e in EMAIL_RE.findall(hh.replace("&#64;", "@")):
                if not BAD_EMAIL.search(e): emails.add(e.lower().strip("."))
            for u in TME.findall(hh): tgs.add(u)
            for k, rx in SOC.items():
                if k not in socials:
                    m = re.search(rx, hh)
                    if m: socials[k] = m.group(0)
    elif "vk." in site: socials.setdefault("vk", site)
    elif "instagram" in site: socials.setdefault("instagram", site)
    elif "t.me/" in site:
        m = TME.search(site); tgs.add(m.group(1)) if m else None
    tg_person, tg_channel = [], []
    for u in c.get("tg_vacancy", []): tgs.add(u)                 # контакт из текста вакансии hh — самый точный
    tgs = list({u.lower(): u for u in tgs}.values())
    tgs.sort(key=lambda u: 0 if u in c.get("tg_vacancy", []) else 1)
    for u in tgs[:4]:
        k = tg_kind(u); time.sleep(0.5)
        if k == "person": tg_person.append(u)
        elif k in ("channel", "group"):
            tg_channel.append(u)
            for h2 in handles_in((TG_INFO.get(u.lower()) or {}).get("desc", ""))[:2]:   # «по вопросам/рекламе — @...» в описании канала
                if h2.lower() != u.lower() and tg_kind(h2) == "person": tg_person.append(h2)
                time.sleep(0.5)
    if tg_channel: socials.setdefault("telegram", "https://t.me/" + tg_channel[0])
    tg_person = list({u.lower(): u for u in tg_person}.values())
    dom = domain_of(site)
    em = sorted(emails, key=lambda e: (0 if dom and e.endswith("@" + dom) else 1,
                                        0 if re.match(r"(info|hello|office|mail|pr|marketing|smm|director|ceo)@", e) else 1))
    c.update({"emails": em[:3], "tg": tg_person[:2], "socials": socials, "domain": dom})
    return c

# ---------------------------------------------------------------- 4. письмо
BIZ = """Ты пишешь первое письмо компании от имени Егора: он делает для бизнеса короткие ролики под ключ (стратегия, сценарии, раскадровка, монтаж Reels/Shorts/клипов). Компания его не ждёт, поэтому за 10 секунд письмо должно показать: «человек посмотрел именно нас и понял, чем может помочь».
Тебе дадут факты о компании: название, город, ниша, рейтинг и отзывы в 2ГИС, какие соцсети есть, и (если есть) вакансию, которую они сейчас открыли на hh.ru.
Как писать:
1) Обращение без имени: «Добрый день» или «Здравствуйте», дальше со строчной буквы.
2) Одно конкретное наблюдение из фактов. Если есть вакансия SMM/маркетолога — скажи, что увидел, что они ищут человека в соцсети, и что видео обычно самое узкое место: SMM-щик пишет посты, а ролики снимать и монтировать некому. Если вакансии нет — оттолкнись от ниши, рейтинга и соцсетей (много отзывов, а в соцсетях видео почти нет; или соцсетей нет вообще). Не выдумывай того, чего нет в фактах (не пиши, что смотрел их ролики, если соцсетей в фактах нет).
3) Одна фраза — чем это помогает именно в их нише (клиент видит процесс/результат/людей до того, как придёт).
4) Одним предложением: Егор делает ролики под ключ — сценарии, раскадровка, монтаж, им нужно только снять на телефон по готовому плану.
5) Лёгкое бесплатное предложение без давления: короткий разбор их соцсетей (3 вещи, которые бы поправил) или 3 идеи роликов под их нишу, «а там уже сами глянете, нужно вам такое или нет».
6) Один вопрос в конце.
Нельзя: цены, скидки, обещания результата и цифр, выдуманные кейсы и клиенты, съёмка на месте, ведение аккаунта, реклама, «уважаемые», «с уважением», «привет», «буду рад», эмодзи, восклицательные знаки. Мужской род от первого лица.
Тема письма: 3–6 слов, по-человечески, без кликбейта и без слова «предложение» (например: «Ролики для {название}»).
{VOICE}
Ответ строго JSON: {"subject": "тема", "text": "письмо без подписи"}"""

FOLLOW_BIZ = """Ты пишешь одно короткое повторное письмо (через 3 дня) компании от имени Егора, который делает ролики под ключ. Тебе дадут первое письмо. 1–2 предложения: новая ценность (одна конкретная идея ролика под их нишу) и лёгкий выход «если неактуально, напишите нет, больше не побеспокою». Без упрёков, без «напоминаю», без цен, без эмодзи. Мужской род.
Ответ строго JSON: {"text": "письмо"}"""

SIGN = ("\n\nЕгор, ролики для бизнеса под ключ\nПримеры работ: " + PORTFOLIO + "\nTelegram: " + MY_TG +
        "\n\nЕсли неактуально, просто ответьте «нет», больше не напишу")

def facts_of(c):
    soc = ", ".join(sorted(c.get("socials", {}).keys())) or "в открытом доступе не нашёл"
    f = [f"Название: {c.get('name')}", f"Город: {c.get('city')}"]
    if c.get("niche"): f.append(f"Ниша: {c['niche']}")
    if c.get("reviews"): f.append(f"2ГИС: рейтинг {c.get('rating')}, отзывов {c['reviews']}")
    if c.get("vacancy"): f.append(f"Сейчас на hh.ru открыта вакансия: «{c['vacancy']}»" + (f", зарплата {c['salary']}" if c.get("salary") else ""))
    f.append(f"Соцсети: {soc}")
    if c.get("site"): f.append(f"Сайт: {c['site']}")
    return "\n".join(f)

def template_letter(c):
    nm = c.get("name") or "вас"
    if c.get("vacancy"):
        obs = (f"увидел, что вы ищете человека на позицию «{c['vacancy']}», и обычно самое узкое место там видео: "
               "посты SMM-щик напишет, а снимать и монтировать ролики некому")
    elif c.get("reviews") and c["reviews"] >= 50:
        obs = f"посмотрел {nm} в 2ГИС, {c['reviews']} отзывов, видно, что клиенты вас любят, а в соцсетях это почти не видно в видео"
    else:
        obs = f"посмотрел {nm}, в вашей нише короткие ролики как раз дают людям увидеть процесс и результат до того, как они придут"
    text = (f"Добрый день, {obs}\n"
            "Я делаю ролики для бизнеса под ключ: сценарии, раскадровка и монтаж, вам остаётся только снять на телефон по готовому плану\n"
            "Могу бесплатно сделать короткий разбор ваших соцсетей, 3 вещи, которые бы поправил, а там уже сами глянете, нужно вам такое или нет\n"
            "Скинуть?")
    return {"subject": subject_for(c), "text": text}

def subject_for(c):
    nm = (c.get("name") or "").strip()
    if not nm or FIO.match(nm) or len(nm) > 40: return "Видео для ваших соцсетей"
    return f"Ролики для «{nm}»"

def compose(c):
    try:
        import autoreply
        if autoreply.llm_on():
            j, prov = autoreply._llm(BIZ.replace("{VOICE}", autoreply.VOICE), [{"role": "user", "content": facts_of(c)}], 700)
            if j:
                txt = autoreply.voicefy(str(j.get("text", "")).strip())
                subj = re.sub(r"[!.]+$", "", str(j.get("subject", "")).strip())[:80]
                if FIO.match(c.get("name") or "") or not subj: subj = subject_for(c)
                if 120 <= len(txt) <= 1100 and subj and autoreply._sane(txt, first=True) and autoreply._COMPLEX.search(txt):
                    return {"subject": subj, "text": txt, "by": prov}
                log("ИИ-письмо отбраковано, беру шаблон:", c.get("name"))
    except Exception as e:
        log("ИИ недоступен:", str(e)[:80])
    t = template_letter(c); t["by"] = "шаблон"
    return t

def compose_follow(c):
    try:
        import autoreply
        if autoreply.llm_on():
            j, _ = autoreply._llm(FOLLOW_BIZ, [{"role": "user", "content": facts_of(c) + "\n\nПервое письмо:\n" + c.get("letter", "")}], 300)
            if j:
                t = autoreply.voicefy(str(j.get("text", "")).strip())
                if 40 <= len(t) <= 500 and autoreply._sane(t, first=True): return t
    except Exception: pass
    return ("Добрый день, возвращаюсь с одной идеей: короткий ролик «как мы работаем изнутри» обычно лучше всего заходит в вашей нише, "
            "могу расписать его под вас бесплатно\nЕсли неактуально, напишите «нет», больше не побеспокою")

# ---------------------------------------------------------------- 5. почта
def smtp_send(cfg, to, subject, body, reply_to_id=None):
    s = cfg["smtp"]
    msg = EmailMessage()
    msg["From"] = formataddr((s.get("from_name") or "Егор", s["user"]))
    msg["To"] = to
    msg["Subject"] = subject
    mid = make_msgid(domain=s["user"].split("@")[-1])
    msg["Message-ID"] = mid
    if reply_to_id:
        msg["In-Reply-To"] = reply_to_id; msg["References"] = reply_to_id
    msg.set_content(body)
    with smtplib.SMTP_SSL(s["host"], int(s["port"]), timeout=40) as srv:
        srv.login(s["user"], s["password"])
        srv.send_message(msg)
    return mid

NEG = re.compile(r"\bнет\b|не актуальн|неактуальн|не интерес|не нужн|не пишите|отпиш|спам|не беспокой|unsubscribe", re.I)

def _dec(v):
    out = ""
    for part, enc in decode_header(v or ""):
        out += part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part
    return out

def _body(msg):
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() == "text/plain" and "attachment" not in str(p.get("Content-Disposition") or ""):
                try: return p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
                except Exception: pass
        return ""
    try: return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
    except Exception: return ""

def imap_check(cfg, st):
    """Ответы и недоставки → статусы и уведомление Егору. Письма не помечаются прочитанными."""
    s, im = cfg["smtp"], cfg["imap"]
    by_email = {}
    for k, c in st["companies"].items():
        if c.get("email_to") and c.get("status") in ("sent", "fu"): by_email[c["email_to"].lower()] = k
    if not by_email: return
    since = (datetime.date.today() - datetime.timedelta(days=14)).strftime("%d-%b-%Y")
    seen = set(st.setdefault("imap_seen", []))
    M = imaplib.IMAP4_SSL(im["host"], int(im["port"]))
    try:
        M.login(s["user"], s["password"]); M.select("INBOX", readonly=True)
        typ, data = M.search(None, f'(SINCE {since})')
        for num in (data[0].split() if data and data[0] else [])[-300:]:
            typ, d = M.fetch(num, "(BODY.PEEK[])")
            if not d or not d[0]: continue
            msg = email.message_from_bytes(d[0][1])
            mid = msg.get("Message-ID") or f"n{num.decode()}"
            if mid in seen: continue
            seen.add(mid)
            frm = parseaddr(msg.get("From") or "")[1].lower()
            body = _body(msg)
            if "mailer-daemon" in frm or "postmaster" in frm:          # недоставка
                for em, k in by_email.items():
                    if em in body.lower():
                        st["companies"][k]["status"] = "bounce"; log("недоставка:", em)
                continue
            k = by_email.get(frm)
            if not k: continue
            c = st["companies"][k]
            first = re.split(r"\n\s*(>|On .+ wrote:|.+ пишет:|\d{1,2}[./]\d{1,2}[./]\d{2,4}.+:)", body)[0].strip()
            c["status"] = "refused" if NEG.search(first[:300]) and len(first) < 300 else "replied"
            c["reply"] = first[:1500]; c["replied_at"] = msk_now().isoformat(timespec="minutes")
            icon = "❌" if c["status"] == "refused" else "🔥"
            notify(f"{icon} ОТВЕТ НА ПИСЬМО — {c['name']} ({c.get('city', '')}, {c.get('niche') or c.get('vacancy', '')})\n"
                   f"от: {frm}\n\n«{first[:700]}»\n\nТема: {_dec(msg.get('Subject'))}\n"
                   f"{c.get('site') or c.get('gis_url') or ''}\nОтветь из почты {s['user']} — первые минуты решают.")
    finally:
        try: M.logout()
        except Exception: pass
        st["imap_seen"] = list(seen)[-3000:]

# ---------------------------------------------------------------- 6. Telegram — через очередь основного бота
TG_BIZ = """Ты пишешь первое сообщение в Telegram в личку от имени Егора. Он сам, лично, нашёл эту компанию и пишет человеку как живой человек из телефона, а не как рассылка. Егор делает для бизнеса короткие ролики под ключ: стратегия, сценарии, раскадровка, монтаж.
Тебе дадут факты: компания, город, ниша, откуда контакт (вакансия на hh.ru, сайт компании, канал компании), имя человека из профиля Telegram (может быть пустым или названием компании).
Как писать, чтобы не было похоже на рассылку:
— 2–3 очень коротких абзаца (они уйдут отдельными сообщениями), всего 250–500 символов. Как в мессенджере, а не как письмо.
— Если имя похоже на настоящее имя человека — начни «Имя, добрый день,» / «Имя, здравствуйте,». Если имени нет или это название компании — просто «Добрый день,».
— Сразу скажи честно, откуда ты о них знаешь: «увидел вашу вакансию SMM на hh» / «зашёл на ваш сайт» / «увидел ваш канал». Одна конкретная деталь из фактов (город, ниша, позиция в вакансии) — так видно, что писал человек.
— Если вакансия про видео (рилсмейкер, мобилограф, монтажёр, видеограф, контент-креатор): предлагаешь закрыть эту задачу подрядчиком под ключ, без найма в штат и обучения человека.
— Если вакансия SMM/маркетолога: ты не претендуешь на неё, а предлагаешь закрыть видео, чтобы их SMM-щику не пришлось ещё и монтировать.
— Обращайся по имени, только если в профиле настоящее имя человека (Анна, Сергей). «Служба заботы», «Команда …», «Admin», название магазина — это не имя, тогда просто «Добрый день,».
— Одной фразой: делаю ролики под ключ, сценарий и монтаж, им остаётся снять на телефон по плану.
— Лёгкое бесплатное предложение (3 идеи роликов под их нишу или короткий разбор соцсетей) и один простой вопрос в конце, на который легко ответить «да».
— Никаких ссылок, цен, скидок, обещаний результата, выдуманных фактов и кейсов. Не пиши «я бот», «рассылка», «предложение о сотрудничестве», «уважаемые», «с уважением», «буду рад», «привет». Без эмодзи и восклицательных знаков. Мужской род.
{VOICE}
Ответ строго JSON: {"text": "сообщение"}"""

def to_parts(t):
    """Одна «простыня» → 2–3 абзаца по предложениям (основной бот шлёт абзацы отдельными сообщениями, как человек)."""
    t = re.sub(r"\n{2,}", "\n", t).strip()
    if "\n" in t: return t
    s = [x for x in re.split(r"(?<=[.?])\s+", t) if x]
    if len(s) < 3: return t
    a = max(1, len(s) // 3); b = max(a + 1, 2 * len(s) // 3)
    return "\n".join(" ".join(p) for p in (s[:a], s[a:b], s[b:]) if p)

def compose_tg(c):
    who = (TG_INFO.get(c["tg"][0].lower()) or {}).get("title", "") if c.get("tg") else ""
    src = ("вакансия на hh.ru: «" + c["vacancy"] + "»") if c.get("vacancy") else ("канал компании" if c.get("tg_from_channel") else "сайт компании")
    facts = facts_of(c) + f"\nОткуда контакт: {src}\nИмя в профиле Telegram: {who or 'нет'}"
    try:
        import autoreply
        if autoreply.llm_on():
            for _ in range(2):
                j, prov = autoreply._llm(TG_BIZ.replace("{VOICE}", autoreply.VOICE), [{"role": "user", "content": facts}], 500)
                if not j:
                    log("ИИ не ответил (лимит/сбой), беру шаблон:", c.get("name"), autoreply.LAST_ERR); break
                t = autoreply.voicefy(to_parts(str(j.get("text", "")).strip()))
                if 150 <= len(t) <= 700 and "http" not in t and "t.me" not in t and autoreply._sane(t, first=True) and autoreply._COMPLEX.search(t):
                    return t, prov
                log("ИИ-сообщение отбраковано проверкой:", c.get("name"), "|", t[:120].replace("\n", " / "))
    except Exception as e:
        log("ИИ недоступен:", str(e)[:80])
    return template_tg(c, who), "шаблон"

RU_NAMES = set("""александр александра алексей алена алёна алина алиса алла анастасия анатолий андрей анна антон арина арсений артем артём
борис вадим валентина валерия варвара василий вера вероника виктор виктория виталий владимир владислав влад галина георгий глеб григорий
дарья денис диана дмитрий евгений евгения егор екатерина елена елизавета жанна иван игорь илья инна ирина карина кира кирилл константин
кристина ксения лариса лев леонид лилия любовь людмила максим маргарита марина мария матвей милана михаил надежда наталья наталия никита
николай нина оксана олег ольга павел полина роман руслан светлана семен семён сергей софья софия станислав степан тамара татьяна тимофей
тимур ульяна федор фёдор эвелина эдуард элина юлия юрий яна ярослав саша маша даша катя лена оля таня настя женя дима миша лиза аня ира юля
alexander alexandra alexey anna anastasia andrey anton daria dmitry elena ekaterina elizaveta irina ivan julia kirill ksenia maria
marina maxim mikhail natalia nikita olga pavel polina roman sergey sofia svetlana tatiana victoria vladimir yana yulia""".split())

def first_name(who):
    w = re.sub(r"[^\wА-Яа-яЁё ]", " ", who or "").split()
    if not w: return ""
    n = w[0]
    return n.capitalize() if n.lower().replace("ё", "е") in {x.replace("ё", "е") for x in RU_NAMES} else ""

def template_tg(c, who=""):
    """Запасной текст без ИИ. Каждая фраза — из нескольких вариантов, чтобы два сообщения не совпадали дословно."""
    R = random.choice
    fn = first_name(who)
    hi = f"{fn}, {R(['добрый день', 'здравствуйте'])}," if fn else R(["Добрый день,", "Здравствуйте,"])
    vac = c.get("vacancy") or ""
    offer = R(["Могу бесплатно накидать 3 идеи роликов под вашу нишу, а там уже сами глянете, нужно вам такое или нет",
               "Предлагаю так, я бесплатно распишу 3 идеи роликов под вас, а там уже сами глянете",
               "Могу для начала бесплатно сделать короткий разбор, что бы я поменял в ваших роликах, а дальше сами решите"])
    ask = R(["Скинуть?", "Прислать?", "Интересно глянуть?", "Скинуть сюда?"])
    if vac and ROLE_HOT.search(vac):
        a = R([f"{hi} увидел на hh, что вы ищете человека на видео, «{vac}»",
               f"{hi} наткнулся на вашу вакансию на hh, «{vac}»",
               f"{hi} увидел вашу вакансию «{vac}» на hh"])
        b = R(["Я как раз этим занимаюсь, только не в штат, а подрядчиком под ключ: сценарий, раскадровка, монтаж, вам остаётся снять на телефон по плану",
               "Если вариант с подрядчиком вам подходит, могу закрыть это под ключ, сценарии, раскадровка и монтаж, без найма и обучения человека",
               "Я делаю ровно это под ключ, сценарий, раскадровка и монтаж, по факту вы получаете готовые ролики без найма в штат"])
    elif vac:
        a = R([f"{hi} увидел вашу вакансию на hh, «{vac}»",
               f"{hi} наткнулся на hh на вашу вакансию «{vac}»"])
        b = R(["Я не на неё, у меня другое: делаю ролики под ключ, сценарий, раскадровка и монтаж, чтобы SMM-щику не пришлось ещё и видео тянуть",
               "Пишу не по самой вакансии, а по видео: делаю ролики под ключ, сценарии и монтаж, обычно это самое узкое место у SMM",
               "Я не SMM, я про видео, делаю ролики под ключ, сценарий, раскадровка, монтаж, как раз то, на что у SMM-щика обычно не хватает рук"])
    else:
        a = R([f"{hi} зашёл на ваш сайт, {c.get('niche') or 'у вас'} как раз хорошо заходит в коротких роликах",
               f"{hi} нашёл вас через сайт, в вашей сфере людям важно увидеть процесс до того, как прийти"])
        b = R(["Я делаю ролики под ключ, сценарий, раскадровка и монтаж, вам остаётся снять на телефон по плану",
               "Я занимаюсь роликами под ключ, сценарии и монтаж, от вас только снять на телефон по готовому плану"])
    return f"{a}\n{b}\n{offer}. {ask}"

def tg_item(c):
    invited = c["tg"][0].lower() in {u.lower() for u in c.get("tg_vacancy", [])}   # сами написали «пишите в тг» в вакансии
    return {"username": c["tg"][0], "invited": invited, "found": time.time(), "post": c.get("vacancy_url", ""), "display": (TG_INFO.get(c["tg"][0].lower()) or {}).get("title") or c.get("name", ""),
            "variant": "BIZ", "niche": c.get("niche") or "бизнес", "uniq": 1,
            "source": c.get("vacancy_url") or c.get("site") or c.get("gis_url") or "",
            "text": re.sub(r"\s*\n\s*", "\n\n", c["tg_text"].strip())}   # абзац = отдельное сообщение (autoclient.split_parts)

def push_tg(c):
    q = jload(TG_QUEUE, [])
    if any(x["username"].lower() == c["tg"][0].lower() for x in q): return
    q.append(tg_item(c)); jsave(TG_QUEUE, q)

def tg_step(st, skip=lambda u: False, max_prepare=3):
    """Шаг для основного бота (autoclient): поиск + до max_prepare компаний → готовые сообщения в Telegram.
    st — словарь внутри state.json основного бота (st["biz"]), поэтому база переживает перезапуски облака.
    skip(username) — True, если этому человеку уже писали / он в стоп-листе."""
    cfg = load_cfg()
    if os.environ.get("GIS_KEY"): cfg["gis_key"] = os.environ["GIS_KEY"]
    st.setdefault("companies", {})
    try: collect(cfg, st)
    except Exception as e: log("поиск бизнеса:", str(e)[:120])
    out, n = [], 0
    for c in sorted((c for c in st["companies"].values() if c.get("status") == "new"), key=lambda c: -priority(c)):
        if n >= max_prepare: break
        n += 1
        try: prepare_one(c)
        except Exception as e: log("обогащение не удалось:", c.get("name"), str(e)[:80])
        c["tg"] = [u for u in c.get("tg", []) if not skip(u)]
        if c.get("stop"): c["status"] = "stop"; continue
        if not c.get("tg"): c["status"] = "no_tg"; continue
        c["tg_text"], c["by"] = compose_tg(c)
        c["status"] = "tg_queued"; c["sent_at"] = today()
        out.append(tg_item(c))
    for c in st["companies"].values():                       # база не пухнет: у отработанных храним только суть
        if c.get("status") in ("no_tg", "no_contact", "stop"):
            for f in ("letter", "subject", "tg_text", "socials", "emails", "address"): c.pop(f, None)
    return out

# ---------------------------------------------------------------- 7. отчёты
def write_reports(st):
    rows = sorted(st["companies"].values(), key=lambda c: c.get("found", ""), reverse=True)
    with open(LEADS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["статус", "компания", "город", "ниша/вакансия", "источник", "почта", "telegram", "соцсети", "сайт",
                    "2ГИС/hh", "рейтинг", "отзывов", "зарплата", "отправлено", "дожим", "ответ"])
        for c in rows:
            w.writerow([c.get("status"), c.get("name"), c.get("city"), c.get("niche") or c.get("vacancy"), c.get("source"),
                        c.get("email_to") or ", ".join(c.get("emails", [])), ", ".join("@" + x for x in c.get("tg", [])),
                        " ".join(c.get("socials", {}).values()), c.get("site"), c.get("gis_url") or c.get("vacancy_url"),
                        c.get("rating") or "", c.get("reviews") or "", c.get("salary") or "", c.get("sent_at", ""),
                        c.get("fu_at", ""), (c.get("reply") or "")[:200]])

def draft(c):
    with open(DRAFTS, "a", encoding="utf-8") as f:
        f.write(f"### {c['name']} — {c.get('city', '')} — {c.get('niche') or c.get('vacancy', '')} [{c.get('by', '')}]\n"
                f"Кому: {', '.join(c.get('emails', [])) or '—'} | TG: {', '.join('@' + x for x in c.get('tg', [])) or '—'}\n"
                f"Соцсети: {' '.join(c.get('socials', {}).values()) or '—'} | Сайт: {c.get('site') or '—'} | "
                f"{c.get('gis_url') or c.get('vacancy_url') or ''}\n"
                f"**Тема:** {c.get('subject', '')}\n\n{c.get('letter', '')}\n\n---\n\n")

# ---------------------------------------------------------------- главный цикл
def in_hours(cfg):
    a, b = cfg["limits"]["hours_msk"]
    return a <= msk_now().hour < b

def collect(cfg, st):
    """Один шаг поиска: hh раз в N часов, 2ГИС — одна пара «ниша × город» за шаг."""
    new = []
    now = time.time()
    if now - st.get("hh_last", 0) > cfg["hh_every_hours"] * 3600:
        for q in cfg["hh_queries"]:
            for page in (0, 1):
                items = hh_search(q, page); time.sleep(random.uniform(3, 6))
                new += items
                if len(items) < 20: break
        st["hh_last"] = now
        log(f"hh.ru: найдено вакансий {len(new)}")
    if cfg.get("gis_key"):
        pairs = [(q, ct) for ct in cfg["cities"] for q in cfg["gis_queries"]]
        i = st.get("gis_i", 0) % len(pairs)
        q, ct = pairs[i]
        page = st.setdefault("gis_page", {}).get(f"{q}|{ct}", 1)
        items, err = gis_search(q, ct, cfg["gis_key"], st, page, cfg["limits"]["min_reviews_2gis"])
        if err:
            log(f"2ГИС «{q}» {ct}: {err}")
            if "403" in err or "401" in err or "ключ" in err.lower(): notify(f"⚠️ 2ГИС не принимает ключ: {err}")
        else:
            log(f"2ГИС «{q}» {ct} стр.{page}: подходящих {len(items)}")
        new += items
        if items and page < 5: st["gis_page"][f"{q}|{ct}"] = page + 1
        else: st["gis_i"] = i + 1
    added = 0
    known_dom = {c.get("domain") for c in st["companies"].values() if c.get("domain")}
    for c in new:
        if c["key"] in st["companies"]: continue
        d = domain_of(c.get("site", ""))
        if d and d in known_dom and not re.search(r"vk\.|instagram|t\.me", d): continue
        c["status"] = "new"; c["found"] = msk_now().isoformat(timespec="minutes")
        st["companies"][c["key"]] = c; added += 1
        if d: known_dom.add(d)
    return added

def prepare(cfg, st):
    """Обогащение и письмо для нескольких новых компаний за шаг."""
    n = 0
    todo = sorted((c for c in st["companies"].values() if c.get("status") == "new"), key=lambda c: -priority(c))
    tg_only = not cfg.get("send_email")
    sent_tg = {u.lower() for x in st["companies"].values() if x.get("status") == "tg_queued" for u in x.get("tg", [])[:1]}
    for c in todo:
        if n >= cfg["limits"]["letters_per_cycle"]: break
        n += 1
        try: prepare_one(c)
        except Exception as e: log("обогащение не удалось:", c.get("name"), str(e)[:80])
        if c.get("stop"): c["status"] = "stop"; log(f"просят не писать в личку: {c['name']}"); continue
        c["tg"] = [u for u in c.get("tg", []) if u.lower() not in sent_tg]
        if tg_only:
            if not c.get("tg"): c["status"] = "no_tg"; log(f"нет личного Telegram: {c['name']}"); continue
            c["tg_text"], c["by"] = compose_tg(c); c["letter"] = c["tg_text"]; c["subject"] = "Telegram"
            c["status"] = "ready"; draft(c); sent_tg.add(c["tg"][0].lower())
            log(f"сообщение готово [{c['by']}]: {c['name']} — @{c['tg'][0]}")
            continue
        taken = {x.get("email_to") for x in st["companies"].values() if x.get("email_to")}
        c["emails"] = [e for e in c.get("emails", []) if e not in taken]
        if not c.get("emails") and not c.get("tg"):
            c["status"] = "no_contact"; log(f"без контакта: {c['name']} ({c.get('site') or '—'})"); continue
        L = compose(c); c.update({"subject": L["subject"], "letter": L["text"], "by": L["by"], "status": "ready"})
        if c.get("tg"): c["tg_text"], _ = compose_tg(c)
        draft(c)
        log(f"письмо готово [{L['by']}]: {c['name']} — {c.get('city')} — почта {c.get('emails')[:1]} tg {c.get('tg')[:1]}")
    return n

def prepare_one(c):
    if c["source"] == "hh":
        if c.get("vacancy_url"):
            c["tg_vacancy"], stop = hh_vacancy_contacts(c["vacancy_url"]); time.sleep(1.5)
            if stop: c["stop"] = stop
        if not c.get("site"): c["site"] = hh_employer_site(c["hh_employer"]); time.sleep(1.5)
    enrich(c)

def send_step(cfg, st, d):
    """Не больше одного письма за вызов; между письмами пауза gap_min."""
    if DRY or not in_hours(cfg) or time.time() < st.get("next_send", 0): return
    lim = cfg["limits"]
    mail_ok = cfg.get("send_email") and cfg["smtp"].get("user") and cfg["smtp"].get("password")
    now = time.time()
    # дожимы
    if mail_ok and d["email"] < lim["email_per_day"]:
        for k, c in st["companies"].items():
            if c.get("status") == "sent" and c.get("email_to") and now - c.get("sent_ts", now) > lim["followup_days"] * 86400:
                t = compose_follow(c)
                try:
                    smtp_send(cfg, c["email_to"], "Re: " + c["subject"], t + SIGN, c.get("msgid"))
                    c.update({"status": "fu", "fu_at": today(), "fu_text": t}); d["email"] += 1
                    log(f"ДОЖИМ отправлен: {c['name']} <{c['email_to']}>")
                except Exception as e:
                    log("дожим не ушёл:", c["name"], str(e)[:120]); c["status"] = "fu_fail"
                st["next_send"] = now + random.uniform(*lim["gap_min"]) * 60
                return
    for c in sorted((c for c in st["companies"].values() if c.get("status") == "ready"), key=lambda c: -priority(c)):
        if mail_ok and c.get("emails") and d["email"] < lim["email_per_day"]:
            to = c["emails"][0]
            try:
                mid = smtp_send(cfg, to, c["subject"], c["letter"] + SIGN)
                c.update({"status": "sent", "email_to": to, "msgid": mid, "sent_at": today(), "sent_ts": now}); d["email"] += 1
                log(f"ОТПРАВЛЕНО письмо: {c['name']} <{to}> — сегодня {d['email']}/{lim['email_per_day']}")
            except smtplib.SMTPAuthenticationError as e:
                notify("⚠️ Почта не пускает: проверь логин и ПАРОЛЬ ПРИЛОЖЕНИЯ в config.json. Отправка писем на паузе.")
                cfg["send_email"] = False; log("SMTP вход не удался:", e); return
            except smtplib.SMTPDataError as e:
                log("почтовый сервер отклонил:", e); notify(f"⚠️ Почта отклонила письмо ({str(e)[:150]}). Пауза 3 часа.")
                st["next_send"] = now + 3 * 3600; return
            except Exception as e:
                log("письмо не ушло:", c["name"], str(e)[:120]); c["emails"] = c["emails"][1:]
                if not c["emails"] and not c.get("tg"): c["status"] = "no_contact"
                return
            st["next_send"] = now + random.uniform(*lim["gap_min"]) * 60
            return
        if cfg.get("send_tg") and c.get("tg") and d["tg"] < lim["tg_per_day"]:
            push_tg(c); c.update({"status": "tg_queued", "sent_at": today(), "sent_ts": now}); d["tg"] += 1
            log(f"в очередь Telegram: @{c['tg'][0]} ({c['name']}) — сегодня {d['tg']}/{lim['tg_per_day']}")
            return

def summary(st, d):
    cs = st["companies"].values()
    cnt = lambda s: sum(1 for c in cs if c.get("status") == s)
    return (f"📊 Поиск бизнеса за {today()}: писем {d['email']}, в Telegram {d['tg']}\n"
            f"Всего в базе {len(st['companies'])}: готово {cnt('ready')}, отправлено {cnt('sent') + cnt('fu')}, "
            f"ответили {cnt('replied')}, отказ {cnt('refused')}, без контакта {cnt('no_contact')}, недоставка {cnt('bounce')}")

def main():
    cfg = load_cfg()
    st = jload(STATE_FILE, {})
    st.setdefault("companies", {}); st.setdefault("days", {})
    if TEST_MAIL:
        s = cfg["smtp"]
        mid = smtp_send(cfg, s["user"], "Проверка отправки — поиск бизнеса", template_letter({"name": "Тест", "reviews": 120})["text"] + SIGN)
        print("отправлено самому себе, Message-ID:", mid); return
    log("старт", "(черновики, без отправки)" if DRY else "",
        f"почта: {'вкл' if cfg.get('send_email') else 'выкл'}, telegram: {'вкл' if cfg.get('send_tg') else 'выкл'}, "
        f"2ГИС: {'есть ключ' if cfg.get('gis_key') else 'нет ключа'}")
    last_imap = 0; last_sum = st.get("sum_day", "")
    while True:
        try:
            cfg = load_cfg()
            d = st["days"].setdefault(today(), {"email": 0, "tg": 0})
            added = collect(cfg, st)
            if added: log(f"новых компаний: {added}")
            prepare(cfg, st)
            send_step(cfg, st, d)
            if not DRY and cfg["smtp"].get("password") and time.time() - last_imap > 600:
                try: imap_check(cfg, st)
                except Exception as e: log("IMAP:", str(e)[:120])
                last_imap = time.time()
            if msk_now().hour >= 20 and last_sum != today():
                notify(summary(st, d)); last_sum = st["sum_day"] = today()
            jsave(STATE_FILE, st); write_reports(st)
        except KeyboardInterrupt:
            jsave(STATE_FILE, st); break
        except Exception:
            log("ошибка круга:", traceback.format_exc()[-600:])
        if ONCE: break
        time.sleep(30)

if __name__ == "__main__":
    main()
