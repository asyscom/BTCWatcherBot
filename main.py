
import os
import io
import time
import asyncio
import logging
import requests
import threading
import hashlib
import binascii
import numpy as np
import matplotlib.pyplot as plt
import pytz
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

# Librerie per Bitcoin e BIP32
from bit import Key
from bip32 import BIP32
from bip32utils import BIP32Key
from bip32utils import BIP32Key  # Presumibilmente necessario per operazioni BIP32
from bip_utils import Bip84, Bip84Coins, Bip32KeyIndex
from Crypto.Hash import RIPEMD160, SHA256

# Librerie per Bech32 e Base58
import bech32
import base58

# Librerie per Telegram Bot
from telegram import (
    Update, 
    Bot, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    CallbackQuery
)
from telegram.ext import (
    Updater, 
    CommandHandler, 
    CallbackContext, 
    CallbackQueryHandler, 
    ConversationHandler, 
    MessageHandler, 
    Filters,
    ContextTypes
)


# Bot Token
BOT_TOKEN = 'yout-telegram-bot-api-key'
# Variabile globale per monitoraggio whales
whale_monitoring = {}
load_dotenv()
# Variabile globale per memorizzare gli alert di prezzo
price_alerts = {}

# Variabili globali
daily_report_enabled = False
scheduler = BackgroundScheduler()

# Variabile per tracciare lo stato del report
daily_report_enabled = False


logging.basicConfig(level=logging.INFO)

#DATABASE#
import sqlite3

# Connessione al database SQLite
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
cursor = conn.cursor()

# Crea le tabelle se non esistono
cursor.execute('''
CREATE TABLE IF NOT EXISTS whale_monitoring (
    chat_id INTEGER PRIMARY KEY,
    threshold INTEGER
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS tracked_transactions (
    chat_id INTEGER,
    txid TEXT,
    PRIMARY KEY (chat_id, txid)
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS block_monitoring (
    chat_id INTEGER PRIMARY KEY
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS price_alerts (
    chat_id INTEGER PRIMARY KEY,
    threshold REAL
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS fee_alerts (
    chat_id INTEGER PRIMARY KEY,
    threshold INTEGER
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS daily_report (
    chat_id INTEGER PRIMARY KEY,
    enabled INTEGER
)
''')

conn.commit()


def monitor_whales_thread(bot, chat_id, threshold):
    url = 'https://mempool.space/api/mempool/recent'
    seen_txids = set()
    while True:
        response = requests.get(url)
        if response.status_code == 200:
            transactions = response.json()
            for tx in transactions:
                amount = tx['value'] / 1e8
                txid = tx['txid']
                if amount >= threshold and txid not in seen_txids:
                    seen_txids.add(txid)
                    message = f"🐋 *Large BTC Transaction Detected!*\n\n💼 Amount: {amount:.2f} BTC\n🔗 [View Transaction](https://mempool.space/tx/{txid})"
                    bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        time.sleep(300)  # Controlla ogni 5 minuti

def check_transaction_status(bot, chat_id, txid):
    url = f'https://blockstream.info/api/tx/{txid}'
    while True:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['status']['confirmed']:
                bot.send_message(chat_id=chat_id, text=f"✅ *Transaction Confirmed!*\n\n🆔 TXID: {txid}")
                break
        time.sleep(60)  # Controlla ogni 60 secondi


def check_price_alerts(bot):
    import sqlite3
    from datetime import datetime
    import time

    # Crea una nuova connessione e un nuovo cursore per questo thread
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()

    while True:
        usd_price, _ = get_price()
        if usd_price:
            cursor.execute('SELECT chat_id, threshold FROM price_alerts')
            alerts = cursor.fetchall()

            for chat_id, threshold in alerts:
                if usd_price >= threshold:
                    bot.send_message(chat_id=chat_id, text=f"🚨 *Price Alert!* Bitcoin has reached ${usd_price}")
                    cursor.execute('DELETE FROM price_alerts WHERE chat_id = ?', (chat_id,))
                    conn.commit()
        time.sleep(60)

    # Chiude la connessione al termine del thread
    conn.close()



def check_fee_alerts(bot, chat_id, threshold):
    import sqlite3
    from datetime import datetime
    import time

    # Crea una nuova connessione e un nuovo cursore per questo thread
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()

    while True:
        fees_data = get_fees()
        if fees_data and fees_data['fastest'] <= threshold:
            bot.send_message(chat_id=chat_id, text=f"🚨 *Fee Alert!* Fastest fee is now {fees_data['fastest']} sat/vB")
            cursor.execute('DELETE FROM fee_alerts WHERE chat_id = ?', (chat_id,))
            conn.commit()
            break  # Termina il thread dopo aver inviato l'alert
        time.sleep(60)

    # Chiude la connessione al termine del thread
    conn.close()


# Function to monitor new blocks (notifica un solo blocco e si ferma)

def monitor_new_blocks(bot, chat_id):
    print(f"DEBUG: bot={bot}, chat_id={chat_id}, type(bot)={type(bot)}, type(chat_id)={type(chat_id)}")

    current_height = get_latest_block_height()
    if current_height is None:
        bot.send_message(chat_id=chat_id, text="❌ Error fetching the latest block height.")
        return

    bot.send_message(chat_id=chat_id, text=f"🚀 Monitoring the next block. Current height: {current_height}")

    while True:
        latest_height = get_latest_block_height()
        if latest_height and latest_height > current_height:
            message = f"🔗 *New Block Mined!*\n\n" \
                      f"🆙 Block Height: {latest_height}\n" \
                      f"🔍 [View Block](https://blockstream.info/block-height/{latest_height})"
            bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            break
        time.sleep(60)


def load_data(updater):
    # Registra il tempo di avvio del bot
    bot_start_time = datetime.now()

    # Carica e ripristina i Fee Alerts validi
    cursor.execute('SELECT chat_id, threshold, timestamp FROM fee_alerts')
    for chat_id, threshold, timestamp in cursor.fetchall():
        threading.Thread(target=check_fee_alerts, args=(updater.bot, chat_id, threshold), daemon=True).start()
    conn.commit()
    # Carica e ripristina i Price Alerts validi
    cursor.execute('SELECT chat_id, threshold, timestamp FROM price_alerts')
    for chat_id, threshold, timestamp in cursor.fetchall():
        threading.Thread(target=check_price_alerts, args=(updater.bot,), daemon=True).start()
    conn.commit()

    # Carica e ripristina il Whale Monitoring valido
    cursor.execute('SELECT chat_id, threshold, timestamp FROM whale_monitoring')
    for chat_id, threshold, timestamp in cursor.fetchall():
        threading.Thread(target=monitor_whales_thread, args=(updater.bot, chat_id, threshold), daemon=True).start()
    conn.commit()

    # Carica e ripristina le Tracked Transactions valide
    cursor.execute('SELECT chat_id, txid, timestamp FROM tracked_transactions')
    for chat_id, txid, timestamp in cursor.fetchall():
        threading.Thread(target=check_transaction_status, args=(updater.bot, chat_id, txid), daemon=True).start()
    conn.commit()

    # Carica e ripristina il Block Monitoring valido
    cursor.execute('SELECT chat_id, timestamp FROM block_monitoring')
    for chat_id, timestamp in cursor.fetchall():
        threading.Thread(target=monitor_new_blocks, args=(updater.bot, chat_id), daemon=True).start()
    conn.commit()

    # Carica e ripristina i Daily Reports validi
    cursor.execute('SELECT chat_id, timestamp FROM daily_report WHERE enabled = 1')
    for chat_id, timestamp in cursor.fetchall():
        scheduler.add_job(
            lambda chat_id=chat_id: asyncio.run(send_daily_report(updater.bot, chat_id)),
            'cron',
            hour=23,
            minute=59,
            timezone=pytz.timezone('Europe/Rome'),
            id=f'daily_report_{chat_id}'
        )
    conn.commit()


def get_btc_dominance():
    API_URL = "https://api.coingecko.com/api/v3/global"
    response = requests.get(API_URL)
    if response.status_code == 200:
        data = response.json()
        return data["data"]["market_cap_percentage"].get("btc", "N/A")
    return "N/A"



def get_btc_stats():
    # Endpoint per ottenere i dati del grafico di mercato (prezzi e volumi)
    MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=1"
    # Endpoint per ottenere i dati globali del mercato (dominanza)
    GLOBAL_DATA_URL = "https://api.coingecko.com/api/v3/global"

    # Richiesta per ottenere prezzi e volumi
    response_market_chart = requests.get(MARKET_CHART_URL)
    # Richiesta per ottenere la dominanza di Bitcoin
    response_global_data = requests.get(GLOBAL_DATA_URL)

    if response_market_chart.status_code == 200 and response_global_data.status_code == 200:
        data = response_market_chart.json()
        global_data = response_global_data.json()

        prices = data.get("prices", [])
        volumes = data.get("total_volumes", [])

        if prices and volumes:
            open_price = prices[0][1]  # Prezzo di apertura
            close_price = prices[-1][1]  # Prezzo di chiusura
            current_price = prices[-1][1]  # Prezzo corrente
            high_price = max(price[1] for price in prices)  # Prezzo massimo
            low_price = min(price[1] for price in prices)  # Prezzo minimo
            volume_24h = volumes[-1][1]  # Volume 24 ore

            # Ottenere la dominanza di Bitcoin
            dominance = global_data["data"]["market_cap_percentage"].get("btc", "N/A")

            # Calcolare la media dei prezzi delle ultime 24 ore
            price_7d_avg = sum(price[1] for price in prices) / len(prices)

            # Restituire 9 valori
            return open_price, close_price, current_price, high_price, low_price, volume_24h, dominance, price_7d_avg

    # Restituire valori di default se qualcosa va storto
    return None, None, None, None, None, None, None, None, None




async def send_daily_report(bot: Bot, chat_id: int):
    logging.info("send_daily_report has been called")
    
    # Ottieni le statistiche estese
    open_price, close_price, current_price, high_price, low_price, volume_24h, dominance, price_7d_avg = get_btc_stats()
    
    # Funzione per formattare i valori numerici con due decimali
    def format_value(value, prefix="$"):
        try:
            return f"{prefix}{float(value):,.2f}"
        except (TypeError, ValueError):
            return "N/A"
    
    # Calcola la variazione di prezzo e la variazione percentuale
    if open_price is not None and close_price is not None:
        price_change = close_price - open_price
        price_change_percent = (price_change / open_price) * 100
        trend = "📈 *Bullish*" if price_change > 0 else "📉 *Bearish*"
    else:
        price_change = None
        price_change_percent = None
        trend = "❓ *Trend Unknown*"

    # Crea il messaggio con tutte le informazioni
    message = f"📊 *Daily Bitcoin Report*\n\n" \
              f"🕗 *Opening Price*: {format_value(open_price)}\n" \
              f"🕔 *Closing Price*: {format_value(close_price)}\n" \
              f"💵 *Current Price*: {format_value(current_price)}\n" \
              f"📈 *High Price*: {format_value(high_price)}\n" \
              f"📉 *Low Price*: {format_value(low_price)}\n" \
              f"🔄 *Change*: {format_value(price_change)} ({price_change_percent:.2f}% if price_change_percent is not None else 'N/A')\n" \
              f"📊 *24h Volume*: {format_value(volume_24h)}\n" \
              f"💰 *Market Cap*: {format_value(market_cap)}\n" \
              f"🌐 *Dominance*: {format_value(dominance, prefix='')}%\n" \
              f"📈 *7-Day Avg Price*: {format_value(price_7d_avg)}\n" \
              f"{trend}\n\n" \
              f"📅 *Data collected at*: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    # Invia il messaggio su Telegram
    await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')


# Funzione per eseguire il job manualmente
def run_job_manually(job_id):
    job = scheduler.get_job(job_id)
    if job:
        threading.Thread(target=asyncio.run, args=(job.func(),)).start()
    else:
        print(f"No job found with ID '{job_id}'")

# Funzione per attivare il daily report


def daily_report_on(update: Update, context: CallbackContext):
    global daily_report_enabled, chat_id
    daily_report_enabled = True
    chat_id = update.effective_chat.id

    scheduler.remove_all_jobs()

    # Wrapper per eseguire la coroutine con asyncio.run
    def send_daily_report_wrapper():
        asyncio.run(send_daily_report(context.bot, chat_id))

    scheduler.add_job(
        send_daily_report_wrapper,
        'cron',
        hour=23,
        minute=59,
        timezone=pytz.timezone('Europe/Rome'),
        id='daily_btc_report'
    )

    cursor.execute('INSERT OR REPLACE INTO daily_report (chat_id, enabled) VALUES (?, ?)', (chat_id, 1))
    conn.commit()
    context.bot.send_message(chat_id=chat_id, text="✅ Daily BTC report activated. You will receive the report every day at 23:59.")

# Funzione per disattivare il daily report
# Funzione per disattivare il daily report
def daily_report_off(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Imposta enabled a 0 e aggiorna il timestamp nel database
    cursor.execute('UPDATE daily_report SET enabled = 0, timestamp = ? WHERE chat_id = ?', (timestamp, chat_id))
    conn.commit()

    # Rimuovi il job dallo scheduler se esiste
    job_id = f'daily_report_{chat_id}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    # Invia una conferma all'utente
    context.bot.send_message(chat_id=chat_id, text="❌ Daily BTC report deactivated. You will no longer receive the daily report.")

def start(update: Update, context: CallbackContext):
    user_language = update.effective_user.language_code

    description_it = "👋 *Benvenuto nel BTCWatcherBot!*\n\n🔍 Esplora le categorie del menu per accedere ai comandi disponibili."
    description_en = "👋 *Welcome to BTCWatcherBot!*\n\n🔍 Explore the menu categories to access available commands."

    description = description_it if user_language == 'it' else description_en

    # Invia solo il messaggio senza la tastiera personalizzata
    if update.message:
        update.message.reply_text(description, parse_mode='Markdown')
    elif update.callback_query:
        update.callback_query.message.reply_text(description, parse_mode='Markdown')

    show_menu(update, context)



# Funzione per gestire i pulsanti

def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    # Gestione dei sotto-menu
    if query.data == 'price_market':
        keyboard = [
            [InlineKeyboardButton("💵 Price", callback_data='cmd_price')],
            [InlineKeyboardButton("💹 Arbitrage", callback_data='cmd_arbitrage')],
            [InlineKeyboardButton("💱 Fiat Rates", callback_data='cmd_fiat_rates')],
            [InlineKeyboardButton("🔔 Set Price Alert", callback_data='cmd_set_price_alert')],
            [InlineKeyboardButton("📊 Price Trend", callback_data='cmd_price_trend')],
            [InlineKeyboardButton("📅 Daily Report ON", callback_data='cmd_daily_report_on')],
            [InlineKeyboardButton("📅 Daily Report OFF", callback_data='cmd_daily_report_off')],
            [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("📈 *Price & Market Tools*", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == 'monitoring_tools':
        keyboard = [
            [InlineKeyboardButton("⛏️ Monitor Blocks", callback_data='cmd_monitor_blocks')],
            [InlineKeyboardButton("🐋 Monitor Whales", callback_data='cmd_monitor_whales')],
            [InlineKeyboardButton("❌ Stop Monitoring Whales", callback_data='cmd_stop_monitor_whales')],
            [InlineKeyboardButton("🔍 Track Transaction", callback_data='cmd_track_tx')],
            [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("🔍 *Monitoring Tools*", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == 'fees_forecasts':
        keyboard = [
            [InlineKeyboardButton("⛽ Current Fees", callback_data='cmd_fees')],
            [InlineKeyboardButton("🧮 Calculate Fees", callback_data='cmd_calc_fee')],
            [InlineKeyboardButton("🔮 Fee Forecast", callback_data='cmd_fee_forecast')],
            [InlineKeyboardButton("🔔 Set Fee Alert", callback_data='cmd_set_fee_alert')],
            [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("⛽ *Fees & Forecasts*", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == 'security_node':
        keyboard = [
            [InlineKeyboardButton("🔒 Security Tips", callback_data='cmd_security')],
            [InlineKeyboardButton("🌐 Node Info", callback_data='cmd_node_info')],
            [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("🔒 *Security & Node Info*", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == 'general':
        keyboard = [
            [InlineKeyboardButton("🙏 Donate", callback_data='cmd_donate')],
            [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("🙏 *General*", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == 'stats_resources':
        keyboard = [
            [InlineKeyboardButton("📊 Blockchain Stats", callback_data='cmd_stats')],
            [InlineKeyboardButton("⚡ Lightning Stats", callback_data='cmd_ln_stats')],
            [InlineKeyboardButton("🌐 Market Cap", callback_data='cmd_market_cap')],
            [InlineKeyboardButton("📈 Volatility Index", callback_data='cmd_volatility')],
            [InlineKeyboardButton("📊 Dominance", callback_data='cmd_dominance')],
            [InlineKeyboardButton("📚 Resources", callback_data='cmd_resources')],
            [InlineKeyboardButton("❓ FAQ", callback_data='cmd_faq')],
            [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text("📊 *Stats & Resources*", reply_markup=reply_markup, parse_mode='Markdown')
    elif query.data == 'cmd_stop_monitor_whales':
        stop_monitor_whales(update, context)

    # Richiami ai comandi esistenti
    elif query.data == 'cmd_price':
        price(query, context)
    elif query.data == 'cmd_arbitrage':
        arbitrage(query, context)
    elif query.data == 'cmd_fiat_rates':
        fiat_rates(query, context)
    elif query.data == 'cmd_set_price_alert':
        query.message.reply_text("🔔 *Enter the price threshold for the alert:*", parse_mode='Markdown')
        context.user_data['awaiting_price_alert'] = True
    elif query.data == 'cmd_price_trend':
        price_trend(query, context)
    elif query.data == 'cmd_monitor_blocks':
        start_block_monitoring(query, context)
    elif query.data == 'cmd_monitor_whales':
        query.message.reply_text("🐋 *Enter the BTC threshold for whale transactions:*", parse_mode='Markdown')
        context.user_data['awaiting_whale_threshold'] = True
    elif query.data == 'cmd_stop_monitor_whales':
        stop_monitor_whales(query, context)
    elif query.data == 'cmd_track_tx':
        query.message.reply_text("🔍 *Enter the transaction ID to track:*", parse_mode='Markdown')
        context.user_data['awaiting_tx_id'] = True
    elif query.data == 'cmd_fees':
        fees(query, context)
    elif query.data == 'cmd_calc_fee':
        query.message.reply_text("🧮 *Enter the transaction size in bytes (e.g., 250):*", parse_mode='Markdown')
        context.user_data['awaiting_tx_size'] = True
    elif query.data == 'cmd_fee_forecast':
        fee_forecast(query, context)
    elif query.data == 'cmd_set_fee_alert':
        query.message.reply_text("🔔 *Enter the fee threshold in sat/vB:*", parse_mode='Markdown')
        context.user_data['awaiting_fee_alert'] = True
    elif query.data == 'cmd_security':
        security(query, context)
    elif query.data == 'cmd_node_info':
        query.message.reply_text("🌐 *Enter the public key of the Lightning node:*", parse_mode='Markdown')
        context.user_data['awaiting_node_info'] = True
    elif query.data == 'cmd_donate':
        donate(query, context)
    elif query.data == 'main_menu':
        show_menu(update, context)
    elif query.data == 'cmd_stats':
        stats(query, context)
    elif query.data == 'cmd_ln_stats':
        ln_stats(query, context)
    elif query.data == 'cmd_market_cap':
        market_cap(query, context)
    elif query.data == 'cmd_volatility':
        volatility(query, context)
    elif query.data == 'cmd_dominance':
        dominance(query, context)
    elif query.data == 'cmd_resources':
        resources(query, context)
    elif query.data == 'cmd_faq':
        faq(query, context)
    elif query.data == 'cmd_daily_report_on':
        daily_report_on(update, context)
    elif query.data == 'cmd_daily_report_off':
        daily_report_off(update, context)


def show_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("📈 Price & Market Tools", callback_data='price_market')],
        [InlineKeyboardButton("🔍 Monitoring Tools", callback_data='monitoring_tools')],
        [InlineKeyboardButton("⛽ Fees & Forecasts", callback_data='fees_forecasts')],
        [InlineKeyboardButton("🔒 Security & Node Info", callback_data='security_node')],
        [InlineKeyboardButton("🙏 General", callback_data='general')],
        [InlineKeyboardButton("📊 Stats & Resources", callback_data='stats_resources')],
        [InlineKeyboardButton("🙏 Donate", callback_data='cmd_donate')]  # Spostato nel menu principale
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Invia un nuovo messaggio se è un CallbackQuery
    if update.callback_query:
        update.callback_query.message.reply_text("🏠 *Menu Principale*", parse_mode='Markdown', reply_markup=reply_markup)
    else:
        update.message.reply_text("🏠 *Menu Principale*", parse_mode='Markdown', reply_markup=reply_markup)


# Funzione per gestire gli input dell'utente
def handle_user_input(update: Update, context: CallbackContext):
    if context.user_data.get('awaiting_tx_size'):
        size = update.message.text.strip()
        if size.isdigit():
            context.args = [size]
            calc_fee(update, context)
            context.user_data['awaiting_tx_size'] = False
        else:
            update.message.reply_text("❌ *Input non valido.* Inserisci un numero intero per la dimensione della transazione.", parse_mode='Markdown')

    elif context.user_data.get('awaiting_price_alert'):
        threshold = update.message.text.strip()
        if threshold.isdigit():
            context.args = [threshold]
            set_price_alert(update, context)
            context.user_data['awaiting_price_alert'] = False
        else:
            update.message.reply_text("❌ *Input non valido.* Inserisci un numero intero per la soglia del prezzo.", parse_mode='Markdown')

    elif context.user_data.get('awaiting_fee_alert'):
        threshold = update.message.text.strip()
        if threshold.isdigit():
            context.args = [threshold]
            set_fee_alert(update, context)
            context.user_data['awaiting_fee_alert'] = False
        else:
            update.message.reply_text("❌ *Input non valido.* Inserisci un numero intero per la soglia delle fee.", parse_mode='Markdown')

    elif context.user_data.get('awaiting_whale_threshold'):
        threshold = update.message.text.strip()
        if threshold.isdigit():
            context.args = [threshold]
            monitor_whales(update, context)
            context.user_data['awaiting_whale_threshold'] = False
        else:
            update.message.reply_text("❌ *Input non valido.* Inserisci un numero intero per la soglia in BTC.", parse_mode='Markdown')

    elif context.user_data.get('awaiting_tx_id'):
        tx_id = update.message.text.strip()
        context.args = [tx_id]
        track_tx(update, context)
        context.user_data['awaiting_tx_id'] = False

    elif context.user_data.get('awaiting_node_info'):
        node_pubkey = update.message.text.strip()
        context.args = [node_pubkey]
        node_info(update, context)
        context.user_data['awaiting_node_info'] = False

# Funzione per annullare l'operazione
def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("❌ *Operazione annullata.*", parse_mode='Markdown')
    context.user_data.clear()

#================



from telegram import Update, CallbackQuery
from telegram.ext import CallbackContext

def donate(update: Update, context: CallbackContext):
    # Determina il chat_id in base al tipo di update
    if isinstance(update, CallbackQuery):
        chat_id = update.message.chat_id
        user_language = update.from_user.language_code
        update.answer()  # Rispondi alla callback per evitare il messaggio di caricamento
    else:
        chat_id = update.effective_chat.id
        user_language = update.effective_user.language_code

    # Messaggio in italiano
    message_it = (
        "🙏 *Grazie per il tuo supporto!*\n\n"
        "Puoi donare tramite Lightning Network o Bitcoin on-chain:\n\n"
        "⚡ *Lightning Address*: `asyscom@davidebtc.me`\n\n"
        "💼 *Indirizzo BTC*: `bc1q9pmxl40z40gl72myf8983lfmdnssklnm08zyzz`\n\n"
        "Ogni donazione aiuta a mantenere e migliorare il bot! Grazie di cuore! 💙"
    )

    # Messaggio in inglese
    message_en = (
        "🙏 *Thank you for your support!*\n\n"
        "You can donate via Lightning Network or Bitcoin on-chain:\n\n"
        "⚡ *Lightning Address*: `asyscom@davidebtc.me`\n\n"
        "💼 *BTC Address*: `bc1q9pmxl40z40gl72myf8983lfmdnssklnm08zyzz`\n\n"
        "Every donation helps maintain and improve the bot! Thank you so much! 💙"
    )

    # Seleziona il messaggio in base alla lingua dell'utente
    message = message_it if user_language == 'it' else message_en

    # Invia il messaggio
    context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')






# Function to get detailed information about a Lightning Network node
def node_info(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("❌ Please provide a node public key. Usage: /node_info [public key]")
        return

    public_key = context.args[0]
    url = f'https://mempool.space/api/v1/lightning/nodes/{public_key}'
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        alias = data.get('alias', 'N/A')
        capacity = int(data.get('capacity', 0)) / 1e8  # Converti da stringa a intero e poi in BTC
        channels = data.get('channels', 'N/A')
        color = data.get('color', 'N/A')
        updated = data.get('updated', 'N/A')

        message = (
            f"🔎 *Lightning Node Info*\n\n"
            f"🏷️ Alias: {alias}\n"
            f"🔑 Public Key: `{public_key}`\n"
            f"💰 Capacity: {capacity:.2f} BTC\n"
            f"🔗 Channels: {channels}\n"
            f"🎨 Color: {color}\n"
            f"🕒 Last Updated: {updated}"
        )
    else:
        message = f"❌ Error fetching node information. Status code: {response.status_code}"

    update.message.reply_text(message, parse_mode='Markdown')



# Function to get Lightning Network stats from Mempool.space
def ln_stats(update: Update, context: CallbackContext):
    url = 'https://mempool.space/api/v1/lightning/statistics/latest'
    response = requests.get(url)

    if response.status_code == 200:
        try:
            data = response.json().get('latest', {})
            node_count = data.get('node_count', 'N/A')
            channel_count = data.get('channel_count', 'N/A')
            total_capacity = data.get('total_capacity', 'N/A') / 1e8  # Converti da satoshi a BTC
            avg_capacity = data.get('avg_capacity', 'N/A') / 1e8
            med_capacity = data.get('med_capacity', 'N/A') / 1e8

            message = (
                f"⚡ *Lightning Network Stats*\n\n"
                f"🖧 Nodes: {node_count}\n"
                f"🔗 Channels: {channel_count}\n"
                f"💰 Total Capacity: {total_capacity:.2f} BTC\n"
                f"📏 Average Channel Capacity: {avg_capacity:.2f} BTC\n"
                f"📈 Median Channel Capacity: {med_capacity:.2f} BTC"
            )
        except Exception as e:
            message = f"❌ Error parsing Lightning Network stats: {str(e)}"
    else:
        message = f"❌ Error fetching Lightning Network stats. Status code: {response.status_code}"

    update.message.reply_text(message, parse_mode='Markdown')

# Function to track a Bitcoin transaction
def track_tx(update: Update, context: CallbackContext):
    try:
        txid = context.args[0]
        chat_id = update.effective_chat.id
        update.message.reply_text(f"🔍 Tracking transaction: {txid}\nPlease wait for confirmation...")

        def check_transaction_status():
            url = f'https://blockstream.info/api/tx/{txid}'
            while True:
                response = requests.get(url)
                if response.status_code == 200:
                    data = response.json()
                    if data['status']['confirmed']:
                        context.bot.send_message(chat_id=chat_id, text=f"✅ *Transaction Confirmed!*\n\n🆔 TXID: {txid}")
                        break
                time.sleep(60)  # Controlla ogni 60 secondi

        threading.Thread(target=check_transaction_status).start()
        # Salva nel database
        cursor.execute('INSERT OR REPLACE INTO tracked_transactions (chat_id, txid) VALUES (?, ?)', (chat_id, txid))
        conn.commit()
    except IndexError:
        update.message.reply_text("❌ Please provide a TXID. Usage: /track_tx [txid]")


# Function to calculate estimated fee for a transaction
def calc_fee(update: Update, context: CallbackContext):
    try:
        if not context.args:
            raise ValueError  # Solleva un errore se non ci sono argomenti

        size = int(context.args[0])
        fees_data = get_fees()
        if fees_data:
            fastest_fee = size * fees_data['fastest']
            half_hour_fee = size * fees_data['half_hour']
            hour_fee = size * fees_data['hour']
            message = (
                f"🧮 *Estimated Transaction Fees*\n\n"
                f"🚀 Fastest \\(10 min\\): {fastest_fee} sat\n"
                f"⚡ Half Hour \\(30 min\\): {half_hour_fee} sat\n"
                f"🐢 Hour \\(60 min\\): {hour_fee} sat"
            )
        else:
            message = "❌ Error fetching network fees."
    except (IndexError, ValueError):
        message = "❌ Please provide a valid transaction size in bytes\\. Usage: /calc\\_fee \\[size\\]"

    update.message.reply_text(message, parse_mode='MarkdownV2')

# Function to show price trend for the last 24 hours
def price_trend(update: Update, context: CallbackContext):
    url = 'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=1'
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        prices = [price[1] for price in data['prices']]
        times = [price[0] / 1000 for price in data['prices']]  # Converti da millisecondi a secondi

        # Converti i timestamp in un formato leggibile
        times = [time.strftime('%H:%M', time.gmtime(t)) for t in times]

        # Crea il grafico
        plt.figure(figsize=(10, 5))
        plt.plot(times, prices, label="BTC Price (USD)")
        plt.xticks(rotation=45)
        plt.title("Bitcoin Price Trend (Last 24 Hours)")
        plt.xlabel("Time")
        plt.ylabel("Price (USD)")
        plt.legend()
        plt.grid()

        # Salva il grafico in un oggetto BytesIO e invialo come foto
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        update.message.reply_photo(photo=buf)
        buf.close()
        plt.close()
    else:
        update.message.reply_text("❌ Error fetching price trend data.")

# Variabile globale per memorizzare gli alert di fee
fee_alerts = {}


# Command to set a fee alert
def set_fee_alert(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    try:
        threshold = int(context.args[0])
        # Salva l'alert nel database
        cursor.execute('INSERT OR REPLACE INTO fee_alerts (chat_id, threshold) VALUES (?, ?)', (chat_id, threshold))
        conn.commit()
        update.message.reply_text(f"🔔 Fee alert set for {threshold} sat/vB!")
    except (IndexError, ValueError):
        update.message.reply_text("❌ Please provide a valid fee threshold. Usage: /set_fee_alert [fee]")





# Command to set a price alert
def set_price_alert(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    try:
        threshold = float(context.args[0])
        price_alerts[chat_id] = threshold
        cursor.execute('INSERT OR REPLACE INTO price_alerts (chat_id, threshold) VALUES (?, ?)', (chat_id, threshold))
        conn.commit()
        update.message.reply_text(f"🔔 Price alert set for ${threshold}!")
    except (IndexError, ValueError):
        update.message.reply_text("❌ Please provide a valid price threshold. Usage: /set_price_alert [price]")


# Function to get BTC price in USD and EUR
def get_price():
    url = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,eur'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        usd_price = data['bitcoin']['usd']
        eur_price = data['bitcoin']['eur']
        return usd_price, eur_price
    else:
        return None, None

# Command to show BTC price
def price(update: Update, context: CallbackContext):
    usd_price, eur_price = get_price()
    if usd_price and eur_price:
        message = f"💰 *Bitcoin Price*\n\n" \
                  f"💵 USD: ${usd_price}\n" \
                  f"💶 EUR: €{eur_price}"
    else:
        message = "❌ Error fetching the Bitcoin price."
    update.message.reply_text(message, parse_mode='Markdown')

# Function to get current mempool fees
def get_fees():
    url = 'https://mempool.space/api/v1/fees/recommended'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        fees = {
            "fastest": data['fastestFee'],
            "half_hour": data['halfHourFee'],
            "hour": data['hourFee']
        }
        return fees
    else:
        return None

# Command to show current fees
def fees(update: Update, context: CallbackContext):
    fees_data = get_fees()
    if fees_data:
        message = f"⛽ *Current Network Fees*\n\n" \
                  f"🚀 Fastest (10 min): {fees_data['fastest']} sat/vB\n" \
                  f"⚡ Half Hour (30 min): {fees_data['half_hour']} sat/vB\n" \
                  f"🐢 Hour (60 min): {fees_data['hour']} sat/vB"
    else:
        message = "❌ Error fetching network fees."
    update.message.reply_text(message, parse_mode='Markdown')

# Function to get the latest block height
def get_latest_block_height():
    url = 'https://blockstream.info/api/blocks/tip/height'
    response = requests.get(url)
    if response.status_code == 200:
        return int(response.text)
    return None


# Command to start block monitoring


# Command to start block monitoring
def start_block_monitoring(update: Update, context: CallbackContext):
    # Determina il chat_id correttamente per messaggi e callback
    if isinstance(update, Update) and update.callback_query:
        chat_id = update.callback_query.message.chat_id
        update.callback_query.message.reply_text("🚀 Started monitoring for new blocks!")
    else:
        chat_id = update.message.chat_id
        update.message.reply_text("🚀 Started monitoring for new blocks!")
    
    # Salva nel database
    cursor.execute('INSERT OR REPLACE INTO block_monitoring (chat_id) VALUES (?)', (chat_id,))
    conn.commit()

    # Avvia il monitoraggio in un nuovo thread
    threading.Thread(target=monitor_new_blocks, args=(context.bot, chat_id), daemon=True).start()


# Command to provide security tips
def security(update: Update, context: CallbackContext):
    tips = (
        "🔐 *Bitcoin Security Tips*\n\n"
        "1. Use a hardware wallet for large amounts.\n"
        "2. Never share your private keys.\n"
        "3. Enable 2FA on exchanges.\n"
        "4. Verify addresses before sending.\n"
        "5. Use CoinJoin to improve privacy."
    )
    update.message.reply_text(tips, parse_mode='Markdown')

# Command to show blockchain stats
# Aggiornamento della funzione `stats` per mostrare lo stato della rete Bitcoin

def stats(update: Update, context: CallbackContext):
    try:
        # Endpoint per ottenere altezza del blocco
        block_height_url = 'https://mempool.space/api/blocks/tip/height'
        block_height_response = requests.get(block_height_url)
        block_height = block_height_response.text if block_height_response.status_code == 200 else 'N/A'

        # Endpoint per ottenere statistiche della mempool
        mempool_url = 'https://mempool.space/api/mempool'
        mempool_response = requests.get(mempool_url)
        if mempool_response.status_code == 200:
            mempool_data = mempool_response.json()
            mempool_count = mempool_data.get('count', 'N/A')
            mempool_vsize = mempool_data.get('vsize', 'N/A')
        else:
            mempool_count = mempool_vsize = 'N/A'

        # Endpoint per ottenere l'aggiustamento della difficoltà
        difficulty_url = 'https://mempool.space/api/v1/difficulty-adjustment'
        difficulty_response = requests.get(difficulty_url)
        if difficulty_response.status_code == 200:
            difficulty_data = difficulty_response.json()
            difficulty_percentage = difficulty_data.get('difficultyChange', 'N/A')
            remaining_blocks = difficulty_data.get('remainingBlocks', 'N/A')
        else:
            difficulty_percentage = remaining_blocks = 'N/A'

        # Endpoint per ottenere l'hashrate della rete
        hashrate_url = 'https://mempool.space/api/v1/mining/pool/foundryusa/hashrate'
        hashrate_response = requests.get(hashrate_url)
        if hashrate_response.status_code == 200:
            hashrate_data = hashrate_response.json()
            avg_hashrate = sum(item['avgHashrate'] for item in hashrate_data) / len(hashrate_data)
            avg_hashrate_eh = avg_hashrate / 1e18  # Converti in EH/s
        else:
            avg_hashrate_eh = 'N/A'

        # Componi il messaggio con tutte le informazioni
        message = (
            f"📊 *Blockchain Stats*\n\n"
            f"📈 Block Height: {block_height}\n"
            f"⏳ Mempool Transactions: {mempool_count}\n"
            f"📦 Mempool Size: {mempool_vsize} vB\n"
            f"⚒️ Difficulty Change: {difficulty_percentage}%\n"
            f"🕒 Blocks Until Adjustment: {remaining_blocks}\n"
            f"🔗 Network Hashrate: {avg_hashrate_eh:.2f} EH/s"
        )

    except Exception as e:
        message = f"❌ Error fetching blockchain stats: {str(e)}"

    update.message.reply_text(message, parse_mode='Markdown')


# Aggiunta della funzione per la previsione delle fee

def fee_forecast(update: Update, context: CallbackContext):
    url = 'https://mempool.space/api/v1/fees/mempool-blocks'
    response = requests.get(url)

    if response.status_code == 200:
        try:
            data = response.json()

            # Estrai le fee dei prossimi blocchi
            fees = [round(block['medianFee'], 1) for block in data[:6]]

            message = (
                "\ud83d\udcc9 *Fee Forecast*\n\n"
                f"\u23f3 1 Hour:\n"
                f"\ud83d\ude80 High Priority: {fees[0]} sat/vB\n"
                f"\u26a1 Medium Priority: {fees[1]} sat/vB\n"
                f"\ud83d\udc11 Low Priority: {fees[2]} sat/vB\n\n"
                f"\u23f3 3 Hours:\n"
                f"\ud83d\ude80 High Priority: {fees[3]} sat/vB\n"
                f"\u26a1 Medium Priority: {fees[4]} sat/vB\n"
                f"\ud83d\udc11 Low Priority: {fees[5]} sat/vB\n"
            )
        except Exception as e:
            message = f"\u274c Error parsing fee forecast data: {str(e)}"
    else:
        message = "\u274c Error fetching fee forecast data."

    update.message.reply_text(message, parse_mode='Markdown')


# Command to monitor large unconfirmed transactions
def monitor_whales(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    threshold = int(context.args[0]) if context.args else 100
    update.message.reply_text(f"🐋 Monitoring for transactions larger than {threshold} BTC...")
    # Salva nel database
    cursor.execute('INSERT OR REPLACE INTO whale_monitoring (chat_id, threshold) VALUES (?, ?)', (chat_id, threshold))
    conn.commit()

    def check_large_transactions():
        seen_txids = set()
        whale_monitoring[chat_id] = True
        while whale_monitoring.get(chat_id, False):
            url = 'https://mempool.space/api/mempool/recent'
            response = requests.get(url)
            if response.status_code == 200:
                transactions = response.json()
                for tx in transactions:
                    amount = tx['value'] / 1e8
                    txid = tx['txid']
                    if amount >= threshold and txid not in seen_txids:
                        seen_txids.add(txid)
                        message = f"🐋 *Large BTC Transaction Detected!*\n\n" \
                                  f"💼 Amount: {amount:.2f} BTC\n" \
                                  f"🔗 [View Transaction](https://mempool.space/tx/{txid})"
                        context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            time.sleep(300)

    threading.Thread(target=check_large_transactions).start()

# Command to stop monitoring large transactions
       
def stop_monitor_whales(update: Update, context: CallbackContext):
    # Determina il chat_id correttamente in base al tipo di update
    if isinstance(update, CallbackQuery):
        chat_id = update.message.chat_id
        update.answer()  # Rispondi alla callback per evitare il messaggio di caricamento
    else:
        chat_id = update.effective_chat.id

    # Rimuovi dal database
    cursor.execute('DELETE FROM whale_monitoring WHERE chat_id = ?', (chat_id,))
    conn.commit()

    # Ferma il monitoraggio modificando il dizionario
    if chat_id in whale_monitoring:
        whale_monitoring[chat_id] = False

    # Invia un messaggio di conferma all'utente
    context.bot.send_message(chat_id=chat_id, text="🐋 Whale monitoring has been stopped.")

       
def arbitrage(update: Update, context: CallbackContext):
    # Dizionario degli exchange e delle rispettive API
    exchanges = {
        "Binance": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        "Coinbase": "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        "Kraken": "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"
    }
    prices = {}

    # Binance
    response = requests.get(exchanges["Binance"])
    if response.status_code == 200:
        data = response.json()
        price = data.get("price")
        if price:
            prices["Binance"] = f"${float(price):,.2f}"
        else:
            prices["Binance"] = "N/A"
    else:
        prices["Binance"] = "N/A"

    # Coinbase
    response = requests.get(exchanges["Coinbase"])
    if response.status_code == 200:
        data = response.json()
        price = data.get("data", {}).get("amount")
        if price:
            prices["Coinbase"] = f"${float(price):,.2f}"
        else:
            prices["Coinbase"] = "N/A"
    else:
        prices["Coinbase"] = "N/A"

    # Kraken
    response = requests.get(exchanges["Kraken"])
    if response.status_code == 200:
        data = response.json()
        result = data.get("result", {})
        pair = result.get("XXBTZUSD", {})
        price = pair.get("c", [None])[0]  # 'c' contiene il prezzo corrente come lista
        if price:
            prices["Kraken"] = f"${float(price):,.2f}"
        else:
            prices["Kraken"] = "N/A"
    else:
        prices["Kraken"] = "N/A"

    # Costruzione del messaggio
    message = (
        "📊 *Bitcoin Arbitrage Opportunities*\n\n"
        f"📈 Binance: {prices['Binance']}\n"
        f"📈 Coinbase: {prices['Coinbase']}\n"
        f"📈 Kraken: {prices['Kraken']}\n"
    )

    # Invia il messaggio
    if update.message:
        update.message.reply_text(message, parse_mode='Markdown')
    elif update.callback_query:
        update.callback_query.message.reply_text(message, parse_mode='Markdown')


# Funzione per ottenere i tassi di cambio fiat-Bitcoin
def fiat_rates(update: Update, context: CallbackContext):
    url = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,eur,gbp,jpy,cny'
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json().get('bitcoin', {})
        message = (
            "\ud83c\udf0d *Bitcoin to Fiat Exchange Rates*\n\n"
            f"\ud83d\udcb5 USD: ${data.get('usd', 'N/A')}\n"
            f"\ud83d\udcb6 EUR: \u20ac{data.get('eur', 'N/A')}\n"
            f"\ud83d\udcb8 GBP: \u00a3{data.get('gbp', 'N/A')}\n"
            f"\ud83c\uddef\ud83c\uddf5 JPY: \u00a5{data.get('jpy', 'N/A')}\n"
            f"\ud83c\udde8\ud83c\uddf3 CNY: \u00a5{data.get('cny', 'N/A')}\n"
        )
    else:
        message = "\u274c Error fetching fiat exchange rates."

    update.message.reply_text(message, parse_mode='Markdown')
##nuove funzioni####

def market_cap(update: Update, context: CallbackContext):
    url = "https://api.coingecko.com/api/v3/global"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        market_cap_usd = data["data"]["total_market_cap"]["usd"]
        btc_dominance = data["data"]["market_cap_percentage"]["btc"]

        message = (
            f"🌐 *Global Crypto Market Stats*\n\n"
            f"💰 *Total Market Cap*: ${market_cap_usd:,.2f}\n"
            f"🔗 *Bitcoin Dominance*: {btc_dominance:.2f}%"
        )
        update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        update.message.reply_text(f"❌ Error fetching market data: {e}")

def volatility(update: Update, context: CallbackContext):
    url = "https://api.alternative.me/fng/"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        volatility_index = data["data"][0]["value"]
        volatility_text = data["data"][0]["value_classification"]
        timestamp = data["data"][0]["timestamp"]

        message = (
            f"📊 *Bitcoin Volatility Index*\n\n"
            f"💹 *Volatility Score*: {volatility_index}\n"
            f"📝 *Classification*: {volatility_text}\n"
            f"📅 *Last Update*: {timestamp}"
        )
        update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        update.message.reply_text(f"❌ Error fetching volatility data: {e}")

def dominance(update: Update, context: CallbackContext):
    url = "https://api.coingecko.com/api/v3/global"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        btc_dominance = data["data"]["market_cap_percentage"]["btc"]
        eth_dominance = data["data"]["market_cap_percentage"]["eth"]

        message = (
            f"🔗 *Cryptocurrency Dominance*\n\n"
            f"₿ *Bitcoin Dominance*: {btc_dominance:.2f}%\n"
            f"Ξ *Ethereum Dominance*: {eth_dominance:.2f}%"
        )
        update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        update.message.reply_text(f"❌ Error fetching dominance data: {e}")

def faq(update: Update, context: CallbackContext):
    message = (
        "❓ *Frequently Asked Questions (FAQ) / Domande Frequenti (FAQ)*\n\n"
        
        "1️⃣ *What is Bitcoin? / Cos'è Bitcoin?*\n"
        "Bitcoin is a decentralized digital currency that uses cryptography for secure transactions without intermediaries.\n"
        "Bitcoin è una valuta digitale decentralizzata che utilizza la crittografia per garantire transazioni sicure e senza intermediari.\n\n"
        
        "2️⃣ *What is the Lightning Network? / Cos'è la Lightning Network?*\n"
        "The Lightning Network is a second-layer network that allows for instant and low-cost Bitcoin transactions.\n"
        "La Lightning Network è una rete di secondo livello che permette transazioni Bitcoin istantanee e a basso costo.\n\n"
        
        "3️⃣ *What are transaction fees? / Cosa sono le fee di transazione?*\n"
        "Fees are commissions paid to miners to confirm transactions on the blockchain.\n"
        "Le fee sono commissioni pagate ai miner per confermare le transazioni sulla blockchain.\n\n"
        
        "4️⃣ *What is a Bitcoin node? / Cos'è un nodo Bitcoin?*\n"
        "A node is a computer running Bitcoin software that helps maintain the decentralized network.\n"
        "Un nodo è un computer che esegue il software Bitcoin e contribuisce a mantenere la rete decentralizzata.\n\n"
        
        "5️⃣ *What does 'on-chain' and 'off-chain' mean? / Cosa significa 'on-chain' e 'off-chain'?*\n"
        "- *On-chain*: Transactions recorded on the main blockchain.\n"
        "  *On-chain*: Transazioni registrate sulla blockchain principale.\n"
        "- *Off-chain*: Transactions made outside the blockchain, e.g., on the Lightning Network.\n"
        "  *Off-chain*: Transazioni effettuate al di fuori della blockchain, ad esempio sulla Lightning Network.\n\n"
        
        "📚 *More info / Ulteriori informazioni*: [Bitcoin.org](https://bitcoin.org/it/)"
    )
    update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)


def resources(update: Update, context: CallbackContext):
    message = (
        "📚 *Bitcoin & Lightning Network Resources / Risorse su Bitcoin e Lightning Network*\n\n"

        "🔗 *General Information / Informazioni Generali:*\n"
        "- [Bitcoin.org](https://bitcoin.org/it/) - Official Bitcoin site / Sito ufficiale di Bitcoin\n"
        "- [Bitcoin Wiki](https://en.bitcoin.it/wiki/Main_Page) - Bitcoin documentation / Documentazione su Bitcoin\n\n"

        "⚡ *Lightning Network:*\n"
        "- [Lightning Network Documentation](https://docs.lightning.engineering/) - Guides and docs / Guide e documentazione\n"
        "- [LN Markets](https://lnmarkets.com/) - Trading on Lightning / Trading sulla Lightning Network\n\n"

        "📖 *Educational Content / Contenuti Educativi:*\n"
        "- [Mastering Bitcoin (Andreas Antonopoulos)](https://github.com/bitcoinbook/bitcoinbook) - Free online book / Libro gratuito online\n"
        "- [Bitcoin Whitepaper](https://bitcoin.org/bitcoin.pdf) - The original Bitcoin whitepaper / Il whitepaper originale di Bitcoin\n\n"

        "🎥 *Videos / Video:*\n"
        "- [Bitcoin Explained Simply](https://www.youtube.com/watch?v=bBC-nXj3Ng4) - YouTube\n"
        "- [Lightning Network Explained](https://www.youtube.com/watch?v=rrr_zPmEiME) - YouTube\n\n"

        "🛠️ *Tools & Explorers / Strumenti e Explorer:*\n"
        "- [Mempool.space](https://mempool.space/) - Bitcoin mempool and block explorer / Mempool e block explorer di Bitcoin\n"
        "- [Amboss](https://amboss.space/) - Lightning Network explorer / Explorer della Lightning Network"
    )
    update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

def debug(update: Update, context: CallbackContext):
    update.message.reply_text(f"Ricevuto: {update.message.text}")


def main():
    updater = Updater(BOT_TOKEN)
    dispatcher = updater.dispatcher

    # Aggiungi i CommandHandler
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('arbitrage', arbitrage))
    dispatcher.add_handler(CallbackQueryHandler(button))
    dispatcher.add_handler(CommandHandler('price', price))
    dispatcher.add_handler(CommandHandler('fees', fees))
    dispatcher.add_handler(CommandHandler('monitor_blocks', start_block_monitoring))
    dispatcher.add_handler(CommandHandler('stats', stats))
    dispatcher.add_handler(CommandHandler('security', security))
    dispatcher.add_handler(CommandHandler('monitor_whales', monitor_whales, pass_args=True))
    dispatcher.add_handler(CommandHandler('stop_monitor_whales', stop_monitor_whales))
    dispatcher.add_handler(CommandHandler('set_price_alert', set_price_alert))
    dispatcher.add_handler(CommandHandler('ln_stats', ln_stats))
    dispatcher.add_handler(CommandHandler('track_tx', track_tx, pass_args=True))
    dispatcher.add_handler(CommandHandler('calc_fee', calc_fee, pass_args=True))
    dispatcher.add_handler(CommandHandler('price_trend', price_trend))
    dispatcher.add_handler(CommandHandler('set_fee_alert', set_fee_alert, pass_args=True))
    dispatcher.add_handler(CommandHandler('node_info', node_info, pass_args=True))
    dispatcher.add_handler(CommandHandler('donate', donate))
    dispatcher.add_handler(CommandHandler('fiat_rates', fiat_rates))
    dispatcher.add_handler(CommandHandler('fee_forecast', fee_forecast))
    dispatcher.add_handler(CommandHandler('market_cap', market_cap))
    dispatcher.add_handler(CommandHandler('volatility', volatility))
    dispatcher.add_handler(CommandHandler('dominance', dominance))
    dispatcher.add_handler(CommandHandler('resources', resources))
    dispatcher.add_handler(CommandHandler('faq', faq))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_user_input))
    dispatcher.add_handler(CommandHandler('menu', show_menu))
    dispatcher.add_handler(CommandHandler("daily_report_on", daily_report_on))
    dispatcher.add_handler(CommandHandler("daily_report_off", daily_report_off))
    dispatcher.add_handler(MessageHandler(Filters.text, debug))

    # Carica i dati dal database passando updater come argomento
    load_data(updater)

    # Avvia il thread per controllare i price alerts
    threading.Thread(target=check_price_alerts, args=(updater.bot,), daemon=True).start()

    # Avvia lo scheduler
    scheduler.start()

    print("Bot is running...")
    updater.start_polling()
    updater.idle()

# Avvia il bot
if __name__ == '__main__':
    main()
