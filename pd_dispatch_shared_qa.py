"""Connect the authenticated staging dashboard to the same local QA API as mobile."""

import http.client
import json
import os
import re

from flask import jsonify, request

from test_sync_server.pd_demo_server import MAX_BODY

_TRIP = re.compile(r"[a-f0-9]{32}")


def register(app, authorized, valid_csrf):
    raw_port = os.environ.get("PD_DISPATCH_SHARED_QA_PORT", "")
    token = os.environ.get("PD_DISPATCH_SHARED_QA_TOKEN", "")
    port = int(raw_port) if re.fullmatch(r"[0-9]{1,5}", raw_port) else 0
    configured = 0 < port <= 65535 and re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token)

    def reply(data, status=200):
        response = jsonify(data)
        response.status_code = status
        response.headers["Cache-Control"] = "private, no-store"
        return response

    def upstream(path, payload=None):
        if not configured:
            return reply({"error": "shared_qa_api_unconfigured"}, 503)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        try:
            connection.request("GET" if body is None else "POST", path, body, headers)
            result = connection.getresponse()
            if result.status in (400, 404, 409):
                return reply({"error": "shared_qa_request_rejected"}, result.status)
            if result.status not in (200, 201):
                return reply({"error": "shared_qa_api_unavailable"}, 503)
            raw = result.read(262145)
            if len(raw) > 262144:
                return reply({"error": "shared_qa_response_too_large"}, 502)
            return reply(json.loads(raw), result.status)
        except (OSError, ValueError, http.client.HTTPException):
            return reply({"error": "shared_qa_api_unavailable"}, 503)
        finally:
            connection.close()

    def write_guard():
        if not authorized():
            return reply({"error": "unauthorized"}, 401)
        if request.content_length is None or request.content_length > MAX_BODY or not valid_csrf():
            return reply({"error": "forbidden"}, 403)
        return None

    @app.get("/dispatch/test-sync/state")
    def pd_shared_qa_state():
        if not authorized():
            return reply({"error": "unauthorized"}, 401)
        return upstream("/v1/dispatch/state")

    @app.post("/dispatch/test-sync/assign")
    def pd_shared_qa_assign():
        denied = write_guard()
        if denied is not None:
            return denied
        trip_id = request.form.get("trip_id", "")
        version = request.form.get("version", "")
        if not _TRIP.fullmatch(trip_id) or not re.fullmatch(r"[0-9]{1,9}", version):
            return reply({"error": "invalid_trip"}, 400)
        return upstream(f"/v1/trips/{trip_id}/assign", {"version": int(version)})

    @app.route("/dispatch/test-sync/trips/<trip_id>/messages", methods=["GET", "POST"])
    def pd_shared_qa_messages(trip_id):
        if not authorized():
            return reply({"error": "unauthorized"}, 401)
        if not _TRIP.fullmatch(trip_id):
            return reply({"error": "invalid_trip"}, 404)
        path = f"/v1/trips/{trip_id}/messages"
        if request.method == "GET":
            return upstream(path)
        denied = write_guard()
        if denied is not None:
            return denied
        return upstream(path, {"text": request.form.get("text", ""),
                               "client_id": request.form.get("client_id", "")})
