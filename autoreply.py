# -*- coding: utf-8 -*-
"""Автодиалог с откликнувшимися: Claude отвечает от имени Егора по правилам ниже.
Включается, только если задан ANTHROPIC_API_KEY (в облаке — секрет репозитория). Без ключа молчит, работает ручной режим."""
import os, json, re, urllib.request

MODEL = os.environ.get("AUTOREPLY_MODEL", "claude-haiku-5-5")
MAX_AUTO = 5          # столько ответов подряд бот даёт сам, дальше — передаёт Егору

SYSTEM = """Ты пишешь в Telegram от имени Егора, видеомонтажёра (Reels/Shorts, YouTube, моушн в After Effects, звук).
Егор откликнулся на вакансию или написал эксперту, человек ответил. Твоя задача — вести живой короткий диалог и подвести к тестовому фрагменту или созвону.

Как писать: по-русски, на «вы», 2–5 коротких предложений, без списков и канцелярита, без эмодзи (максимум один), как живой занятой человек.
Схема: 1) ответь по сути на то, что сказал человек; 2) назови одну конкретную проблему, которая из его слов следует (сроки, нестабильное качество, ролики не удерживают, звук); 3) предложи решение: тест на его материале, примеры, созвон 10 минут; 4) один вопрос в конце.
Факты, которые можно называть: канал с работами https://t.me/zakulisy715; цены: короткий ролик от 3 000 ₽ (стандарт 5 000, премиум с моушном 8 000), длинное видео от 5 000 ₽, пакеты 12 000 / 40 000 ₽ в месяц; договор, чек самозанятого, предоплата 50%; тест — бесплатный фрагмент 10–15 секунд.
Жёсткие правила: не придумывай кейсы, отзывы, клиентов, цифры результатов и сроки, которых нет выше; не обещай то, чего не знаешь; не называй цену ниже указанной и не торгуйся;
если человек прямо спрашивает, бот ли ты, честно скажи: «Я помощник Егора, он подключится лично» и поставь handoff=true;
не дави, если человек отказал — вежливо попрощайся.
handoff=true ставь, когда человек: согласился и готов начать, просит созвон, называет бюджет/условия для обсуждения, присылает материал или ТЗ, задаёт вопрос, на который у тебя нет фактов, злится, или диалог идёт дольше четырёх ответов.
Ответь строго JSON без пояснений: {"text": "...", "handoff": true|false, "reason": "коротко почему"}"""

FIRST = """Ты пишешь первое сообщение в Telegram от имени Егора, видеомонтажёра, автору вакансии.
Что Егор умеет: монтаж Reels/Shorts/TikTok и длинных YouTube-видео, субтитры, цвет, звук и саунд-дизайн, чистка голоса (подкасты), моушн-графика в After Effects (титры, инфографика, анимация логотипа, заставки).
Что НЕ умеет и за что не берётся: съёмка на выезде/офлайн в другом городе, SMM целиком (контент-планы, сторис, тексты, ведение аккаунтов), дизайн каруселей, ретушь фото, AI-генерация видео, копирайтинг, продажи, работа «в штат» в офисе, оплата ниже 2 000 ₽ за ролик.
Сначала реши fit: подходит ли вакансия Егору (основная задача — монтаж/моушн/звук, удалённо). Если нет — fit=false.
Если да — напиши письмо: по-русски, на «вы», 4–7 коротких предложений, абзацами, без эмодзи, как живой человек, без шаблонного «Готов взять в работу».
Схема: обращение по имени, если оно понятно; одна деталь из вакансии или био, показывающая, что прочитал; конкретная проблема, которая обычно возникает у таких заказчиков (назови её прямо, но без запугивания); как Егор её решает; ссылка на работы https://t.me/zakulisy715; предложение бесплатного тестового фрагмента на их материале; один вопрос в конце.
Цену называй, только если её просят в вакансии: короткий ролик от 3 000 ₽. Для зарплатных вакансий цену не называй.
Не выдумывай кейсы, клиентов, отзывы, цифры и опыт, которых нет выше.
Ответь строго JSON: {"fit": true|false, "reason": "коротко", "text": "письмо или пусто"}"""

def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))

def _claude(system, messages, max_tokens=600):
    body = {"model": MODEL, "max_tokens": max_tokens, "system": system, "messages": messages}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    out = json.loads(urllib.request.urlopen(req, timeout=60).read())["content"][0]["text"]
    return json.loads(re.search(r"\{.*\}", out, re.S).group(0))

def _bio(username):
    try:
        h = urllib.request.urlopen(urllib.request.Request(f"https://t.me/{username}", headers={"User-Agent": "Mozilla/5.0"}),
                                   timeout=15).read().decode("utf-8", "replace")
        m = re.search(r'tgme_page_description[^>]*>(.*?)</div>', h, re.S)
        return re.sub(r"<[^>]+>", " ", m.group(1)).strip()[:400] if m else ""
    except Exception: return ""

def first_message(vacancy, username, display):
    """Вакансия + био автора → {'fit','reason','text'} или None (тогда скрипт берёт шаблон)."""
    if not enabled(): return None
    try:
        j = _claude(FIRST, [{"role": "user", "content": f"Автор: {display} (@{username})\nБио автора: {_bio(username) or 'нет'}\n\nВакансия:\n{vacancy[:2500]}"}])
        fit = bool(j.get("fit")); txt = str(j.get("text", "")).strip()
        if fit and (len(txt) < 120 or len(txt) > 1500 or "zakulisy715" not in txt): return None
        return {"fit": fit, "reason": str(j.get("reason", ""))[:120], "text": txt}
    except Exception:
        return None

def generate(e, their_text):
    """e — запись лида из state['sent'], их последнее сообщение → {'text','handoff','reason'} или None."""
    if not enabled(): return None
    thread = [{"role": "assistant", "content": e.get("text", "")}]
    for h in e.get("thread", []):
        thread.append({"role": "user" if h["who"] == "them" else "assistant", "content": h["text"]})
    thread.append({"role": "user", "content": their_text})
    # слить подряд идущие реплики одной роли
    msgs = []
    for m in thread:
        if msgs and msgs[-1]["role"] == m["role"]: msgs[-1]["content"] += "\n" + m["content"]
        else: msgs.append(dict(m))
    if msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": f"(контекст: {e.get('display', '')} ответил на отклик по вакансии {e.get('source', '')})"})
    body = {"model": MODEL, "max_tokens": 500, "system": SYSTEM, "messages": msgs}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    try:
        out = json.loads(urllib.request.urlopen(req, timeout=60).read())["content"][0]["text"]
        j = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        txt = str(j.get("text", "")).strip()
        if not txt or len(txt) > 900: return None
        return {"text": txt, "handoff": bool(j.get("handoff")), "reason": str(j.get("reason", ""))[:120]}
    except Exception:
        return None
