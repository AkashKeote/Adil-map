from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response

# Import the Flask app from server.py
try:
    from server import app as flask_app
except Exception as e:
    # Minimal fallback app so deployment doesn't crash
    from flask import Flask, jsonify
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def _fallback_home():
        return jsonify({
            "message": "Backend failed to import server.py",
            "error": str(e)
        }), 500


# Vercel expects a WSGI callable named 'app'
app = flask_app


