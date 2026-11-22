"""WSGI entry point and local Socket.IO server."""
import os

from netmon.web import create_app, socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")),
        debug=False, allow_unsafe_werkzeug=True)
