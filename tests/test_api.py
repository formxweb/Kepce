"""Uçtan uca test: gerçek sunucu + sahte indirici (Instagram'a bağlanmaz)."""
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from app import config
from app.downloader import MSG_PRIVATE, FakeDownloader
from app.main import RateLimiter, client_ip, create_app

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = create_app(downloader=FakeDownloader(speed=0.04), data_dir=Path(cls.tmp.name),
                             ttl_seconds=600)
        cls.base = f"http://127.0.0.1:{free_port()}"
        port = int(cls.base.rsplit(":", 1)[1])
        cls.server = uvicorn.Server(uvicorn.Config(cls.app, host="127.0.0.1", port=port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 10
        while not cls.server.started and time.time() < deadline:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.tmp.cleanup()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with OPENER.open(req, timeout=15) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def create(self, urls):
        status, _, raw = self.call("POST", "/api/jobs", {"urls": urls})
        return status, json.loads(raw)

    def wait(self, job_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, _, raw = self.call("GET", f"/api/jobs/{job_id}")
            job = json.loads(raw)
            if job["finished"]:
                return job
            time.sleep(0.1)
        self.fail("liste zamanında bitmedi")

    # --- testler -------------------------------------------------------
    def test_index_page(self):
        status, headers, raw = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("kepçe", raw.decode())
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_full_flow(self):
        status, job = self.create([
            "https://www.instagram.com/reel/ABCdef12345/?igsh=xyz",
            "instagram.com/p/coklu12345",
            "https://www.instagram.com/reel/gizli12345/",
            "https://www.instagram.com/reels/ABCdef12345/",  # tekrar
        ])
        self.assertEqual(status, 201)
        self.assertEqual([i["code"] for i in job["items"]], ["ABCdef12345", "coklu12345", "gizli12345"])

        job = self.wait(job["id"])
        single, multi, private = job["items"]
        self.assertEqual(single["status"], "done")
        self.assertEqual(single["progress"], 100)
        self.assertEqual(single["owner"], "demo_hesap")
        self.assertEqual([f["name"] for f in single["files"]], ["instagram_ABCdef12345.mp4"])
        self.assertEqual([f["name"] for f in multi["files"]],
                         ["instagram_coklu12345_1.mp4", "instagram_coklu12345_2.mp4"])
        self.assertEqual(private["status"], "error")
        self.assertEqual(private["error"], MSG_PRIVATE)
        self.assertTrue(private["can_retry"])

        # Tek video
        status, headers, raw = self.call("GET", single["files"][0]["url"])
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "video/mp4")
        self.assertIn('attachment; filename="instagram_ABCdef12345.mp4"', headers["Content-Disposition"])
        self.assertEqual(raw[4:8], b"ftyp")

        # Küçük resim
        status, headers, raw = self.call("GET", single["files"][0]["thumb"])
        self.assertEqual(status, 200)
        self.assertTrue(raw.startswith(b"\xff\xd8"))

        # Çoklu gönderinin her videosu ayrı MP4 olarak iner
        for f in multi["files"]:
            status, headers, raw = self.call("GET", f["url"])
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "video/mp4")
            self.assertIn(f'filename="{f["name"]}"', headers["Content-Disposition"])
            self.assertEqual(raw[4:8], b"ftyp")

        # ZIP ucu artık yok
        status, _, _ = self.call("GET", f"/api/jobs/{job['id']}/zip")
        self.assertEqual(status, 404)

        # Olmayan dosya numarası
        status, _, _ = self.call("GET", f"/api/jobs/{job['id']}/items/1/files/9")
        self.assertEqual(status, 404)

        # Başarısız linki yeniden dene: 3 denemeden sonra durmalı
        retry_path = f"/api/jobs/{job['id']}/items/{private['id']}/retry"
        for _ in range(config.MAX_ATTEMPTS - 1):
            status, _, _ = self.call("POST", retry_path)
            self.assertEqual(status, 200)
            job = self.wait(job["id"])
        self.assertFalse(job["items"][2]["can_retry"])
        status, _, raw = self.call("POST", retry_path)
        self.assertEqual(status, 409)

        # Hazır videoyu yeniden deneme olmaz
        status, _, _ = self.call("POST", f"/api/jobs/{job['id']}/items/1/retry")
        self.assertEqual(status, 409)

    def test_too_many_links(self):
        urls = [f"https://www.instagram.com/reel/CODE{n:06d}/" for n in range(21)]
        status, body = self.create(urls)
        self.assertEqual(status, 422)
        self.assertIn("20", body["error"])

    def test_no_valid_links(self):
        status, body = self.create(["https://www.youtube.com/watch?v=abc", "selam"])
        self.assertEqual(status, 422)
        self.assertIn("Instagram", body["error"])

    def test_bad_body(self):
        status, _, _ = self.call("POST", "/api/jobs", {"urls": "tek-metin"})
        self.assertEqual(status, 400)

    def test_unknown_job(self):
        status, _, raw = self.call("GET", "/api/jobs/yok-boyle-bir-liste")
        self.assertEqual(status, 404)
        status, _, _ = self.call("GET", "/api/jobs/yok/items/1/files/0")
        self.assertEqual(status, 404)

    def test_path_traversal(self):
        status, _, raw = self.call("GET", "/..%2F..%2Fetc%2Fpasswd")
        self.assertEqual(status, 404)
        self.assertNotIn(b"root:", raw)

    def test_zz_cleanup(self):
        status, job = self.create(["https://www.instagram.com/reel/TEMIZLIK01/"])
        self.assertEqual(status, 201)
        self.wait(job["id"])
        store = self.app.state.store
        job_dir = store.jobs[job["id"]].dir
        self.assertTrue(job_dir.exists())
        store.cleanup(now=time.time() + 601)
        self.assertFalse(job_dir.exists())
        status, _, _ = self.call("GET", f"/api/jobs/{job['id']}")
        self.assertEqual(status, 404)


class RateLimitTest(unittest.TestCase):
    def test_limit(self):
        rl = RateLimiter(limit=2, window_seconds=3600)
        self.assertTrue(rl.allow("1.2.3.4")[0])
        self.assertTrue(rl.allow("1.2.3.4")[0])
        allowed, wait = rl.allow("1.2.3.4")
        self.assertFalse(allowed)
        self.assertGreater(wait, 3500)
        self.assertTrue(rl.allow("5.6.7.8")[0])

    def test_client_ip_uses_rightmost_forwarded(self):
        class Req:
            headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}
            client = type("C", (), {"host": "10.0.0.1"})()
        old = config.TRUST_PROXY
        try:
            config.TRUST_PROXY = True
            self.assertEqual(client_ip(Req()), "203.0.113.9")
            config.TRUST_PROXY = False
            self.assertEqual(client_ip(Req()), "10.0.0.1")
        finally:
            config.TRUST_PROXY = old


if __name__ == "__main__":
    unittest.main()
