# -*- coding: utf-8 -*-
"""Тесты «все боты пишут» (16.11). Осечка, которую ловим: боты 2–3 не написали ни одного письма,
потому что холодные шли только при пустой очереди вакансий. Запуск: python tests_bots_fair.py
Проверяется тот же plan_send(), что работает в облаке, — не копия."""
import sys, os, time, collections
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

def world(n_hot=200, n_biz=30, n_par=30, n_exp=30, silent=20):
    """Как в облаке: вакансий всегда больше, чем успеваем отправить, все очереди полны, есть молчуны для дожимов."""
    hot = [{"username": f"vac{i}", "found": NOW - 60, "text": "x"} for i in range(n_hot)]
    cold = ([{"username": f"biz{i}", "variant": "BIZ", "found": NOW} for i in range(n_biz)] +
            [{"username": f"par{i}", "variant": "PARTNER", "found": NOW} for i in range(n_par)] +
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
      all(got[k] > 0 for k in ("hot", "BIZ", "PARTNER", "cold", "fu")))
check("ни один бот не получает больше 2 отправок из 5 подряд (честный круг)",
      all(collections.Counter(seq[i:i + 5]).most_common(1)[0][1] <= 2 for i in range(0, 15)))
check("первые 5 отправок — по одной от каждого бота", sorted(seq[:5]) == sorted(c.SLOTS))

print("2. Лимиты в день")
s2 = dict(S, limit_hot=40, limit_cold=6, limit_fu=3)
got, seq, d = run(world(), s2, 200)
check("холодных (2+3+эксперты) ровно limit_cold", d["cold"] == 6)
check("дожимов ровно limit_fu", d["fu"] == 3)
check("лимит холодных поделён между ботами 2, 3 и экспертами поровну", got["BIZ"] == got["PARTNER"] == got["cold"] == 2)
check("вакансии не превышают limit_hot", d["hot"] == 40)
check("после исчерпания всех лимитов — ждём, а не шлём", seq[-1] is None)
check("дожимы не съедают лимит новых писем (раньше был общий)", d["cold"] == 6 and d["fu"] == 3)

print("3. Выключатели ботов в пульте")
for key, sl in (("biz_on", "BIZ"), ("partners_on", "PARTNER"), ("cold_on", "cold"), ("hot_on", "hot"), ("fu_on", "fu")):
    got, _, _ = run(world(), dict(S, **{key: False}), 60)
    others = [k for k in c.SLOTS if k != sl]
    check(f"{key}=выкл: бот молчит, остальные пишут", got[sl] == 0 and all(got[k] > 0 for k in others))

print("4. Пустые очереди и мягкий режим")
st = world(n_biz=0); got, _, _ = run(st, S, 20)
check("нет компаний — остальные идут без пауз", got["BIZ"] == 0 and got["PARTNER"] > 0 and got["hot"] > 0)
st = world(n_hot=0); got, _, _ = run(st, S, 12)
check("нет вакансий — холодные и дожимы всё равно идут", got["hot"] == 0 and got["BIZ"] > 0 and got["fu"] > 0)
got, _, _ = run(world(), S, 20, warm=True, lim_hot=100)
check("мягкий режим после ограничения: только вакансии", got["hot"] == 20 and sum(got.values()) == 20)
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

print("7. Защита от возврата старой ошибки")
src = open(os.path.join(HERE, "autoclient.py"), encoding="utf-8").read()
check("основной цикл выбирает письмо через plan_send", "job = plan_send(" in src)
check("в цикле нет старого «холодные только если нет вакансий»", "if not job and not warm and in_hours(HOURS_COLD)" not in src)
check("ошибка импорта ботов 2–3 не глотается молча", "BIZ_ERR" in src and "PAR_ERR" in src)

print(f"\nИтого: {ok} прошло, {bad} провалено")
sys.exit(1 if bad else 0)
