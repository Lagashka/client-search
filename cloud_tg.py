# Облачный режим (GitHub Actions). Основной вариант — Telegram Web в Chromium (класс Web из autoclient.py)
# плюс пульт бота (BotLink). Запасной вариант без браузера — TgCloud на Telethon (нужны api_id/api_hash).
import os, re, time, datetime, importlib.util, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DEVICE = dict(device_model="Client Search", system_version="Cloud", app_version="1.0")

def load_bot_control():
    spec = importlib.util.spec_from_file_location("bot_control", os.path.join(HERE, "bot-control.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

class CloudCtl:
    """Пульт в облаке: процесс не запускаем и не убиваем — кнопки ▶️/⏹ включают и выключают работу."""
    def __init__(self, bc):
        self.bc = bc
        self.cfg = bc.jload(bc.CFG, {})
        self.cfg.setdefault("offset", 0); self.cfg.setdefault("want", True); self.cfg["v3"] = True
        self.started = time.time(); self.crashes = []; self.proc = None
        self.active = bool(self.cfg["want"])      # реальное состояние (пульт сначала меняет cfg, потом зовёт start/stop)
    def save(self): self.bc.jsave(self.bc.CFG, self.cfg)
    def running(self): return self.active
    def start(self):
        was = self.active; self.active = True; self.cfg["want"] = True; self.save(); return not was
    def stop(self):
        was = self.active; self.active = False; self.cfg["want"] = False; self.save(); return was

class BotLink:
    """Кнопки пульта и итог дня внутри процесса поиска. Подмешивается к Web и к TgCloud."""
    def init_bot(self):
        self.bc = load_bot_control()
        self.ctl = CloudCtl(self.bc)
        self._warned409 = False

    def want(self):
        return self.ctl.running()

    def tick_bot(self):
        bc, ctl = self.bc, self.ctl
        try:
            r = bc.api("getUpdates", http_timeout=15, offset=ctl.cfg["offset"], timeout=0,
                       allowed_updates=["message", "callback_query"])
        except urllib.error.HTTPError as e:
            if e.code == 409 and not self._warned409:     # кнопки забирает пульт на компьютере
                self._warned409 = True
                bc.say("⚠️ На компьютере всё ещё работает старый пульт, и кнопки уходят ему. "
                       "Запусти на ПК «Выключить локальный пульт.bat».")
            return
        except Exception:
            return
        for u in r.get("result", []):
            try: bc.process_update(ctl, u)
            except Exception as ex: bc.clog("облако: ошибка обработки кнопки:", ex)
        now = datetime.datetime.now()                      # в workflow задан TZ=Europe/Moscow
        if now.hour == bc.REPORT_HOUR and ctl.cfg.get("report_date") != now.date().isoformat():
            ctl.cfg["report_date"] = now.date().isoformat(); ctl.save()
            try: bc.evening_report(ctl)
            except Exception as ex: bc.clog("облако: отчёт:", ex)

class TgCloud(BotLink):
    """Запасной вариант: то же, что Web, но через Telethon (MTProto), без браузера."""
    page = True          # для совместимости с autoclient.web_up()

    def __init__(self, Limited):
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        self.Limited = Limited
        self.spam_text = ""
        self.c = TelegramClient(StringSession(os.environ.get("TG_SESSION", "")), int(os.environ.get("TG_API_ID", "0")),
                                os.environ.get("TG_API_HASH", ""), flood_sleep_threshold=60, **DEVICE)
        self.init_bot()

    def start(self):
        self.c.connect()
        if not self.c.is_user_authorized():
            self.bc.say("⚠️ Облако: вход в Telegram недействителен (сессию отозвали или она устарела).")
            raise SystemExit(2)

    def close(self):
        pass

    def _flood(self, e):
        if e.seconds > 600:
            raise self.Limited(f"Telegram просит паузу {e.seconds // 60} мин (FloodWait)")
        time.sleep(e.seconds + 2)

    def _user(self, username):
        from telethon import errors
        from telethon.tl.types import User
        for _ in range(2):
            try:
                ent = self.c.get_entity(username)
                break
            except errors.FloodWaitError as e:
                self._flood(e)
            except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError, ValueError, TypeError):
                return None, "нет такого пользователя"
        else:
            return None, "не удалось найти"
        if not isinstance(ent, User) or ent.bot or ent.deleted:
            return None, "это не личный аккаунт"
        return ent, ""

    def _send(self, ent, text):
        from telethon import errors
        try:
            self.c.send_message(ent, text)
            return "sent"
        except errors.PeerFloodError:
            raise self.Limited("Telegram ограничил сообщения незнакомым (PEER_FLOOD)")
        except errors.FloodWaitError as e:
            self._flood(e); return "fail:FloodWait"
        except (errors.UserPrivacyRestrictedError, errors.UserIsBlockedError, errors.InputUserDeactivatedError,
                errors.ChatWriteForbiddenError) as e:
            return "skip:" + type(e).__name__
        except errors.RPCError as e:
            if "PREMIUM" in str(e).upper(): return "skip:пишут только Premium"
            return "fail:" + str(e)[:80]

    def send_new(self, username, text):
        ent, why = self._user(username)
        if not ent: return f"skip:{why}", None
        if self.c.get_messages(ent, limit=1):
            return "skip:переписка уже была", str(ent.id)
        return self._send(ent, text), str(ent.id)

    def send_reply(self, username, peer_id, text):
        ent, why = self._user(username)
        if not ent: return f"skip:{why}"
        return self._send(ent, text)

    def send_followup(self, username, peer_id, text):
        ent, why = self._user(username)
        if not ent: return f"skip:{why}"
        msgs = self.c.get_messages(ent, limit=10)
        if any(not m.out for m in msgs): return "replied"
        if sum(1 for m in msgs if m.out) != 1: return "skip:в чате не одно наше сообщение"
        return self._send(ent, text)

    def scan_replies(self, peers):
        found = {}
        for d in self.c.iter_dialogs(limit=300):
            pid = str(d.id)
            if pid in peers and d.message is not None and not d.message.out:
                found[pid] = re.sub(r"\s+", " ", d.message.message or "[медиа]").strip()[:200]
        return found

    def search_channels(self, q):
        from telethon.tl.functions.contacts import SearchRequest
        r = self.c(SearchRequest(q=q, limit=40))
        return {ch.username for ch in r.chats if getattr(ch, "username", None)}

    def spambot_ok(self):
        self.spam_text = ""
        bot = self.c.get_entity("SpamBot")
        prev = self.c.get_messages(bot, limit=1)
        last_id = prev[0].id if prev else 0
        self.c.send_message(bot, "/start")
        text = ""
        for _ in range(20):
            time.sleep(1)
            inc = [m for m in self.c.get_messages(bot, limit=3) if not m.out and m.id > last_id]
            if inc: text = inc[0].message or ""; break
        self.spam_text = re.sub(r"\s+", " ", text).strip()
        if re.search(r"free as a bird|no limits|свободен от|нет ограничений|не ограничен", text, re.I): return True
        if re.search(r"limited|ограничен|annoying|жалоб|к сожалению|unfortunately|пожаловал", text, re.I): return False
        return None

    def open_chat(self, username, peer_id=None):
        return "skip", "в облаке не нужно"

    def clear_input(self):
        pass
