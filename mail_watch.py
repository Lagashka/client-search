# -*- coding: utf-8 -*-
"""Почта: нейросеть видит, если клиент написал не в Telegram, а на почту (или пришло приглашение/отказ с hh.ru).

Секреты: MAIL_USER (адрес), MAIL_PASS (пароль приложения, НЕ обычный пароль), MAIL_IMAP (необязательно: imap.gmail.com /
imap.yandex.ru / imap.mail.ru — по домену подставляется сам). Только чтение: письма НЕ помечаются прочитанными, бот ничего не отправляет.

Раз в 10 минут:
  • новые входящие за 3 дня (повторно не смотрит — Message-ID в state.json);
  • отбрасывает рассылки, уведомления сервисов, свои письма, спам;
  • сопоставляет с лидами всех ботов: по домену компании, имени, названию компании, нику Telegram, вакансии hh;
  • нейросеть: это клиент? чего хочет (интерес / вопрос / отказ / приглашение)? что ответить;
  • если это лид — он помечается «ответил по почте»: дожимы ему в Telegram больше не идут;
  • Егору уведомление: кто, о чём, совет-ответ (отвечает Егор сам из почты).
"""
import os, re, time, imaplib, email, datetime
from email.header import decode_header
from email.utils import parseaddr

BULK_FROM = re.compile(r"no-?reply|noreply|do-?not-?reply|mailer-daemon|postmaster|newsletter|news@|info@(?!.*hh\.ru)|"
                       r"notifications?@|support@|bounce|marketing@|promo|digest", re.I)
SERVICE_DOM = re.compile(r"@(.*\.)?(google|youtube|apple|github|telegram|vk|ok|mail|yandex|tinkoff|tbank|sber|ozon|wildberries|"
                         r"avito|aliexpress|steam|discord|tiktok|instagram|facebook|meta|linkedin|notion|figma|canva|adobe|"
                         r"spotify|netflix|zoom)\.(com|ru|net|io|me)$", re.I)
HH = re.compile(r"@(.*\.)?(hh\.ru|headhunter\.ru)$", re.I)
HH_EVENT = re.compile(r"приглаш|пригласил|интервью|собеседован|отказ|не готов|сообщени|ответил на ваш отклик|работодатель", re.I)

def imap_host(user):
    if os.environ.get("MAIL_IMAP"): return os.environ["MAIL_IMAP"]
    d = user.split("@")[-1].lower()
    return {"gmail.com": "imap.gmail.com", "yandex.ru": "imap.yandex.ru", "ya.ru": "imap.yandex.ru", "mail.ru": "imap.mail.ru",
            "bk.ru": "imap.mail.ru", "inbox.ru": "imap.mail.ru", "list.ru": "imap.mail.ru", "rambler.ru": "imap.rambler.ru"}.get(d, "imap." + d)

def configured():
    return bool(os.environ.get("MAIL_USER") and os.environ.get("MAIL_PASS"))

def _dec(v):
    out = ""
    for part, enc in decode_header(v or ""):
        out += part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part
    return out

def body_of(msg):
    plain, htm = "", ""
    for p in (msg.walk() if msg.is_multipart() else [msg]):
        if "attachment" in str(p.get("Content-Disposition") or ""): continue
        try: t = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
        except Exception: continue
        if p.get_content_type() == "text/plain" and not plain: plain = t
        elif p.get_content_type() == "text/html" and not htm: htm = t
    t = plain or re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(style|script).*?</\1>", " ", htm))
    t = re.split(r"\n\s*(>|On .+ wrote:|.+ пишет:|-----Original|\d{1,2}[./]\d{1,2}[./]\d{2,4}.{0,40}:\s*$)", t, flags=re.M)[0]   # без цитаты
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()

def is_bulk(msg, frm):
    if HH.search(frm): return False                         # hh.ru пишет с noreply, но это приглашения/отказы — важно
    if msg.get("List-Unsubscribe") or msg.get("List-Id") or (msg.get("Precedence") or "").lower() in ("bulk", "list", "junk"): return True
    if msg.get("Auto-Submitted", "no").lower() != "no": return True
    return bool(BULK_FROM.search(frm) or SERVICE_DOM.search(frm))

def match_lead(st, frm, name, subject, body):
    """→ ("sent", username) | ("company", key) | ("hh", vacancy_id) | (None, None)"""
    dom = frm.split("@")[-1].lower()
    free = dom in ("gmail.com", "mail.ru", "yandex.ru", "ya.ru", "bk.ru", "inbox.ru", "list.ru", "rambler.ru", "icloud.com", "outlook.com")
    low = f"{name} {subject} {body[:2000]}".lower()
    comps = ((st.get("biz") or {}).get("companies") or {})
    if not free:
        for k, c in comps.items():
            if c.get("domain") and dom.endswith(c["domain"].lower()): return "company", k
    for u, e in (st.get("sent") or {}).items():
        if u.lower() in low or ("@" + u.lower()) in low: return "sent", u
    for k, c in comps.items():
        nm = (c.get("name") or "").lower()
        if len(nm) >= 5 and nm in low: return "company", k
    for vid, a in ((st.get("hh_api") or {}).get("applied") or {}).items():
        emp = (a.get("employer") or "").lower()
        if len(emp) >= 4 and emp in low: return "hh", vid
    nm = (name or "").strip().lower()
    if len(nm) >= 4:
        for u, e in (st.get("sent") or {}).items():
            if (e.get("display") or "").strip().lower() == nm: return "sent", u
    return None, None

MAIL = """Ты помощник Егора (монтажёр, ролики под ключ: сценарий, раскадровка, монтаж; прайс: монтаж 3 000 / 5 000 / 8 000 ₽, серия из 5 роликов 19 000 ₽, сценарный пакет 7 000 ₽; бесплатно только тест 10–15 с). Ему пришло письмо на почту.
Тебе дадут: от кого, тему, текст и (если есть) кому из его лидов это письмо соответствует и что Егор писал ему раньше.
Определи: is_client — это потенциальный клиент/работодатель/партнёр, который пишет по делу (а не реклама, сервис, рассылка, спам, личное)?
intent — одно из: "интерес", "вопрос", "приглашение", "отказ", "другое". summary — одной фразой, чего человек хочет. reply — готовый ответ от имени Егора (на «вы», коротко, до 400 знаков, без «!» и эмодзи, без канцелярита, один вопрос в конце, цены только из прайса, без выдуманных сроков) или "" если отвечать не нужно.
Ответ строго JSON: {"is_client": true/false, "intent": "...", "summary": "...", "reply": "..."}"""

def review(frm, name, subject, body, lead_info=""):
    try:
        import autoreply, analyst, human
        if not autoreply.llm_on(): return None
        j = analyst._llm_guarded(MAIL, [{"role": "user", "content": f"От: {name} <{frm}>\nТема: {subject}\n{lead_info}\n\nТекст:\n{body[:2500]}"}], 600)
        if not j: return None
        r = str(j.get("reply") or "")
        if r:
            r = human.humanize(autoreply.voicefy(r)); r = r[:1].upper() + r[1:]
            if not autoreply._sane(r, body): r = ""
        return {"is_client": bool(j.get("is_client")), "intent": str(j.get("intent", ""))[:20], "summary": str(j.get("summary", ""))[:300], "reply": r}
    except Exception:
        return None

def step(st, notify, log, crm=None, force=False):
    if not configured(): return
    m = st.setdefault("mail", {})
    if not force and time.time() - m.get("ts", 0) < 10 * 60: return
    m["ts"] = time.time()
    if m.get("off_until", 0) > time.time(): return
    user, pw = os.environ["MAIL_USER"], os.environ["MAIL_PASS"]
    seen = set(m.setdefault("seen", []))
    try:
        M = imaplib.IMAP4_SSL(imap_host(user), 993, timeout=30)
        M.login(user, pw)
    except Exception as e:
        m["fails"] = m.get("fails", 0) + 1
        if m["fails"] >= 3:
            m["off_until"] = time.time() + 6 * 3600; m["fails"] = 0
            notify(f"⚠️ Почта {user}: не могу войти ({str(e)[:100]}). Нужен пароль приложения, а не обычный. Пауза 6 ч.")
        return
    m["fails"] = 0
    try:
        M.select("INBOX", readonly=True)                                  # readonly: письма остаются непрочитанными
        since = (datetime.date.today() - datetime.timedelta(days=3)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f"(SINCE {since})")
        nums = (data[0].split() if data and data[0] else [])[-150:]
        first_run = not m.get("init")
        for num in nums:
            typ, hd = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT LIST-UNSUBSCRIBE LIST-ID PRECEDENCE AUTO-SUBMITTED)])")
            if not hd or not hd[0] or not isinstance(hd[0], tuple): continue
            h = email.message_from_bytes(hd[0][1])
            mid = (h.get("Message-ID") or f"n{num.decode()}").strip()
            if mid in seen: continue
            seen.add(mid)
            if first_run: continue                         # первый запуск: старые письма просто запоминаем, не засыпаем уведомлениями
            name, frm = parseaddr(_dec(h.get("From")))
            frm = frm.lower(); subject = _dec(h.get("Subject"))
            if frm == user.lower() or is_bulk(h, frm): continue
            if HH.search(frm) and not HH_EVENT.search(subject): continue    # hh.ru: только приглашения, отказы, сообщения
            typ, full = M.fetch(num, "(BODY.PEEK[])")
            if not full or not full[0] or not isinstance(full[0], tuple): continue
            body = body_of(email.message_from_bytes(full[0][1]))
            kind, key = match_lead(st, frm, name, subject, body)
            lead_info, e = "", None
            if kind == "sent":
                e = st["sent"][key]; lead_info = f"Это лид из Telegram @{key} ({e.get('display', '')}), Егор писал ему:\n{(e.get('text') or '')[:600]}"
            elif kind == "company":
                c = st["biz"]["companies"][key]; lead_info = f"Это компания из базы: {c.get('name')}, {c.get('city', '')}, {c.get('vacancy') or c.get('niche') or ''}"
            elif kind == "hh":
                a = st["hh_api"]["applied"][key]; lead_info = f"Это работодатель, на чью вакансию Егор откликнулся на hh: {a.get('name')} — {a.get('employer')}"
            r = review(frm, name, subject, body, lead_info)
            if not kind and not HH.search(frm) and not (r and r["is_client"]): continue      # не лид и не по делу — молчим
            if kind == "sent" and e is not None:                         # ответил по почте → в Telegram его больше не дожимаем
                e["replied"] = e.get("replied") or datetime.datetime.now().isoformat(timespec="minutes")
                e["reply_channel"] = "почта"; e["handoff"] = True; e.pop("pending", None)
                e["last_in"] = body[:300]; e["last_in_ts"] = time.time()
                if crm:
                    try: crm.mark(e, crm.classify(body[:500]), body[:300])
                    except Exception: pass
            if kind == "company":
                st["biz"]["companies"][key]["status"] = "replied_mail"
                tgu = (st["biz"]["companies"][key].get("tg") or [""])[0]
                if tgu and tgu in st.get("sent", {}):
                    st["sent"][tgu].update(replied=st["sent"][tgu].get("replied") or datetime.datetime.now().isoformat(timespec="minutes"),
                                           reply_channel="почта", handoff=True)
            if kind == "hh": st["hh_api"]["applied"][key]["mail"] = subject[:100]
            icon = {"отказ": "❌", "приглашение": "🎉", "интерес": "🔥", "вопрос": "💬"}.get((r or {}).get("intent", ""), "📧")
            txt = (f"{icon} ПИСЬМО НА ПОЧТУ — {name or frm}\n{frm}\nТема: {subject[:120]}\n"
                   + (f"Это твой лид: {lead_info.splitlines()[0]}\n" if lead_info else "")
                   + f"\n«{body[:600]}»"
                   + (f"\n\n🧠 {r['summary']}" if r and r.get("summary") else "")
                   + (f"\n💡 Можно ответить:\n«{r['reply']}»" if r and r.get("reply") else "")
                   + ("\n\n✋ Дожимы ему в Telegram остановлены." if kind in ("sent", "company") else "")
                   + ("\nОтветь из почты: https://mail.google.com" if "gmail" in user else "\nОтветь из почты."))
            notify(txt)
            log(f"почта: {icon} {frm} — {subject[:60]} ({kind or 'не из базы'})")
        if first_run:
            m["init"] = time.time(); log(f"почта: подключена, запомнил {len(nums)} старых писем, слежу за новыми")
    finally:
        m["seen"] = list(seen)[-3000:]
        try: M.logout()
        except Exception: pass
