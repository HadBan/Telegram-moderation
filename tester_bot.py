"""
╔══════════════════════════════════════════════════╗
║       TELEGRAM БОТ-МОДЕРАТОР + AI  v3.5          ║
║         ДЛЯ ХОСТИНГА BotHost                      ║
╚══════════════════════════════════════════════════╝
"""
import logging, json, re, asyncio, os, random, secrets, base64
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from groq import Groq

# =====================================================
# 🔧 НАСТРОЙКИ (ЗАПОЛНИТЬ!)
# =====================================================
BOT_TOKEN = "bot_token"  # ⚠️ ВСТАВЬТЕ ТОКЕН
GROQ_API_KEY = "groq_token"  # ⚠️ ВСТАВЬТЕ КЛЮЧ (можно оставить пустым, если не нужен AI)

# 👑 ВЛАДЕЛЬЦЫ (укажите ID через запятую)
OWNER_IDS = [6276293498, 5019808756]

# 🎰 DONATIONALERTS (замените на свой ник)
DONATION_ALERTS_PAGE = "ваш_ник"  # ⚠️ ЗАМЕНИТЕ!

# Курс монет (Fрайды)
PRICE_LIST_DA = {
    500: 59,
    1000: 99,
    2500: 119,
    5000: 159,
    10000: 299,
    50000: 599
}
# =====================================================

GROQ_MODEL = "llama-3.3-70b-versatile"

# Базовый список оскорблений
INSULTS = ["идиот","кретин","дебил","даун","тупой","тупая","глупый","глупая","дурак","дура","дурачок","урод","уродина","чмо","чмошник","лох","лошара","придурок","ненормальный","псих","бестолочь","болван","тупица","бездарь","идиотка","stupid","idiot","fool","dumb"]

insults_library = set()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {"mute_duration": 30, "warn_limit": 3, "ai_moderation": True, "ai_assistant": True}
chat_settings = {}
ROLE_NAMES = {0: "👤 Участник", 1: "🤝 Хелпер", 2: "🛡 Модератор", 3: "👑 Владелец"}
roles = {}
warnings = {}
unmute_tasks = {}
muted_users = {}
conversation_history = {}
casino_data = {}
groq_client = None
active_model = None

# ─────────────────────── Функция проверки владельца ─────────────
def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

# ─────────────────────── Загрузка библиотеки оскорблений ─────────
def load_insults_library():
    global insults_library
    try:
        with open("insults_library.txt", "r", encoding="utf-8") as f:
            insults_library = set(word.strip().lower() for word in f.readlines() if word.strip() and not word.startswith("#"))
        logger.info(f"📚 Загружена библиотека оскорблений: {len(insults_library)} слов")
    except FileNotFoundError:
        insults_library = set()
        with open("insults_library.txt", "w", encoding="utf-8") as f:
            f.write("# Новые оскорбления будут добавляться сюда автоматически\n")

def save_insult_to_library(word: str) -> bool:
    global insults_library
    word = word.lower().strip()
    if word and word not in INSULTS and word not in insults_library:
        insults_library.add(word)
        try:
            with open("insults_library.txt", "a", encoding="utf-8") as f:
                f.write(f"{word}\n")
            return True
        except Exception as e:
            logger.error(f"Ошибка: {e}")
    return False

def remove_insult_from_library(word: str) -> bool:
    global insults_library
    word = word.lower().strip()
    if word in insults_library:
        insults_library.remove(word)
        try:
            with open("insults_library.txt", "w", encoding="utf-8") as f:
                f.write("# Новые оскорбления будут добавляться сюда автоматически\n")
                for w in sorted(insults_library):
                    f.write(f"{w}\n")
            return True
        except Exception as e:
            logger.error(f"Ошибка: {e}")
    return False

# ─────────────────────── Настройки ───────────────────────────────
def load_settings():
    global chat_settings
    try:
        with open("settings3.json", "r") as f:
            chat_settings = {int(k): v for k, v in json.load(f).items()}
    except FileNotFoundError:
        chat_settings = {}
def save_settings():
    with open("settings3.json", "w") as f:
        json.dump(chat_settings, f, ensure_ascii=False, indent=2)
def get_setting(chat_id, key):
    return chat_settings.get(chat_id, {}).get(key, DEFAULT_SETTINGS[key])
def set_setting(chat_id, key, value):
    chat_settings.setdefault(chat_id, {})[key] = value
    save_settings()

# ─────────────────────── Роли ───────────────────────────────────
def load_roles():
    global roles
    try:
        with open("roles3.json", "r") as f:
            roles = {int(k): {int(u): v for u, v in m.items()} for k, m in json.load(f).items()}
    except FileNotFoundError:
        roles = {}
def save_roles():
    with open("roles3.json", "w") as f:
        json.dump(roles, f, ensure_ascii=False, indent=2)
def get_role(chat_id, user_id):
    if is_owner(user_id):
        return 3
    return roles.get(chat_id, {}).get(user_id, 0)
def set_role(chat_id, user_id, role):
    roles.setdefault(chat_id, {})[user_id] = role
    save_roles()

async def effective_role(update, context, user_id=None):
    uid = user_id or update.effective_user.id
    chat_id = update.effective_chat.id
    bot_role = get_role(chat_id, uid)
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        if any(a.user.id == uid for a in admins):
            bot_role = max(bot_role, 2)
    except:
        pass
    return bot_role

async def require_role(update, context, min_role):
    role = await effective_role(update, context)
    if role < min_role:
        await update.message.reply_text(f"❌ Недостаточно прав. Нужна роль: {ROLE_NAMES.get(min_role, str(min_role))} или выше.")
        return False
    return True

async def require_owner(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для владельца бота!")
        return False
    return True

# ─────────────────────── Предупреждения ─────────────────────────
def load_warnings():
    global warnings
    try:
        with open("warnings3.json", "r") as f:
            warnings = {int(k): {int(u): c for u, c in v.items()} for k, v in json.load(f).items()}
    except FileNotFoundError:
        warnings = {}
def save_warnings():
    with open("warnings3.json", "w") as f:
        json.dump(warnings, f)
def get_warn_count(chat_id, user_id):
    return warnings.get(chat_id, {}).get(user_id, 0)
def add_warn(chat_id, user_id):
    warnings.setdefault(chat_id, {})[user_id] = warnings.get(chat_id, {}).get(user_id, 0) + 1
    save_warnings()
    return warnings[chat_id][user_id]
def reset_warns(chat_id, user_id):
    if chat_id in warnings and user_id in warnings[chat_id]:
        del warnings[chat_id][user_id]
        save_warnings()

# ─────────────────────── Мут ────────────────────────────────────
def is_user_muted(chat_id, user_id):
    return chat_id in muted_users and user_id in muted_users[chat_id]
def add_muted_user(chat_id, user_id):
    muted_users.setdefault(chat_id, set()).add(user_id)
def remove_muted_user(chat_id, user_id):
    if chat_id in muted_users and user_id in muted_users[chat_id]:
        muted_users[chat_id].discard(user_id)
        if not muted_users[chat_id]:
            del muted_users[chat_id]

def cancel_unmute_task(chat_id, user_id):
    if chat_id in unmute_tasks and user_id in unmute_tasks[chat_id]:
        t = unmute_tasks[chat_id][user_id]
        if not t.done():
            t.cancel()
        del unmute_tasks[chat_id][user_id]

async def do_unmute(context, chat_id, user_id, user_name):
    try:
        remove_muted_user(chat_id, user_id)
        name = user_name or "Пользователь"
        await context.bot.send_message(chat_id=chat_id, text=f"🔊 [{name}](tg://user?id={user_id}) — мут снят!", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        if chat_id in unmute_tasks and user_id in unmute_tasks[chat_id]:
            del unmute_tasks[chat_id][user_id]

async def schedule_unmute(context, chat_id, user_id, minutes, user_name=None):
    cancel_unmute_task(chat_id, user_id)
    async def _task():
        await asyncio.sleep(minutes * 60)
        await do_unmute(context, chat_id, user_id, user_name)
    task = asyncio.create_task(_task())
    unmute_tasks.setdefault(chat_id, {})[user_id] = task

async def mute_user(context, chat_id, user_id, minutes, user_name=None):
    add_muted_user(chat_id, user_id)
    await schedule_unmute(context, chat_id, user_id, minutes, user_name)

# ─────────────────────── Казино (Fрайды) ─────────────────────────
def load_casino():
    global casino_data
    try:
        with open("casino3.json", "r") as f:
            casino_data = {int(k): v for k, v in json.load(f).items()}
    except FileNotFoundError:
        casino_data = {}
def save_casino():
    with open("casino3.json", "w") as f:
        json.dump(casino_data, f)
def get_balance(user_id):
    if user_id not in casino_data:
        casino_data[user_id] = {"balance": 100, "last_bonus": 0}
        save_casino()
    return casino_data[user_id]["balance"]
def set_balance(user_id, amount):
    casino_data.setdefault(user_id, {"balance": 100, "last_bonus": 0})["balance"] = amount
    save_casino()
def add_balance(user_id, amount):
    set_balance(user_id, get_balance(user_id) + amount)

# ─────────────────────── AI Groq ─────────────────────────────────
def init_groq():
    global groq_client, active_model
    if not GROQ_API_KEY:
        logger.warning("⚠️ Groq API ключ не настроен")
        return
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        preferred = ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "llama-3.1-8b-instant"]
        try:
            available = [m.id for m in groq_client.models.list()]
            active_model = next((m for m in preferred if m in available), available[0] if available else GROQ_MODEL)
        except:
            active_model = GROQ_MODEL
        logger.info(f"✅ Groq AI: {active_model}")
    except Exception as e:
        logger.error(f"❌ Groq ошибка: {e}")
        groq_client = None

def contains_insult(text):
    text_lower = text.lower()
    for word in INSULTS:
        if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
            return True
    for word in insults_library:
        if len(word) > 2 and word in text_lower:
            return True
    return False

async def check_insult_with_groq(text, chat_id):
    if contains_insult(text):
        return True, "🔍 обнаружено оскорбление"
    if not get_setting(chat_id, "ai_moderation") or not groq_client or not active_model:
        return False, ""
    try:
        prompt = f'Ты модератор. Текст: "{text}". Игнорируй маты! Отмечай ТОЛЬКО оскорбления. Если нашел новое слово, укажи в "new_word". Ответь JSON: {{"is_insult": true/false, "reason": "", "new_word": ""}}'
        resp = groq_client.chat.completions.create(model=active_model, messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=100)
        raw = resp.choices[0].message.content
        match = re.search(r'\{[^}]+\}', raw)
        if match:
            data = json.loads(match.group())
            if data.get("is_insult"):
                reason = data.get('reason', 'оскорбление')
                if data.get("new_word"):
                    new_word = data["new_word"].lower().strip()
                    if new_word and len(new_word) > 2:
                        if save_insult_to_library(new_word):
                            reason += f" (📝 '{new_word}' добавлено)"
                return True, f"🤖 AI: {reason}"
        return False, ""
    except Exception as e:
        logger.error(f"Groq ошибка: {e}")
        return False, ""

async def get_ai_response(text, user_id, chat_id):
    if not groq_client or not active_model:
        return "❌ AI не доступен"
    key = f"{chat_id}_{user_id}"
    history = conversation_history.get(key, [])[-10:]
    try:
        messages = [{"role": "system", "content": "Ты умный AI-ассистент. Отвечай на русском."}] + history + [{"role": "user", "content": text}]
        resp = groq_client.chat.completions.create(model=active_model, messages=messages, temperature=0.7, max_tokens=1500)
        answer = resp.choices[0].message.content
        conversation_history.setdefault(key, [])
        conversation_history[key] += [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
        while len(conversation_history[key]) > 20:
            conversation_history[key].pop(0)
        return answer
    except Exception as e:
        return f"❌ Ошибка: {str(e)[:100]}"

# ─────────────────────── МАГАЗИН (DonationAlerts) ────────────────
async def cmd_donate(update, context):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "❌ *Покупка Fрайдов доступна только в ЛС!*\n\n"
            f"👤 Напишите боту: @{context.bot.username}",
            parse_mode="Markdown"
        )
        return
    
    user_id = update.effective_user.id
    balance = get_balance(user_id)
    
    text = f"🛒 *Магазин Fрайдов*\n\n👤 Баланс: `{balance}` Fрайдов\n\n💰 *Пакеты:*\n"
    for coins, price in PRICE_LIST_DA.items():
        text += f"• `{coins}` Fрайдов — `{price}` ₽\n"
    text += f"\n💳 DonationAlerts (СБП/карта)"
    
    keyboard = []
    row = []
    for coins, price in PRICE_LIST_DA.items():
        row.append(InlineKeyboardButton(f"{coins}🪙 {price}₽", callback_data=f"da_buy_{coins}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❓ Как оплатить?", callback_data="da_help")])
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def da_callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    if query.data == "da_help":
        await query.edit_message_text(
            "📖 *Как оплатить:*\n\n1️⃣ Нажмите на пакет\n2️⃣ Оплатите через DonationAlerts\n3️⃣ Fрайды придут автоматически\n\n❓ Вопросы? Пишите @ваш_ник",
            parse_mode="Markdown"
        )
        return
    
    if query.data.startswith("da_buy_"):
        coins = int(query.data.split("_")[2])
        price = PRICE_LIST_DA.get(coins)
        if not price:
            await query.edit_message_text("❌ Ошибка")
            return
        
        user_id = query.from_user.id
        payment_id = secrets.token_hex(8)
        custom_data = base64.b64encode(f"{user_id}:{coins}:{payment_id}".encode()).decode()
        donate_url = f"https://www.donationalerts.ru/r/{DONATION_ALERTS_PAGE}?amount={price}&message=Покупка+{coins}+Fрайдов&custom_data={custom_data}"
        
        text = f"💸 *Оплата {coins} Fрайдов*\n💰 Сумма: {price} ₽\n\n[Перейти к оплате]({donate_url})\n\n✅ После оплаты Fрайды начислятся автоматически!"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Оплатить", url=donate_url)]]), parse_mode="Markdown")

# ─────────────────────── КОМАНДЫ КАЗИНО ─────────────────────────
async def cmd_casino(update, context):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "🎰 *КАЗИНО (Fрайды)*\n\n"
            "`/casino баланс` — баланс\n"
            "`/casino бонус` — бонус (раз в день)\n"
            "`/casino <ставка>` — игра 50/50\n"
            "`/casino куб <ставка> <1-6>` — угадай (x5)\n"
            "`/donate` — купить Fрайды\n\n"
            "💰 Начальный баланс: 100 Fрайдов",
            parse_mode="Markdown"
        )
        return
    
    cmd = context.args[0].lower()
    if cmd in ["баланс", "balance"]:
        await update.message.reply_text(f"💰 Баланс: *{get_balance(user_id)}* Fрайдов", parse_mode="Markdown")
    
    elif cmd in ["бонус", "bonus"]:
        now = int(datetime.now().timestamp())
        last = casino_data.get(user_id, {}).get("last_bonus", 0)
        if now - last < 86400:
            hours = 24 - ((now - last) // 3600)
            await update.message.reply_text(f"🎁 Бонус через {hours} ч.")
            return
        bonus = random.randint(50, 200)
        add_balance(user_id, bonus)
        casino_data[user_id]["last_bonus"] = now
        save_casino()
        await update.message.reply_text(f"🎁 +{bonus} Fрайдов! Баланс: {get_balance(user_id)}", parse_mode="Markdown")
    
    elif cmd in ["куб", "dice"]:
        if len(context.args) < 3:
            await update.message.reply_text("❌ /casino куб <ставка> <1-6>")
            return
        try:
            bet, guess = int(context.args[1]), int(context.args[2])
        except:
            await update.message.reply_text("❌ Ошибка ввода")
            return
        if guess < 1 or guess > 6:
            await update.message.reply_text("❌ Число 1-6")
            return
        balance = get_balance(user_id)
        if bet <= 0 or bet > balance:
            await update.message.reply_text(f"❌ Недостаточно. Баланс: {balance}")
            return
        result = random.randint(1, 6)
        if result == guess:
            win = bet * 5
            add_balance(user_id, win - bet)
            await update.message.reply_text(f"🎲 Выпало: {result}\n🎉 Выигрыш: {win} Fрайдов!\n💰 Баланс: {get_balance(user_id)}", parse_mode="Markdown")
        else:
            add_balance(user_id, -bet)
            await update.message.reply_text(f"🎲 Выпало: {result}\n😢 Проигрыш: {bet} Fрайдов\n💰 Баланс: {get_balance(user_id)}", parse_mode="Markdown")
    
    else:
        try:
            bet = int(cmd)
        except:
            await update.message.reply_text("❌ Неизвестная команда")
            return
        balance = get_balance(user_id)
        if bet <= 0 or bet > balance:
            await update.message.reply_text(f"❌ Недостаточно. Баланс: {balance}")
            return
        win = random.choice([True, False])
        if win:
            add_balance(user_id, bet)
            await update.message.reply_text(f"🎰 Выигрыш! +{bet} Fрайдов\n💰 Баланс: {get_balance(user_id)}", parse_mode="Markdown")
        else:
            add_balance(user_id, -bet)
            await update.message.reply_text(f"🎰 Проигрыш. -{bet} Fрайдов\n💰 Баланс: {get_balance(user_id)}", parse_mode="Markdown")

# ─────────────────────── КОМАНДА ДЛЯ ВЛАДЕЛЬЦЕВ ──────────────────
async def cmd_add_fraids(update, context):
    if not await require_owner(update, context):
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ `/add_fraids <пользователь> <количество>`\n\n"
            "Примеры:\n"
            "• `/add_fraids @username 1000`\n"
            "• ответом на сообщение: `/add_fraids 1000`",
            parse_mode="Markdown"
        )
        return
    
    target_id = None
    target_name = None
    amount = None
    
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        target_name = update.message.reply_to_message.from_user.first_name
        amount = int(context.args[0])
    elif context.args[0].startswith("@"):
        username = context.args[0].lstrip("@")
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, f"@{username}")
            target_id = member.user.id
            target_name = member.user.first_name
            amount = int(context.args[1])
        except:
            await update.message.reply_text(f"❌ @{username} не найден")
            return
    elif context.args[0].isdigit():
        target_id = int(context.args[0])
        amount = int(context.args[1])
        target_name = str(target_id)
    else:
        await update.message.reply_text("❌ Неверный формат")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Количество > 0")
        return
    
    old = get_balance(target_id)
    add_balance(target_id, amount)
    new = get_balance(target_id)
    
    await update.message.reply_text(
        f"✅ *Пополнение Fрайдов*\n\n"
        f"👤 [{target_name}](tg://user?id={target_id})\n"
        f"➕ +{amount} Fрайдов\n"
        f"💰 {old} → {new}",
        parse_mode="Markdown"
    )
    
    try:
        await context.bot.send_message(target_id, f"🎉 Вам начислено +{amount} Fрайдов!\n💰 Баланс: {new}")
    except:
        pass

# ─────────────────────── ОСТАЛЬНЫЕ КОМАНДЫ (сокращённо) ──────────
async def cmd_start(update, context):
    await update.message.reply_text("👮 Бот-модератор v3.5\n🎰 Есть казино на Fрайдах!\n/donate — купить Fрайды\n/casino — играть\n/commands — все команды")

async def cmd_commands(update, context):
    await update.message.reply_text(
        "📋 *Команды:*\n"
        "/start, /casino, /donate, /myrole, /rules\n"
        "👑 Владельцам: /add_fraids, /add_insult",
        parse_mode="Markdown"
    )

async def cmd_myrole(update, context):
    role = await effective_role(update, context)
    await update.message.reply_text(f"Ваша роль: {ROLE_NAMES.get(role, 'Участник')}")

async def cmd_rules(update, context):
    await update.message.reply_text("🚫 Правила: запрещены оскорбления. Маты разрешены.")

async def cmd_learned_insults(update, context):
    if insults_library:
        words = sorted(list(insults_library))[:30]
        await update.message.reply_text(f"📚 Выученные: {', '.join(words)}", parse_mode="Markdown")
    else:
        await update.message.reply_text("📚 Пока нет выученных оскорблений")

async def cmd_add_insult(update, context):
    if not await require_owner(update, context):
        return
    if not context.args:
        return
    word = " ".join(context.args).lower()
    if save_insult_to_library(word):
        await update.message.reply_text(f"✅ Добавлено: {word}")

# ─────────────────────── АВТОМОДЕРАЦИЯ ──────────────────────────
async def auto_moderate(update, context):
    msg = update.message
    if not msg or not msg.text or msg.chat.type == "private":
        return
    user = msg.from_user
    if not user or is_owner(user.id):
        return
    chat_id = msg.chat_id
    if get_role(chat_id, user.id) >= 3:
        return
    if is_user_muted(chat_id, user.id):
        try:
            await msg.delete()
        except:
            pass
        return
    
    is_insult, reason = await check_insult_with_groq(msg.text, chat_id)
    if not is_insult:
        return
    
    try:
        await msg.delete()
    except:
        pass
    
    warn_limit = get_setting(chat_id, "warn_limit")
    mute_dur = get_setting(chat_id, "mute_duration")
    warn_count = add_warn(chat_id, user.id)
    mention = f"[{user.first_name}](tg://user?id={user.id})"
    
    if warn_count >= warn_limit:
        await mute_user(context, chat_id, user.id, mute_dur, user.first_name)
        reset_warns(chat_id, user.id)
        await msg.reply_text(f"🔇 {mention} мут на {mute_dur} мин", parse_mode="Markdown")
    else:
        remaining = warn_limit - warn_count
        await msg.reply_text(f"⚠️ {mention} оскорбление! {warn_count}/{warn_limit}. Ещё {remaining} — мут", parse_mode="Markdown")

async def ai_assistant(update, context):
    msg = update.message
    if not msg or not msg.text or not get_setting(msg.chat_id, "ai_assistant"):
        return
    if msg.chat.type == "private":
        respond = True
    elif f"@{context.bot.username}" in msg.text:
        respond = True
        msg._unfreeze()
        msg.text = msg.text.replace(f"@{context.bot.username}", "").strip()
    elif msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id:
        respond = True
    else:
        return
    
    await context.bot.send_chat_action(msg.chat_id, "typing")
    response = await get_ai_response(msg.text, msg.from_user.id, msg.chat_id)
    for i in range(0, len(response), 4000):
        await msg.reply_text(response[i:i+4000])

# ─────────────────────── MAIN ───────────────────────────────────
async def resolve_target(update, context):
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        return u.id, u.first_name, u.username
    return None, None, None

async def can_moderate(update, target_id, action):
    if is_owner(target_id):
        await update.message.reply_text(f"❌ Нельзя {action} владельца")
        return False
    return True

async def cmd_mute(update, context):
    if not await require_role(update, context, 1):
        return
    user_id, name, _ = await resolve_target(update, context)
    if not user_id:
        return
    minutes = int(context.args[0]) if context.args else 30
    await mute_user(context, update.effective_chat.id, user_id, minutes, name)
    await update.message.reply_text(f"🔇 {name} замучен на {minutes} мин")

async def cmd_unmute(update, context):
    if not await require_role(update, context, 1):
        return
    user_id, name, _ = await resolve_target(update, context)
    if user_id:
        await do_unmute(context, update.effective_chat.id, user_id, name)

# ... (остальные модераторские команды по аналогии, они есть в полной версии)

# ─────────────────────── ЗАПУСК ─────────────────────────────────
def main():
    if not BOT_TOKEN:
        print("❌ Ошибка: BOT_TOKEN не настроен!")
        return
    
    load_warnings()
    load_settings()
    load_roles()
    load_casino()
    load_insults_library()
    init_groq()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Основные команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("commands", cmd_commands))
    app.add_handler(CommandHandler("myrole", cmd_myrole))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("casino", cmd_casino))
    app.add_handler(CommandHandler("donate", cmd_donate))
    app.add_handler(CommandHandler("learned_insults", cmd_learned_insults))
    
    # Владельцы
    app.add_handler(CommandHandler("add_fraids", cmd_add_fraids))
    app.add_handler(CommandHandler("add_insult", cmd_add_insult))
    
    # Модерация (базовые)
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    
    # Обработчики
    app.add_handler(CallbackQueryHandler(da_callback_handler, pattern="^da_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_moderate))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_assistant), group=1)
    
    print("✅ Бот запущен на BotHost!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
