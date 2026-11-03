import os
import re
import sqlite3
import threading
import logging
import random
import qrcode
from io import BytesIO
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ================== CONFIG ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "8612102965"))
PORT = int(os.environ.get("PORT", 10000))
BAN_API = "https://jexarcodexacstoban.vercel.app/close?access_token="
API_KEY = "ANIXH"

# States
(ASK_TOKEN, ASK_UPI, ASK_PRICE, ASK_WELCOME, ASK_GIFT_ID, ASK_TRAILS, BCAST_TEXT) = range(7)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

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

# ================== MAIN MENU (Reply Keyboard) ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user.id,))
    
    welcome_img = get_setting("welcome_image")
    caption = f"Welcome {user.first_name}!\n\nSelect an option from the menu below."
    
    kb = [
        [KeyboardButton("BAN ACCOUNT"), KeyboardButton("SUPPORT")],
        [KeyboardButton("GET PREMIUM")]
    ]
    if user.id == OWNER_ID:
        kb.append([KeyboardButton("OWNER PANEL")])
    
    reply_markup = ReplyKeyboardMarkup(kb, resize_keyboard=True)
    
    if welcome_img:
        try:
            await update.message.reply_photo(photo=welcome_img, caption=caption, reply_markup=reply_markup)
            return
        except: pass
    await update.message.reply_text(caption, reply_markup=reply_markup)

# ================== BAN ACCOUNT (Inline Buttons) ==================
async def ban_account_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = db_execute("SELECT is_premium, trails FROM users WHERE user_id=?", (user_id,))[0]
    is_premium, trails = user_data
    
    if is_premium == 0 and trails <= 0:
        return await update.message.reply_text("You have 0 free trails left. Please buy premium.", 
                                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("GET PREMIUM", callback_data="premium", style="success")]]))
                                               
    if is_premium == 0:
        db_execute("UPDATE users SET trails = trails - 1 WHERE user_id=?", (user_id,))
        await update.message.reply_text(f"Using 1 free trail. Trails left: {trails-1}")

    await update.message.reply_text("Enter Access Token:")
    return ASK_TOKEN

async def process_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    await update.message.reply_text("Processing Ban...")
    
    import requests
    try:
        res = requests.get(f"{BAN_API}{token}&key={API_KEY}")
        data = res.json()
        
        if data.get("success", res.status_code == 200):
            name = data.get("name", "Unknown")
            uid = data.get("uid", "Unknown")
            await update.message.reply_text(f"✅ Account Banned Successfully!\n\nName: {name}\nUID: {uid}")
        else:
            await update.message.reply_text("❌ Ban failed. Invalid token.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
    
    return ConversationHandler.END

# ================== GET PREMIUM ==================
async def premium_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = get_setting("premium_price", "19")
    upi = get_setting("upi_id", "vansh111@naviaxis")
    
    # Unique amount generation (e.g. 19.45)
    random_paise = random.randint(1, 99)
    unique_amount = float(price) + (random_paise / 100.0)
    
    user_id = update.effective_user.id
    db_execute("INSERT INTO payments (user_id, amount, status) VALUES (?,?,?)", (user_id, unique_amount, "PENDING"))
    
    qr_data = f"upi://pay?pa={upi}&pn=Owner&am={unique_amount}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO(); img.save(bio, format="PNG"); bio.seek(0)
    
    caption = (
        f"<b>Go and Pay Rs {unique_amount:.2f}</b>\n"
        f"<b>Payment will be auto verified.</b>\n\n"
        f"<blockquote>{upi}</blockquote>\n\n"
        f"Waiting for payment..."
    )
    
    await update.message.reply_photo(photo=InputFile(bio, filename="qr.png"), caption=caption, parse_mode="HTML")
    await update.message.reply_text("Please send the exact amount. Once paid, admin will verify shortly.")

# ================== PAYMENT VERIFY (Group Reader) ==================
async def group_sms_reader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text: return
    
    # Match format: credited with Rs.XX.XX. Txn ID: YYYY
    amt_match = re.search(r'(?:Rs\.?|INR)\s*([0-9]+\.[0-9]{2})', text)
    txn_match = re.search(r'Txn ID:\s*([A-Za-z0-9]+)', text)
    
    if amt_match and txn_match:
        amount = float(amt_match.group(1))
        txn_id = txn_match.group(1)
        
        # Find matching pending payment
        pending = db_execute("SELECT id, user_id FROM payments WHERE status='PENDING' AND ABS(amount - ?) < 0.01", (amount,))
        
        if pending:
            p_id, u_id = pending[0]
            db_execute("UPDATE payments SET status='VERIFIED', txn_id=? WHERE id=?", (txn_id, p_id))
            db_execute("UPDATE users SET is_premium=1 WHERE user_id=?", (u_id,))
            
            try:
                await context.bot.send_message(chat_id=u_id, text="✅ <b>Payment Verified! Now you are a premium user, get unlimited access now.</b>", parse_mode="HTML")
            except: pass
            
            await update.message.reply_text(f"Payment {amount} verified for user {u_id}.")

# ================== OWNER PANEL ==================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    kb = [
        [InlineKeyboardButton("Total Users", callback_data="stats", style="primary"), InlineKeyboardButton("Payments", callback_data="paystats", style="primary")],
        [InlineKeyboardButton("Set UPI ID", callback_data="set_upi", style="primary"), InlineKeyboardButton("Set Price", callback_data="set_price", style="primary")],
        [InlineKeyboardButton("Set Welcome Image", callback_data="set_welcome", style="primary")],
        [InlineKeyboardButton("Gift Premium", callback_data="gift_prem", style="success")],
        [InlineKeyboardButton("Broadcast", callback_data="broadcast", style="danger")],
        [InlineKeyboardButton("Set Trails", callback_data="set_trails", style="danger")]
    ]
    await update.message.reply_text("<b>OWNER PANEL</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def owner_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    
    if data == "stats":
        total = db_execute("SELECT COUNT(*) FROM users")[0][0]
        prem = db_execute("SELECT COUNT(*) FROM users WHERE is_premium=1")[0][0]
        await query.message.reply_text(f"Total Users: {total}\nPremium Users: {prem}")
    elif data == "paystats":
        pays = db_execute("SELECT amount, user_id, txn_id FROM payments WHERE status='VERIFIED'")
        if not pays: return await query.message.reply_text("No payments yet.")
        text = "Verified Payments:\n"
        for p in pays: text += f"₹{p[0]} | User {p[1]} | Txn: {p[2]}\n"
        await query.message.reply_text(text)
    elif data == "set_upi":
        await query.message.reply_text("Send new UPI ID:")
        return ASK_UPI
    elif data == "set_price":
        await query.message.reply_text("Send new Premium Price (numbers only):")
        return ASK_PRICE
    elif data == "set_welcome":
        await query.message.reply_text("Send Welcome Image:")
        return ASK_WELCOME
    elif data == "gift_prem":
        await query.message.reply_text("Send User ID to gift premium:")
        return ASK_GIFT_ID
    elif data == "set_trails":
        await query.message.reply_text("Send number of free trails (e.g. 1, 2, 0):")
        return ASK_TRAILS
    elif data == "broadcast":
        await query.message.reply_text("Send the message/photo to broadcast:")
        return BCAST_TEXT

async def save_upi(update, context):
    set_setting("upi_id", update.message.text)
    await update.message.reply_text("UPI Updated!")
    return ConversationHandler.END

async def save_price(update, context):
    set_setting("premium_price", update.message.text)
    await update.message.reply_text("Price Updated!")
    return ConversationHandler.END

async def save_welcome(update, context):
    if update.message.photo:
        set_setting("welcome_image", update.message.photo[-1].file_id)
        await update.message.reply_text("Welcome Image Set!")
    return ConversationHandler.END

async def save_gift(update, context):
    uid = update.message.text
    db_execute("UPDATE users SET is_premium=1 WHERE user_id=?", (uid,))
    await update.message.reply_text(f"User {uid} gifted premium!")
    try: await context.bot.send_message(chat_id=uid, text="🎁 Admin gifted you Premium Access!")
    except: pass
    return ConversationHandler.END

async def save_trails(update, context):
    trails = update.message.text
    db_execute("UPDATE users SET trails=?", (trails,))
    await update.message.reply_text(f"All users set to {trails} trails.")
    return ConversationHandler.END

async def do_broadcast(update, context):
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
    await update.message.reply_text(f"Broadcast sent to {success} users.")
    return ConversationHandler.END

# ================== MAIN ==================
def main():
    threading.Thread(target=run_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation for Ban
    ban_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^BAN ACCOUNT$"), ban_account_btn)],
        states={ASK_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_token)]},
        fallbacks=[]
    )

    # Owner States
    owner_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(owner_callbacks)],
        states={
            ASK_UPI: [MessageHandler(filters.TEXT, save_upi)],
            ASK_PRICE: [MessageHandler(filters.TEXT, save_price)],
            ASK_WELCOME: [MessageHandler(filters.PHOTO, save_welcome)],
            ASK_GIFT_ID: [MessageHandler(filters.TEXT, save_gift)],
            ASK_TRAILS: [MessageHandler(filters.TEXT, save_trails)],
            BCAST_TEXT: [MessageHandler(filters.ALL, do_broadcast)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(ban_conv)
    app.add_handler(owner_conv)
    app.add_handler(MessageHandler(filters.Regex("^GET PREMIUM$"), premium_btn))
    app.add_handler(MessageHandler(filters.Regex("^OWNER PANEL$"), owner_panel))
    
    # Payment reader (bot must be in group)
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_sms_reader))

    logger.info("FF Ban Bot Started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
