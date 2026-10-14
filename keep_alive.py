import os
from flask import Flask
from threading import Thread

app = Flask(__name__)


@app.route("/")
def home():
    return "TopBot is online", 200


def _run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def keep_alive():
    t = Thread(target=_run, daemon=True)
    t.start()
