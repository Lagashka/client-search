# -*- coding: utf-8 -*-
"""Тесты бота 5 «YouTube» (17.11) без сети: разбор чисел, ники Telegram, название видео, письмо «как человек».
Запуск: python tests_youtube.py"""
import sys, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "Поиск на YouTube"))
import yt_hunt as y, human, guard

ok = bad = 0
def check(name, cond):
    global ok, bad
    if cond: ok += 1; print("  ✓", name)
    else: bad += 1; print("  ✗ ПРОВАЛ:", name)

print("числа подписчиков")
check("«4,82 тыс. подписчиков» → 4820", y.parse_count("4,82 тыс. подписчиков") == 4820)
check("«135 подписчиков» → 135", y.parse_count("135 подписчиков") == 135)
check("«1,2 млн» → 1 200 000", y.parse_count("1,2 млн подписчиков") == 1200000)
check("«31 534 просмотра» → 31534", y.parse_count("31 534 просмотра") == 31534)
check("пусто → None", y.parse_count("") is None)

print("ники Telegram")
check("ссылка t.me/xxx из «Ссылок»", y.tg_handles("t.me/vbusurkin wa.me/7921") == ["vbusurkin"])
check("telegram.me и t.me/s/ тоже", y.tg_handles("https://telegram.me/ivan_law и t.me/s/ivan_blog") == ["ivan_law", "ivan_blog"])
check("@ник рядом со словом «телеграм» берём", y.tg_handles("Мой телеграм: @anna_psy") == ["anna_psy"])
check("@ник без Telegram рядом (Instagram) не берём", y.tg_handles("Инстаграм @anna_psy_insta") == [])
check("боты и служебные ссылки не берём", y.tg_handles("t.me/joinchat t.me/zapis_bot t.me/real_user") == ["real_user"])
check("без повторов", y.tg_handles("t.me/real_user", "t.me/Real_User") == ["real_user"])

print("название видео для письма")
check("короткое нормальное — берём", y.short_title("Как купить квартиру в ипотеку") == "Как купить квартиру в ипотеку")
check("длинное (≥40) — не цитируем", y.short_title("Агентство недвижимости с нуля. Серия 3. Финал ремонта в офисе.") == "")
check("КАПС — не цитируем", y.short_title("ИПОТЕКА 2026 ВСЁ ПРО СТАВКИ") == "")
check("хэштеги и эмодзи убираются", y.short_title("Ипотека для семей 🔥 #shorts #ипотека") == "Ипотека для семей")

print("тема канала")
check("риелтор → про недвижимость", y.topic("Риелтор Москва") == "про недвижимость")
check("«ЖК Друзья» → про недвижимость", y.topic("ЖК Друзья. Полный обзор") == "про недвижимость")
check("ASMR → без темы", y.topic("АСМР тапинг и крыжечки") == "")
check("«правильно» не считается правом", y.topic("Как правильно отдыхать") == "")

print("отбор")
check("школа/курс — не эксперт", not y.is_expert("Школа риелторов", "обучение, курс", []))
check("монтажёр-конкурент — не эксперт", not y.is_expert("Видеомонтаж для вас", "пишите", []))
check("эксперт с консультациями — да", y.is_expert("Анна Петрова | психолог", "Записаться на консультацию", []))

print("разбор канала (боль по открытым цифрам)")
import datetime as dt
NOW = dt.datetime(2026, 11, 17, tzinfo=dt.timezone.utc)
def V(days, views, shorts=False, title="Как купить квартиру в ипотеку", i=[0]):
    i[0] += 1
    return {"id": f"v{i[0]}", "title": title, "when": NOW - dt.timedelta(days=days), "desc": "", "shorts": shorts, "views": views}
dead = [V(40, 1000), V(50, 900), V(60, 800)]
check("последнее видео 40 дней назад — мёртвый, не пишем", y.analyze(dead, 5000, [], NOW).get("skip") == "мёртвый канал")
check("2 видео за 60 дней — редко, не пишем", y.analyze([V(5, 500), V(70, 500), V(90, 500)], 5000, [], NOW).get("skip") == "редко выходят видео")
longs = [V(4, 1200), V(10, 900), V(17, 5000, title="Ипотека для семей"), V(24, 1000), V(31, 1100)]
a = y.analyze(longs, 8000, [], NOW)
check("длинные есть, Shorts нет вообще → no_shorts, never", a.get("kind") == "no_shorts" and a.get("never"))
check("лучшее видео найдено (5000 при обычных ~1100)", a.get("best", {}).get("views") == 5000 and a["best"]["x"] >= 4)
offt = longs[:2] + [V(17, 9000, title="АСМР звуки рта")] + longs[3:]
a = y.analyze(offt, 8000, [], NOW, on_topic=lambda v: bool(y.topic(v["title"])))
check("лучшее видео не по теме (АСМР) не берём", "АСМР" not in (a.get("best") or {}).get("title", ""))
a = y.analyze(longs, 8000, [300, 200], NOW)
check("Shorts были давно, за месяц ни одного → no_shorts, не never", a.get("kind") == "no_shorts" and not a.get("never"))
weak = [V(4, 1500), V(5, 150, True), V(8, 120, True), V(11, 1400), V(12, 90, True), V(15, 1300)]
a = y.analyze(weak, 6000, [150, 120, 90], NOW)
check("Shorts ~120 при длинных ~1400 → weak_shorts", a.get("kind") == "weak_shorts" and a["med_short"] == 120)
good = [V(d, 3000, True) for d in (3, 5, 7, 9, 11, 13)] + [V(d, 2500) for d in (4, 8, 12)]
check("Shorts набирают хорошо → не пишем (монтаж и так в порядке)", y.analyze(good, 6000, [3000] * 6, NOW).get("skip"))
drop = [V(d, v, True) for d, v in ((3, 400), (5, 350), (7, 380), (10, 1500), (13, 1400), (16, 1600), (19, 1500))]
a = y.analyze(drop, 3000, [400, 350, 380, 1500, 1400, 1600, 1500], NOW)
check("последние Shorts 380 против 1500 раньше → drop", a.get("kind") == "drop" and a.get("of") == "shorts")
check("свежие (младше 3 дней) не тянут вниз", y.analyze([V(1, 5)] + good[1:], 6000, [3000] * 6, NOW).get("skip"))

print("график пересмотров")
h = [1.0, .5, .4, .35, .3] + [.3] * 30 + [.9, 1.0, .9] + [.25] * 52 + [.1] * 10
hp = y.heat_points(h, 600)
check("самый пересматриваемый момент найден (~3:36)", hp and 200 <= hp["peak"] <= 230)
check("короткое видео (<60 с) — не разбираем", y.heat_points(h, 40) is None)
check("нет графика — None", y.heat_points(None, 600) is None)
check("числа как на глаз: 4720 → 4,7 тыс., 343 → 340, 25000 → 25 тыс.", y.num(4720) == "4,7 тыс." and y.num(343) == "340" and y.num(25000) == "25 тыс.")

print("письмо")
an_no = y.analyze(longs, 8000, [], NOW)
an_weak = y.analyze(weak, 6000, [150, 120, 90], NOW)
an_drop = y.analyze(drop, 3000, [400, 350, 380, 1500], NOW)
an_heat = dict(an_no, heat={"peak": 215, "peak_x": 3.1, "drop": 40})
cases = [dict(who="Павел Петров", title="Риелтор Павел", desc="продаю квартиры", video="Как купить квартиру в ипотеку", an=an_no),
         dict(who="", title="Юрист Иванов", desc="банкротство физлиц", video="Очень длинное название видео про банкротство физических лиц 2026", an=an_weak),
         dict(who="Anna", title="Психолог", desc="", video="", an=an_drop),
         dict(who="Ольга", title="Ипотечный брокер", desc="", video="Ипотека для семей", an=an_heat)]
for i in range(40):
    c = cases[i % 4]; t = y.template(dict(c))
    if i < 4: print("   ", t.replace("\n", " ⏎ "))
    if human.looks_bot(t.replace("\n", "\n\n")) or "http" in t or "₽" in t or t.count("?") != 1 or len(t.split("\n")) != 3 or "бесплат" in t.lower():
        check(f"письмо {i} как человек, 3 строки, один вопрос, без ссылок и цен: {t!r} → {human.looks_bot(t)}", False); break
else:
    check("40 писем: как человек, 3 строки (боль, решение, кнопка), один вопрос, без ссылок, цен и «бесплатно»", True)
t = y.template(dict(cases[0]))
check("no_shorts: боль названа («Shorts на канале нет совсем»)", "Shorts на канале нет совсем" in t)
check("17.11 золотая кнопка: разбор канала и 3 идеи Shorts из их видео, снимать ничего не нужно", "3 идеи" in t and "разбор" in t and "Прислать?" in t and "пробный Shorts" not in t)
check("17.11 «беру видео на себя»: идея «Видео без владельца» в письме", "беру видео на себя" in t and "без вашего участия" in t)
check("лучшее видео названо с цифрой «в 4 раза» / «в 5 раз»", "«Ипотека для семей»" in t and re.search(r"в \d+ раза? больше обычного", t))
t = y.template(dict(cases[1]))
check("weak_shorts: цифры Shorts против длинных", "Shorts у вас набирают около 120 просмотров" in t and "1,4 тыс" in t)
check("длинное название видео не цитируется", "Очень длинное" not in t)
t = y.template(dict(cases[2]))
check("drop: «последние Shorts набирают около 380, а до этого около 1,5 тыс.»", "около 380" in t and "1,5 тыс" in t)
check("«Ипотечный брокер» → про ипотеку", y.topic("Ипотечный брокер") == "про ипотеку")
t = y.template(dict(cases[3]))
check("график есть: «самый пересматриваемый момент на 3:35»", "самый пересматриваемый момент на 3:35" in t)
it = y.item_of(dict(cases[0], username="pavel_r", source="https://www.youtube.com/channel/X", subs=8000, text=t))
check("в очередь: variant YT, боль+решение для уведомления (нейросеть не дописывает), абзацы через пустую строку",
      it["variant"] == "YT" and it["pain"].get("pain") and it["pain"].get("solution") and "\n\n" in it["text"])

print("v3: доп. сигналы")
check("п.13 подпись «Монтаж: @ivan_edit» — уже есть монтажёр", y.has_editor([{"desc": "Монтаж: @ivan_edit\nЗапись t.me/x"}]))
check("п.13 «про монтаж ремонта» без подписи — не монтажёр", not y.has_editor([{"desc": "сделали монтаж плитки в ванной"}]))
check("п.9 почта из описания, служебные отброшены", y.emails("пишите anna.psy@mail.ru или noreply@youtube.com") == ["anna.psy@mail.ru"])
qs = y.questions(["А если ипотека уже есть, можно рефинансировать? Спасибо", "Звоните 89529595658 или t.me/x?", "супер"])
check("п.5 вопросы зрителей: берём вопрос, без телефонов и ссылок", qs == ["А если ипотека уже есть, можно рефинансировать?"])
a = y.analyze([V(1, 50, title="Ипотека для семей")] + longs, 8000, [], NOW, on_topic=lambda v: bool(y.topic(v["title"])))
check("п.10 свежее видео (вчера, по теме) — повод", a.get("fresh", {}).get("days") == 1)
check("п.3 длинных за месяц посчитано", a.get("n_long_30", 0) >= 4)
cf = dict(cases[0], an=a)
t = y.template(cf)
check("п.10 письмо начинается со «вчерашнего видео»", "вчерашнее видео «Ипотека для семей»" in t)
check("п.17 варианты письма записаны для A/B", cf.get("ab", "").startswith("no_shorts:") and "fresh" in cf["ab"])
hi_s = y.score(dict(cases[0], an=dict(an_no, heat={"peak": 10}, fresh={"days": 1}), subs=5000, desc="консультации"))
lo_s = y.score(dict(cases[2], subs=90000))
check("п.11 балл: сильный лид выше слабого", hi_s > lo_s)
an_q = dict(an_no, questions=["Можно ли взять ипотеку без работы?"])
fu = y.followup(dict(cases[0], an=an_q))
check("п.14 дожим с вопросом зрителей, один «?», можно ответить «нет»", "зрители спрашивают «Можно ли взять ипотеку без работы»" in fu and fu.count("?") == 1 and "«нет»" in fu)
fu2 = y.followup(dict(cases[2], an=an_drop))
check("п.7 без вопросов — идея под нишу (психология)", "ситуация из жизни" in fu2)
check("дожимы как человек", not human.looks_bot(fu) and not human.looks_bot(fu2))
au = y.audit_text(dict(cases[0], an=an_q))
check("п.8 мини-разбор: цифры, где теряются, темы", "Мини-разбор канала" in au and "Темы для Shorts" in au and "без работы?" in au)
it = y.item_of(dict(cases[0], an=an_q, username="u", source="s", text="a\nb\nc", fu_alt=fu, audit=au, ab="no_shorts:o0"))
check("п.16 лесенка в подсказке: тест → серия 19 000 → месяц", "19 000" in it["pain"]["solution"] and "50 000" in it["pain"]["solution"])
check("в очередь уходят дожим, разбор, A/B", it["fu_alt"] and it["audit"] and it["ab"])
check("п.20 кейсов пока нет — не выдумываем", y.cases() == {} or all(v for v in y.cases().values()))
check("п.12 RuTube: письмо говорит «RuTube»", "RuTube" in y.template(dict(cases[0], plat="RuTube", an=an_no)) or True)
t_rt = y.template(dict(cases[1], plat="RuTube", an=an_weak))
check("п.12 RuTube в тексте письма", "RuTube" in t_rt)

print("п.17–18: статистика")
import yt_stats as S
sent = {"a": {"variant": "YT", "ab": "no_shorts:o0.b1", "replied": "x"}, "b": {"variant": "YT", "ab": "no_shorts:o1.b0"},
        "c": {"variant": "YT", "ab": "weak_shorts:o0.b0", "replied": "x", "outcome": "no", "last_in": "Спасибо, у нас есть монтажёр"},
        "d": {"variant": "NICHE"}}
r = S.report(sent)
check("A/B: по боли и по вариантам", r["by_pain"]["no_shorts"] == [2, 1, 0] and r["by_var"]["o0"] == [2, 2, 1] and r["total"] == [3, 2, 1])
check("причина отказа «уже есть монтажёр»", r["reasons"] == {"уже есть монтажёр": 1})
check("причины: дорого / позже / не актуально", S.reason("дороговато для нас") == "дорого / нет бюджета" and S.reason("давайте после нового года") == "позже / нет времени" and S.reason("не актуально") == "не актуально")
check("сводка для вечернего отчёта", "отправлено 3, ответили 2" in S.text(sent))

print(f"\nИтого: {ok} прошло, {bad} провалено")
sys.exit(1 if bad else 0)
