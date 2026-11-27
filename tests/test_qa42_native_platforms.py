import json
import uuid
from werkzeug.test import Client
from werkzeug.wrappers import Response
from ops.qa.qa42_local_https import prepare

def test_native_platforms():
    app, tokens, dispatch, _ = prepare()
    client = Client(app, Response)
    headers = {"Authorization": "Bearer " + tokens["passenger"]}
    ids = {}
    for platform in ("android", "ios", "website"):
        payload = {"request_id": str(uuid.uuid4()), "from": "Synthetic A",
                   "to": "Synthetic B", "trip_date": "2030-01-01", "trip_time": "12:00"}
        response = client.post("/native-orders", json=payload,
            headers={**headers, "X-PD-Native-Platform": platform})
        if platform == "website":
            assert response.status_code == 400
        else:
            assert response.status_code == 201, response.get_data(as_text=True)
            ids[platform] = response.json["order_id"]
            again = client.post("/native-orders", json=payload,
                headers={**headers, "X-PD-Native-Platform": platform})
            assert again.status_code == 200
            assert again.json["order_id"] == ids[platform]
    queue = client.get("/dispatch/orders/state", headers={"X-Telegram-Init-Data": dispatch})
    assert queue.status_code == 200
    assert {row["source"]: row["id"] for row in queue.json["orders"]} == ids
