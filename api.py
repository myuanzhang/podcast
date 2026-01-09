import asyncio
import threading

from flask import Flask, jsonify, request
from flask_cors import CORS
from waitress import serve

from workflow import run_workflow
from logging_utils import configure_logging, log_error, log_info, log_warning

app = Flask(__name__)
CORS(app)

_COMPONENT = "api"


configure_logging()


@app.route("/healthz", methods=["GET"])
def healthz():
    """
    Simple health check endpoint to verify the server is running.
    Returns 200 OK with a JSON payload.
    """
    return jsonify({"status": "ok", "message": "Agentic API is healthy"}), 200


@app.route("/run_workflow", methods=["POST"])
def ask_agent():
    # Support both form-data (with file) and application/json
    user_id = request.json.get("user_id")
    topic = request.json.get("topic")
    days = request.json.get("days")
    args = request.json.get("args")

    if not user_id:
        log_warning("api.request.missing_user_id", component=_COMPONENT, topic=topic, days=days, args=args)
        return jsonify({"error": "user_id is required"}), 400

    if not topic:
        log_warning("api.request.missing_topic", component=_COMPONENT, user_id=user_id, days=days, args=args)
        return jsonify({"error": "topic is required"}), 400

    # normalize args to list (handle string, list, or None)
    if args is None:
        args_list = None
    elif isinstance(args, str):
        parsed = [u.strip() for u in args.split(",") if u.strip()]
        args_list = parsed or None
    elif isinstance(args, list):
        args_list = [str(u).strip() for u in args if str(u).strip()] or None
    else:
        # if user sends something unexpected (like a number), fallback to default behaviour
        args_list = None

    log_info(
        "api.request.received",
        component=_COMPONENT,
        user_id=user_id,
        topic=topic,
        days=days,
        args=args_list,
    )

    def bg_task(topic, days, args):
        try:
            kwargs = {"topic": topic, "days": days}
            if args is not None:
                kwargs["urls"] = args
            asyncio.run(run_workflow(**kwargs))
        except Exception as e:
            log_error(
                "api.workflow.exception",
                component=_COMPONENT,
                exc=e,
                user_id=user_id,
                topic=topic,
                days=days,
                args=args,
            )

    threading.Thread(target=bg_task, args=(topic, days, args_list), daemon=True).start()
    log_info("api.workflow.started", component=_COMPONENT, user_id=user_id, topic=topic)
    return jsonify({"result": "Workflow started"}), 202


if __name__ == "__main__":
    log_info("api.server.start", component=_COMPONENT, port=5004)
    serve(app, listen='*:5004')
