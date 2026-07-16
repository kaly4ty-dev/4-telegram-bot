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
        bal = exchange.fetch_balance()
        free = 0
        if 'USDT' in bal and isinstance(bal['USDT'], dict):
            free = bal['USDT'].get('free', 0) or 0
        if free == 0 and 'free' in bal:
            free = bal['free'].get('USDT', 0) or 0
        if free == 0 and 'total' in bal:
            free = bal['total'].get('USDT', 0) or 0
        await update.message.reply_text(f"🟢 Bot running on Render!\nMode: LIVE MEXC\nTP: {TP}% | SL: {SL}%\nUSDT Free: ${free:.4f}")
    except Exception as e:
        await update.message.reply_text(f"🟢 Bot running! Balance check: {e}")

async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Usage: /buy 5  or  /buy 5 usdt")
            return
        text = " ".join(context.args).lower().replace('usdt','').strip()
        amount = float(text)
        
        bal = exchange.fetch_balance()
        free_usdt = 0
        if 'USDT' in bal and isinstance(bal['USDT'], dict):
            free_usdt = bal['USDT'].get('free', 0) or 0
        if free_usdt == 0 and 'free' in bal:
            free_usdt = bal['free'].get('USDT', 0) or 0
            
        if free_usdt < amount:
            await update.message.reply_text(f"❌ Insufficient funds.\nYou have: ${free_usdt:.2f}\nYou tried: ${amount}")
            return
            
        await update.message.reply_text(f"⏳ Buying ${amount} of {SYMBOL}...")
         UNCOMMENT NEXT 2 LINES TO TRADE REAL MONEY:
         order = exchange.create_market_buy_order(SYMBOL, amount)
         await update.message.reply_text(f"✅ Bought! Order ID: {order['id']}\nTP: {TP}% | SL: {SL}%")
        
        await update.message.reply_text(f"✅ BUY signal OK (Test Mode)!\nYou have ${free_usdt:.2f} available.\nUncomment lines 62-63 to trade live.\nTP: {TP}% SL: {SL}% will apply.")
    except Exception as e:
        await update.message.reply_text(f"❌ Buy failed: {e}")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        free = 0
        if 'USDT' in bal and isinstance(bal['USDT'], dict):
            free = bal['USDT'].get('free', 0) or 0
        if free == 0 and 'free' in bal:
            free = bal['free'].get('USDT', 0) or 0
        if free == 0 and 'total' in bal:
            free = bal['total'].get('USDT', 0) or 0
        
        await update.message.reply_text(f"💰 USDT Free: ${free:.4f}")
    except Exception as e:
        await update.message.reply_text(f"Balance error: {e}\nRaw keys: {str(e)[:100]}")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("price", price_cmd))
app.add_handler(CommandHandler("status", status_cmd))
app.add_handler(CommandHandler("balance", balance_cmd))
app.add_handler(CommandHandler("buy", buy_cmd))

print("Bot started with TRADING logic...")
app.run_polling(drop_pending_updates=True)
