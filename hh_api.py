# -*- coding: utf-8 -*-
"""Бот 4: автономные отклики на hh.ru через ОФИЦИАЛЬНЫЙ API соискателя (api.hh.ru), без браузера и без капчи на кнопке.

Нужны секреты (раз и навсегда, см. «hh — как подключить.md»):
  HH_CLIENT_ID, HH_CLIENT_SECRET — приложение Егора на dev.hh.ru
  HH_ACCESS, HH_REFRESH, HH_EXP   — токены после входа (скрипт hh_auth.py кладёт их в секреты GitHub сам)
  HH_UA                           — «ClientSearch/1.0 (почта)», hh требует контакт разработчика в User-Agent
Токены обновляются сами и хранятся в state.json (облачный кэш).

Что делает (раз в несколько минут, внутри autoclient):
  • ищет удалённые вакансии монтажёра/рилсмейкера/мобилографа за 3 дня;
  • пропускает: с тестом, с откликом на внешнем сайте, архивные, «офис», уже откликнулись в эту компанию;
  • пишет сопроводительное по тексту вакансии (нейросеть + проверки «как человек», иначе шаблон) и откликается;
  • не больше LIMIT в день, пауза 3–8 мин, 9–21 МСК; одна компания — один отклик;
  • раз в 30 мин смотрит отклики: приглашение / отказ / новое сообщение → уведомление Егору с советом нейросети.
Если hh вдруг попросит капчу — бот НЕ обходит её, а присылает Егору ссылку и ждёт.
"""
import os, re, json, time, random, datetime, html, urllib.request, urllib.parse, urllib.error

API = "https://api.hh.ru"
LIMIT = 20
GAP = (180, 480)
HOURS = (0, 24)            # 16.11 Егор: круглосуточно, с паузами GAP и дневным лимитом
QUERIES = ["рилсмейкер", "монтажер reels", "видеомонтажер", "мобилограф", "монтажер видео", "монтажер shorts",
           "моушн-дизайнер", "видеомонтаж удаленно", "монтажер роликов", "контент-мейкер видео"]
ROLE = re.compile(r"монтаж|рилс|reels|shorts|мобилограф|моушн|motion|видео|video|контент-?мейкер|ugc", re.I)
SKIP = re.compile(r"офис|оператор|фотограф\b|водител|продав|курьер|модел|стажер|стажёр|преподават|учител|наставник|инженер|"
                  r"видеонаблюд|монтажник|электромонт|сборщик|сантех", re.I)
PORTFOLIO = "https://t.me/zakulisy715"

def configured():
    return bool(os.environ.get("HH_CLIENT_ID") and (os.environ.get("HH_REFRESH") or os.environ.get("HH_ACCESS")))

def _ua():
    return os.environ.get("HH_UA") or "ClientSearch/1.0"

def _req(method, path, st, data=None, auth=True, retry=True):
    url = path if path.startswith("http") else API + path
    hdr = {"HH-User-Agent": _ua(), "User-Agent": _ua(), "Accept": "application/json"}
    if auth: hdr["Authorization"] = "Bearer " + token(st)
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    if body is not None: hdr["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=hdr, method=method), timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try: j = json.loads(raw)
        except Exception: j = {"raw": raw[:300]}
        if e.code == 403 and auth and retry and "token" in raw and "expired" in raw:      # токен протух раньше срока
            st.setdefault("hh_api", {})["exp"] = 0
            return _req(method, path, st, data, auth, retry=False)
        return e.code, j

def token(st):
    t = st.setdefault("hh_api", {})
    if not t.get("access"):
        t.update(access=os.environ.get("HH_ACCESS", ""), refresh=os.environ.get("HH_REFRESH", ""),
                 exp=float(os.environ.get("HH_EXP") or 0))
    if t.get("access") and time.time() < t.get("exp", 0) - 3600: return t["access"]
    if t.get("access") and not t.get("exp"): return t["access"]
    # access истёк → refresh (у hh refresh одноразовый: новый сохраняем в state.json)
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": t.get("refresh", "")}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://hh.ru/oauth/token", data=body,
                                    headers={"User-Agent": _ua(), "Content-Type": "application/x-www-form-urlencoded"}), timeout=30) as r:
            j = json.loads(r.read().decode())
        t.update(access=j["access_token"], refresh=j.get("refresh_token", t.get("refresh")), exp=time.time() + int(j.get("expires_in", 1209600)))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        if "token not expired" in raw: t["exp"] = time.time() + 86400           # ещё живой — пользуемся
        else: t["dead"] = raw[:200]
    return t.get("access", "")

def resume_id(st):
    t = st.setdefault("hh_api", {})
    if t.get("resume"): return t["resume"]
    code, j = _req("GET", "/resumes/mine", st)
    items = (j or {}).get("items") or []
    pub = [r for r in items if (r.get("status") or {}).get("id") == "published"] or items
    if pub: t["resume"] = pub[0]["id"]
    return t.get("resume")

def text_of(htm):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", htm or ""))).strip()

def search(st):
    out = {}
    for q in QUERIES:
        code, j = _req("GET", "/vacancies?" + urllib.parse.urlencode({"text": q, "schedule": "remote", "period": 3, "per_page": 50,
                                                                      "order_by": "publication_time", "area": 113}), st)   # без входа hh отвечает 403
        for v in (j or {}).get("items") or []:
            name = v.get("name", "")
            if not ROLE.search(name) or SKIP.search(name): continue
            if v.get("has_test") or v.get("archived") or v.get("response_url"): continue    # тест / отклик на чужом сайте
            out.setdefault(str(v["id"]), {"id": str(v["id"]), "name": name, "employer": (v.get("employer") or {}).get("name", ""),
                                          "employer_id": str((v.get("employer") or {}).get("id") or ""), "url": v.get("alternate_url", "")})
        time.sleep(random.uniform(1, 2))
    return list(out.values())

LETTER = """Ты пишешь сопроводительное письмо к отклику на hh.ru от имени Егора — монтажёра коротких вертикальных роликов (Reels/Shorts), делает их под ключ: сценарий, раскадровка, монтаж. Работает удалённо. Портфолио: https://t.me/zakulisy715, Telegram @chernyshev_edit.
Тебе дадут вакансию и её текст. Найди главную боль работодателя, которую видно из текста (объём роликов, нет идей и сценариев, нужен стиль, сроки, нужен человек надолго), и построй письмо вокруг неё.
Голос Егора: начни «Здравствуйте,», дальше со строчной, на запятых, 2–3 коротких абзаца, 350–650 символов, без «!», без эмодзи, без длинных тире, без перечислений через запятую, без «уважаемые», «с уважением», «буду рад», «с удовольствием», «это как раз мой профиль». Одна конкретная деталь из вакансии своими словами (не цитата в кавычках), как Егор снимает эту боль, предложение сделать тестовое, в конце портфолио и Telegram. Не выдумывай опыт в их нише, кейсы, цифры, обещания результата, возраст. Мужской род.
Ответ строго JSON: {"text": "письмо"}"""

def letter(v, desc):
    try:
        import autoreply, human, analyst
        if autoreply.llm_on():
            j = analyst._llm_guarded(LETTER, [{"role": "user", "content": f"Вакансия: {v['name']}\nКомпания: {v['employer']}\n\n{desc[:2500]}"}], 700)
            if j:
                t = human.humanize(autoreply.voicefy(str(j.get("text", "")).strip()), allow_link=True)
                if 250 <= len(t) <= 1000 and "zakulisy715" in t and autoreply._sane(t, desc, first=True) and not human.looks_bot(t, allow_link=True):
                    return t, "ИИ"
    except Exception:
        pass
    R = random.choice
    role = "монтажёра" if re.search(r"монтаж", v["name"], re.I) else "рилсмейкера" if re.search(r"рилс|reels", v["name"], re.I) else "человека на видео"
    t = (f"Здравствуйте, {R(['увидел', 'прочитал'])}, что вы ищете {role}, монтирую короткие вертикальные ролики, работаю удалённо с вашими исходниками\n\n"
         f"{R(['Могу закрыть задачу под ключ, от сценария до готового ролика', 'Беру ролик целиком, со сценарием и раскадровкой, или только монтаж'])}, "
         f"{R(['сроки держу', 'по срокам не подвожу'])}\n\n"
         f"{R(['Готов сделать тестовое, чтобы вы сразу оценили', 'Предлагаю начать с тестового, а там сами глянете'])}. Работы {PORTFOLIO}, Telegram @chernyshev_edit")
    return t, "шаблон"

def step(st, notify, log, s=None):
    """Один шаг: не чаще раза в GAP, в рабочие часы, до LIMIT в день. Возвращает True, если отклик ушёл."""
    if not configured(): return False
    h = st.setdefault("hh_api", {})
    if h.get("dead"):
        if h.get("dead_noted") != datetime.date.today().isoformat():
            h["dead_noted"] = datetime.date.today().isoformat()
            notify("⚠️ hh.ru: вход устарел, отклики стоят. Запусти на ПК «hh — войти (API).bat», это 1 минута.")
        return False
    if h.get("captcha_until", 0) > time.time(): return False
    hour = datetime.datetime.now().hour
    if not (HOURS[0] <= hour < HOURS[1]) or time.time() < h.get("next", 0): return False
    today = datetime.date.today().isoformat()
    day = h.setdefault("day", {})
    if day.get("date") != today: day.clear(); day.update(date=today, n=0)
    limit = int((s or {}).get("limit_hhapi", LIMIT))
    if day["n"] >= limit: return False
    applied = h.setdefault("applied", {})
    done_emp = {a.get("employer_id") for a in applied.values() if a.get("employer_id")}
    if not h.get("queue") or time.time() - h.get("searched", 0) > 3 * 3600:
        h["queue"] = [v for v in search(st) if v["id"] not in applied and v["employer_id"] not in done_emp]
        h["searched"] = time.time(); log(f"hh.ru API: в очереди вакансий {len(h['queue'])}")
    rid = resume_id(st)
    if not rid:
        log("hh.ru API: не нашёл опубликованное резюме"); h["next"] = time.time() + 3600; return False
    while h["queue"]:
        v = h["queue"].pop(0)
        if v["id"] in applied or v["employer_id"] in done_emp: continue
        code, full = _req("GET", f"/vacancies/{v['id']}", st)
        if code != 200 or full.get("archived") or full.get("has_test") or full.get("response_url"):
            applied[v["id"]] = {"skip": "тест/архив/чужой сайт", "employer_id": v["employer_id"]}; continue
        if (full.get("relations") or []): applied[v["id"]] = {"skip": "уже откликались", "employer_id": v["employer_id"]}; continue
        desc = text_of(full.get("description"))
        if SKIP.search(desc[:400]) and not ROLE.search(desc[:400]): applied[v["id"]] = {"skip": "не наш профиль"}; continue
        try:
            import guard
            if guard.no_dm(desc) and re.search(r"не (пишите|откликайтесь) без|только с тестов", desc, re.I):
                applied[v["id"]] = {"skip": "просят без сопроводительных"}; continue
        except Exception: pass
        txt, by = letter(v, desc)
        code, j = _req("POST", "/negotiations", st, {"vacancy_id": v["id"], "resume_id": rid, "message": txt})
        h["next"] = time.time() + random.uniform(*GAP)
        if code in (200, 201):
            applied[v["id"]] = {"employer_id": v["employer_id"], "name": v["name"], "employer": v["employer"], "url": v["url"],
                                "ts": time.time(), "letter": txt, "by": by, "state": "response", "desc": desc[:1500]}
            day["n"] += 1; done_emp.add(v["employer_id"])
            log(f"hh.ru ОТКЛИК [{by}] {v['name']} — {v['employer']} ({day['n']}/{limit})")
            return True
        errs = " ".join(str(e.get("value") or e.get("type")) for e in (j.get("errors") or [])) or json.dumps(j)[:200]
        if "captcha" in errs:
            cu = next((e.get("captcha_url") for e in j.get("errors") or [] if e.get("captcha_url")), "")
            h["captcha_until"] = time.time() + 3600; h["queue"].insert(0, v)
            notify("🧩 hh.ru попросил капчу. Обходить её бот не будет: пройди по ссылке сам, через час продолжу.\n" + (cu or "https://hh.ru"))
            return False
        if "limit_exceeded" in errs or "negotiations_limit" in errs:
            day["n"] = limit; log("hh.ru: дневной лимит откликов hh исчерпан"); return False
        applied[v["id"]] = {"skip": errs[:100], "employer_id": v["employer_id"]}
        log(f"hh.ru отклик не прошёл ({code}): {v['name']} — {errs[:120]}")
        if code == 403 and ("token" in errs or "oauth" in errs): h["dead"] = errs[:200]; return False
    return False

STATES = {"invitation": "🎉 ПРИГЛАШЕНИЕ", "discard": "❌ Отказ", "interview": "🎉 СОБЕСЕДОВАНИЕ", "offer": "🎉 ОФФЕР", "hired": "🎉 ВЗЯЛИ"}

def check_responses(st, notify, log):
    """Раз в 30 мин: что ответили работодатели на hh (приглашение, отказ, новое сообщение) → Егору с советом нейросети."""
    if not configured() or st.get("hh_api", {}).get("dead"): return
    h = st["hh_api"]
    if time.time() - h.get("checked", 0) < 30 * 60: return
    h["checked"] = time.time()
    code, j = _req("GET", "/negotiations?per_page=50&order_by=updated_at", st)
    if code != 200: return
    applied = h.setdefault("applied", {})
    for n in (j.get("items") or []):
        vid = str((n.get("vacancy") or {}).get("id") or "")
        stt = (n.get("state") or {}).get("id", "")
        a = applied.setdefault(vid, {"name": (n.get("vacancy") or {}).get("name", ""), "employer": ((n.get("vacancy") or {}).get("employer") or {}).get("name", "")})
        upd = n.get("has_updates") and n.get("updated_at") != a.get("seen_upd")
        if stt == a.get("state") and not upd: continue
        a["state"] = stt; a["seen_upd"] = n.get("updated_at")
        if stt == "response" and not upd: continue
        last = ""
        if n.get("messages_url"):
            c2, m = _req("GET", n["messages_url"], st)
            msgs = [x for x in (m.get("items") or []) if (x.get("author") or {}).get("participant_type") == "employer"]
            last = text_of(msgs[-1].get("text")) if msgs else ""
        head = STATES.get(stt, "💬 Новое сообщение")
        adv = ""
        try:
            import analyst
            if stt != "discard" and last:
                r = analyst.reply_advice({"kind": "hot", "display": a.get("employer", ""), "text": a.get("letter", "")}, last)
                if r: adv = f"\n\n🧠 {r['insight']}\n💡 Можно ответить:\n«{r['reply']}»"
        except Exception: pass
        log(f"hh.ru {head}: {a.get('name')} — {a.get('employer')}")
        notify(f"{head} на hh.ru — {a.get('employer', '')}\n{a.get('name', '')}" + (f"\n\n«{last[:600]}»" if last else "") + adv +
               "\n\nОтветь на hh: https://hh.ru/applicant/negotiations")
