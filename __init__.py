import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, g, request
import uuid

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

    from .routes import main

    app.register_blueprint(main)

    @app.before_request
    def attach_request_id():
        g.request_id = uuid.uuid4().hex[:10]

    @app.after_request
    def log_request(response):
        logging.info("request_id=%s method=%s path=%s status=%s", g.request_id, request.method, request.path, response.status_code)
        response.headers["X-AVA-Request-ID"] = g.request_id
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "ava"}), 200

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        logging.exception("Unhandled Flask exception")
        return jsonify({"error": "Internal server error", "request_id": g.request_id}), 500


    return app
