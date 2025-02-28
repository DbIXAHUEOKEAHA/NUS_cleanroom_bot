import requests
from flask import Flask, request
import os

SUBSCRIBERS_FILE = "subscribers.txt"

# Flask app setup
app = Flask(__name__)

# Function to send messages
def send_telegram_message(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    requests.post(url, json=payload)

# Function to add new subscribers
def add_subscriber(chat_id):
    with open(SUBSCRIBERS_FILE, "a+") as f:
        f.seek(0)
        subscribers = f.read().splitlines()
        if str(chat_id) not in subscribers:
            f.write(str(chat_id) + "\n")
            send_telegram_message(chat_id, "✅ You are now subscribed to booking updates!")

# Function to get all subscribers
def get_subscribers():
    with open(SUBSCRIBERS_FILE, "r") as f:
        return f.read().splitlines()

# Webhook endpoint for Telegram
@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.json
    chat_id = data["message"]["chat"]["id"]
    text = data["message"]["text"]

    if text == "/start":
        add_subscriber(chat_id)
        return {"ok": True}

    return {"ok": True}

# Function to broadcast updates to all subscribers
def broadcast_update(message):
    subscribers = get_subscribers()
    for chat_id in subscribers:
        send_telegram_message(chat_id, message)

# Run the Flask app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))