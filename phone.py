###############################################
# phone.py - the web chat page for your phone
# The look and layout live in phone_page.html
###############################################

import os
import socket
import threading

from flask import request as flask_request, jsonify, Response

import config

log = []
log_lock = threading.Lock()

PAGE_FILE = os.path.join(config.BASE_DIR, "phone_page.html")


def local_ip():
    """Work out this machine's address on the home network."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_page():
    try:
        with open(PAGE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<h1>phone_page.html is missing</h1><p>{e}</p>"


def authorised(supplied):
    return supplied == config.PHONE_PASSWORD


def register(app, responder):
    """
    Wire the phone routes onto the Flask app.
    'responder' is the function that turns a message into a reply.
    """

    @app.route('/', methods=['GET'])
    def phone_page():
        return Response(load_page(), mimetype='text/html')

    @app.route('/history', methods=['GET'])
    def phone_history():
        if not authorised(flask_request.args.get('p', '')):
            return jsonify({"error": "no"}), 403
        with log_lock:
            return jsonify({"lines": list(log[-40:])})

    @app.route('/say', methods=['POST'])
    def phone_say():
        data = flask_request.get_json(silent=True) or {}
        if not authorised(str(data.get("password", ""))):
            return jsonify({"error": "no"}), 403

        message = str(data.get("message", "")).strip()
        if not message:
            return jsonify({"reply": ""})

        print(f"\n>> {config.PHONE_USER} (phone): {message}")
        reply = responder(config.PHONE_USER, message, True) or ""

        with log_lock:
            log.append({"who": "me", "text": message})
            log.append({"who": "her", "text": reply})
            del log[:-80]

        return jsonify({"reply": reply})


def banner():
    ip = local_ip()
    print()
    print("-" * 50)
    print("  PHONE CHAT")
    print(f"  On your phone, open:  http://{ip}:{config.LISTEN_PORT}")
    print(f"  Password: {config.PHONE_PASSWORD}")
    print("-" * 50)
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(f"http://{ip}:{config.LISTEN_PORT}")
        qr.make()
        qr.print_ascii(invert=True)
    except ImportError:
        print("  (for a scannable QR code: pip install qrcode)")
    except Exception:
        pass
    print()