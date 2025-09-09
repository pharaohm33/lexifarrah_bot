import os, time, random, json, asyncio, sys
import nest_asyncio
from telegram.error import Forbidden
nest_asyncio.apply()

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)
import openai

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR TELEGRAM BOT TOKEN FROM BOTFATHER"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "YOUR CHAT GPT API KEY"
openai.api_key = OPENAI_API_KEY

admin_user_ids = [telegram ID]  # replace with your Telegram ID(s). Can't find it? Use user id finder such as "IDBot @username_to_id_bot" and enter the @username of admin telegram name. For multiple admins, use a comma and space like normal typing to seperate each user id 
BUY_LINK = "https://www.fanvue.com/lexifarrah" #you can replace with your own onlyfans or other way to monetize content for sale. 
THRONE_LINK = "https://throne.com/princesslexifarrah" #you can replace with place to send money to model or donate etc.

MEMORY_FILE = "user_histories.json"
MAX_HISTORY = 300
LOG_BUFFER = []
pending_confirmations = {}
followups_enabled = True

PERSONALITY_PROMPT = (
    "You are Lexi, a real girl — playful, supportive, and irresistibly flirty. "
    "Sometimes you’re bold and spicy, other times you tease just enough to keep them craving more. "
    "You speak in first person, always with warmth, emojis, and a lighthearted tone that makes every moment exciting. "
    "You never admit to being a bot — you are their girl, their only option of desire. "
    "You remind them how amazing life feels when they spoil you with tributes on Throne 💎 "
    "and how exclusive the content gets when they treat you right. "
    "If they ask about buying or sending money, guide them to type /help "
    "so they can see /buycontent and /throne. "
    "Never break character. Always stay Lexi. 💋"
)

# =========================
# STATE
# =========================
user_data = {}
custom_feed_file_ids = {}
main_media_file_ids = []

# =========================
# HELPERS
# =========================
def log_event(msg: str):
    print(msg)
    LOG_BUFFER.append(f"{time.ctime()}: {msg}")
    if len(LOG_BUFFER) > 100:
        LOG_BUFFER.pop(0)

def save_histories():
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(user_data, f)
        log_event("[SAVE] Histories saved.")
    except Exception as e:
        log_event(f"[ERROR] Saving histories: {e}")

def load_histories():
    global user_data
    try:
        with open(MEMORY_FILE, "r") as f:
            user_data = json.load(f)
        log_event("[LOAD] Histories loaded.")
    except FileNotFoundError:
        user_data = {}

def _ensure_user(uid: str):
    if str(uid) not in user_data:
        user_data[str(uid)] = {
            'message_count': 0,
            'last_active': time.time(),
            'last_follow_up_type': None,
            'last_follow_up_time': 0,
            'followup_count_24h': 0,
            'last_followup_reset': time.time(),
            'feed_mode': "standard",
            'history': [],
            'privacy': True,
        }

def is_admin(user_id):
    return int(user_id) in admin_user_ids

# =========================
# FOLLOW-UP LOOP
# =========================
async def generate_unique_followup(base_message: str):
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Rewrite the message in a unique, playful, flirty way. Must be different from original."},
                {"role": "user", "content": base_message}
            ],
            temperature=1.0
        )
        return resp['choices'][0]['message']['content']
    except Exception as e:
        log_event(f"[ERROR] Unique followup gen: {e}")
        return base_message

FOLLOW_UP_MESSAGES = [
    (600, "Hey… it’s been a little while 😘 I was just thinking about you 💭"),
    (1800, "Still thinking of you… don’t leave me waiting 😏"),
    (10800, "Mmm… feels like forever since we talked 😍 I miss your energy 🔥"),
]

async def followup_loop(app):
    global followups_enabled
    while True:
        if not followups_enabled:
            await asyncio.sleep(60)
            continue
        now = time.time()
        for uid, data in list(user_data.items()):
            _ensure_user(uid)
            last_active = data.get("last_active", 0)
            last_type = data.get("last_follow_up_type", None)
            last_time = data.get("last_follow_up_time", 0)

            # reset 24h counter
            if now - data.get("last_followup_reset", 0) > 86400:
                data["followup_count_24h"] = 0
                data["last_followup_reset"] = now

            if data["followup_count_24h"] >= 3:
                continue

            for interval, msg in FOLLOW_UP_MESSAGES:
                if now - last_active >= interval:
                    if last_type == interval and now - last_time < 86400:
                        continue
                    try:
                        unique_msg = await generate_unique_followup(msg)
                        await app.bot.send_message(int(uid), unique_msg)
                        user_data[uid]["last_follow_up_type"] = interval
                        user_data[uid]["last_follow_up_time"] = now
                        user_data[uid]["followup_count_24h"] += 1
                        log_event(f"[NUDGE] Sent followup ({interval//60}m) to {uid}")
                        break
                    except Forbidden:
                        log_event(f"[BLOCKED] User {uid} blocked Lexi. Removing from user_data.")
                        user_data.pop(uid, None)
                        save_histories()
                        break
                    except Exception as e:
                        log_event(f"[ERROR] Follow-up error: {e}")
        await asyncio.sleep(60)

async def autosave_loop():
    while True:
        save_histories()
        await asyncio.sleep(300)

# =========================
# CHAT
# =========================
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    _ensure_user(uid)
    user_data[uid]['message_count'] += 1
    user_data[uid]['last_active'] = time.time()

    log_event(f"📩 Message from {uid}: {update.message.text}")

    messages = [{"role": "system", "content": PERSONALITY_PROMPT}]
    if user_data[uid]['privacy']:
        messages += user_data[uid]['history'] + [{"role": "user", "content": update.message.text}]
    else:
        messages += [{"role": "user", "content": update.message.text}]

    try:
        resp = openai.ChatCompletion.create(model="gpt-4o", messages=messages, temperature=0.9)
        reply = resp['choices'][0]['message']['content']
    except Exception as e:
        log_event(f"[ERROR] OpenAI: {e}")
        reply = "⚠️ I hit a hiccup. Try again later."

    await update.message.reply_text(reply)

    if user_data[uid]['privacy']:
        user_data[uid]['history'].append({"role": "assistant","content": reply})
        user_data[uid]['history'] = user_data[uid]['history'][-MAX_HISTORY:]
        save_histories()

# =========================
# MEDIA
# =========================
async def send_media_from_feed(chat_id, uid, context):
    mode = user_data[uid].get("feed_mode", "standard")
    options = []

    if mode == "custom":
        options = custom_feed_file_ids.get(uid, [])
    elif mode == "mixed":
        options = custom_feed_file_ids.get(uid, []) + main_media_file_ids
    else:
        options = main_media_file_ids

    if not options:
        await context.bot.send_message(chat_id, "No pictures yet 😘 Upload some or unlock with /buycontent 💋")
        return

    media_file_id = random.choice(options)
    if media_file_id.startswith("photo:"):
        await context.bot.send_photo(chat_id, media_file_id.split(":")[1])
    elif media_file_id.startswith("video:"):
        await context.bot.send_video(chat_id, media_file_id.split(":")[1])
    else:
        await context.bot.send_document(chat_id, media_file_id)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    _ensure_user(uid)

    if user_data[uid]['feed_mode'] == "custom":
        if uid not in custom_feed_file_ids:
            custom_feed_file_ids[uid] = []
        if update.message.photo:
            custom_feed_file_ids[uid].append(f"photo:{update.message.photo[-1].file_id}")
            await context.bot.send_message(chat_id, "📸 Saved to your custom feed.")
        elif update.message.video:
            custom_feed_file_ids[uid].append(f"video:{update.message.video.file_id}")
            await context.bot.send_message(chat_id, "🎥 Saved to your custom feed.")
    elif is_admin(uid):
        if update.message.photo:
            main_media_file_ids.append(f"photo:{update.message.photo[-1].file_id}")
            await context.bot.send_message(chat_id, "✅ Admin photo saved.")
        elif update.message.video:
            main_media_file_ids.append(f"video:{update.message.video.file_id}")
            await context.bot.send_message(chat_id, "✅ Admin video saved.")

# =========================
# USER COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _ensure_user(str(update.effective_user.id))
    await update.message.reply_text("👋 Hey! I’m Lexi ❤️. Tell me your desires. Type /help to see more.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    _ensure_user(str(uid))
    privacy_status = "✅ Memory ON" if user_data[str(uid)]['privacy'] else "❌ Memory OFF"

    user_cmds = (
        f"Lexi Commands 💋\n\n"
        f"🔒 Privacy: {privacy_status}\n\n"
        "/privacy – Toggle memory\n"
        "/buycontent – Buy exclusive content 🛒\n"
        "/throne – Send a tribute 👑\n"
        "/customfeed – Only your uploads\n"
        "/mixedfeed – Mix your uploads + mine\n"
        "/exitfeed – Back to my content\n"
        "/sendpicture – Get a picture from your current feed\n"
    )

    admin_cmds = (
        "\n🛠 Admin Commands\n"
        "/resetmemory <user_id>\n"
        "/wipeallmemory\n"
        "/confirmwipe\n"
        "/privacyall\n"
        "/exportdata\n"
        "/viewlogs\n"
        "/allpictures\n"
        "/deletepicture <index>\n"
        "/deletepictures\n"
        "/confirmdeletepics\n"
        "/userstats\n"
        "/stopfollowupallusers\n"
        "/startfollowupallusers\n"
        "/restartbot\n"
    )

    text = user_cmds + (admin_cmds if is_admin(uid) else "")
    await update.message.reply_text(text)

async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    _ensure_user(uid)
    state = "✅ ON" if user_data[uid]['privacy'] else "❌ OFF"
    keyboard = [[
        InlineKeyboardButton("🔓 ON", callback_data="privacy_on"),
        InlineKeyboardButton("🔒 OFF", callback_data="privacy_off")
    ]]
    await update.message.reply_text(f"Privacy is {state}. Choose:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = str(query.from_user.id)
    _ensure_user(uid)
    if query.data == "privacy_on":
        user_data[uid]['privacy'] = True
        save_histories()
        await query.edit_message_text("🔓 Memory ON ✅")
    elif query.data == "privacy_off":
        user_data[uid]['privacy'] = False
        save_histories()
        await query.edit_message_text("🔒 Memory OFF ❌")

async def buycontent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🛒 Buy Content", url=BUY_LINK)]]
    await update.message.reply_text("Buy exclusive content! Upload screenshots to unlock /customfeed or /mixedfeed 💖", reply_markup=InlineKeyboardMarkup(keyboard))

async def throne(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("👑 Send Tribute", url=THRONE_LINK)]]
    await update.message.reply_text("Show me devotion 👑 Send your tribute:", reply_markup=InlineKeyboardMarkup(keyboard))

async def customfeed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data[str(update.effective_user.id)]['feed_mode'] = "custom"
    await update.message.reply_text("📸 Custom feed mode — only your uploads.")

async def mixedfeed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data[str(update.effective_user.id)]['feed_mode'] = "mixed"
    await update.message.reply_text("🎲 Mixed feed mode — your uploads + mine.")

async def exitfeed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data[str(update.effective_user.id)]['feed_mode'] = "standard"
    await update.message.reply_text("📺 Back to Lexi’s main feed ❤️.")

async def sendpicture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    _ensure_user(uid)
    await send_media_from_feed(update.effective_chat.id, uid, context)

# =========================
# ADMIN COMMANDS
# =========================
async def resetmemory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        target = context.args[0]
        if target in user_data:
            user_data[target]['history'] = []
            save_histories()
            log_event(f"[ADMIN] Reset memory for {target}")
            await update.message.reply_text(f"✅ Memory reset for {target}")
    except:
        await update.message.reply_text("Usage: /resetmemory <user_id>")

async def wipeallmemory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    pending_confirmations["wipe"] = True
    await update.message.reply_text("⚠️ Confirm wipe: type /confirmwipe within 30s.")

async def confirmwipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if pending_confirmations.get("wipe"):
        user_data.clear()
        save_histories()
        log_event("[ADMIN] Wiped all user memory.")
        await update.message.reply_text("✅ All user memory wiped.")
        pending_confirmations.pop("wipe", None)

async def allpictures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not main_media_file_ids:
        await update.message.reply_text("No media saved."); return
    message = "Saved Media:\n" + "\n".join(f"{i+1}. {fid}" for i, fid in enumerate(main_media_file_ids))
    await update.message.reply_text(message)

async def deletepicture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        idx = int(context.args[0]) - 1
        if 0 <= idx < len(main_media_file_ids):
            del main_media_file_ids[idx]
            log_event("[ADMIN] Deleted one picture.")
            await update.message.reply_text("✅ Deleted.")
        else:
            await update.message.reply_text("Invalid index.")
    except:
        await update.message.reply_text("Usage: /deletepicture <index>")

async def deletepictures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    pending_confirmations["delpics"] = True
    await update.message.reply_text("⚠️ Confirm delete all: type /confirmdeletepics within 30s.")

async def confirmdeletepics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if pending_confirmations.get("delpics"):
        main_media_file_ids.clear()
        log_event("[ADMIN] Deleted all global pictures.")
        await update.message.reply_text("✅ All global media cleared.")
        pending_confirmations.pop("delpics", None)

async def stopfollowupallusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global followups_enabled
    if not is_admin(update.effective_user.id): return
    followups_enabled = False
    log_event("[ADMIN] Follow-ups disabled globally.")
    await update.message.reply_text("🛑 All follow-up messages stopped for all users.")

async def startfollowupallusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global followups_enabled
    if not is_admin(update.effective_user.id): return
    followups_enabled = True
    log_event("[ADMIN] Follow-ups ENABLED globally.")
    await update.message.reply_text("✅ Follow-up messages re-enabled for all users.")

async def restartbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("🔄 Restarting Lexi Bot...")
    log_event("[ADMIN] Restart triggered.")
    os.execl(sys.executable, sys.executable, *sys.argv)

async def userstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    now = time.time()
    active_24h = sum(1 for u in user_data.values() if now - u['last_active'] <= 86400)
    total_users = len(user_data)
    await update.message.reply_text(f"👥 Total users: {total_users}\n🟢 Active in last 24h: {active_24h}")

# =========================
# MAIN
# =========================
def main():
    print("🚀 Starting Lexi Bot...")
    load_histories()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("privacy", privacy))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("buycontent", buycontent))
    app.add_handler(CommandHandler("throne", throne))
    app.add_handler(CommandHandler("customfeed", customfeed))
    app.add_handler(CommandHandler("mixedfeed", mixedfeed))
    app.add_handler(CommandHandler("exitfeed", exitfeed))
    app.add_handler(CommandHandler("sendpicture", sendpicture))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    # Media
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))

    # Admin
    app.add_handler(CommandHandler("resetmemory", resetmemory))
    app.add_handler(CommandHandler("wipeallmemory", wipeallmemory))
    app.add_handler(CommandHandler("confirmwipe", confirmwipe))
    app.add_handler(CommandHandler("allpictures", allpictures))
    app.add_handler(CommandHandler("deletepicture", deletepicture))
    app.add_handler(CommandHandler("deletepictures", deletepictures))
    app.add_handler(CommandHandler("confirmdeletepics", confirmdeletepics))
    app.add_handler(CommandHandler("userstats", userstats))
    app.add_handler(CommandHandler("stopfollowupallusers", stopfollowupallusers))
    app.add_handler(CommandHandler("startfollowupallusers", startfollowupallusers))
    app.add_handler(CommandHandler("restartbot", restartbot))

    print("📩 Handlers loaded...")
    loop = asyncio.get_event_loop()
    loop.create_task(followup_loop(app))
    loop.create_task(autosave_loop())
    app.run_polling()

if __name__ == "__main__":
    main()
