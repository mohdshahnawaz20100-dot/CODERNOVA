import os
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running!"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    8951234836:AAH2P6ZBcCBSMbPoy1l4dvIu7FeQP-pYCDo
