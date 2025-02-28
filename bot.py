import json
import requests
import telegram
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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

# Extract Booking Data (get first column as equipment options)
def extract_booking_table():
    url = f"https://www.mnff.com.sg/index.php/booking/calendar/{datetime.today().strftime('%Y-%m-%d')}/1"
    response = requests.get(url)
    if response.status_code != 200:
        print("Error: Failed to fetch booking table.")
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")
    equipment_options = []

    # Loop through the first table to get the first column (equipment)
    for table in tables[:1]:  # Only parse the first table
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all(["th", "td"])
            if cols:
                equipment = cols[0].text.strip()  # First column is the equipment name
                if equipment:
                    equipment = equipment.split(" ")[1:]  # Remove the first element (day)
                    equipment = " ".join(equipment).replace("(Rules)", "").strip()  # Remove "(Rules)"
                    equipment_options.append(equipment)

    return equipment_options

# Command: Start
def start(update, context):
    update.message.reply_text("Welcome! Use /subscribe to get booking updates. Send /manage_equipment to manage your equipment.")

# Command: Subscribe
def subscribe(update, context):
    chat_id = str(update.message.chat_id)
    subscribers = load_subscribers()
    subscribers[chat_id] = {"equipment": []}
    save_subscribers(subscribers)
    update.message.reply_text("Send /manage_equipment to manage your equipment.")

# Command: My Equipment
def my_equipment(update, context):
    chat_id = str(update.message.chat_id)
    subscribers = load_subscribers()
    
    # Get user's tracked equipment
    user_equipment = subscribers.get(chat_id, {}).get("equipment", [])

    if not user_equipment:
        update.message.reply_text("❌ You are not subscribed to any equipment. Use /manage_equipment to subscribe.")
        return

    # Show only equipment user is subscribed to
    equipment_list = "\n".join(user_equipment)
    update.message.reply_text(f"📋 Your Subscribed Equipment:\n{equipment_list}")

# Command: Manage Equipment
def manage_equipment(update, context):
    chat_id = str(update.message.chat_id)
    subscribers = load_subscribers()
    
    # Get user's tracked equipment
    user_equipment = subscribers.get(chat_id, {}).get("equipment", [])
    equipment_options = extract_booking_table()

    if not equipment_options:
        update.message.reply_text("⚠️ Failed to fetch equipment options.")
        return

    # Create Inline Keyboard Buttons for available equipment
    keyboard = []
    for idx, equipment in enumerate(equipment_options):
        button_text = f"🔘 {equipment}" if equipment in user_equipment else f"➕ {equipment}"
        callback_data = f"toggle_{idx}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text("Here are the equipment options. Click to manage:", reply_markup=reply_markup)

# Command: Unsubscribe
def unsubscribe(update, context):
    chat_id = str(update.message.chat_id)
    subscribers = load_subscribers()
    subscribers.pop(chat_id, None)
    save_subscribers(subscribers)
    update.message.reply_text("❌ You have unsubscribed from the booking updates.")

# Callback for Handling Inline Button Clicks
def button(update, context):
    query = update.callback_query
    query.answer()

    chat_id = str(query.message.chat.id)
    subscribers = load_subscribers()
    equipment_options = extract_booking_table()

    # Handle 'toggle' action for adding/removing equipment
    if query.data.startswith("toggle_"):
        idx = int(query.data.split("_")[1])
        equipment = equipment_options[idx]

        if equipment not in subscribers.get(chat_id, {}).get("equipment", []):
            # Add to tracked equipment
            subscribers[chat_id]["equipment"].append(equipment)
            query.edit_message_text(text=f"✅ {equipment} added to your tracked equipment.")
        else:
            # Remove from tracked equipment
            subscribers[chat_id]["equipment"].remove(equipment)
            query.edit_message_text(text=f"❌ {equipment} removed from your tracked equipment.")
        
        save_subscribers(subscribers)
    
    # Handle unsubscribe
    elif query.data == "unsubscribe":
        subscribers.pop(chat_id, None)
        save_subscribers(subscribers)
        query.edit_message_text(text="❌ You have unsubscribed from the booking updates.")

    # Update the 'My Equipment' view
    my_equipment(update, context)

# Monitor Booking Changes
def monitor_bookings(bot):
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
                    bot.send_message(chat_id=chat_id, text=message.strip())
        
        previous_snapshot = current_snapshot

# Main Function to Start Bot
def main():
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Register Command Handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("subscribe", subscribe))
    dp.add_handler(CommandHandler("my_equipment", my_equipment))
    dp.add_handler(CommandHandler("manage_equipment", manage_equipment))
    dp.add_handler(CommandHandler("unsubscribe", unsubscribe))

    # Register Callback Handler for Inline Buttons
    dp.add_handler(CallbackQueryHandler(button))

    # Start Monitoring in a Separate Thread
    threading.Thread(target=monitor_bookings, daemon=True, args=(updater.bot,)).start()

    # Start Polling
    updater.start_polling()
    updater.idle()

# Run the Bot
if __name__ == "__main__":
    main()