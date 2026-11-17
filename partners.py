# -*- coding: utf-8 -*-
"""Бот 3 «Поиск партнёров»: SMM-специалисты, таргетологи, SMM/digital-агентства → партнёрский оффер в Telegram от имени Егора.

Работает внутри основного бота (autoclient.py, облако GitHub Actions), как bizhunt:
    partners.partner_step(st["partners"], skip, tg_search=web.search_channels, parse=parse_channel)
→ список готовых сообщений (variant "PARTNER") → общая холодная очередь autoclient (лимиты, часы, @SpamBot, guard, дожим).

Источники:
  1. Поиск Telegram (Telegram Web основного аккаунта) по запросам «таргетолог», «smm агентство» … → каналы специалистов
     и агентств → контакт владельца из описания канала («по вопросам — @...»).
  2. Доски вакансий/резюме SMM (t.me/s, без аккаунта): посты #резюме SMM/таргет → @ник автора.
  3. Снежный ком: ссылки из описаний профильных каналов → в очередь на проверку.
Оффер (15.11, Егор): партнёр берёт ролики по прайсу 3.0 и продаёт клиенту под своим брендом с наценкой 20%;
бесплатный тест 10–15 с на материале его клиента. Условия для переговоров — «Оффер партнёрам.md» рядом.
"""
import os, re, sys, time, random, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(os.path.dirname(BASE), "Поиск бизнеса"), BASE):
    if p not in sys.path: sys.path.append(p)
import bizhunt as B          # fetch, clean, tg_kind, TG_INFO, handles_in, first_name, to_parts

def log(*a): B.log("партнёры:", *a)

QUERIES = ["таргетолог", "smm специалист", "smm агентство", "таргетированная реклама", "smm менеджер",
           "таргет вконтакте", "продвижение в соцсетях", "ведение соцсетей", "smm продвижение", "digital агентство",
           "таргетолог вк", "маркетолог фриланс", "реклама вконтакте", "smm для бизнеса", "таргет инстаграм",
           "агентство smm продвижения", "интернет маркетолог", "контент маркетинг", "smm студия", "таргетолог москва",
           "smm менеджер фриланс", "маркетинговое агентство", "продвижение бизнеса", "таргетолог отзывы",
           "вакансии smm", "smm работа удаленно", "таргетолог вакансии", "резюме smm",
           # 17.11 «Видео без владельца»: маркетологи, менеджеры по рекламе/маркетингу, продюсеры и агентства с клиентами, которым некогда сниматься
           "менеджер по маркетингу", "руководитель маркетинга", "менеджер по рекламе", "продюсер блогеров", "продюсер экспертов",
           "маркетолог для экспертов", "контент-менеджер", "маркетолог в клинику", "маркетолог в строительство", "маркетинг для малого бизнеса"]
BOARDS = ["vakansii_smm", "marketing_jobs", "digital_vakansii", "smmvacancy", "normrabota"]   # доски, где бывают #резюме SMM

ROLE = re.compile(r"smm|смм|таргет|target|маркетолог|маркетинг|продвижени|соц\.?\s?сет|директолог|авитолог|digital|диджитал|реклам|продюсер|контент-?менеджер", re.I)
BOARD = re.compile(r"ваканси|работа|резюме|фриланс|freelance|job|карьер|удал[её]нк", re.I)
SCHOOL = re.compile(r"курс|школа|академи|обучени|обучаю|марафон|интенсив|наставничеств|университет|колледж", re.I)
RESUME = re.compile(r"#резюме|#ищу_?работу|#ищуработу|#ищу_?клиент|#ищу_?проект|#помогу|ищу клиентов|ищу проект|беру проект|возьму проект|ищу заказ|свободн\w* для проект", re.I)
NOT_RES = re.compile(r"#ваканси|#vacancy|ищем|требуется|в команду нужен|нужен смм|нужен smm|нужен таргетолог", re.I)
COMPETITOR = re.compile(r"монтаж[её]р|видеомонтаж|рилсмейкер|reelsmaker|мобилограф|видеограф|моушн|motion", re.I)
AD_NEAR = re.compile(r"(реклам\w*|\bads\b|прайс на рекламу|размещени\w*)[^@]{0,25}$", re.I)

def _no_dm(text):
    try:
        import guard
        return guard.no_dm(text)
    except Exception:
        return ""

def owner_handles(desc, channel):
    """Ники из описания канала: сначала «автор/связь/по вопросам», менеджер по рекламе — последним (он не владелец)."""
    out = []
    for m in re.finditer(r"@([A-Za-z][A-Za-z0-9_]{4,31})|t\.me/([A-Za-z][A-Za-z0-9_]{4,31})", desc or ""):
        u = m.group(1) or m.group(2)
        if u.lower() == channel.lower() or u in [x for x, _ in out]: continue
        out.append((u, bool(AD_NEAR.search(desc[max(0, m.start() - 40):m.start()]))))
    return [u for u, ad in sorted(out, key=lambda x: x[1])]

FRESH_DAYS = 30
SUBS = (20, 60000)

def role_of(text):
    t = (text or "").lower()
    if re.search(r"агентств|студи[яи]|agency|команда маркетолог|продакшн", t): return "agency"
    if re.search(r"таргет|target|директолог|авитолог|реклам[аы] в вк|ads\b", t): return "target"
    if re.search(r"smm|смм|соцсет|соц\. сет|ведение", t): return "smm"
    if re.search(r"продюсер|менеджер\w* по (маркетингу|рекламе)|контент-?менеджер|руководител\w* маркетинг", t): return "manager"
    if re.search(r"маркетолог|маркетинг|продвижени|digital|диджитал", t): return "marketing"
    return ""

def _fresh(posts, days):
    now = datetime.datetime.now(datetime.timezone.utc)
    return [p for p in posts if p.get("when") and (now - p["when"]).days <= days]

def _person(u, skip):
    if not u or skip(u) or u.lower().endswith("bot"): return False
    k = B.tg_kind(u); time.sleep(0.5)
    return k == "person"

# ---------------------------------------------------------------- сообщение
PARTNER = """Ты пишешь первое сообщение в Telegram в личку от имени Егора. Его идея «Видео без владельца»: он берёт видео на себя, сотрудники клиента снимают по минуте в день, монтаж и публикация на нём. Он лично нашёл канал или резюме этого человека и пишет как живой человек с телефона, а не как рассылка.
Кому: SMM-специалист, таргетолог, маркетолог, менеджер по маркетингу или рекламе, продюсер или SMM/digital-агентство. У них есть клиенты, которым нужно видео, но владельцы не хотят и не успевают им заниматься.
Что предлагает Егор (партнёрство, не продажу):
— он берёт видео на себя: сценарии, монтаж, публикация, а клиент партнёра по заданиям Егора снимает свою работу по минуте в день;
— ролики под брендом партнёра: партнёр платит Егору по его прайсу и продаёт клиенту с наценкой 20% (это заработок партнёра), клиент общается только с партнёром;
— первый тест на материале клиента партнёра бесплатно.
Тебе дадут факты: кто это (таргетолог/SMM/агентство), откуда контакт (канал или резюме на доске), название канала, кусок описания или поста, имя из профиля.
Как писать:
— 3 коротких абзаца (уйдут отдельными сообщениями), всего 300–600 символов. Как в мессенджере.
— Начало: «Имя, добрый день,» только если имя — настоящее имя человека; иначе «Добрый день,». Сразу честно, откуда о нём знаешь («увидел ваш канал про таргет», «увидел ваше резюме в канале …») и одна конкретная деталь из фактов.
— Второй абзац: кто ты одной фразой и почему пишешь именно ему (таргетологу — свежие видеокреативы, без них реклама выгорает; SMM — клиенты просят Reels, а монтировать некогда; агентству — постоянный человек на видео без найма).
— Третий абзац: схема коротко (по моему прайсу, ваша наценка 20%, под вашим брендом), бесплатный тест и один простой вопрос в конце.
— Никаких ссылок, цен в рублях, обещаний результата, выдуманных фактов и кейсов. Не пиши «я бот», «рассылка», «предложение о сотрудничестве», «уважаемые», «с уважением», «буду рад», «привет». Без эмодзи и восклицательных знаков. Мужской род.
{VOICE}
Ответ строго JSON: {"text": "сообщение"}"""

def facts_of(c):
    kind = {"target": "таргетолог", "smm": "SMM-специалист", "agency": "SMM/digital-агентство", "marketing": "маркетолог",
            "manager": "менеджер по маркетингу/рекламе или продюсер"}.get(c["role"], "SMM/маркетинг")
    src = f"резюме на доске «{c.get('board_title') or c.get('board')}»" if c["src"] == "resume" else f"его канал «{c.get('title')}»"
    return (f"Кто: {kind}\nОткуда контакт: {src}\nИмя в профиле Telegram: {c.get('who') or 'нет'}\n"
            f"Фрагмент: {(c.get('snippet') or '')[:400]}")

USE_LLM = False   # 15.11: бесплатная модель пишет «Хочете», имя латиницей, домыслы — партнёрам только выверенный шаблон

def compose(c):
    if not USE_LLM: return template(c), "шаблон"
    try:
        import autoreply
        if autoreply.llm_on():
            for _ in range(2):
                j, prov = autoreply._llm(PARTNER.replace("{VOICE}", autoreply.VOICE), [{"role": "user", "content": facts_of(c)}], 600)
                if not j:
                    log("ИИ не ответил, беру шаблон"); break
                t = autoreply.voicefy(B.to_parts(str(j.get("text", "")).strip()))
                if (200 <= len(t) <= 800 and "http" not in t and "t.me" not in t and "20%" in t and "₽" not in t
                        and autoreply._sane(t, first=True)):
                    return t, prov
                log("ИИ-сообщение отбраковано:", t[:120].replace("\n", " / "))
    except Exception as e:
        log("ИИ недоступен:", str(e)[:80])
    return template(c), "шаблон"

B.RU_NAMES |= set("""лина ангелина злата мира ева есения василиса снежана регина камила камилла эльвира альбина алия адель асель
артур давид марк даниил данил данила богдан ринат рустам тигран арина вика ника лера соня алёна ульяна милена""".split())

TOPICS = [(r"вконтакт|\bвк\b|vk", "про ВК"), (r"авито", "про Авито"), (r"маркетплейс|wildberries|\bwb\b|ozon|озон", "про маркетплейсы"),
          (r"инстаграм|instagram|инст\b", "про инсту"), (r"телеграм|telegram|посев", "про Telegram"),
          (r"недвижим|риелт|застройщ", "про недвижимость"), (r"бьюти|beauty|салон|космет|ногт|маникюр", "про бьюти"),
          (r"эксперт|инфобиз|запуск|онлайн-школ", "про экспертов и запуски"), (r"ресторан|кафе|доставк", "про общепит"),
          (r"кейс", "с кейсами")]

def topic(text):
    """Одна живая деталь своими словами («пишете про ВК», «с кейсами») — вместо цитаты названия канала."""
    for rx, w in TOPICS:
        if re.search(rx, text or "", re.I): return w
    return ""

def template(c):
    """Как пишет Егор с телефона: со строчной после приветствия, на запятых, без точки в конце, одна деталь, один вопрос.
    Без названия канала в кавычках, без перечислений услуг, без ссылок. 2 или 3 сообщения — по-разному."""
    R = random.choice
    cap = lambda s: s[:1].upper() + s[1:]
    fn = B.first_name(c.get("who", ""))
    hi = f"{fn}, {R(['добрый день', 'здравствуйте'])}" if fn else R(["Добрый день", "Здравствуйте"])
    role = c["role"]
    tp = topic((c.get("snippet") or "") + " " + (c.get("title") or ""))
    who = {"target": "таргет", "smm": "SMM", "marketing": "маркетинг", "agency": "продвижение", "manager": "маркетинг"}.get(role, "SMM")
    if c["src"] == "resume":
        a = R([f"{hi}, увидел ваше резюме в канале с вакансиями по SMM",
               f"{hi}, наткнулся на ваше резюме в SMM-канале" + (f", вижу, вы работаете {tp}" if tp else ""),
               f"{hi}, попалось ваше резюме в канале с вакансиями, решил написать"])
    elif role == "agency":
        a = R([f"{hi}, наткнулся на ваш канал, вы же агентство, правильно понимаю?",
               f"{hi}, нашёл ваше агентство в Telegram" + (f", вижу, много пишете {tp}" if tp else ""),
               f"{hi}, посмотрел ваш канал, вы ведь берёте клиентов на продвижение?"])
    else:
        a = R([f"{hi}, наткнулся на ваш канал про {who}" + (f", особенно {tp}" if tp and R([0, 1]) else ""),
               f"{hi}, посмотрел ваш канал, вы же {'таргетолог' if role == 'target' else 'SMM-щик' if role == 'smm' else 'маркетолог'}, правильно понимаю?",
               f"{hi}, полистал ваш канал" + (f", вы пишете {tp}" if tp else f" про {who}")])
    # 17.11 «Видео без владельца»: у партнёра есть клиенты, которым некогда или не хочется заниматься видео. Я беру видео на себя,
    # клиент снимает по минуте в день по моим заданиям, монтаж и публикация на мне, всё под брендом партнёра, наценка партнёра 20%.
    ask = R(["интересно?", "как вам такое?", "актуально для вас?"])
    # 2 строки — откуда знаю → схема одной фразой → один вопрос. Без бесплатного теста и длинного «зачем вам».
    short = R(["я беру видео на себя: ваши клиенты снимают по минуте в день по моим заданиям, монтаж и публикация на мне под вашим брендом, вы ставите сверху 20%",
               "я делаю видео для клиентов, которым некогда им заниматься: они снимают по минуте в день, остальное на мне под вашим брендом, наценка ваша 20%"])
    return f"{a}\n{cap(short)}, {ask}"

def item_of(c):
    return {"username": c["username"], "invited": False, "found": time.time(), "post": "", "display": c.get("who") or c.get("title") or "",
            "variant": "PARTNER", "niche": "партнёр-" + (c["role"] or "smm"), "uniq": 1, "source": c["source"],
            "ctx": (f"Кто: {c['role']} ({'резюме на доске вакансий' if c['src'] == 'resume' else 'свой Telegram-канал'})\n"
                    f"Канал/доска: {c.get('title') or c.get('board_title') or ''}\nТекст: {c.get('snippet', '')}")[:2000],
            "text": re.sub(r"\s*\n\s*", "\n\n", c["text"].strip())}

# ---------------------------------------------------------------- поиск
def scan_board(name, ch, ps, skip):
    """Пост #резюме SMM/таргет на доске → кандидаты (ник автора из поста)."""
    out = []
    seenp = set(ps.setdefault("posts", []))
    for p in ch["posts"]:
        if p["id"] in seenp: continue
        seenp.add(p["id"])
        t = p["text"]
        if not RESUME.search(t) or NOT_RES.search(t) or not ROLE.search(t): continue
        if COMPETITOR.search(t[:300]) and not re.search(r"таргет|smm-?специалист|smm-?менеджер", t[:300], re.I): continue   # монтажёр = конкурент
        if _no_dm(t): continue
        if p.get("when") and (datetime.datetime.now(datetime.timezone.utc) - p["when"]).days > 14: continue
        for u in B.handles_in(t)[:2]:
            if u.lower() == name.lower(): continue
            if _person(u, skip):
                out.append({"username": u, "src": "resume", "board": name, "board_title": ch.get("title") or name,
                            "role": role_of(t) or "smm", "snippet": t[:500], "source": f"https://t.me/{p['id']}",
                            "who": (B.TG_INFO.get(u.lower()) or {}).get("title", "")})
                break
    ps["posts"] = list(seenp)[-3000:]
    return out

def check_channel(name, ch, ps, skip):
    """Канал специалиста/агентства → контакт владельца; доска → в список досок; ссылки → снежный ком."""
    text = f"{ch.get('title', '')} {ch.get('desc', '')}"
    if not ROLE.search(text): return []
    if BOARD.search(ch.get("title", "")):
        if name not in ps["boards"] and _fresh(ch["posts"], 7): ps["boards"].append(name); log(f"новая доска резюме/вакансий @{name}")
        return scan_board(name, ch, ps, skip)
    fr = ps["frontier"]; known = set(ps["seen"]) | {x.lower() for x in fr}
    for n in re.findall(r"t\.me/([A-Za-z][A-Za-z0-9_]{4,31})", ch.get("desc", "")) + [l for p in ch["posts"][-10:] for l in p.get("links", [])][:20]:
        if n.lower() not in known and not n.lower().endswith("bot"): fr.append(n); known.add(n.lower())
    if SCHOOL.search(ch.get("title", "")) or len(SCHOOL.findall(ch.get("desc", ""))) >= 2: return []   # школы и курсы SMM — у них ученики, а не клиенты
    if COMPETITOR.search(ch.get("title", "")): return []                   # канал монтажёра/рилсмейкера — конкурент, не партнёр
    if _no_dm(ch.get("desc", "")): return []
    if not (SUBS[0] <= (ch.get("subs") or 0) <= SUBS[1]) or not _fresh(ch["posts"], FRESH_DAYS): return []
    for u in owner_handles(ch.get("desc", ""), name)[:3]:
        if u.lower() == name.lower(): continue
        if _person(u, skip):
            last = next((p["text"] for p in reversed(ch["posts"]) if len(p["text"]) > 60), "")
            return [{"username": u, "src": "channel", "title": ch.get("title") or name, "role": role_of(text) or "smm",
                     "snippet": (ch.get("desc", "") + " | " + last)[:500], "source": f"https://t.me/{name}",
                     "who": (B.TG_INFO.get(u.lower()) or {}).get("title", "")}]
    return []

def partner_step(ps, skip=lambda u: False, tg_search=None, parse=None, max_new=2, max_check=6):
    """Один шаг (autoclient зовёт раз в 15 мин): до max_check каналов проверить, до max_new сообщений вернуть.
    ps — st["partners"] в state.json основного бота. parse(name) — autoclient.parse_channel (t.me/s)."""
    if not parse: return []
    for k, v in (("frontier", []), ("seen", []), ("boards", []), ("qi", 0), ("bi", 0), ("pending", []), ("posts", [])):
        ps.setdefault(k, v)
    seen = set(ps["seen"])
    cands = []
    # 1. доска резюме — одна за шаг, по кругу
    boards = list(dict.fromkeys(BOARDS + ps["boards"]))
    if boards:
        b = boards[ps["bi"] % len(boards)]; ps["bi"] += 1
        ch = parse(b); time.sleep(1)
        if ch: cands += scan_board(b, ch, ps, skip)
    # 2. поиск Telegram → каналы
    if not ps["frontier"] and tg_search:
        q = QUERIES[ps["qi"] % len(QUERIES)]; ps["qi"] += 1
        try:
            found = [n for n in tg_search(q) if n.lower() not in seen]
            ps["frontier"] += found; log(f"поиск «{q}»: новых каналов {len(found)}")
        except Exception as e:
            log("поиск в Telegram не удался:", str(e)[:80])
    for _ in range(max_check):
        if not ps["frontier"] or len(cands) >= max_new: break
        n = ps["frontier"].pop(0)
        if n.lower() in seen: continue
        seen.add(n.lower())
        ch = parse(n); time.sleep(random.uniform(1, 2))
        if ch: cands += check_channel(n, ch, ps, skip)
    ps["seen"] = list(seen)[-8000:]; ps["frontier"] = ps["frontier"][:300]
    # 3. письма: лишние кандидаты ждут следующего шага
    pend = {c["username"].lower(): c for c in ps["pending"] + cands}
    out = []
    for ul, c in list(pend.items()):
        if len(out) >= max_new: break
        del pend[ul]
        if skip(c["username"]): continue
        c["text"], by = compose(c)
        out.append(item_of(c))
        log(f"партнёр @{c['username']} ({c['role']}, {c['src']}) ← {c['source']} [{by}]")
    ps["pending"] = list(pend.values())[:30]
    return out

if __name__ == "__main__":        # локальная проверка без отправки: доски + шаблоны
    sys.path.insert(0, os.path.join(os.path.dirname(BASE), "Автопоиск клиентов (telegram)", "auto"))
    import autoclient
    ps = {}
    for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 3):
        for it in partner_step(ps, parse=autoclient.parse_channel):
            print("\n=== @" + it["username"], it["niche"], it["source"], "\n" + it["text"])
    print("\nдосок:", len(BOARDS + ps.get("boards", [])), "pending:", len(ps.get("pending", [])))
