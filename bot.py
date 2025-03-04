import threading
import requests
import telegram
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import psycopg2
from psycopg2.extras import Json

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = "8064663105:AAE7RFqr0CO6dXYxRN9IHH9Cz3aE1MRPis0"

# PostgreSQL Connection String (replace with your Railway.app PostgreSQL URL)
DATABASE_URL = "postgresql://postgres:CiDoZpCyhjqXNAjwvDEBHYvkmPLideSu@postgres-80am.railway.internal:5432/railway"

# Interval for Checking Booking Updates
SLEEP_TIME = 30

# Time slot duration (2 hours instead of 1)
TIME_SLOT_DURATION = 0.25  # In hours
N_TIME_SLOT = 8  # Number of table cells in one monitored slot

global_snapshot = {}
monitoring_active = True

# Connect to PostgreSQL
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# Initialize Database (create tables if they don't exist)
def initialize_database():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id BIGINT PRIMARY KEY,
            equipment TEXT[],
            time_slots INTEGER[]
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

# Load Subscribers from PostgreSQL
def load_subscribers():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM subscribers")
    subscribers = {str(row[0]): {"equipment": row[1], "time_slots": row[2]} for row in cur.fetchall()}
    cur.close()
    conn.close()
    return subscribers

# Save Subscribers to PostgreSQL
def save_subscribers(subscribers):
    conn = get_db_connection()
    cur = conn.cursor()
    
    for chat_id, data in subscribers.items():
        equipment = data.get("equipment", [])
        time_slots = data.get("time_slots", [])
        
        cur.execute("""
            INSERT INTO subscribers (chat_id, equipment, time_slots)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE 
            SET equipment = EXCLUDED.equipment, time_slots = EXCLUDED.time_slots
        """, (chat_id, equipment if equipment else [], time_slots if time_slots else []))
    
    conn.commit()
    cur.close()
    conn.close()

# Function to generate today's booking URL
def get_today_url():
    today = datetime.today().strftime("%Y-%m-%d")
    return f"https://www.mnff.com.sg/index.php/booking/calendar/{today}/1"

def get_future_date(days_from_today: int) -> str:
    """Returns the date in 'dd.mm' format for the given number of days from today."""
    if not (1 <= days_from_today <= 7):
        raise ValueError("days_from_today must be between 1 and 7")

    future_date = datetime.today() + timedelta(days=days_from_today)
    return future_date.strftime("%d.%m")

def float_to_time(float_time):
    # Separate hours and minutes
    hours = int(float_time)
    minutes = int((float_time - hours) * 60)

    # Determine AM/PM
    if hours < 12:
        period = "AM"
    else:
        period = "PM"

    # Convert to 12-hour format
    if hours == 0:
        hours_12 = 12
    else:
        hours_12 = hours if hours <= 12 else hours - 12

    # Format the time as HH:MM AM/PM
    time_str = f"{hours_12}:{minutes:02d} {period}"
    return time_str


# Extract Booking Data (get first column as equipment options)
def extract_equipment_options():
    url = get_today_url()
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

equipment_options = extract_equipment_options()

# Command: Start
def start(update, context):
    update.effective_message.reply_text("Welcome! Use /menu to access the bot's features.")

def extract_booking_table(equipment, time_slots):
    """Extracts booking status for given equipment and time slots."""
    url = get_today_url()
    response = requests.get(url)

    if response.status_code != 200:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")

    extracted_rows = []
    for i in equipment:
        for day_index, table in enumerate(tables):
            data = table.find_all("tr")
            rows = data[equipment_options.index(i)].find_all(["th", "td"])
            row_data = []
            for row in rows:
                colspan = int(row.get("colspan", 1))
                cell_text = row.text.strip()
                row_data.extend([cell_text] * colspan)

            extracted_rows.append([row_data[j + 1] for j in time_slots if j < len(row_data) - 1])

    return extracted_rows if extracted_rows else None

def send_notification(update, message):
    try:
        update.effective_message.reply_text(message)
    except telegram.error.NetworkError as e:
        print(f"⚠️ Network error while sending message: {e}")
        time.sleep(5)  # Wait and retry
        try:
            update.effective_message.reply_text(message)
        except Exception as e:
            print(f"❌ Failed again: {e}")  # Log and prevent a crash

def monitor_bookings(update, context):
    """Monitors the booking table and notifies subscribers of changes."""
    global global_snapshot, monitoring_active

    while monitoring_active:
        time.sleep(SLEEP_TIME)

        subscribers = load_subscribers()
        if not subscribers:
            monitoring_active = False  # Stop monitoring if no subscribers
            return

        for chat_id, user_data in subscribers.items():
            user_equipment = user_data.get("equipment", [])
            selected_time_slots = user_data.get("time_slots", [])

            if not user_equipment or not selected_time_slots:
                continue

            current_snapshot = extract_booking_table(user_equipment, selected_time_slots)
            if current_snapshot is None:
                continue

            if chat_id not in global_snapshot:
                global_snapshot[chat_id] = current_snapshot
                continue

            previous_snapshot = global_snapshot[chat_id]
            message = ""
            changes_detected = False
            days = len(previous_snapshot) // len(user_equipment)

            for day in range(days):
                for n_equipment, eq in enumerate(user_equipment):
                    for slot in range(len(previous_snapshot[day])):
                        equipment = eq
                        prev = previous_snapshot[day + days * n_equipment][slot]
                        curr = current_snapshot[day + days * n_equipment][slot]

                        if prev and not curr:
                            slot_label = float_to_time(selected_time_slots[slot]*TIME_SLOT_DURATION)
                            
                            message += f"🔴 Cancellation: {prev} removed from {equipment} on {get_future_date(day)}, Time Slot {slot_label}\n"
                            changes_detected += True
                            
                        elif not prev and curr:
                            slot_label = float_to_time(selected_time_slots[slot]*TIME_SLOT_DURATION)
                            
                            message += f"🟢 New Booking: {curr} added to {equipment} on {get_future_date(day)}, Time Slot {slot_label}\n"
                            changes_detected = True
                            
            if changes_detected:
                send_notification(update, message.strip())

            global_snapshot[chat_id] = current_snapshot  # Update snapshot

def start_monitoring(update, context):
    """Starts monitoring if not already running."""
    global monitoring_thread, monitoring_active

    if not monitoring_active:
        monitoring_active = True
        monitoring_thread = threading.Thread(target=monitor_bookings, args=(update, context), daemon=True)
        monitoring_thread.start()
        update.effective_message.reply_text("✅ Monitoring started!")

def stop_monitoring(update, context):
    """Stops monitoring if no users remain."""
    global monitoring_active
    subscribers = load_subscribers()
    
    if not subscribers:
        monitoring_active = False
        update.effective_message.reply_text("⛔ No active subscribers. Monitoring stopped.")

# Command: Menu
def menu(update, context):
    keyboard = [
        [InlineKeyboardButton("Manage Equipment", callback_data="manage_equipment"),
         InlineKeyboardButton("My Equipment", callback_data="my_equipment")],
        [InlineKeyboardButton("Time Monitor", callback_data="time_monitor"), 
          InlineKeyboardButton("My Time Slots", callback_data="my_time_slots")],
        [InlineKeyboardButton("Unsubscribe", callback_data="unsubscribe")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.effective_message.reply_text("Choose an option:", reply_markup=reply_markup)

# Command: Subscribe
def subscribe(update, context):
    chat_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    
    # Initialize user's preferences if not already subscribed
    if chat_id not in subscribers:
        subscribers[chat_id] = {
            "equipment": [],
            "time_slots": list(range(96))  # Default to all time slots active
        }
        save_subscribers(subscribers)
        update.effective_message.reply_text("You have subscribed. Use /menu to manage your settings.")
    else:
        update.effective_message.reply_text("You are already subscribed. Use /menu to manage your settings.")
    
    # Start monitoring
    start_monitoring(update, context)
    
# Command: My Equipment
def my_equipment(update, context):
    chat_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    
    # Get user's tracked equipment
    user_equipment = subscribers.get(chat_id, {}).get("equipment", [])

    if chat_id not in subscribers:
        update.effective_message.reply_text("❌ You are not subscribed to the bot. Use /subscribe to subscribe.")
        return

    if not user_equipment:
        update.effective_message.reply_text("❌ You are not subscribed to any equipment. Use /manage_equipment to subscribe to updates.")
        return

    # Show only equipment user is subscribed to
    equipment_list = "\n".join(user_equipment)
    update.effective_message.reply_text(f"📋 Your Subscribed Equipment:\n{equipment_list}")

# Command: Manage Equipment
def manage_equipment(update, context):
    chat_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    
    # Get user's tracked equipment
    user_equipment = subscribers.get(chat_id, {}).get("equipment", [])

    if chat_id not in subscribers:
        update.effective_message.reply_text("❌ You are not subscribed to the bot. Use /subscribe to subscribe.")
        return

    if not equipment_options:
        update.effective_message.reply_text("⚠️ Failed to fetch equipment options.")
        return

    # Create Inline Keyboard Buttons for available equipment
    keyboard = []
    for idx, equipment in enumerate(equipment_options):
        button_text = f"➖ {equipment}" if equipment in user_equipment else f"➕ {equipment}"
        callback_data = f"toggle_{idx}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe")])
    keyboard.append([InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")])  # Add a back button
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Use "edit_message_text" instead of sending a new message
    if update.callback_query:
        update.callback_query.message.edit_text(
            text="Here are the equipment options. Click to manage:",
            reply_markup=reply_markup
        )
    else:
        update.effective_message.reply_text("Here are the equipment options. Click to manage:", reply_markup=reply_markup)

# Command: Unsubscribe
def unsubscribe(update, context):
    chat_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    subscribers.pop(chat_id, None)
    save_subscribers(subscribers)
    update.effective_message.reply_text("❌ You have unsubscribed from the booking updates.")
    stop_monitoring(update, context)

# Command: My Time Slots
def my_time_slots(update, context):
    chat_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    user_settings = subscribers.get(chat_id, {})

    if chat_id not in subscribers:
        update.effective_message.reply_text("❌ You are not subscribed to the bot. Use /subscribe to subscribe.")
        return

    # Show only active time slots
    active_time_slots = []
    for idx in range(0, 96, N_TIME_SLOT):  # Group slots by 2 hours (4 slots per time block)
        start_time = (idx * TIME_SLOT_DURATION) % 24
        end_time = ((idx + N_TIME_SLOT) * TIME_SLOT_DURATION) % 24
        start_label = f"{start_time % 12 or 12} {'AM' if start_time < 12 else 'PM'}"
        end_label = f"{end_time % 12 or 12} {'AM' if end_time < 12 else 'PM'}"
        time_range = f"{start_label} - {end_label}"

        # If this time slot is monitored by the user
        if idx in user_settings.get("time_slots", []):
            active_time_slots.append(time_range)

    if active_time_slots:
        time_slot_list = "\n".join(active_time_slots)
        message = f"📅 Monitored Time Slots:\n{time_slot_list}"
    else:
        message = "❌ You are not monitoring any time slots. Use /time_monitor to set them."
        
    update.effective_message.reply_text(message)

# Command: Time Monitor
def time_monitor(update, context):
    chat_id = str(update.effective_chat.id)
    subscribers = load_subscribers()
    selected_time_slots = subscribers.get(chat_id, {}).get("time_slots", [])
    
    if chat_id not in subscribers:
        update.effective_message.reply_text("❌ You are not subscribed to the bot. Use /subscribe to subscribe.")
        return
    
    # Create Inline Buttons for time slots (Active or Inactive)
    keyboard = []
    for idx in range(0, 96, N_TIME_SLOT):  # Group slots by 2 hours (8 slots per time block)
        start_time = (idx * TIME_SLOT_DURATION)
        end_time = ((idx + N_TIME_SLOT) * TIME_SLOT_DURATION)
        start_label = f"{int(start_time % 12) or 12} {'AM' if start_time < 12 else 'PM'}"
        end_label = f"{int(end_time % 12) or 12} {'AM' if end_time < 12 else 'PM'}"
        time_range = f"{start_label} - {end_label}"

        time_slot_range = [InlineKeyboardButton(f"{'➖' if idx in selected_time_slots else '➕'} Slot {time_range}", callback_data=f"time_range_{idx}")]
        keyboard.append(time_slot_range)
    
    keyboard.append([InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")])  # Back to menu button
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Use "edit_message_text" instead of sending a new message
    if update.callback_query:
        update.callback_query.message.edit_text(
            text="Select time slots to manage:", reply_markup = reply_markup)
    else:
        update.effective_message.reply_text(text="Select time slots to manage:", reply_markup = reply_markup)

# Callback for Handling Inline Button Clicks
def button(update, context):
    query = update.callback_query
    query.answer()

    chat_id = str(query.message.chat.id)
    subscribers = load_subscribers()
    
    user_equipment = subscribers.get(chat_id, {}).get("equipment", [])
    selected_time_slots = subscribers.get(chat_id, {}).get("time_slots", [])

    if query.data.startswith("toggle_"):
        idx = int(query.data.split("_")[1])
        equipment = equipment_options[idx]

        # Handle adding/removing equipment
        if equipment not in subscribers.get(chat_id, {}).get("equipment", []):
            subscribers[chat_id]["equipment"].append(equipment)
            query.edit_message_text(text=f"✅ {equipment} added to your tracked equipment.")
        else:
            subscribers[chat_id]["equipment"].remove(equipment)
            query.edit_message_text(text=f"❌ {equipment} removed from your tracked equipment.")

        save_subscribers(subscribers)
        
        # Create Inline Keyboard Buttons for available equipment
        keyboard = []
        for idx, equipment in enumerate(equipment_options):
            button_text = f"➖ {equipment}" if equipment in user_equipment else f"➕ {equipment}"
            callback_data = f"toggle_{idx}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

        keyboard.append([InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe")])
        keyboard.append([InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")])  # Add a back button
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Use "edit_message_text" instead of sending a new message
        if update.callback_query:
            update.callback_query.message.edit_text(
                text="Here are the equipment options. Click to manage:",
                reply_markup=reply_markup
            )
        else:
            update.effective_message.reply_text("Here are the equipment options. Click to manage:", reply_markup=reply_markup)

    elif query.data.startswith("time_range_"):
        start_slot = int(query.data.split("_")[2])
        end_slot = start_slot + N_TIME_SLOT  # 2-hour block (8 slots per block)
        start_label = f"{int(start_slot*TIME_SLOT_DURATION % 12) or 12} {'AM' if start_slot*TIME_SLOT_DURATION < 12 else 'PM'}"
        end_label = f"{int(end_slot*TIME_SLOT_DURATION % 12) or 12} {'AM' if end_slot*TIME_SLOT_DURATION < 12 else 'PM'}"

        # Mark the selected time range for batch update later
        selected_time_slots = subscribers.get(chat_id, {}).get("time_slots", [])
        if start_slot not in selected_time_slots:
            for i in range(N_TIME_SLOT):
                selected_time_slots.append(start_slot + i)
            query.edit_message_text(text=f"Time slot {start_label} - "
                                        f"{end_label} added to selection.")
        else:
            for i in range(N_TIME_SLOT):
                selected_time_slots.remove(start_slot + i)
            query.edit_message_text(text=f"Time slot {start_label} - "
                                        f"{end_label} removed from selection.")

        selected_time_slots = sorted(selected_time_slots)
        subscribers[chat_id]["time_slots"] = selected_time_slots
        save_subscribers(subscribers)
        keyboard = []
        for idx in range(0, 96, N_TIME_SLOT):  # Group slots by 2 hours (8 slots per time block)
            start_time = (idx * TIME_SLOT_DURATION)
            end_time = ((idx + N_TIME_SLOT) * TIME_SLOT_DURATION)
            start_label = f"{int(start_time % 12) or 12} {'AM' if start_time < 12 else 'PM'}"
            end_label = f"{int(end_time % 12) or 12} {'AM' if end_time < 12 else 'PM'}"
            time_range = f"{start_label} - {end_label}"

            time_slot_range = [InlineKeyboardButton(f"{'➖' if idx in selected_time_slots else '➕'} Slot {time_range}", callback_data=f"time_range_{idx}")]
            keyboard.append(time_slot_range)
        
        keyboard.append([InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")])  # Back to menu button
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Use "edit_message_text" instead of sending a new message
        if update.callback_query:
            update.callback_query.message.edit_text(
                text="Select time slots to manage:", reply_markup = reply_markup)
        else:
            update.effective_message.reply_text(text="Select time slots to manage:", reply_markup = reply_markup)

    elif query.data == "menu":
        query.message.reply_text("/menu")

    elif query.data == "back_to_menu":
        menu(update, context)

    elif query.data == "manage_equipment":
        manage_equipment(update, context)
        
    elif query.data == "my_equipment":
        my_equipment(update, context)
        
    elif query.data == "time_monitor":
        time_monitor(update, context)
        
    elif query.data == "my_time_slots":
        my_time_slots(update, context)
        
    elif query.data == "unsubscribe":
        unsubscribe(update, context)

def main():
    # Initialize the database
    initialize_database()

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
    dispatcher.add_handler(CommandHandler("my_time_slots", my_time_slots))
    dispatcher.add_handler(CommandHandler("time_monitor", time_monitor))
    dispatcher.add_handler(CallbackQueryHandler(button))

    # Start the Bot
    updater.start_polling()

if __name__ == "__main__":
    main()