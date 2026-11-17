# -*- coding: utf-8 -*-
"""Тесты «все боты пишут» (16.11). Осечка, которую ловим: боты 2–3 не написали ни одного письма,
потому что холодные шли только при пустой очереди вакансий. Запуск: python tests_bots_fair.py
Проверяется тот же plan_send(), что работает в облаке, — не копия."""
import sys, os, re, time, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autoclient as c

ok = bad = 0
def check(name, cond):
    global ok, bad
    if cond: ok += 1; print("  ✓", name)
    else: bad += 1; print("  ✗ ПРОВАЛ:", name)

NOW = time.time()
S = dict(c.DEFAULTS)

def world(n_hot=200, n_biz=30, n_par=30, n_exp=30, silent=20, n_nic=30):
    """Как в облаке: вакансий всегда больше, чем успеваем отправить, все очереди полны, есть молчуны для дожимов."""
    hot = [{"username": f"vac{i}", "found": NOW - 60, "text": "x"} for i in range(n_hot)]
    cold = ([{"username": f"biz{i}", "variant": "BIZ", "found": NOW} for i in range(n_biz)] +
            [{"username": f"par{i}", "variant": "PARTNER", "found": NOW} for i in range(n_par)] +
            [{"username": f"nic{i}", "variant": "NICHE", "found": NOW} for i in range(n_nic)] +      # 17.11: бот 5 «Мастера»
            [{"username": f"exp{i}", "variant": "A", "found": NOW} for i in range(n_exp)])
    sent = {f"old{i}": {"kind": "hot", "ts": NOW - 30 * 3600, "peer": 1} for i in range(silent)}
    return {"hot_q": hot, "cold_q": cold, "sent": sent}

def day(): return {"hot": 0, "cold": 0, "fu": 0, "by": {}}

def run(st, s, ticks, d=None, warm=False, lim_hot=None):
    """Имитация отправки: plan_send → «отправлено» → как в autoclient (pop q[0], счётчики)."""
    d = d or day(); got = collections.Counter(); seq = []
    for _ in range(ticks):
        job = c.plan_send(st, s, d, NOW, lim_hot if lim_hot is not None else int(s["limit_hot"]), warm)
        if not job: seq.append(None); continue
        kind, item = job
        if kind == "fu":
            st["sent"][item]["fu"] = "today"; st["sent"][item].pop("_tm", None); d["fu"] += 1; sl = "fu"
        else:
            q = st["hot_q"] if kind == "hot" else st["cold_q"]
            check_item = q.pop(0)
            assert check_item is item, "отправка взяла не то письмо, что выбрал планировщик"
            d[kind] += 1; sl = c.slot_of(item, kind)
        got[sl] += 1; seq.append(sl)
    return got, seq, d

print("1. Главная осечка: очередь вакансий никогда не пустеет")
got, seq, _ = run(world(), S, 20)
check("за 20 отправок письмо получил каждый бот: вакансии, компании, партнёры, эксперты, дожимы",
      all(got[k] > 0 for k in ("hot", "BIZ", "PARTNER", "NICHE", "cold", "fu")))
check("ни один бот не получает больше 2 отправок из 5 подряд (честный круг)",
      all(collections.Counter(seq[i:i + 5]).most_common(1)[0][1] <= 2 for i in range(0, 15)))
check("первые 6 отправок — по одной от каждого бота", sorted(seq[:6]) == sorted(c.SLOTS))

print("2. Лимиты в день")
s2 = dict(S, limit_hot=40, limit_cold=8, limit_fu=3)
got, seq, d = run(world(), s2, 200)
check("холодных (2+3+5+эксперты) ровно limit_cold", d["cold"] == 8)
check("дожимов ровно limit_fu", d["fu"] == 3)
check("лимит холодных поделён между ботами 2, 3, 5 и экспертами поровну", got["BIZ"] == got["PARTNER"] == got["NICHE"] == got["cold"] == 2)
check("вакансии не превышают limit_hot", d["hot"] == 40)
check("после исчерпания всех лимитов — ждём, а не шлём", seq[-1] is None)
check("дожимы не съедают лимит новых писем (раньше был общий)", d["cold"] == 8 and d["fu"] == 3)

print("3. Выключатели ботов в пульте")
for key, sl in (("biz_on", "BIZ"), ("partners_on", "PARTNER"), ("niche_on", "NICHE"), ("cold_on", "cold"), ("hot_on", "hot"), ("fu_on", "fu")):
    got, _, _ = run(world(), dict(S, **{key: False}), 60)
    others = [k for k in c.SLOTS if k != sl]
    check(f"{key}=выкл: бот молчит, остальные пишут", got[sl] == 0 and all(got[k] > 0 for k in others))

print("4. Пустые очереди и мягкий режим")
st = world(n_biz=0); got, _, _ = run(st, S, 20)
check("нет компаний — остальные идут без пауз", got["BIZ"] == 0 and got["PARTNER"] > 0 and got["hot"] > 0)
st = world(n_hot=0); got, _, _ = run(st, S, 12)
check("нет вакансий — холодные и дожимы всё равно идут", got["hot"] == 0 and got["BIZ"] > 0 and got["fu"] > 0)
got, _, _ = run(world(), S, 20, warm=True, lim_hot=100)
check("мягкий режим после ограничения: только вакансии и мастера (17.11)",
      got["hot"] > 0 and got["NICHE"] > 0 and got["hot"] + got["NICHE"] == sum(got.values()) == 20)
# 17.11 тест бота 5: всё выключено, кроме мастеров, мягкий режим — пишут только мастера
only = dict(S, hot_on=False, biz_on=False, partners_on=False, cold_on=False, niche_on=True)
got, _, _ = run(world(), only, 10, warm=True, lim_hot=100)
check("тест бота 5: в мягком режиме пишут только «Мастера»", got["NICHE"] > 0 and got["NICHE"] == sum(got.values()))
st = world(); st["hot_q"][0]["found"] = NOW - 49 * 3600; run(st, S, 1)
check("вакансии старше 48 ч выбрасываются", all(NOW - x["found"] < 48 * 3600 for x in st["hot_q"]))

print("5. Письмо компании из вакансии («пишите в тг») — в очереди вакансий, но выключатель бота 2")
st = world(n_hot=0); st["hot_q"] = [{"username": "invbiz", "variant": "BIZ", "found": NOW}]
job = c.plan_send(st, dict(S, biz_on=False), day(), NOW, 40, False)
check("biz_on=выкл: такое письмо не уходит", not (job and job[0] == "hot"))

print("6. Сторож: включённый бот сутки молчит — уведомление с причиной")
st = world(); s6 = dict(S)
check("первые сутки после запуска сторож молчит", c.health_problems(st, s6, NOW, {}) == [])
old = NOW - 25 * 3600
for k in c.SLOTS: st["health"][k]["since"] = old
st["health"]["hot"]["sent"] = NOW - 60
p = dict(c.health_problems(st, s6, NOW, {}))
check("вакансии писали час назад — не тревога", "hot" not in p)
check("компании и партнёры сутки без отправки — тревога", "BIZ" in p and "PARTNER" in p)
check("в причине видно, что письма в очереди есть, но не уходят", "в очереди 30" in p["BIZ"])
st["cold_q"] = [x for x in st["cold_q"] if x["variant"] != "PARTNER"]; st["health"]["PARTNER"]["found"] = old
p = dict(c.health_problems(st, s6, NOW, {}))
check("пустая очередь партнёров — «поиск ничего не находит»", "ничего не находит" in p["PARTNER"])
st["day"] = {"cold": 20}
check("лимит исчерпан — так и пишет", "лимит" in dict(c.health_problems(st, s6, NOW, {}))["BIZ"])
check("выключенный бот — не тревога", "BIZ" not in dict(c.health_problems(st, dict(s6, biz_on=False), NOW, {})))
check("модуль не загрузился — тревога сразу, с текстом ошибки",
      "ImportError" in dict(c.health_problems(world(), s6, NOW, {"BIZ": "ImportError: x"}))["BIZ"])
check("бота включили заново — снова сутки на разгон", "BIZ" not in dict(c.health_problems(st, s6, NOW, {})))
st["health"]["BIZ"]["since"] = old
check("мягкий режим — причина названа", "мягкий" in dict(c.health_problems(st, s6, NOW, {}, warm=True))["BIZ"])

print("7. Вакансии на съёмку — не наши (16.11: «бот отвлекается на вакансии видеооператора»)")
import safety, autoreply
SHOOT = ["Ищем видеооператора на съёмки мероприятий в Москве, оплата 5000 за смену",
         "Требуется видеооператор-монтажёр в продакшн, полный день",
         "Нужен оператор для съёмки рилс в салоне красоты, монтаж тоже на вас",
         "Ищу видеографа на свадьбу 12 декабря",
         "Нужен мобилограф для ресторана, съёмка и монтаж reels 3 раза в неделю",
         "Ищем UGC-креатора, снимать видео с товаром",
         "Ищем рилсмейкера: съёмка и монтаж роликов для клиники, выезд на съёмку 2 раза в неделю",
         "Нужен человек снимать и монтировать сторис для кофейни",
         "Ищем фотографа и видеографа на проект"]
OURS = ["Ищу монтажёра рилс, исходники даём, 10 роликов в месяц, удалённо",
        "Нужен видеомонтажёр на YouTube, снимает наш оператор, от вас монтаж и графика",
        "Ищем монтажёра для подкастов, материал уже есть, удалённо",
        "Требуется монтажер reels, съёмку делаем сами, нужна динамика и субтитры",
        "Нужен моушн-дизайнер в After Effects для рекламных роликов",
        "Ищу монтажера коротких видео для эксперта, нужен хук и субтитры, оплата 2000 за ролик",
        "Ищем рилсмейкера только на монтаж, без съёмки"]
check("все 9 вакансий на съёмку отсеиваются правилом", all(safety.shoot_job(t) for t in SHOOT))
check("все 7 вакансий на монтаж проходят правило", not any(safety.shoot_job(t) for t in OURS))
check("бот 1: вакансии на съёмку не считаются вакансиями (is_hot)", not any(c.is_hot(t) for t in SHOOT))
check("бот 1: вакансии на монтаж — вакансии (is_hot)", all(c.is_hot(t) for t in OURS))
check("«Требуется монтажер» — вакансия, а «Я монтажер, беру заказы» — реклама (баг подстроки до 16.11)",
      c.is_hot("Требуется монтажер видео на проект") and not c.is_hot("Я монтажер, нужен проект? пишите"))
check("фильтр «наш профиль» отказывает съёмке с понятной причиной",
      all(not autoreply.rule_fit(t)[0] for t in SHOOT) and "съёмк" in autoreply.rule_fit(SHOOT[0])[1])
check("фильтр «наш профиль» пропускает монтаж", all(autoreply.rule_fit(t)[0] for t in OURS))
st = world(n_hot=0)
st["hot_q"] = [{"username": "op1", "found": NOW, "ctx": "Вакансия в канале «x»:\n" + SHOOT[0] + "\nБио автора в Telegram: нет"},
               {"username": "ph1", "found": NOW, "ctx": "Вакансия в канале «x»:\n" + OURS[0] + "\nБио автора в Telegram: фотограф, снимаю свадьбы"}]
c.plan_send(st, S, day(), NOW, 40, False)
check("вакансия оператора, попавшая в очередь раньше, выбрасывается перед отправкой", [x["username"] for x in st["hot_q"]] == ["ph1"])
check("фотограф, который ищет монтажёра, — клиент (био автора не путает)", st["hot_q"] and st["hot_q"][0]["username"] == "ph1")
check("в поиске бота 1 нет запросов про видеографа, мобилографа, UGC",
      not any(re.search(r"видеограф|мобилограф|ugc|оператор", q) for q in c.HOT_QUERIES))
import hh_api
check("бот 4 (hh.ru): нет запроса «мобилограф», вакансия оператора отсеивается",
      "мобилограф" not in hh_api.QUERIES and hh_api.shoot_job("Видеооператор-монтажёр"))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "Поиск бизнеса"))
import bizhunt
check("бот 2: нет запросов «мобилограф»/«видеограф», вакансия видеографа отсеивается",
      not any(q in ("мобилограф", "видеограф") for q in bizhunt.DEFAULT_CFG["hh_queries"]) and bizhunt.shoot_job("Видеограф в салон"))

print("7б. Остальные «не наши» вакансии (по разбору 34 диалогов 16.11)")
NOT_OURS = ["Ищу монтажёра рилс, оплата бартер — бесплатные услуги салона",
            "Нужен рилсмейкер на некоммерческий проект, монтаж тизера",
            "Ищем монтажёра в штат: полная занятость, 2-3 дня в неделю в офисе в Бишкеке",
            "Монтируешь нарезки из наших исходников и получаешь $1 за каждого подписчика",
            "Ищу монтажёра reels, оплата за подписчиков"]
check("бартер, некоммерческие, штат с офисом, оплата за подписчиков — отсекаются",
      all(not autoreply.rule_fit(t)[0] for t in NOT_OURS))
check("удалённый штат и обычная оплата — проходят",
      autoreply.rule_fit("Ищем монтажёра reels в штат, полная занятость, удалённо, оплата 60 000 в месяц")[0]
      and autoreply.rule_fit(OURS[5])[0])

print("8. Сводка «Не дожаты»")
sent = {"a": {"replied": "x", "thread": [{"who": "me", "text": "1"}, {"who": "them", "text": "интересно, сколько?"}], "last_in_ts": NOW - 3600, "display": "Аня"},
        "b": {"replied": "x", "thread": [{"who": "them", "text": "нет"}], "last_in_ts": NOW - 3600, "crm": "refused"},
        "c": {"replied": "x", "thread": [{"who": "them", "text": "да"}], "last_in_ts": NOW - 7200, "human": True, "human_ts": NOW - 60},
        "d": {"replied": "x", "thread": [{"who": "them", "text": "давно"}], "last_in_ts": NOW - 20 * 86400},
        "e": {"replied": "x", "thread": [{"who": "them", "text": "ок"}, {"who": "me", "text": c.HOLD_TEXTS[0]}], "last_in_ts": NOW - 100},
        "f": {"replied": "x", "thread": [{"who": "them", "text": "сколько?"}, {"who": "me", "text": "5 000 ₽, начинаем?"}], "last_in_ts": NOW - 500}}
rows = c.undone_leads({"sent": sent}, NOW)
check("в сводке те, кому ты не ответил; «Секундочку» ответом не считается; отказ, старые и отвеченные — нет",
      [r["u"] for r in rows] == ["e", "a"])

print("9. Защита от возврата старой ошибки")
src = open(os.path.join(HERE, "autoclient.py"), encoding="utf-8").read()
check("основной цикл выбирает письмо через plan_send", "job = plan_send(" in src)
check("в цикле нет старого «холодные только если нет вакансий»", "if not job and not warm and in_hours(HOURS_COLD)" not in src)
check("ошибка импорта ботов 2–3 не глотается молча", "BIZ_ERR" in src and "PAR_ERR" in src)

print(f"\nИтого: {ok} прошло, {bad} провалено")
sys.exit(1 if bad else 0)
