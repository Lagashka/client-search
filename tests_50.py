# -*- coding: utf-8 -*-
"""Тесты защит из «50 ошибок ботов.md». Запуск: python tests_50.py"""
import sys, os, re, time, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "Поиск партнёров"))
import safety, human, analyst, autoclient as c, partners as P

ok = bad = 0
def check(name, cond):
    global ok, bad
    if cond: ok += 1; print("  ✓", name)
    else: bad += 1; print("  ✗ ПРОВАЛ:", name)

T = "Анна, здравствуйте, увидел вашу вакансию, я продюсирую ролики под ключ, от сценария до монтажа\n\nПонимаю, монтаж съедает время\n\nМогу бесплатно сделать тест, как вам?"
it = lambda u, t=T: {"username": u, "text": t}
print("safety.pre_send")
check("№1 дубль между ботами: второму боту тому же человеку не пишем", safety.pre_send("cold", it("Anna_pro"), {"anna_PRO": {}}) != "")
check("№2 свой аккаунт", safety.pre_send("cold", it("chernyshev_edit"), {}) != "")
check("№3 бот / служебный аккаунт", safety.pre_send("cold", it("SalonSupportBot"), {}) != "" and safety.pre_send("cold", it("support"), {}) != "")
check("№4 кривой ник", safety.pre_send("cold", it("@an na"), {}) != "" and safety.pre_send("cold", it("https://t.me/x"), {}) != "")
check("№5 пустое письмо", safety.pre_send("cold", it("anna_pro", ""), {}) != "")
check("№6 мусор шаблона/ИИ", safety.pre_send("cold", it("anna_pro", T + " {name}"), {}) != "" and safety.pre_send("cold", it("anna_pro", T + " None"), {}) != "")
check("№7 письмо не на русском", safety.pre_send("cold", it("anna_pro", "Hello Anna, I saw your vacancy and I make reels for business, want a free test? " * 2), {}) != "")
check("№8 нормальное письмо проходит", safety.pre_send("hot", it("anna_pro"), {"other": {}}) == "")

print("одинаковые тексты")
seen = {safety.text_hash(T)}
v = safety.vary(T, seen)
check("№9 одинаковый текст второму человеку меняется", v != T and safety.text_hash(v) not in seen)
check("№10 уникальный текст не трогаем", safety.vary(T + " 1", seen) == T + " 1")

print("«Секундочку»")
check("№11 мягкий отказ без «секундочку»", all(safety.soft_no(x) for x in ["Спасибо, не надо", "нам не требуется", "Нет, спасибо", "неактуально уже"]))
check("№12 обычный ответ — «секундочку» можно", not safety.soft_no("Здравствуйте, а сколько стоит?"))

print("фильтр «пишет человек»")
check("№13 «!» и длинное тире", human.looks_bot("Здравствуйте! Делаю ролики — быстро") != "")
check("№14 ссылка незнакомому (не вакансия)", human.looks_bot("Добрый день, вот мои работы t.me/zakulisy715 как вам?") != "")
check("№15 перечисление услуг", human.looks_bot("делаю хук, суть, субтитры, призыв") != "")
check("№16 канцелярит «готов предоставить»", human.looks_bot("Готов предоставить вам готовый контент") != "")
check("№17 humanize убирает ‑ и неразрывные пробелы", "‑" not in human.humanize("10‑15 секунд за сутки"))

print("нейросеть: боль до диалога")
check("№18 вставка боли в письмо из 3 сообщений — вместо второго", human.parts(analyst.inject(T, "Вижу, что сценарии тоже на вас"))[1] == "Вижу, что сценарии тоже на вас" and len(human.parts(analyst.inject(T, "x"))) == 3)
check("№19 вставка в письмо из 2 сообщений — становится 3", len(human.parts(analyst.inject("а\n\nб", "x"))) == 3)
analyst._FAILS.update(n=0, until=time.time() + 100)
check("№20 нейросеть лежит → не дёргаем 30 мин (отправка не тормозит)", analyst._llm_guarded("x", [], 10) is None)
analyst._FAILS.update(n=0, until=0)

print("аналитик")
m = {"bots": {}, "reasons": {}, "log": {"ограничения Telegram": 2, "письмо похоже на бота": 0}, "queues": {"холодная": 0}, "companies": {},
     "settings": {"limit_cold": 20, "limit_hot": 40, "gap": 30, "hot_on": True, "biz_on": True, "partners_on": True, "cold_on": True, "fu_on": True},
     "limited_until": "", "days": 7}
check("№21 после ограничений Telegram лимиты не поднимаем", not analyst._clean_actions([{"label": "x", "set": {"limit_cold": 99}}]))   # 99 нет в списке

print("очередь и часы")
q = [{"username": "a", "variant": "BIZ"}, {"username": "b", "variant": "A"}]
s = dict(c.DEFAULTS, biz_on=False)
check("№22 выключенный бот: его письмо пропускается, берётся следующее", c.pick_allowed(list(q), "cold", s)["username"] == "b")
check("№23 все выключены — ничего не шлём", c.pick_allowed(list(q), "cold", dict(s, cold_on=False)) is None)

print("дожимы")
check("№24 дожим компании — без «вашего канала»", "канал" not in c.followup_text({"kind": "cold", "variant": "BIZ", "display": "Ольга"}))
check("№25 дожим партнёру — про партнёрство", "партн" in c.followup_text({"kind": "cold", "variant": "PARTNER", "display": ""}) or "клиент" in c.followup_text({"kind": "cold", "variant": "PARTNER", "display": ""}))

print("бот 3: партнёры")
check("№26 резюме монтажёра — конкурент, не партнёр", bool(P.COMPETITOR.search("#резюме Я видеомонтажёр и рилсмейкер")))
check("№27 менеджер по рекламе — последним, владелец — первым", P.owner_handles("Реклама: @ads_manager. Автор: @olga_target", "chan") == ["olga_target", "ads_manager"])
check("№28 шаблон партнёру проходит фильтр «пишет человек» (40 раз)", all(not human.looks_bot(human.humanize(P.template(
    {"src": "channel", "title": "T", "role": r, "who": "Сергей", "snippet": "таргет вк"}).replace("\n", "\n\n"))) for r in ["target", "smm", "agency"] * 14))

print(f"\nИтого: {ok} прошло, {bad} провалено")
sys.exit(1 if bad else 0)
