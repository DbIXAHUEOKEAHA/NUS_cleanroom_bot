import json
import requests
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from bs4 import BeautifulSoup
from datetime import datetime
import time
import threading

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = "8064663105:AAE7RFqr0CO6dXYxRN9IHH9Cz3aE1MRPis0"

# File to Store Subscribers
SUBSCRIBERS_FILE = "subscribers.json"

# Interval for Checking Booking Updates
SLEEP_TIME = 30

# Load & Save Subscribers
def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, "w") as file:
        json.dump(subscribers, file, indent=4)

# Extract Booking Data
def extract_booking_table():
    url = f"https://www.mnff.com.sg/index.php/booking/calendar/{datetime.today().strftime('%Y-%m-%d')}/1"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")
    return [[col.text.strip() for col in row.find_all(["th", "td"])] for table in tables for row in table.find_all("tr")[:15]]

# Command: Start
def start(update, context):
    update.message.reply_text("Welcome! Use /subscribe to get booking updates.")

# Command: Subscribe
def subscribe(update, context):
    chat_id = str(update.message.chat_id)
    subscribers = load_subscribers()
    subscribers[chat_id] = {"equipment": []}
    save_subscribers(subscribers)
    update.message.reply_text("Send /set_equipment followed by numbers (e.g., /set_equipment 3 5 9) to track equipment.")

# Command: Set Equipment
def set_equipment(update, context):
    chat_id = str(update.message.chat_id)
    numbers = [int(n) for n in context.args if n.isdigit() and 1 <= int(n) <= 15]
    
    if numbers:
        subscribers = load_subscribers()
        subscribers[chat_id] = {"equipment": numbers}
        save_subscribers(subscribers)
        update.message.reply_text(f"✅ Tracking equipment: {', '.join(map(str, numbers))}")
    else:
        update.message.reply_text("⚠️ Invalid input. Use /set_equipment 1 2 3 (numbers between 1-15).")

# Command: Unsubscribe
def unsubscribe(update, context):
    chat_id = str(update.message.chat_id)
    subscribers = load_subscribers()
    subscribers.pop(chat_id, None)
    save_subscribers(subscribers)
    update.message.reply_text("❌ You have unsubscribed.")

# Monitor Booking Changes
def monitor_bookings():
    previous_snapshot = extract_booking_table()
    if previous_snapshot is None:
        print("⚠️ Failed to fetch initial booking data. Monitoring stopped.")
        return
    print(f"✅ Monitoring started for {datetime.today().strftime('%Y-%m-%d')}.")

    while True:
        time.sleep(SLEEP_TIME)
        current_snapshot = extract_booking_table()
        if current_snapshot is None:
            continue
        
        changes_detected = {}
        for day in range(len(previous_snapshot)):
            for slot in range(len(previous_snapshot[day])):
                prev, curr = previous_snapshot[day][slot], current_snapshot[day][slot]
                if prev and not curr:
                    changes_detected.setdefault(slot + 1, []).append(f"🔴 Cancellation: {prev} removed on Day {day + 1}")
                elif not prev and curr:
                    changes_detected.setdefault(slot + 1, []).append(f"🟢 New Booking: {curr} added on Day {day + 1}")
        
        if changes_detected:
            subscribers = load_subscribers()
            for chat_id, data in subscribers.items():
                user_equipment = data["equipment"]
                message = "\n".join("\n".join(changes_detected.get(e, [])) for e in user_equipment)
                if message:
                    context.bot.send_message(chat_id=chat_id, text=message.strip())
        
        previous_snapshot = current_snapshot

# Main Function to Start Bot
def main():
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Register Command Handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("subscribe", subscribe))
    dp.add_handler(CommandHandler("set_equipment", set_equipment, pass_args=True))
    dp.add_handler(CommandHandler("unsubscribe", unsubscribe))

    # Start Monitoring Thread
    threading.Thread(target=monitor_bookings, daemon=True).start()

    # Start Polling
    updater.start_polling()
    updater.idle()

# Run the Bot
if __name__ == "__main__":
    main()