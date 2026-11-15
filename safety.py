# -*- coding: utf-8 -*-
"""Последняя линия защиты перед отправкой — общая для всех ботов (1 вакансии, 2 компании, 3 партнёры, эксперты).
Список ошибок, от которых защищает, — «50 ошибок ботов.md» рядом. Тесты — tests_50.py."""
import re, hashlib

OWN = {"chernyshev_edit", "zakulisy715", "pepeclodai715bot", "lagashka"}          # свои аккаунты, каналы и бот пульта
USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
JUNK = re.compile(r"\{|\}|\bNone\b|\bnull\b|undefined|\[\s*имя\s*\]|<[a-z/]+>|\\n|Traceback|\bjson\b", re.I)
SERVICE = re.compile(r"(bot|_bot|support|helpdesk|noreply|robot)$|^(admin|support|help|info)$", re.I)
SOFT_NO = re.compile(r"не надо|не нужно|не интересно|нет,? спасибо|неактуальн|не актуальн|не пишите|отпишитесь|не беспокойте|"
                     r"нам не требуется|уже нашли|вакансия закрыта|закрыли вакансию|спам", re.I)

def pre_send(kind, item, sent):
    """'' — можно отправлять, иначе причина пропуска. sent — st["sent"] (кому уже писали любые боты)."""
    u = (item.get("username") or "").lstrip("@").strip()
    if not USERNAME.match(u): return f"неверный ник «{u[:40]}»"
    ul = u.lower()
    if ul in OWN: return "это свой аккаунт или канал"
    if SERVICE.search(ul): return "служебный аккаунт или бот"
    if any(k.lower() == ul for k in sent): return "ему уже писал другой бот"
    t = item.get("text") or ""
    if len(t.strip()) < 60: return "пустое или слишком короткое письмо"
    if JUNK.search(t): return "в письме мусор от шаблона или нейросети"
    cyr = len(re.findall(r"[А-Яа-яЁё]", t)); lat = len(re.findall(r"[A-Za-z]", re.sub(r"t\.me/\S+|https?://\S+|@\w+", "", t)))
    if cyr < 3 * lat: return "письмо не на русском"
    return ""

def text_hash(t):
    return hashlib.md5(re.sub(r"\W+", "", (t or "").lower()).encode()).hexdigest()[:12]

GREET = [("Добрый день", "Здравствуйте"), ("добрый день", "здравствуйте")]
ASKS = [("интересно?", "как вам?"), ("скинуть?", "прислать?"), ("обсудим?", "интересно?"), ("как вам такое?", "актуально для вас?")]

def vary(t, seen):
    """Одинаковый текст разным людям — сигнал спама для Telegram: меняем приветствие/вопрос, пока не станет уникальным."""
    if text_hash(t) not in seen: return t
    for a, b in GREET + ASKS:
        for x, y in ((a, b), (b, a)):
            if x in t:
                t2 = t.replace(x, y, 1)
                if text_hash(t2) not in seen: return t2
    return t.rstrip("?") + (", что скажете?" if t.rstrip().endswith("?") else "")

def soft_no(text):
    """Мягкий отказ, который классификатор мог не распознать: на него не шлём «Секундочку, сейчас вернусь»."""
    return bool(SOFT_NO.search(text or ""))
