import os
import re
import sqlite3
import threading
import logging
import requests
import qrcode
from io import BytesIO
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ================== CONFIG ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "8612102965"))
PORT = int(os.environ.get("PORT", 10000))
BAN_API = "https://jexarcodexacstoban.vercel.app/close?access_token="
API_KEY = "ANIXH"

# States for Conversations
(ASK_TOKEN, ASK_UPI, ASK_PRICE, ASK_WELCOME, ASK_GIFT_ID, ASK_TRAILS, BCAST_TEXT) = range(7)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== STYLISH FONT ==================
def st(text: str) -> str:
    upper = {"A":"𝙰","B":"𝙱","C":"𝙲","D":"𝙳","E":"𝙴","F":"𝙵","G":"𝙶","H":"𝙷","I":"𝙸","J":"𝙹","K":"𝙺","L":"𝙻","M":"𝙼","N":"𝙽","O":"𝙾","P":"𝙿","Q":"𝚀","R":"𝚁","S":"𝚂","T":"𝚃","U":"𝚄","V":"𝚅","W":"𝚆","X":"𝚇","Y":"𝚈","Z":"𝚉"}
    lower = {"a":"𝚊","b":"𝚋","c":"𝚌","d":"𝚍","e":"𝚎","f":"𝚏","g":"𝚐","h":"𝚑","i":"𝚒","j":"𝚓","k":"𝚔","l":"𝚕","m":"𝚖","n":"𝚗","o":"𝚘","p":"𝚙","q":"𝚚","r":"𝚛","s":"𝚜","t":"𝚝","u":"𝚞","v":"𝚟","w":"𝚠","x":"𝚡","y":"𝚢","z":"𝚣"}
    digits = {"0":"𝟶","1":"𝟷","2":"𝟸","3":"𝟹","4":"𝟺","5":"𝟻","6":"𝟼","7":"𝟽","8":"𝟾","9":"𝟿"}
    out = []
    for ch in text:
        if ch in upper: out.append(upper[ch])
        elif ch in lower: out.append(lower[ch])
        elif ch in digits: out.append(digits[ch])
        else: out.append(ch)
    return "".join(out)

# ================== PORT SERVER ==================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-type', 'text/html'); self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, format, *args): pass

def run_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    server.serve_forever()

# ================== DATABASE ==================
def init_db():
    conn = sqlite3.connect("ff_ban_bot.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, is_premium INTEGER DEFAULT 0, trails INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, status TEXT, txn_id TEXT)""")
    conn.commit(); conn.close()
init_db()

def db_execute(query, params=()):
    conn = sqlite3.connect("ff_ban_bot.db")
    c = conn.cursor(); c.execute(query, params)
    conn.commit(); res = c.fetchall(); conn.close()
    return res

def get_setting(key, default=None):
    res = db_execute("SELECT value FROM settings WHERE key=?", (key,))
    return res[0][0] if res else default

def set_setting(key, value):
    db_execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))

# ================== KEYBOARDS ==================
def get_main_keyboard(user_id):
    kb = [
        [KeyboardButton(st("BAN ACCOUNT")), KeyboardButton(st("SUPPORT"))],
        [KeyboardButton(st("GET PREMIUM"))]
    ]
    if user_id == OWNER_ID:
        kb.append([KeyboardButton(st("OWNER PANEL"))])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def get_owner_keyboard():
    kb = [
        [KeyboardButton(st("SET UPI")), KeyboardButton(st("SET PRICE"))],
        [KeyboardButton(st("SET WELCOME")), KeyboardButton(st("GIFT PREMIUM"))],
        [KeyboardButton(st("SET TRAILS")), KeyboardButton(st("BROADCAST"))],
        [KeyboardButton(st("STATS")), KeyboardButton(st("MAIN MENU"))]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ================== START & MAIN MENU ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user.id,))
    
    welcome_img = get_setting("welcome_image")
    caption = f"{st('Welcome')} {user.first_name}!\n\n{st('Select an option from menu')}"
    
    if welcome_img:
        try:
            await update.message.reply_photo(photo=welcome_img, caption=caption, reply_markup=get_main_keyboard(user.id))
            return
        except: pass
    await update.message.reply_text(caption, reply_markup=get_main_keyboard(user.id))

async def main_menu_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ================== BAN ACCOUNT ==================
async def ban_account_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = db_execute("SELECT is_premium, trails FROM users WHERE user_id=?", (user_id,))[0]
    is_premium, trails = user_data
    
    if is_premium == 0 and trails <= 0:
        return await update.message.reply_text(st("You have 0 free trails left. Please buy premium."))
                                               
    if is_premium == 0:
        db_execute("UPDATE users SET trails = trails - 1 WHERE user_id=?", (user_id,))
        await update.message.reply_text(f"{st('Using 1 free trail. Trails left')}: {trails-1}")

    await update.message.reply_text(st("Enter Access Token:"))
    return ASK_TOKEN

async def process_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    await update.message.reply_text(st("Processing Ban..."))
    
    try:
        res = requests.get(f"{BAN_API}{token}&key={API_KEY}", timeout=8)
        data = res.json()
        
        if data.get("success", res.status_code == 200):
            name = data.get("name", "Unknown")
            uid = data.get("uid", "Unknown")
            level = data.get("level", "N/A")
            
            msg = f"<blockquote>ID Banned Successfully\nName: {name}\nUID: {uid}\nLevel: {level}</blockquote>"
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text("<blockquote>Ban Failed: Invalid Access Token</blockquote>", parse_mode="HTML")
    except Exception:
        await update.message.reply_text("<blockquote>Ban Failed: Invalid Access Token</blockquote>", parse_mode="HTML")
    
    return ConversationHandler.END

# ================== GET PREMIUM & CANCEL ==================
async def premium_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = get_setting("premium_price", "19")
    upi = get_setting("upi_id", "vansh111@naviaxis")
    user_id = update.effective_user.id
    
    db_execute("INSERT INTO payments (user_id, amount, status) VALUES (?,?,?)", (user_id, float(price), "PENDING"))
    
    qr_data = f"upi://pay?pa={upi}&pn=Owner&am={price}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO(); img.save(bio, format="PNG"); bio.seek(0)
    
    caption = (
        f"<b>{st('Go and Pay')} Rs {price}</b>\n"
        f"<b>{st('Payment will be auto verified.')}</b>\n\n"
        f"<blockquote>{upi}</blockquote>\n\n"
        f"{st('Waiting for payment...')}"
    )
    
    # RED CANCEL BUTTON
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(st("CANCEL PAYMENT"), callback_data="cancel_payment", style="danger")]])
    
    await update.message.reply_photo(photo=InputFile(bio, filename="qr.png"), caption=caption, reply_markup=kb, parse_mode="HTML")

async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_caption(caption=st("Payment Cancelled."), reply_markup=None)

# ================== OWNER PANEL KEYBOARD ==================
async def owner_panel_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(st("Owner Panel"), reply_markup=get_owner_keyboard())

async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = db_execute("SELECT COUNT(*) FROM users")[0][0]
    prem = db_execute("SELECT COUNT(*) FROM users WHERE is_premium=1")[0][0]
    await update.message.reply_text(f"{st('Total Users')}: {total}\n{st('Premium Users')}: {prem}")

# Owner Setup Flows
async def ask_upi(update, context):
    await update.message.reply_text(st("Send new UPI ID:")); return ASK_UPI
async def save_upi(update, context):
    set_setting("upi_id", update.message.text); await update.message.reply_text(st("UPI Updated!"), reply_markup=get_owner_keyboard()); return ConversationHandler.END

async def ask_price(update, context):
    await update.message.reply_text(st("Send new Premium Price:")); return ASK_PRICE
async def save_price(update, context):
    set_setting("premium_price", update.message.text); await update.message.reply_text(st("Price Updated!"), reply_markup=get_owner_keyboard()); return ConversationHandler.END

async def ask_welcome(update, context):
    await update.message.reply_text(st("Send Welcome Image:")); return ASK_WELCOME
async def save_welcome(update, context):
    if update.message.photo:
        set_setting("welcome_image", update.message.photo[-1].file_id)
        await update.message.reply_text(st("Image Set!"), reply_markup=get_owner_keyboard())
    return ConversationHandler.END

async def ask_gift(update, context):
    await update.message.reply_text(st("Send User ID to gift premium:")); return ASK_GIFT_ID
async def save_gift(update, context):
    uid = update.message.text
    db_execute("UPDATE users SET is_premium=1 WHERE user_id=?", (uid,))
    await update.message.reply_text(f"{st('Gifted premium to')} {uid}", reply_markup=get_owner_keyboard())
    try: await context.bot.send_message(chat_id=uid, text=st("Admin gifted you Premium!"))
    except: pass
    return ConversationHandler.END

async def ask_trails(update, context):
    await update.message.reply_text(st("Send number of free trails (e.g. 1, 0):")); return ASK_TRAILS
async def save_trails(update, context):
    trails = update.message.text
    db_execute("UPDATE users SET trails=?", (trails,))
    await update.message.reply_text(f"{st('All users set to')} {trails} {st('trails.')}", reply_markup=get_owner_keyboard())
    return ConversationHandler.END

async def ask_bcast(update, context):
    await update.message.reply_text(st("Send message/photo to broadcast:")); return BCAST_TEXT
async def do_bcast(update, context):
    users = db_execute("SELECT user_id FROM users")
    success = 0
    for u in users:
        try:
            if update.message.photo:
                await context.bot.send_photo(chat_id=u[0], photo=update.message.photo[-1].file_id, caption=update.message.caption or "")
            else:
                await context.bot.send_message(chat_id=u[0], text=update.message.text)
            success += 1
        except: pass
    await update.message.reply_text(f"{st('Broadcast sent to')} {success} {st('users.')}", reply_markup=get_owner_keyboard())
    return ConversationHandler.END

# ================== SMS AUTO-VERIFY ==================
async def group_sms_reader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text: return
    
    amt_match = re.search(r'(?:Rs\.?|INR)\s*([0-9]+(?:\.[0-9]{1,2})?)', text)
    txn_match = re.search(r'Txn ID:\s*([A-Za-z0-9]+)', text)
    
    if amt_match and txn_match:
        amount = float(amt_match.group(1))
        txn_id = txn_match.group(1)
        pending = db_execute("SELECT id, user_id FROM payments WHERE status='PENDING' AND ABS(amount - ?) < 0.01", (amount,))
        
        if pending:
            p_id, u_id = pending[0]
            db_execute("UPDATE payments SET status='VERIFIED', txn_id=? WHERE id=?", (txn_id, p_id))
            db_execute("UPDATE users SET is_premium=1 WHERE user_id=?", (u_id,))
            try:
                await context.bot.send_message(chat_id=u_id, text=f"<b>{st('Payment Verified! Now you are a premium user, get unlimited access now.')}</b>", parse_mode="HTML")
            except: pass
            await update.message.reply_text(f"Payment {amount} verified for user {u_id}.")

# ================== MAIN ==================
def main():
    threading.Thread(target=run_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    ban_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{st('BAN ACCOUNT')}$"), ban_account_btn)],
        states={ASK_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_token)]}, fallbacks=[]
    )

    owner_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{st('SET UPI')}$"), ask_upi),
            MessageHandler(filters.Regex(f"^{st('SET PRICE')}$"), ask_price),
            MessageHandler(filters.Regex(f"^{st('SET WELCOME')}$"), ask_welcome),
            MessageHandler(filters.Regex(f"^{st('GIFT PREMIUM')}$"), ask_gift),
            MessageHandler(filters.Regex(f"^{st('SET TRAILS')}$"), ask_trails),
            MessageHandler(filters.Regex(f"^{st('BROADCAST')}$"), ask_bcast),
        ],
        states={
            ASK_UPI: [MessageHandler(filters.TEXT, save_upi)],
            ASK_PRICE: [MessageHandler(filters.TEXT, save_price)],
            ASK_WELCOME: [MessageHandler(filters.PHOTO, save_welcome)],
            ASK_GIFT_ID: [MessageHandler(filters.TEXT, save_gift)],
            ASK_TRAILS: [MessageHandler(filters.TEXT, save_trails)],
            BCAST_TEXT: [MessageHandler(filters.ALL, do_bcast)],
        }, fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(ban_conv)
    app.add_handler(owner_conv)
    app.add_handler(MessageHandler(filters.Regex(f"^{st('GET PREMIUM')}$"), premium_btn))
    app.add_handler(MessageHandler(filters.Regex(f"^{st('OWNER PANEL')}$"), owner_panel_btn))
    app.add_handler(MessageHandler(filters.Regex(f"^{st('STATS')}$"), owner_stats))
    app.add_handler(MessageHandler(filters.Regex(f"^{st('MAIN MENU')}$"), main_menu_btn))
    app.add_handler(CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$"))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_sms_reader))

    logger.info("FF Ban Bot Started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
