# -*- coding: utf-8 -*-
"""Защита аккаунта от жалоб на спам.

Жалобы прилетают почти всегда от двух типов людей:
1) «не тот человек»: ник взят из ссылки Threads/Instagram/TikTok, а в Telegram под этим ником — посторонний;
2) люди, которые прямо пишут «в личку не писать», «спам — бан/жалоба», «отклики только через форму/почту/бота».
Таким не пишем вообще. Плюс: точная дата снятия ограничения из ответа @SpamBot и мягкий разгон после него."""
import re, datetime, html as _html, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (client-search)", "Accept-Language": "ru-RU,ru;q=0.9"}

# ---------- 1. только настоящие Telegram-контакты ----------
FOREIGN_URL = re.compile(r"(?:https?://)?(?:www\.)?(?!t\.me\b|telegram\.me\b)[a-z0-9.-]+\.(?:com|net|ru|me|io|app|ly|be|tv|org|kz|by|ua)/\S*", re.I)
SOCIAL = re.compile(r"(inst|insta|instagram|инст\w*|tiktok|тик\s?ток|youtube|ютуб\w*|threads|тредс|vk|вк|вконтакте|"
                    r"twitter|твиттер|linkedin|behance|pinterest|facebook|fb|дзен|rutube|likee)\s*[:\-—–]?\s*$", re.I)
FOREIGN_SOURCE = re.compile(r"источник\s*:?\s*(threads|тредс|instagram|инстаграм|linkedin|hh\b|headhunter|хедхантер|"
                            r"vk|вконтакте|facebook|twitter|tiktok|avito|авито|habr|хабр|fl\.ru|kwork)", re.I)

def tg_handles(text):
    """@ники из текста, которые действительно про Telegram (без ников из ссылок и подписей других соцсетей)."""
    t = FOREIGN_URL.sub(" ", text or "")
    out = []
    for m in re.finditer(r"@([A-Za-z][A-Za-z0-9_]{4,31})", t):
        before = t[max(0, m.start() - 25):m.start()]
        if SOCIAL.search(before): continue                    # «Inst: @name», «TikTok — @name»
        if t[m.end():m.end() + 2].startswith(".") and re.match(r"\.[a-z0-9]", t[m.end():m.end() + 2], re.I):
            continue                                          # «@bina.uae» — это ник Instagram
        out.append(m.group(1))
    return out

def contact_problem(post_text, username, tme_links=()):
    """Почему @username нельзя считать контактом автора вакансии (или '' — всё в порядке)."""
    u = username.lower()
    in_tme = u in {x.lower() for x in tme_links}
    if not in_tme and u not in {x.lower() for x in tg_handles(post_text)}:
        return "ник взят из ссылки/подписи другой соцсети — в Telegram это может быть посторонний человек"
    if FOREIGN_SOURCE.search(post_text or "") and not in_tme and not re.search(r"(?:t\.me/|telegram|тг|tg|телеграм)\W{0,15}@?" + re.escape(username), post_text or "", re.I):
        return "вакансия перепощена из другой соцсети, Telegram-контакт не указан явно"
    return ""

# ---------- 2. «не пишите», «спам — бан», «только через форму» ----------
NO_DM = re.compile(
    r"не пиш\w*\s+(мне\s+)?(в\s+)?(лс|личк\w*|личные|директ)|в\s+(лс|личку|личные)\s+не\s+пис|лс\s+закрыт|"
    r"(спам|реклам\w*|предложени\w*\s+услуг|навязыв\w*|рассылк\w*)\s*[-—–=:→>]*\s*(сразу\s+)?(=\s*)?(бан|блок|жалоб|репорт|в\s+спам)|"
    r"жалоб\w*\s+на\s+спам|кидаю\s+в\s+спам|отправляю\s+в\s+спам|сразу\s+в\s+спам|репорч\w*|"
    r"не\s+предлагайте|без\s+предложений\s+услуг|услуги\s+не\s+предлагать|не\s+нужно\s+предлагать|"
    r"по\s+рекламе\s+не\s+пис|"
    r"отклик\w*\s+(принимаю\s+|принимаем\s+)?только\s+(через|в|на)\s+(бот|форм|сайт|гугл|google|hh|почт|e-?mail)|"
    r"(резюме|отклики|портфолио)\s+(присылайте\s+|отправляйте\s+|направляйте\s+)?(только\s+)?(на\s+почту|на\s+e-?mail|в\s+форму|через\s+форму|через\s+бота|в\s+бота)",
    re.I)

def no_dm(text):
    m = NO_DM.search(text or "")
    return f"просит не писать в личку / грозит жалобой («{m.group(0)[:40]}»)" if m else ""

# ---------- проверка прямо перед отправкой (для всего, что лежит в очереди) ----------
def _get(url):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15).read().decode("utf-8", "replace")
    except Exception:
        return None

def _clean(h):
    return _html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", "\n", h or ""))).strip()

def check_before_send(kind, item):
    """'' — можно писать; иначе причина пропуска. Сетевые сбои писать не мешают."""
    u = item["username"]
    page = _get(f"https://t.me/{u}")
    if page is not None:
        bio = _clean((re.search(r'tgme_page_description[^>]*>(.*?)</div>', page, re.S) or [None, ""])[1])
        why = no_dm(bio)
        if why: return "в био " + why
    post = item.get("post") or ""
    m = re.match(r"https://t\.me/([A-Za-z0-9_]+)/(\d+)", post)
    if kind == "hot" and m:
        h = _get(f"https://t.me/{m.group(1)}/{m.group(2)}?embed=1&mode=tme")
        if h:
            body = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', h, re.S)
            text = _clean(body.group(1)) if body else ""
            links = re.findall(r'href="(?:https?:)?//t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/?(?:\?[^"]*)?"', body.group(1) if body else "")
            if text:
                why = contact_problem(text, u, links) or no_dm(text)
                if why: return why
    return ""

# ---------- 3. точная дата снятия ограничения из ответа @SpamBot ----------
MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "ма": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
          "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

def spam_until(text, now=None):
    """Текст @SpamBot → наивный datetime по МЕСТНОМУ времени процесса (когда ограничение снимут) или None."""
    t = (text or "").lower()
    d = None
    for m in re.finditer(r"(\d{1,2})\s+([а-яa-z]{3,})\.?,?\s+(\d{4})(?:\s*г\.?)?(?:,?\s*(?:в\s*)?(\d{1,2}):(\d{2}))?\s*(utc|gmt|мск|msk)?", t):
        mon = next((v for k, v in MONTHS.items() if m.group(2).startswith(k)), None)
        if mon: d = (int(m.group(3)), mon, int(m.group(1)), m.group(4), m.group(5), m.group(6)); break
    if not d:
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:,?\s*(?:в\s*)?(\d{1,2}):(\d{2}))?\s*(utc|gmt|мск|msk)?", t)
        if m: d = (int(m.group(3)), int(m.group(2)), int(m.group(1)), m.group(4), m.group(5), m.group(6))
    if not d: return None
    y, mo, dd, hh, mi, tz = d
    try:
        when = datetime.datetime(y, mo, dd, int(hh or 23), int(mi or 59))
    except ValueError:
        return None
    off = {"utc": 0, "gmt": 0, "мск": 3, "msk": 3}.get(tz or "", None)
    if off is None:                     # пояс не указан — считаем UTC и берём запас 3 часа
        off, when = 0, when + datetime.timedelta(hours=3)
    aware = when.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=off)))
    local = aware.astimezone().replace(tzinfo=None)
    return local + datetime.timedelta(minutes=30)       # небольшой запас
