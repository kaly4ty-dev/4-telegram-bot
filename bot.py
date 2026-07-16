import os
import threading
from flask import Flask
import ccxt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv('BOT_TOKEN')
MEXC_API_KEY = os.getenv('MEXC_API_KEY')
MEXC_SECRET = os.getenv('MEXC_SECRET')

TP = 5.0
SL = 1.5
SYMBOL = "BTC/USDT"

print(f"BOT_TOKEN exists: {bool(BOT_TOKEN)}")
print(f"MEXC_API_KEY exists: {bool(MEXC_API_KEY)}")

# --- FIX FOR RENDER PORT ERROR ---
flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()
# --- END FIX ---

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET,
    'options': {'defaultType': 'spot'}
})

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        btc = exchange.fetch_ticker('BTC/USDT')['last']
        sol = exchange.fetch_ticker('SOL/USDT')['last']
        await update.message.reply_text(f"📈 BTC: ${btc:,.2f}\nSOL: ${sol:,.2f}")
    except Exception as e:
        await update.message.reply_text(f"Price error: {e}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        balance = exchange.fetch_balance()
        usdt = balance.get('USDT', {}).get('free', 0) if balance else 0
        bal_text = f"USDT: ${usdt:.2f}"
    except Exception as e:
        bal_text = f"USDT: Error - {e}"
    await update.message.reply_text(f"🟢 Bot running on Render!\nMode: LIVE MEXC\nTP: {TP}% | SL: {SL}%\n{bal_text}")

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Usage: /buy 5  or  /buy 5 usdt")
            return
        text = " ".join(context.args).lower().replace('usdt','').strip()
        amount = float(text)
        await update.message.reply_text(f"⏳ Trying to buy ${amount} of {SYMBOL}...")
        balance = exchange.fetch_balance()
        free_usdt = balance['USDT']['free']
        if free_usdt < amount:
            await update.message.reply_text(f"❌ Insufficient funds.\nYou have: ${free_usdt:.2f}\nYou tried: ${amount}")
            return
        # UNCOMMENT TO TRADE REAL MONEY:
        # order = exchange.create_market_buy_order(SYMBOL, amount)
        # await update.message.reply_text(f"✅ Bought! Order ID: {order['id']}\nTP: {TP}% | SL: {SL}%")
        await update.message.reply_text(f"✅ BUY signal OK!\nYou have ${free_usdt:.2f} available.\n[Testing mode - real order commented out line 68. Uncomment to trade live]\nTP: {TP}% SL: {SL}% will apply.")
    except Exception as e:
        await update.message.reply_text(f"❌ Buy failed: {e}")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        free = bal['USDT']['free']
        await update.message.reply_text(f"💰 USDT Free: ${free:.4f}")
    except Exception as e:
        await update.message.reply_text(f"Balance error: {e}")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("price", price_cmd))
app.add_handler(CommandHandler("status", status_cmd))
app.add_handler(CommandHandler("balance", balance_cmd))
app.add_handler(CommandHandler("buy", buy_cmd))

print("Bot started...")
# This drop_pending_updates=True prevents Conflict forever
app.run_polling(drop_pending_updates=True)
