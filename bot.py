import json
import requests
import telegram
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import threading

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = "8064663105:AAE7RFqr0CO6dXYxRN9IHH9Cz3aE1MRPis0"

# File to Store Subscribers
SUBSCRIBERS_FILE = "subscribers.json"

# Interval for Checking Booking Updates
SLEEP_TIME = 30

# Time slot duration (15 mins)
TIME_SLOT_DURATION = 15

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
                    equipment = equipment.split(" ")[2:]  # Remove the first element (day)
                    equipment = " ".join(equipment).replace("(Rules)", "").strip()  # Remove "(Rules)"
                    equipment_options.append(equipment)

    return equipment_options

# Command: Start
def start(update, context):
    update.message.reply_text("Welcome! Use /menu to access the bot's features.")

# Command: Menu
def menu(update, context):
    keyboard = [
        [InlineKeyboardButton("Manage Equipment", callback_data="manage_equipment"),
         InlineKeyboardButton("My Equipment", callback_data="my_equipment")],
        [InlineKeyboardButton("Time Monitor", callback_data="time_monitor")],
        [InlineKeyboardButton("Unsubscribe", callback_data="unsubscribe")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Choose an option:", reply_markup=reply_markup)

# Command: Subscribe
def subscribe(update, context):
    chat_id = str(update.message.chat_id)
    subscribers = load_subscribers()
    
    # Initialize user's preferences if not already subscribed
    if chat_id not in subscribers:
        subscribers[chat_id] = {
            "equipment": [],
            "time_slots": list(range(96))  # Default to all time slots active
        }
        save_subscribers(subscribers)
        update.message.reply_text("You have subscribed. Use /menu to manage your settings.")
    else:
        update.message.reply_text("You are already subscribed. Use /menu to manage your settings.")

# Command: My Equipment
def my_equipment(update, context):
    chat_id = str(update.message.chat.id)
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
    chat_id = str(update.message.chat.id)
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
    keyboard.append([InlineKeyboardButton("Back to Menu", callback_data="menu")])  # Add a back button
    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text("Here are the equipment options. Click to manage:", reply_markup=reply_markup)

# Command: Unsubscribe
def unsubscribe(update, context):
    chat_id = str(update.message.chat.id)
    subscribers = load_subscribers()
    subscribers.pop(chat_id, None)
    save_subscribers(subscribers)
    update.message.reply_text("❌ You have unsubscribed from the booking updates.")

# Command: Time Monitor
def time_monitor(update, context):
    chat_id = str(update.message.chat.id)
    subscribers = load_subscribers()
    user_settings = subscribers.get(chat_id, {})
    time_slots = user_settings.get("time_slots", list(range(96)))  # Default is all slots

    # Create Inline Buttons for time slots (Active or Inactive)
    keyboard = []
    for idx in range(0, 96, 12):  # Group slots in 12 for easier navigation
        start_time = (idx * TIME_SLOT_DURATION) // 60
        end_time = ((idx + 11) * TIME_SLOT_DURATION) // 60
        start_label = f"{start_time % 12 or 12} {'AM' if start_time < 12 else 'PM'}"
        end_label = f"{end_time % 12 or 12} {'AM' if end_time < 12 else 'PM'}"
        time_range = f"{start_label} - {end_label}"

        time_slot_range = [InlineKeyboardButton(f"Slot {time_range}", callback_data=f"time_range_{idx}")]
        keyboard.append(time_slot_range)
    
    keyboard.append([InlineKeyboardButton("Back to Menu", callback_data="menu")])  # Back to menu button
    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text("Select time slots to manage:", reply_markup=reply_markup)

# Batch Time Slot Management (confirm & update)
def confirm_time_slots(update, context):
    chat_id = str(update.message.chat.id)
    subscribers = load_subscribers()
    user_settings = subscribers.get(chat_id, {})
    selected_slots = user_settings.get("selected_time_slots", [])

    if not selected_slots:
        update.message.reply_text("❌ No time slots selected. Use /time_monitor to select.")
        return

    # Confirm and update time slots
    user_settings["time_slots"] = selected_slots
    del user_settings["selected_time_slots"]
    save_subscribers(subscribers)

    time_slot_ranges = [
        f"{(start_slot * TIME_SLOT_DURATION) // 60 % 12 or 12} {'AM' if start_slot < 12 else 'PM'} - "
        f"{((start_slot + 11) * TIME_SLOT_DURATION) // 60 % 12 or 12} {'AM' if (start_slot + 11) < 12 else 'PM'}"
        for start_slot in selected_slots
    ]
    update.message.reply_text(f"✅ Time slots updated: {', '.join(time_slot_ranges)}")

# Callback for Handling Inline Button Clicks
def button(update, context):
    query = update.callback_query
    query.answer()

    chat_id = str(query.message.chat.id)
    subscribers = load_subscribers()
    user_settings = subscribers.get(chat_id, {})

    if query.data.startswith("toggle_"):
        idx = int(query.data.split("_")[1])
        equipment_options = extract_booking_table()
        equipment = equipment_options[idx]

        # Handle adding/removing equipment
        if equipment not in user_settings.get("equipment", []):
            user_settings.setdefault("equipment", []).append(equipment)
            query.edit_message_text(text=f"✅ {equipment} added to your tracked equipment.")
        else:
            user_settings["equipment"].remove(equipment)
            query.edit_message_text(text=f"❌ {equipment} removed from your tracked equipment.")

        save_subscribers(subscribers)

    elif query.data.startswith("time_range_"):
        start_slot = int(query.data.split("_")[2])
        end_slot = start_slot + 11

        # Mark the selected time range for batch update later
        selected_time_slots = user_settings.setdefault("selected_time_slots", [])
        if start_slot not in selected_time_slots:
            selected_time_slots.append(start_slot)
            time_range = f"{(start_slot * TIME_SLOT_DURATION) // 60 % 12 or 12} {'AM' if start_slot < 12 else 'PM'} - " \
                         f"{((start_slot + 11) * TIME_SLOT_DURATION) // 60 % 12 or 12} {'AM' if (start_slot + 11) < 12 else 'PM'}"
            query.edit_message_text(text=f"Time slot {time_range} added to selection.")
        else:
            selected_time_slots.remove(start_slot)
            query.edit_message_text(text=f"Time slot removed.")

        save_subscribers(subscribers)

    elif query.data == "menu":
        menu(update, context)

    elif query.data == "back_to_menu":
        menu(update, context)

def main():
    # Create the Updater and pass it your bot's token
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Add Handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("menu", menu))
    dispatcher.add_handler(CommandHandler("subscribe", subscribe))
    dispatcher.add_handler(CommandHandler("my_equipment", my_equipment))
    dispatcher.add_handler(CommandHandler("manage_equipment", manage_equipment))
    dispatcher.add_handler(CommandHandler("unsubscribe", unsubscribe))
    dispatcher.add_handler(CommandHandler("time_monitor", time_monitor))
    dispatcher.add_handler(CallbackQueryHandler(button))

    # Start the Bot
    updater.start_polling()

if __name__ == "__main__":
    main()