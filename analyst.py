# -*- coding: utf-8 -*-
"""Аналитик для всех трёх ботов: считает воронку, находит узкие места и предлагает решения. Есть два слоя:
  1) правила (работают всегда, без интернета и ключей): цифры по каждому боту, причины отказов, сбои из лога;
  2) нейросеть (Groq: qwen3 / gpt-oss-120b, бесплатно, ключ GROQ_API_KEY уже в облаке — через autoreply._llm):
     читает цифры, тексты ответов и отказов, объясняет, где проблема, и предлагает, что поменять.
Предложенные действия — только безопасные настройки пульта (вкл/выкл ботов, лимиты, пауза): Егор применяет их кнопкой.

Ещё совет по ответу клиенту: на каждый ответ лида нейросеть предлагает текст в голосе Егора, он уходит только по кнопке.
"""
import re, json, time, datetime, collections

BOTS = {"hot": "1 Вакансии", "BIZ": "2 Компании", "PARTNER": "3 Партнёры", "cold": "Эксперты (холодные)"}
SAFE = {"hot_on": (True, False), "biz_on": (True, False), "partners_on": (True, False), "cold_on": (True, False),
        "fu_on": (True, False), "limit_hot": (25, 40, 60), "limit_cold": (10, 20, 30, 40), "gap": (60, 90, 180, 300)}
REASONS = [("дорого / цена", r"дорог|бюджет|не потян|дешевле|цен[аы] высок|не по карману"),
           ("уже есть исполнитель", r"уже есть|свой монтаж|сами монтир|в штате|уже нашли|нашли человек"),
           ("не актуально", r"не актуальн|неактуальн|не нужн|не интерес|нет потребн|пока нет|не сейчас|позже"),
           ("закрыли вакансию", r"закрыт|вакансия не|набор окончен|уже не ищ"),
           ("реакция на рассылку/бота", r"бот|рассылк|спам|шаблон|нейросет|chatgpt|гпт"),
           ("хотят цену/примеры", r"сколько|стоимост|прайс|пример|портфолио|кейс")]

def bot_of(e):
    if e.get("kind") == "hot" and e.get("variant") != "BIZ": return "hot"
    v = e.get("variant")
    return v if v in ("BIZ", "PARTNER") else "cold"

def metrics(st, log_text="", settings=None, days=7):
    now = time.time(); since = now - days * 86400
    per = collections.defaultdict(lambda: {"sent": 0, "replied": 0, "refused": 0, "hot": 0, "agreed": 0, "replies": [], "refusals": []})
    for u, e in (st.get("sent") or {}).items():
        if e.get("ts", 0) < since: continue
        b = per[bot_of(e)]; b["sent"] += 1
        if e.get("replied") and not e.get("junk"):
            b["replied"] += 1
            txt = (e.get("last_in") or "")[:160]
            if e.get("crm") == "refused" or e.get("outcome") == "no": b["refused"] += 1; b["refusals"].append(txt)
            else: b["replies"].append(txt)
            if e.get("crm") == "interest": b["hot"] += 1
            if e.get("crm") == "agreed": b["agreed"] += 1
    reasons = collections.Counter()
    for b in per.values():
        for t in b["refusals"] + b["replies"]:
            for name, rx in REASONS:
                if re.search(rx, t, re.I): reasons[name] += 1
    lines = [l for l in (log_text or "").splitlines() if re.match(r"\d\d\.\d\d \d", l)][-3000:]
    def cnt(rx): return sum(1 for l in lines if re.search(rx, l, re.I))
    logm = {"не наш профиль": cnt(r"не наш профиль"), "письмо похоже на бота": cnt(r"похоже на бота"),
            "сбои поиска": cnt(r"не удал|не прочитан|ошибк"), "НЕ ПИШУ (guard)": cnt(r"НЕ ПИШУ"),
            "ограничения Telegram": cnt(r"ограничен|PEER_FLOOD|FloodWait|SpamBot: ЕСТЬ"),
            "новые вакансии": cnt(r"ВАКАНСИЯ: @"), "компании в очередь": cnt(r"бизнес в очередь"),
            "партнёры в очередь": cnt(r"партнёр в очередь"), "холодные лиды": cnt(r"холодный лид")}
    biz = collections.Counter(c.get("status") for c in ((st.get("biz") or {}).get("companies") or {}).values())
    pt = st.get("partners") or {}
    s = settings or {}
    return {"days": days, "bots": {BOTS[k]: {kk: vv for kk, vv in v.items()} for k, v in per.items()},
            "reasons": dict(reasons), "log": logm,
            "queues": {"вакансии": len(st.get("hot_q") or []), "холодная": len(st.get("cold_q") or [])},
            "companies": dict(biz), "partners": {"каналов в очереди": len(pt.get("frontier") or []), "досок": len(pt.get("boards") or []),
                                                 "ждут письма": len(pt.get("pending") or [])},
            "settings": {k: s.get(k) for k in SAFE}, "limited_until": st.get("limited_until") or ""}

def rule_findings(m):
    """Диагноз без нейросети: [(проблема, решение, действие|None)]."""
    out = []
    S = m["settings"]
    for name, b in m["bots"].items():
        n, r = b["sent"], b["replied"]
        if n >= 15 and r == 0:
            out.append((f"{name}: {n} писем за {m['days']} дн. и ни одного ответа",
                        "первое сообщение не цепляет или не та аудитория. Сменить первую фразу и оффер, проверить пару писем глазами", None))
        elif n >= 10 and r * 100 // n < 8:
            out.append((f"{name}: ответов всего {100 * r // n}% ({r} из {n})", "слабое начало письма, нужна более конкретная деталь про человека", None))
        if r >= 5 and b["agreed"] == 0 and b["hot"] == 0:
            out.append((f"{name}: отвечают ({r}), но ни одного горячего", "узкое место в переговорах, а не в поиске. Разбери диалоги со скиллом sales-mentor", None))
    for name, k in (("1 Вакансии", "hot_on"), ("2 Компании", "biz_on"), ("3 Партнёры", "partners_on")):
        b = m["bots"].get(name, {"sent": 0})
        if S.get(k) is False: continue
        if b["sent"] == 0:
            out.append((f"{name}: за {m['days']} дн. не отправлено ни одного письма", "бот не находит контакты. Смотри лог и очередь", None))
    rs = m["reasons"]
    if rs.get("дорого / цена", 0) >= 3:
        out.append((f"Часто отказывают из-за цены ({rs['дорого / цена']} раз)", "предлагать вход дешевле: тест или сценарный пакет 7 000 ₽, а не сразу серию", None))
    if rs.get("реакция на рассылку/бота", 0) >= 1:
        out.append(("Кто-то заметил рассылку или бота", "снизить объём и паузы, проверить тексты фильтром «как человек»",
                    {"label": "Пауза 180 с и 10 холодных в день", "set": {"gap": 180, "limit_cold": 10}}))
    if m["log"]["ограничения Telegram"] or m["limited_until"]:
        out.append(("Telegram ограничивал аккаунт", "снизить лимиты на 3 дня",
                    {"label": "Лимиты 25/10, пауза 180 с", "set": {"limit_hot": 25, "limit_cold": 10, "gap": 180}}))
    if m["queues"]["холодная"] >= 25 and S.get("limit_cold", 20) <= 20 and not m["limited_until"]:
        out.append(("Холодная очередь копится (" + str(m["queues"]["холодная"]) + ")", "контактов больше, чем лимит, можно чуть поднять",
                    {"label": "Холодных 30 в день", "set": {"limit_cold": 30}}))
    comp = m["companies"]
    tot = sum(comp.values())
    if tot >= 30 and comp.get("no_tg", 0) * 100 // tot > 70:
        out.append((f"Компании: у {comp.get('no_tg', 0)} из {tot} нет Telegram", "искать компании, где Telegram указан: hh-вакансии с «пишите в тг», а не 2ГИС", None))
    if m["log"]["письмо похоже на бота"] >= 10:
        out.append(("Нейросеть часто пишет «как бот»", "письма уходят шаблоном, это нормально. Если много, можно сменить модель", None))
    return out

ANALYST = """Ты аналитик продаж и маркетолог, помогаешь Егору (монтажёр Reels, ролики под ключ, прайс: монтаж от 3 000 ₽, серия из 5 роликов 19 000 ₽, сценарный пакет 7 000 ₽). У него три бота в Telegram, которые сами пишут первое сообщение: 1 — отклики на вакансии монтажёра, 2 — компании (hh.ru, 2ГИС), 3 — партнёры (SMM, таргетологи, агентства: продают ролики Егора с наценкой 20%). Диалоги дальше ведёт Егор. Цель — первые оплаты в ближайшие 1–2 недели.
Тебе дадут цифры за последние дни: по каждому боту отправлено/ответили/отказы/горячие/согласились, тексты ответов и отказов, причины, события лога, очереди, настройки.
Задача: найти 1–3 главных узких места (где теряются деньги) и для каждого дать конкретное решение, которое можно сделать сегодня. Опирайся только на цифры, ничего не выдумывай; если данных мало (меньше 10 писем) — так и скажи и предложи, что делать, чтобы их набрать.
Можно предложить действия с настройками только из списка: hot_on/biz_on/partners_on/cold_on/fu_on (true/false), limit_hot (25/40/60), limit_cold (10/20/30/40), gap (60/90/180/300). Не предлагай рост лимитов, если были ограничения Telegram.
Пиши по-русски, коротко, на «ты», без воды и без markdown-звёздочек.
Ответ строго JSON: {"summary": "1–2 предложения: что сейчас главное", "problems": [{"problem": "...", "fix": "..."}], "actions": [{"label": "коротко", "set": {"ключ": значение}}]}"""

def _clean_actions(acts):
    out = []
    for a in acts or []:
        st = {k: v for k, v in (a.get("set") or {}).items() if k in SAFE and v in SAFE[k]}
        if st and a.get("label"): out.append({"label": str(a["label"])[:40], "set": st})
    return out[:3]

def llm_review(m):
    try:
        import autoreply
        if not autoreply.llm_on(): return None
        data = json.loads(json.dumps(m, ensure_ascii=False, default=str))
        for b in data["bots"].values():
            b["replies"] = b["replies"][-8:]; b["refusals"] = b["refusals"][-8:]
        j, prov = autoreply._llm(ANALYST, [{"role": "user", "content": json.dumps(data, ensure_ascii=False)[:9000]}], 900)
        if not j or not j.get("summary"): return None
        probs = [p for p in (j.get("problems") or []) if p.get("problem") and p.get("fix")][:3]
        return {"summary": str(j["summary"])[:400], "problems": probs, "actions": _clean_actions(j.get("actions")), "by": prov}
    except Exception:
        return None

def report(st, log_text="", settings=None, days=7, use_llm=True):
    """→ (текст для Telegram, [действия {label, set}])"""
    m = metrics(st, log_text, settings, days)
    rows = []
    for name in ("1 Вакансии", "2 Компании", "3 Партнёры", "Эксперты (холодные)"):
        b = m["bots"].get(name)
        if not b: rows.append(f"• {name}: писем 0"); continue
        pct = f"{100 * b['replied'] // b['sent']}%" if b["sent"] else "0%"
        rows.append(f"• {name}: писем {b['sent']}, ответили {b['replied']} ({pct}), отказ {b['refused']}, горячих {b['hot']}, согласились {b['agreed']}")
    text = f"🧠 Разбор за {days} дн.\n\n" + "\n".join(rows)
    if m["reasons"]:
        text += "\n\nЧто пишут в ответ: " + ", ".join(f"{k} {v}" for k, v in sorted(m["reasons"].items(), key=lambda x: -x[1]))
    found = rule_findings(m)
    actions = [f[2] for f in found if f[2]]
    ai = llm_review(m) if use_llm else None
    if ai:
        text += f"\n\n🤖 Нейросеть: {ai['summary']}"
        for i, p in enumerate(ai["problems"], 1):
            text += f"\n{i}. {p['problem']}\n   → {p['fix']}"
        actions = ai["actions"] + [a for a in actions if a not in ai["actions"]]
    if found:
        text += "\n\n📏 По правилам:" + "".join(f"\n• {p}\n   → {f}" for p, f, _ in found)
    if not ai and not found:
        text += "\n\nПроблем по цифрам не видно. Если писем мало, просто дай ботам поработать."
    if not ai and use_llm:
        text += "\n\n(нейросеть сейчас недоступна, разбор только по правилам)"
    seen, uniq = set(), []
    cur = m["settings"]
    for a in actions:
        k = json.dumps(a["set"], sort_keys=True)
        if all(cur.get(x) == v for x, v in a["set"].items()): continue        # и так уже стоит — не предлагаем
        if k not in seen: seen.add(k); uniq.append(a)
    if uniq: text += "\n\nМожно применить кнопкой ниже, всё обратимо в 🤖 Боты и ⚙️ Настройки."
    return text[:3900], uniq[:3]

# ---------------------------------------------------------------- боль клиента ДО диалога
PAIN = """Ты маркетолог и продюсер коротких роликов, помогаешь Егору. Егор делает ролики под ключ: сценарий, раскадровка, монтаж Reels/Shorts/видеокреативов, клиент только снимает на телефон по плану. Съёмку, ведение соцсетей и рекламу он НЕ делает.
Тебе дадут всё, что известно о человеке или компании ДО диалога: текст вакансии, описание и посты Telegram-канала, био, резюме, нишу, цифры канала.
Задача:
1) pain — главная боль этого человека, связанная с видео и контентом, которую видно ИМЕННО из этих данных (не общая фраза). Пример: «нужно 12 рилс в месяц, а в вакансии просят ещё и сценарии — значит, некому придумывать идеи»; «в канале 3 тыс. подписчиков, а видео нет, новых людей не приходит»; «таргетологу нужны свежие креативы каждую неделю, а клиент сам их не делает».
2) solution — как Егор закрывает эту боль, одной фразой (для Егора, что предложить в разговоре).
3) line — 1–2 предложения для первого сообщения в Telegram от имени Егора: своими словами назвать эту боль так, чтобы человек узнал себя, и сказать, как Егор её снимает. Голос Егора: на «вы», на запятых, без «!», без эмодзи, без кавычек и цитат, без перечислений через запятую, без ссылок, без цен, без выдуманных фактов и цифр (цифры только из данных), без обещаний результата, мужской род, 120–260 символов. Начинай не с «Я» и не с приветствия.
Примеры line в голосе Егора (ритм, не копируй):
«Вижу, что идеи и сценарии на 12 роликов в месяц у вас тоже на исполнителе, а это самое тяжёлое, я как раз беру ролик целиком, от идеи до монтажа, вам остаётся снять на телефон»
«Судя по постам, креативы у ваших клиентов выгорают за неделю, а новые сами они не сделают, я могу закрывать это потоком, вы только ставите в рекламу»
«У вас 2400 подписчиков, а видео в канале нет, новые люди сейчас приходят как раз через короткие ролики, я могу сделать их из ваших же постов»
Нельзя: «я предлагаю», «готов предоставить», «готовый контент», «без лишних усилий», «вы готовы к…?», канцелярит и вопросы-ловушки.
Если данных слишком мало, чтобы увидеть конкретную боль, верни {"skip": true}.
Ответ строго JSON: {"pain": "...", "solution": "...", "line": "..."}"""

WHO = {"hot": "человек, который ищет монтажёра (вакансия)", "BIZ": "компания (нашёл через hh.ru / 2ГИС / сайт)",
       "PARTNER": "SMM-специалист / таргетолог / агентство — потенциальный партнёр (продаёт ролики Егора своим клиентам с наценкой 20%)",
       "cold": "эксперт со своим Telegram-каналом"}

def lead_pain(item, kind):
    """→ {"pain", "solution", "line"} или None. Нейросеть читает контекст человека до первого письма."""
    try:
        import autoreply, human
        if not autoreply.llm_on() or not item.get("ctx"): return None
        who = WHO.get(item.get("variant") if item.get("variant") in ("BIZ", "PARTNER") else kind, WHO["cold"])
        j, _ = autoreply._llm(PAIN, [{"role": "user", "content": f"Кто: {who}\nИмя: {item.get('display', '')}\n\n{item['ctx'][:2000]}"}], 500)
        if not j or j.get("skip") or not j.get("line") or not j.get("pain"): return None
        line = human.humanize(autoreply.voicefy(str(j["line"]).strip()))
        line = line[:1].upper() + line[1:]
        nums_ok = all(n in item["ctx"] for n in re.findall(r"\d{2,}", line))          # цифры — только из данных
        if re.search(r"\bЕгор\w*|сервис|мы (делаем|берём|предлагаем)|наша", line, re.I): return None     # только от первого лица
        if not (80 <= len(line) <= 300) or not nums_ok or "₽" in line or human.looks_bot(line) or not autoreply._sane(line, item["ctx"], first=True):
            return None
        return {"pain": str(j["pain"])[:300], "solution": str(j.get("solution", ""))[:300], "line": line}
    except Exception:
        return None

def inject(text, line):
    """Вставляет «боль + решение» в письмо: вместо второго сообщения (3 сообщения) или вторым (2 сообщения)."""
    import human
    ps = human.parts(text)
    if len(ps) >= 3: ps[1] = line
    elif len(ps) == 2: ps.insert(1, line)
    else: ps.append(line)
    return "\n\n".join(ps)

# ---------------------------------------------------------------- совет по ответу клиенту
ADVISE = """Ты наставник Егора по продажам. Егор — монтажёр, делает ролики под ключ (сценарий, раскадровка, монтаж). Прайс 3.0: монтаж ролика 3 000 / 5 000 / 8 000 ₽, серия из 5 роликов под ключ 19 000 ₽, сценарный пакет 7 000 ₽, продюсер на месяц 50 000 ₽. Бесплатно — только тест 10–15 секунд или 3 идеи роликов. Предоплата 50%. Для партнёров (SMM, таргетологи): Егор работает по прайсу, партнёр продаёт клиенту с наценкой 20%.
Тебе дадут: кто это (вакансия, компания, партнёр, эксперт), первое письмо Егора и ответ человека.
Задача: 1) одной фразой — что человек на самом деле хочет или чего боится; 2) готовый ответ от имени Егора, который двигает к следующему шагу (тест, созвон, цена, исходник). Ответ в голосе Егора: на «вы», с обращения по имени с большой буквы («Сергей, ...»), дальше со строчной, коротко (до 350 знаков), без «!», эмодзи и канцелярита, один вопрос в конце. Не выдумывай кейсов, цен вне прайса и обещаний результата. 3 000 / 5 000 / 8 000 ₽ — это простой / средний / сложный монтаж, а не длительность ролика. Сроки называй только такие: короткий ролик 1–2 дня, тест за сутки. Если для точной цены не хватает данных — задай один уточняющий вопрос вместо цены.
Ответ строго JSON: {"insight": "...", "reply": "..."}"""

def reply_advice(e, their_text):
    """→ {"insight", "reply"} или None. Только совет: отправляет Егор кнопкой."""
    try:
        import autoreply, human
        if not autoreply.llm_on(): return None
        who = {"hot": "вакансия (человек искал монтажёра)", "BIZ": "компания", "PARTNER": "партнёр (SMM/таргетолог/агентство)"}.get(
            e.get("variant") if e.get("variant") in ("BIZ", "PARTNER") else e.get("kind"), "эксперт, холодное письмо")
        pn = e.get("pain") or {}
        pain_txt = f"Боль, найденная до диалога: {pn.get('pain')}; решение: {pn.get('solution')}\n" if pn else ""
        msg = (f"Кто: {who}\nИмя: {e.get('display', '')}\n{pain_txt}\n"
               f"Первое письмо Егора:\n{(e.get('text') or '')[:900]}\n\nОтвет человека:\n{their_text[:600]}")
        j, _ = autoreply._llm(ADVISE, [{"role": "user", "content": msg}], 500)
        if not j or not j.get("reply"): return None
        r = human.humanize(autoreply.voicefy(str(j["reply"]).strip()))
        r = r[:1].upper() + r[1:]
        if len(r) < 20 or len(r) > 600 or not autoreply._sane(r, their_text) or human.looks_bot(r, allow_link=True): return None
        return {"insight": str(j.get("insight", ""))[:200], "reply": r}
    except Exception:
        return None
