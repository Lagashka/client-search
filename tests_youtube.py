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

print("письмо")
cases = [dict(who="Павел Петров", title="Риелтор Павел", desc="продаю квартиры", video="Как купить квартиру в ипотеку", has_shorts=False),
         dict(who="", title="Юрист Иванов", desc="банкротство физлиц", video="Очень длинное название видео про банкротство физических лиц 2026", has_shorts=True),
         dict(who="Anna", title="Психолог", desc="", video="", has_shorts=False)]
for i in range(30):
    c = cases[i % 3]; t = y.template(dict(c))
    if i < 3: print("   ", t.replace("\n", " ⏎ "))
    if human.looks_bot(t) or "http" in t or "₽" in t or t.count("?") != 1 or len(t.split("\n")) != 2 or "бесплат" in t.lower():
        check(f"письмо {i} как человек, 2 строки, один вопрос, без ссылок и цен: {t!r} → {human.looks_bot(t)}", False); break
else:
    check("30 писем: как человек, 2 строки, один вопрос, без ссылок, цен и «бесплатно»", True)
t = y.template(dict(cases[0]))
check("короткое название видео попало в письмо", "«Как купить квартиру в ипотеку»" in t)
t = y.template(dict(cases[1]))
check("длинное название заменено на тему («про банкротство»)", "про банкротство" in t and "«" not in t)
check("с Shorts не спрашиваем «нарезаете ли Shorts»", all("Shorts из длинных видео нарезаете" not in y.template(dict(cases[1])) for _ in range(20)))
it = y.item_of(dict(cases[0], username="pavel_r", source="https://www.youtube.com/channel/X", subs=1000, text=t))
check("письмо в очередь: variant YT, без «боли», абзацы через пустую строку", it["variant"] == "YT" and it["pain"] == {} and "\n\n" in it["text"])

print(f"\nИтого: {ok} прошло, {bad} провалено")
sys.exit(1 if bad else 0)
