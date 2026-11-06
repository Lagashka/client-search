# -*- coding: utf-8 -*-
"""CRM: база лидов, воронка и конверсия. Считается из state.json["sent"] сразу при каждом событии.
Выдаёт: БАЗА ЛИДОВ.md, leads.csv и «живое табло» — одно сообщение в боте, которое редактируется на месте."""
import re, os, csv, json, time, datetime, urllib.request

# статусы воронки (по возрастанию ценности)
ST_SENT, ST_SILENT, ST_REPLIED, ST_INTEREST, ST_AGREED, ST_REFUSED = "sent", "silent", "replied", "interest", "agreed", "refused"
LABEL = {ST_SENT: "📤 отправлено", ST_SILENT: "😶 молчит >48ч", ST_REPLIED: "💬 ответил", ST_INTEREST: "🔥 горячий",
         ST_AGREED: "✅ согласился", ST_REFUSED: "❌ отказ"}

AGREE = re.compile(r"(?<!не )давайте|договорил|по рукам|(?<!не )согласн|(?<!не )согласен|готов(ы)? начать|присылайте|скидываю|пришлю|высылайте|"
                   r"когда начн|оплат|реквизит|счёт|счет на|созвон|созвонимся|удобно в|давай тест|попробуем|начинаем|берём|берем", re.I)
INTEREST = re.compile(r"сколько|цена|прайс|стоим|портфолио|примеры|пример|расскаж|подробн|интересно|какие сроки|сроки|"
                      r"объ[её]м|ттз|бриф|ссылк|покажите|можете|перевож|передам|менеджер|уточню|отпишусь|свяж|"
                      r"sending|send|price|portfolio|how much|interested|\?", re.I)
REFUSE = re.compile(r"не актуальн|неактуальн|не нужн|не интерес|не надо|не требуется|уже наш(ли|ёл|ел)|уже выбрал|"
                    r"уже есть монтаж|нет,? спасибо|спасибо,? (но )?нет|спасибо,? не|отказ|вакансия закрыта|"
                    r"набор закрыт|не пишите|не беспокойте|спам|нашл[аи] специалист|закрыт[аоы]|"
                    r"не подход|к сожалению|не рассматрива|выбрал\w* (друг|специалист|исполнител)|уже взял|"
                    r"не в приоритете|не ищем|не требуются|неинтерес", re.I)

def classify(text):
    """Текст ответа клиента → статус. Порядок важен: отказ → согласие → интерес → просто ответ."""
    t = (text or "").strip()
    if not t: return ST_REPLIED
    if REFUSE.search(t): return ST_REFUSED
    if AGREE.search(t): return ST_AGREED
    if INTEREST.search(t): return ST_INTEREST
    return ST_REPLIED

def status(e, now=None):
    """Текущий статус лида: берём явный e['crm'], иначе выводим."""
    now = now or time.time()
    s = e.get("crm")
    if s: return s
    if e.get("outcome") == "no": return ST_REFUSED          # записи, сделанные до CRM
    if e.get("replied"): return ST_REPLIED
    if now - e.get("ts", now) > 48 * 3600: return ST_SILENT
    return ST_SENT

def mark(e, new_status, text=None):
    """Двигаем лид по воронке; назад (из согласия в интерес) — не откатываем, кроме отказа."""
    rank = {ST_SENT: 0, ST_SILENT: 0, ST_REPLIED: 1, ST_INTEREST: 2, ST_AGREED: 3, ST_REFUSED: 4}
    old = e.get("crm")
    if old and rank.get(new_status, 0) < rank.get(old, 0) and new_status != ST_REFUSED: return
    e["crm"] = new_status
    e.setdefault("history", []).append({"t": datetime.datetime.now().isoformat(timespec="seconds"), "s": new_status,
                                        "msg": (text or "")[:160]})
    e["history"] = e["history"][-30:]

def funnel(st):
    now = time.time(); c = {k: 0 for k in LABEL}
    for e in st["sent"].values(): c[status(e, now)] += 1
    total = len(st["sent"])
    answered = c[ST_REPLIED] + c[ST_INTEREST] + c[ST_AGREED] + c[ST_REFUSED]
    warm = c[ST_INTEREST] + c[ST_AGREED]
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "—"
    return {"c": c, "total": total, "answered": answered, "warm": warm,
            "reply_rate": pct(answered, total), "warm_rate": pct(warm, total), "close_rate": pct(c[ST_AGREED], total)}

def table_rows(st):
    now = time.time(); rows = []
    for u, e in st["sent"].items():
        rows.append({"username": u, "name": e.get("display", ""), "kind": "вакансия" if e["kind"] == "hot" else "холодное",
                     "status": status(e, now), "sent": e.get("date", ""), "replied": e.get("replied", ""),
                     "source": e.get("source", ""), "last_reply": (e.get("history") or [{}])[-1].get("msg", ""),
                     "auto_replies": e.get("auto_n", 0), "link": f"https://t.me/{u}"})
    order = {ST_AGREED: 0, ST_INTEREST: 1, ST_REPLIED: 2, ST_SENT: 3, ST_SILENT: 4, ST_REFUSED: 5}
    rows.sort(key=lambda r: (order[r["status"]], r["sent"]), reverse=False)
    return rows

def write_files(st, base):
    f = funnel(st); rows = table_rows(st); c = f["c"]
    md = [f"# База лидов\n\nОбновлено: {datetime.datetime.now():%d.%m %H:%M:%S}\n",
          "## Воронка", f"- Отправлено всего: **{f['total']}**",
          f"- Ответили: **{f['answered']}** ({f['reply_rate']})", f"- Горячие + согласились: **{f['warm']}** ({f['warm_rate']})",
          f"- Согласились: **{c[ST_AGREED]}** (конверсия в сделку {f['close_rate']})", f"- Отказались: **{c[ST_REFUSED]}**",
          f"- Молчат >48ч: **{c[ST_SILENT]}**, ждут ответа: **{c[ST_SENT]}**\n",
          "## Лиды", "| статус | кто | тип | отправлено | последний ответ | ссылка |", "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {LABEL[r['status']]} | {r['name']} (@{r['username']}) | {r['kind']} | {r['sent']} | {r['last_reply'][:70]} | {r['link']} |")
    try:
        open(os.path.join(base, "БАЗА ЛИДОВ.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
        with open(os.path.join(base, "leads.csv"), "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["статус", "имя", "username", "тип", "отправлено", "ответил", "последний ответ", "автоответов", "источник", "ссылка"])
            for r in rows:
                w.writerow([LABEL[r["status"]], r["name"], r["username"], r["kind"], r["sent"], r["replied"], r["last_reply"],
                            r["auto_replies"], r["source"], r["link"]])
    except Exception: pass

def board_text(st):
    f = funnel(st); c = f["c"]; rows = table_rows(st)
    hot = [r for r in rows if r["status"] in (ST_AGREED, ST_INTEREST)][:8]
    lines = [f"📊 БАЗА ЛИДОВ · {datetime.datetime.now():%d.%m %H:%M}", "",
             f"📤 отправлено {f['total']}  💬 ответили {f['answered']} ({f['reply_rate']})",
             f"🔥 горячие {c[ST_INTEREST]}  ✅ согласились {c[ST_AGREED]}  ❌ отказ {c[ST_REFUSED]}",
             f"😶 молчат {c[ST_SILENT]}  ⏳ ждём {c[ST_SENT]}",
             f"🎯 конверсия: ответ {f['reply_rate']} → тёплый {f['warm_rate']} → сделка {f['close_rate']}"]
    if hot:
        lines += ["", "Сейчас в работе:"] + [f"{LABEL[r['status']][:2]} {r['name']} @{r['username']} — {r['last_reply'][:50]}" for r in hot]
    if st.get("diag"): lines += ["", st["diag"]]
    return "\n".join(lines)

def push_board(st, token, chat_id, buttons=None):
    """Одно «живое» сообщение: первый раз отправляем и закрепляем, дальше редактируем."""
    if not token: return
    def call(m, **p):
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{m}", data=json.dumps(p).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    txt = board_text(st)
    if txt == st.get("board_text"): return
    kb = {"inline_keyboard": buttons or [[{"text": "📋 Выгрузить базу (CSV)", "callback_data": "crm:csv"}]]}
    try:
        if st.get("board_id"):
            call("editMessageText", chat_id=chat_id, message_id=st["board_id"], text=txt, reply_markup=kb)
        else:
            r = call("sendMessage", chat_id=chat_id, text=txt, reply_markup=kb, disable_notification=True)
            st["board_id"] = r["result"]["message_id"]
            try: call("pinChatMessage", chat_id=chat_id, message_id=st["board_id"], disable_notification=True)
            except Exception: pass
        st["board_text"] = txt
    except Exception as ex:
        if "not found" in str(ex).lower() or "400" in str(ex): st["board_id"] = 0   # сообщение удалили — создадим заново
