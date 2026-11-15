# -*- coding: utf-8 -*-
"""Тесты почты и hh.ru API без сети. Запуск: python tests_mail_hh.py"""
import sys, os, email
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import mail_watch as M, hh_api as H, human, safety, autoreply
autoreply.llm_on = lambda: False          # тесты без сети: проверяем правила и шаблоны, а не нейросеть

ok = bad = 0
def check(n, c):
    global ok, bad
    if c: ok += 1; print("  ✓", n)
    else: bad += 1; print("  ✗ ПРОВАЛ:", n)

def msg(frm, subj, body, extra=""):     # как настоящее письмо: байты UTF-8
    return email.message_from_bytes(f"From: {frm}\nSubject: {subj}\nMessage-ID: <1@x>\n{extra}Content-Type: text/plain; charset=utf-8\n"
                                    f"Content-Transfer-Encoding: 8bit\n\n{body}".encode("utf-8"))

print("почта: что считать рассылкой")
check("рассылка с List-Unsubscribe — мимо", M.is_bulk(msg("Shop <news@shop.ru>", "Скидки", "x", "List-Unsubscribe: <mailto:u@x>\n"), "news@shop.ru"))
check("noreply сервиса — мимо", M.is_bulk(msg("x <noreply@google.com>", "Security", "x"), "noreply@google.com"))
check("hh.ru с noreply — НЕ мимо (приглашения важны)", not M.is_bulk(msg("hh <noreply@hh.ru>", "Вас пригласили", "x"), "noreply@hh.ru"))
check("живой человек — не рассылка", not M.is_bulk(msg("Ольга <olga@salon-leto.ru>", "Ролики", "x"), "olga@salon-leto.ru"))
check("автоответ «я в отпуске» — мимо", M.is_bulk(msg("a <a@b.ru>", "Отпуск", "x", "Auto-Submitted: auto-replied\n"), "a@b.ru"))

print("почта: текст без цитаты")
b = M.body_of(msg("a@b.ru", "Re", "Да, интересно, сколько стоит?\n\n15.11.2026, 12:00, Егор пишет:\n> Добрый день, я делаю ролики"))
check("цитата нашего письма отрезана", "интересно" in b and "делаю ролики" not in b)

print("почта: кто это из лидов")
st = {"sent": {"olga_leto": {"display": "Ольга Петрова", "text": "..."}},
      "biz": {"companies": {"k1": {"name": "Салон Лето", "domain": "salon-leto.ru", "tg": ["olga_leto"]}}},
      "hh_api": {"applied": {"123": {"employer": "Медиа Плюс", "name": "Рилсмейкер"}}}}
check("по домену компании", M.match_lead(st, "director@salon-leto.ru", "", "Ролики", "") == ("company", "k1"))
check("по нику Telegram в тексте", M.match_lead(st, "x@gmail.com", "", "Re", "это @olga_leto из телеграма") == ("sent", "olga_leto"))
check("по работодателю с hh", M.match_lead(st, "hr@gmail.com", "", "Отклик", "Здравствуйте, компания Медиа Плюс, по вашему отклику") == ("hh", "123"))
check("по имени отправителя", M.match_lead(st, "op@gmail.com", "Ольга Петрова", "Re", "") == ("sent", "olga_leto"))
check("чужой — не лид", M.match_lead(st, "x@gmail.com", "Иван", "Привет", "как дела") == (None, None))
check("адрес IMAP по домену", M.imap_host("a@gmail.com") == "imap.gmail.com" and M.imap_host("a@yandex.ru") == "imap.yandex.ru")

print("hh.ru: фильтры вакансий")
check("рилсмейкер — наш", bool(H.ROLE.search("Рилсмейкер (удалённо)")) and not H.SKIP.search("Рилсмейкер (удалённо)"))
check("монтажник/электромонтажник — не наш", bool(H.SKIP.search("Электромонтажник")) and bool(H.SKIP.search("Монтажник видеонаблюдения")))
check("оператор/фотограф — не наш", bool(H.SKIP.search("Видеооператор")) or bool(H.SKIP.search("оператор")))
check("без секретов бот 4 спит", not H.configured() or os.environ.get("HH_CLIENT_ID"))

print("hh.ru: сопроводительное шаблоном")
import random
for i in range(20):
    t, by = H.letter({"name": random.choice(["Рилсмейкер", "Видеомонтажёр", "Мобилограф"]), "employer": "X"}, "")
    if human.looks_bot(t, allow_link=True): break
check("20 писем шаблоном проходят фильтр «как человек»", not human.looks_bot(t, allow_link=True))
check("в письме есть портфолио и Telegram", "zakulisy715" in t and "@chernyshev_edit" in t)
print(f"\nИтого: {ok} прошло, {bad} провалено"); sys.exit(1 if bad else 0)
