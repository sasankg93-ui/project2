"""Run: API_KEY=... locust -f loadtest/locustfile.py --host http://localhost:8000
Each virtual user: presign -> PUT a small JPEG to S3 -> create job -> poll until finished."""
import io
import os
import time

import requests
from locust import HttpUser, between, task
from PIL import Image

API_KEY = os.environ.get("API_KEY", "change-me")


def make_jpeg(size=(1600, 1200)) -> bytes:
    buf = io.BytesIO()
    Image.effect_noise(size, 40).convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue()


class MediaUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.client.headers["X-API-Key"] = API_KEY
        self.payload = make_jpeg()

    @task
    def image_flow(self):
        r = self.client.post("/v1/uploads/presign", name="presign", json={
            "filename": "load.jpg", "content_type": "image/jpeg", "size_bytes": len(self.payload)})
        if r.status_code != 200:
            return
        p = r.json()
        put = requests.put(p["upload_url"], data=self.payload, headers=p["headers"], timeout=60)
        if put.status_code >= 300:
            return
        r = self.client.post("/v1/jobs", name="create job", json={
            "source_key": p["source_key"], "media_type": "image",
            "image": {"width": 800, "quality": 80}})
        if r.status_code != 202:
            return
        job_id, start = r.json()["job_id"], time.time()
        while time.time() - start < 120:
            time.sleep(1)
            st = self.client.get(f"/v1/jobs/{job_id}", name="/v1/jobs/[id]").json()["status"]
            if st in ("completed", "failed"):
                self.environment.events.request.fire(
                    request_type="E2E", name=f"job {st}", response_time=(time.time() - start) * 1000,
                    response_length=0, exception=None if st == "completed" else Exception("failed"),
                    context={})
                return
