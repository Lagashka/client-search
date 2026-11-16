# -*- coding: utf-8 -*-
"""Голос Егора: письма короткие и живые, уходят несколькими сообщениями с паузой 5–10 с. Без сети и без Telegram."""
import os, re, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autoreply as a
import autoclient as c

ok = bad = 0
def check(name, cond):
    global ok, bad
    if cond: ok += 1; print("  ✓", name)
    else: bad += 1; print("  ✗ ПРОВАЛ:", name)

def clean(t):
    return ("!" not in t and "🙂" not in t and not t.rstrip().endswith(".") and "Нашёл вашу вакансию" not in t
            and "«Ищу" not in t and "уважаем" not in t.lower())

print("voicefy")
v = a.voicefy("Отлично! Здравствуйте 🙂.\n\nРаботы здесь: https://t.me/zakulisy715.")
check("нет «!», эмодзи и точки в конце абзаца", "!" not in v and "🙂" not in v and not v.split("\n")[0].endswith(".") and not v.endswith("."))
check("ссылка осталась целой", v.endswith("https://t.me/zakulisy715"))

print("split_parts и отправка несколькими сообщениями")
check("3 абзаца = 3 сообщения", len(c.split_parts("а\n\nб\n\nв")) == 3)
check("строка внутри абзаца остаётся одним сообщением", len(c.split_parts("а\nб\n\nв")) == 2)
check("больше 4 абзацев сливаются в 4 сообщения", len(c.split_parts("1\n\n2\n\n3\n\n4\n\n5\n\n6")) == 4)

class Fake(c.Web):
    def __init__(self, fail_at=None):
        self.sent = []; self.fail_at = fail_at; self.cleared = 0
    def _type_and_send(self, t):
        if self.fail_at is not None and len(self.sent) == self.fail_at: return "fail:тест"
        self.sent.append(t); return "sent"
    def clear_input(self): self.cleared += 1
pauses = []
real_sleep = c.time.sleep
c.time.sleep = lambda x: pauses.append(x)
w = Fake(); r = w.type_and_send("раз\n\nдва\n\nтри", split=True)
check("3 сообщения подряд, last_parts=3", r == "sent" and w.sent == ["раз", "два", "три"] and w.last_parts == 3)
check("между сообщениями 2 паузы по 5–10 секунд", len(pauses) == 2 and all(5 <= x <= 10 for x in pauses))
pauses.clear(); w = Fake(); w.type_and_send("раз\n\nдва", split=False)
check("без split — одно сообщение и без пауз", w.sent == ["раз\n\nдва"] and not pauses)
w = Fake(fail_at=1); r = w.type_and_send("раз\n\nдва\n\nтри", split=True)
check("если первое ушло, а второе нет — письмо считается отправленным, last_parts=1", r == "sent" and w.last_parts == 1)
w = Fake(fail_at=0); r = w.type_and_send("раз\n\nдва", split=True)
check("если не ушло первое — ошибка возвращается", r.startswith("fail") and w.last_parts == 0)
c.time.sleep = real_sleep

print("учёт исходящих при нескольких сообщениях (бот не принимает свои за ответ Егора)")
e = {"n_out": 3}
check("после письма из 3 частей бот знает про 3 исходящих", c.bot_out(e) == 3)
c.add_out(e, 2); check("автоответ из 2 частей: 5 исходящих", c.bot_out(e) == 5)
e2 = {"thread": [{"who": "me", "text": "x"}], "fu": "2026-11-09"}
check("старые записи без n_out считаются по прежней формуле", c.bot_out(e2) == 3)
class F2(c.Web):
    def __init__(self, n_out): self.n = n_out; self.sent = []
    def open_chat(self, u, pid=None): return "ok", "1"
    def bubbles(self): return (self.n, 0)
    def last_is_out(self): return False
    def type_and_send(self, t, split=False): self.sent.append((t, split)); return "sent"
w = F2(3); check("дожим уходит, если в чате ровно 3 наших сообщения из первого письма", w.send_followup("u", "1", "т", known_out=3) == "sent" and w.sent[0][1] is True)
w = F2(4); check("дожим отменён, если Егор дописал сам (4 вместо 3)", w.send_followup("u", "1", "т", known_out=3).startswith("skip"))
w = F2(5); check("автоответ отменён, если исходящих больше, чем отправил бот", w.send_reply("u", "1", "т", auto=True, known_out=3) == "skip:ответил сам")

print("письма по шаблону в голосе Егора")
random.seed(7)
post = {"text": "Ищу монтажёра Reels для эксперта по ипотеке, нужно 8 роликов в месяц, на постоянную работу, удалённо", "channel": "x"}
for i in range(3):
    t = c.compose_hot(post, "Вакансии", "Иван Петров")
    parts = c.split_parts(t)
    check(f"вакансия #{i+1}: имя + здравствуйте/добрый день, 2 сообщения, до 350 знаков, один вопрос, без «рассылочных» оборотов (16.11)",
          re.match(r"^Иван, (здравствуйте|добрый день), ", t) and len(parts) == 2 and len(t) <= 350 and t.count("?") == 1 and clean(t)
          and "zakulisy715" in t and not c.human.looks_bot(t, allow_link=True))
print("   Пример (вакансия):\n   " + t.replace("\n", "\n   "))
ch = {"title": "Долги без паники", "desc": "Юрист по банкротству", "subs": 1200, "avg_views": 180, "n_posts": 10, "videos": 0,
      "posts": ["Как не потерять единственное жильё при банкротстве"]}
for v_ in "ABC":
    t = c.compose_cold(ch, "Мария Иванова", "юрист", v_)
    check(f"холодное {v_}: 2 сообщения, «Я Егор», пост по теме, без точки и «!», до 350 знаков, один вопрос (16.11)",
          len(c.split_parts(t)) == 2 and "Я Егор" in t and "единственное жильё" in t and clean(t) and len(t) <= 350 and t.count("?") == 1)
    if v_ == "C": check("в варианте C цена 19 000 ₽, без старых 39/50 тысяч и скидок", "19 000 ₽" in t and "50 000" not in t and "39 000" not in t and "скидк" not in t)
    if v_ == "A": print("   Пример (холодное A):\n   " + t.replace("\n", "\n   "))
for kind in ("hot", "cold"):
    t = c.followup_text({"kind": kind, "display": "Иван Петров"})
    check(f"дожим {kind}: коротко, в голосе", len(t) < 280 and clean(t) and t.startswith("Иван, "))

print("первое письмо короткое: без «под ключ», бесплатного теста и перечня услуг (16.11, жалобы на рассылку)")
random.seed(21)
for i in range(6):
    t_ = c.compose_hot(post, "Вакансии", "Иван Петров")
    check(f"вакансия #{i+1}: нет «под ключ / бесплатно / сценарии / раскадровка»", not a.FIRST_TOO_MUCH.search(t_))
for v_ in "ABC":
    t_ = c.compose_cold(ch, "Мария Иванова", "юрист", v_)
    check(f"холодное {v_}: нет «под ключ / бесплатно / сценарии / раскадровка»", not a.FIRST_TOO_MUCH.search(t_))
check("промпты первых писем требуют короткое письмо и больше не требуют «комплекс»",
      "КОРОТКОЕ" in a.FIRST and "КОРОТКОЕ" in a.COLD and "ОБЯЗАТЕЛЬНО в письме одним предложением" not in a.FIRST + a.COLD)

print("ответы бота и защита от «рассылочности»")
r = a.rule_reply("сколько стоит?", None)["text"]
check("ответ про цену: 50 000 (не 39 000), без «!» и точки в конце", "50 000" in r and "39 000" not in r and clean(r))
check("прощание в голосе", clean(a.goodbye()))
check("«Нашёл вашу вакансию в «…»» отклоняется в первом письме", not a._sane("Нашёл вашу вакансию в «Видеомонтаж»: «Ищу монтажёра». Я Егор.", first=True))
check("«рад сотрудничеству» отклоняется в первом письме", not a._sane("Здравствуйте, буду рад сотрудничеству, Я Егор", first=True))
check("простыня больше 900 знаков отклоняется в первом письме", not a._sane("слово " * 200, first=True))
check("живое письмо проходит", a._sane("Иван, здравствуйте, увидел вашу вакансию\n\nЗнаю, как это бывает\n\nМогу бесплатно сделать тест", first=True))
check("в промптах ИИ есть блок «ГОЛОС ЕГОРА» и нет старых примеров",
      all("ГОЛОС ЕГОРА" in x and "{VOICE}" not in x for x in (a.SYSTEM, a.FIRST, a.COLD, a.FOLLOW)) and "Долги без паники" not in a.COLD and "прошлый монтажёр пропал" not in a.FIRST)

print("ИИ-штампы и правило «один вопрос до цены»")
check("«не просто X, а Y» отклоняется", not a._sane("Это не просто монтаж, а система, которая работает"))
check("«в современном мире» отклоняется", not a._sane("В современном мире видео решает всё"))
check("«давайте разберёмся» отклоняется", not a._sane("Давайте разберёмся, что вам подойдёт"))
check("обычная фраза с «просто» проходит", a._sane("Это просто, снимаете на телефон и присылаете"))
check("штамп отклоняется и в ответах клиентам (не только в первых письмах)", not a._sane("Важно отметить, что цена от 3 000 ₽"))
check("правило ИИ «один уточняющий вопрос до цены» есть в SYSTEM", "ОДИН уточняющий вопрос про неё" in a.SYSTEM and "сразу цена, условия и закрывающий вопрос" in a.SYSTEM)

print(f"\nИтого: {ok} прошло, {bad} провалено"); sys.exit(1 if bad else 0)
