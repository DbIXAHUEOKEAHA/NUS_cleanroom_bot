import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time

sleep_time = 30

# Telegram Bot Credentials (replace with your actual token & chat ID)
TELEGRAM_BOT_TOKEN = "8064663105:AAE7RFqr0CO6dXYxRN9IHH9Cz3aE1MRPis0"  # <-- Replace with your Bot Token
TELEGRAM_CHAT_ID = "491743114"  # <-- Replace with your Chat ID

# Function to send message to Telegram
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, json=payload)

# Function to generate today's booking URL
def get_today_url():
    today = datetime.today().strftime("%Y-%m-%d")
    return f"https://www.mnff.com.sg/index.php/booking/calendar/{today}/1"

# Function to extract the 9th row from each table
def extract_booking_table():
    url = get_today_url()
    response = requests.get(url)

    if response.status_code != 200:
        print(f"Failed to retrieve page. Status code: {response.status_code}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")

    extracted_rows = []
    for day_index, table in enumerate(tables):
        rows = table.find_all("tr")
        if len(rows) >= 9:
            cols = rows[8].find_all(["th", "td"])
            row_data = []
            for col in cols:
                colspan = int(col.get("colspan", 1))
                cell_text = col.text.strip()
                row_data.extend([cell_text] * colspan)
            extracted_rows.append(row_data)

    return extracted_rows if extracted_rows else None

# Monitoring loop
previous_snapshot = extract_booking_table()
if previous_snapshot is None:
    send_telegram_message("⚠️ Failed to fetch initial booking data. Monitoring stopped.")
    exit()

send_telegram_message(f"✅ Monitoring started for {datetime.today().strftime('%Y-%m-%d')}.")

while True:
    time.sleep(sleep_time)

    current_snapshot = extract_booking_table()
    if current_snapshot is None:
        send_telegram_message("⚠️ Failed to fetch data. Skipping this check...")
        continue

    # Compare snapshots and send updates to Telegram
    changes_detected = False
    message = ""

    for day in range(len(previous_snapshot)):
        for slot in range(len(previous_snapshot[day])):
            prev = previous_snapshot[day][slot]
            curr = current_snapshot[day][slot]

            if prev and not curr:
                message += f"🔴 Cancellation: {prev} removed on Day {day + 1}, Time Slot {slot}\n"
                changes_detected = True
            elif not prev and curr:
                message += f"🟢 New Booking: {curr} added on Day {day + 1}, Time Slot {slot}\n"
                changes_detected = True

    if changes_detected:
        send_telegram_message(message.strip())

    # Update snapshot
    previous_snapshot = current_snapshot