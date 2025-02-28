import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
from flask import Flask, request

app = Flask(__name__)

# Telegram Bot Credentials
TELEGRAM_BOT_TOKEN = "8064663105:AAE7RFqr0CO6dXYxRN9IHH9Cz3aE1MRPis0"
WEBHOOK_URL = "nuscleanroombot-production.up.railway.app"  # Replace with Railway public URL
SUBSCRIBERS_FILE = "subscribers.json"
SLEEP_TIME = 30  # Check interval in seconds

# Load subscribers from file
def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Save subscribers to file
def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, "w") as file:
        json.dump(subscribers, file, indent=4)

# Send message to a specific user
def send_telegram_message(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    requests.post(url, json=payload)

# Get today's booking URL
def get_today_url():
    today = datetime.today().strftime("%Y-%m-%d")
    return f"https://www.mnff.com.sg/index.php/booking/calendar/{today}/1"

# Extract booking data from website
def extract_booking_table():
    url = get_today_url()
    response = requests.get(url)

    if response.status_code != 200:
        print(f"Failed to retrieve page. Status code: {response.status_code}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")

    extracted_rows = []
    for table in tables:
        rows = table.find_all("tr")
        for row in rows[:15]:  # Limit to 15 equipment rows
            cols = row.find_all(["th", "td"])
            row_data = [col.text.strip() for col in cols]
            extracted_rows.append(row_data)

    return extracted_rows if extracted_rows else None

# Handle incoming Telegram messages
@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    update = request.get_json()

    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"]["text"]

        subscribers = load_subscribers()

        if text == "/start":
            send_telegram_message(chat_id, "Welcome! Send /subscribe to choose equipment.")
        elif text == "/subscribe":
            subscribers[str(chat_id)] = {"equipment": []}
            save_subscribers(subscribers)
            send_telegram_message(chat_id, "Send /set_equipment followed by numbers (e.g., /set_equipment 3 5 9) to track equipment.")
        elif text.startswith("/set_equipment"):
            numbers = [int(n) for n in text.split()[1:] if n.isdigit() and 1 <= int(n) <= 15]
            if numbers:
                subscribers[str(chat_id)] = {"equipment": numbers}
                save_subscribers(subscribers)
                send_telegram_message(chat_id, f"✅ You are now tracking equipment: {', '.join(map(str, numbers))}")
            else:
                send_telegram_message(chat_id, "⚠️ Invalid input. Use /set_equipment 1 2 3 (numbers between 1-15).")
        elif text == "/my_equipment":
            eq = subscribers.get(str(chat_id), {}).get("equipment", [])
            send_telegram_message(chat_id, f"🔍 You are tracking: {', '.join(map(str, eq)) if eq else 'None'}")
        elif text == "/unsubscribe":
            subscribers.pop(str(chat_id), None)
            save_subscribers(subscribers)
            send_telegram_message(chat_id, "❌ You have unsubscribed from updates.")

    return "OK", 200

# Start monitoring
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
            print("⚠️ Failed to fetch data. Skipping this check...")
            continue

        changes_detected = {}

        for day in range(len(previous_snapshot)):
            for slot in range(len(previous_snapshot[day])):
                prev = previous_snapshot[day][slot]
                curr = current_snapshot[day][slot]

                if prev and not curr:
                    change_msg = f"🔴 Cancellation: {prev} removed on Day {day + 1}, Time Slot {slot}"
                elif not prev and curr:
                    change_msg = f"🟢 New Booking: {curr} added on Day {day + 1}, Time Slot {slot}"
                else:
                    continue

                if slot + 1 not in changes_detected:
                    changes_detected[slot + 1] = []
                changes_detected[slot + 1].append(change_msg)

        if changes_detected:
            subscribers = load_subscribers()
            for chat_id, data in subscribers.items():
                user_equipment = data["equipment"]
                user_message = ""

                for equip in user_equipment:
                    if equip in changes_detected:
                        user_message += "\n".join(changes_detected[equip]) + "\n"

                if user_message:
                    send_telegram_message(chat_id, user_message.strip())

        previous_snapshot = current_snapshot

# Start Flask server and monitoring thread
if __name__ == "__main__":
    from threading import Thread

    # Start monitoring in a separate thread
    Thread(target=monitor_bookings, daemon=True).start()

    # Start Flask server for Telegram webhook
    app.run(host="0.0.0.0", port=5000)