import os, logging, ccxt, threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def get_env(*names):
    for n in names:
        v=os.getenv(n)
        if v:
            v=v.strip().strip('"').strip("'").replace(" ","").replace("\n","")
            if v:
                logger.info(f"FOUND {n} len={len(v)}")
                return v
    logger.error(f"MISSING {names}")
    return None

TELEGRAM_TOKEN=get_env('TELEGRAM_BOT_TOKEN','TELEGRAM_TOKEN','BOT_TOKEN')
MEXC_API_KEY=get_env('MEXC_API_KEY','MEXC_KEY')
MEXC_API_SECRET=get_env('MEXC_API_SECRET','MEXC_SECRET','MEXC_SECRET_KEY')

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN missing in Render!")
if ":" not in TELEGRAM_TOKEN:
    raise ValueError("Token invalid - no ':'")

exchange=None
if MEXC_API_KEY and MEXC_API_SECRET:
    try:
        exchange=ccxt.mexc({'apiKey':MEXC_API_KEY,'secret':MEXC_API_SECRET})
        logger.info("MEXC OK")
    except Exception as e:
        logger.error(f"MEXC init fail: {e}")

# --- FAKE WEB SERVER FOR RENDER ---
web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Bot is running! Telegram bot is alive."

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()
# -----------------------------------

async def start(update, context):
    await update.message.reply_text("Bot ONLINE! /balance /status")

async def balance_cmd(update, context):
    if not exchange:
        await update.message.reply_text("MEXC keys missing! Add MEXC_API_KEY + MEXC_API_SECRET in Render")
        return
    try:
        bal=exchange.fetch_balance()
        msg="Wallet:\n"
        for c in ['USDT','BTC','PEPE','SHIB','DOGE','BONK','WIF']:
            if c in bal and bal[c].get('free',0)>0:
                msg+=f"{c}: {bal[c]['free']}\n"
        await update.message.reply_text(msg if len(msg)>10 else "Wallet empty or no free balance")
    except Exception as e:
        logger.error(f"Balance error: {e}")
        await update.message.reply_text(f"Error: {e}")

async def status_cmd(update, context):
    await update.message.reply_text("No active trades - normal after deploy. Use /balance")

logger.info("Starting bot polling...")
app=Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start",start))
app.add_handler(CommandHandler("balance",balance_cmd))
app.add_handler(CommandHandler("status",status_cmd))
app.add_handler(CommandHandler("help",start))
app.add_handler(CommandHandler("sell",balance_cmd))

app.run_polling()
