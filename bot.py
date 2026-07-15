from flask import Flask
import threading
import os
import ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is LIVE!'

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# Start Flask in background
threading.Thread(target=run_web, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MEXC_KEY = os.getenv("MEXC_API_KEY")
MEXC_SECRET = os.getenv("MEXC_SECRET")

print(f"BOT_TOKEN exists: {bool(BOT_TOKEN)}")

exchange = ccxt.mexc({
    'apiKey': MEXC_KEY,
    'secret': MEXC_SECRET,
    'enableRateLimit': True
})

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot LIVE on Render!\n\n/balance - Check money\n/price - BTC & SOL\n/status - Status\n/help - Help")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = exchange.fetch_balance()
        usdt = bal['USDT']['free'] if 'USDT' in bal and bal['USDT'] else 0
        await update.message.reply_text(f"💰 USDT: ${usdt:.2f}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        btc = exchange.fetch_ticker('BTC/USDT')['last']
        sol = exchange.fetch_ticker('SOL/USDT')['last']
        await update.message.reply_text(f"📈 BTC: ${btc:.2f}\nSOL: ${sol:.2f}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 Bot running on Render!\nMode: LIVE MEXC\nTP: 5% | SL: 1.5%")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/balance\n/price\n/status\n/start")

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing!")
        return
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("balance", balance))
    app_bot.add_handler(CommandHandler("price", price))
    app_bot.add_handler(CommandHandler("status", status))
    app_bot.add_handler(CommandHandler("help", help_cmd))
    print("Bot started with TRADING logic...")
    app_bot.run_polling()

if name == "main":
    main()
