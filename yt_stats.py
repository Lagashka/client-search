# -*- coding: utf-8 -*-
"""Бот 5 «YouTube»: чему учится схема (17.11).
п. 17 — A/B: какая боль и какой вариант письма дают ответы (ключ item["ab"] = «боль:варианты»).
п. 18 — причины отказов: на что отвечают «нет» → что править в фильтрах и письме.
Только счёт, без имён — можно в публичный лог облака."""
import re, collections

REASONS = [("уже есть монтажёр", r"есть монтаж|свой монтаж|уже монтир|у нас (есть )?(монтаж|команд|специалист)|работаю с монтаж|есть человек"),
           ("монтирует сам", r"сам[аи]? (монтир|делаю|справля)|монтирую сам|делаю сам"),
           ("дорого / нет бюджета", r"дорог|бюджет|нет денег|не по карману|бесплатно|сколько стоит"),
           ("не нужны Shorts", r"shorts не|шортс\w* не|коротк\w* не|не делаем (shorts|шортс|коротк)|не (нужн|интересн)\w* (shorts|шортс|коротк)"),
           ("позже / нет времени", r"позже|потом|не сейчас|нет времени|занят|после нового года|в следующ"),
           ("не актуально", r"не актуальн|неактуальн|не нужн|не интерес|не надо|нет,? спасибо|спасибо,? нет|не требуется"),
           ("раздражение / спам", r"спам|не пишите|не беспокойте|откуда (у вас )?(мой|контакт)|заблок")]

def reason(text):
    t = (text or "").lower()
    for name, rx in REASONS:
        if re.search(rx, t): return name
    return "другое"

def _yt(sent):
    return [e for e in (sent or {}).values() if e.get("variant") == "YT"]

def report(sent):
    """{"by_pain": {боль: [отправлено, ответили, отказ]}, "by_var": {вариант: [...]}, "reasons": {...}, "total": [...]}."""
    by_pain, by_var, rs = collections.defaultdict(lambda: [0, 0, 0]), collections.defaultdict(lambda: [0, 0, 0]), collections.Counter()
    tot = [0, 0, 0]
    for e in _yt(sent):
        ab = e.get("ab") or "?:"
        pain, vs = ab.split(":", 1) if ":" in ab else (ab, "")
        rep = bool(e.get("replied")); no = e.get("outcome") == "no" or e.get("crm") == "refused"
        for row in [by_pain[pain], tot] + [by_var[v] for v in vs.split(".") if v]:
            row[0] += 1; row[1] += rep; row[2] += no
        if no: rs[reason(e.get("last_in"))] += 1
    return {"by_pain": dict(by_pain), "by_var": dict(by_var), "reasons": dict(rs), "total": tot}

PAIN_NAME = {"no_shorts": "нет Shorts", "weak_shorts": "слабые Shorts", "drop": "просели просмотры"}
VAR_NAME = {"o0": "начало «посмотрел ваш YouTube»", "o1": "начало «наткнулся, посмотрел несколько роликов»", "fresh": "повод: свежее видео",
            "b0": "кнопка «посмотрите, как выглядит у вас»", "b1": "кнопка «без обязательств»", "best": "лучшее видео с цифрой",
            "heat": "самый пересматриваемый момент", "flen": "Shorts слишком длинные", "f0": "решение, вариант 1", "f1": "решение, вариант 2",
            "f2": "решение, вариант 3"}

def pct(r): return f"{100 * r[1] // r[0]}%" if r[0] else "—"

def text(sent, min_n=5):
    """Короткая сводка для вечернего отчёта и «🧠 Разбор». Вывод «что лучше» — только когда отправлено ≥ min_n в каждой группе."""
    r = report(sent)
    if not r["total"][0]: return ""
    out = [f"🎥 5️⃣ YouTube: отправлено {r['total'][0]}, ответили {r['total'][1]} ({pct(r['total'])}), отказов {r['total'][2]}"]
    if r["by_pain"]:
        out.append("По боли: " + ", ".join(f"{PAIN_NAME.get(k, k)} {v[1]}/{v[0]} ({pct(v)})" for k, v in sorted(r["by_pain"].items(), key=lambda x: -x[1][0])))
    ok = {k: v for k, v in r["by_var"].items() if v[0] >= min_n}
    if len(ok) >= 2:
        best = max(ok.items(), key=lambda x: x[1][1] / x[1][0])
        worst = min(ok.items(), key=lambda x: x[1][1] / x[1][0])
        if best[0] != worst[0]:
            out.append(f"Лучше работает: {VAR_NAME.get(best[0], best[0])} ({pct(best[1])}), хуже: {VAR_NAME.get(worst[0], worst[0])} ({pct(worst[1])})")
    else:
        out.append(f"Какой вариант письма лучше, скажу, когда в каждом будет хотя бы {min_n} отправок")
    if r["reasons"]:
        out.append("Почему отказывают: " + ", ".join(f"{k} {v}" for k, v in sorted(r["reasons"].items(), key=lambda x: -x[1])))
    return "\n".join(out)
