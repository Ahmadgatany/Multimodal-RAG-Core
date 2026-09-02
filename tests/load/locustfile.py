"""Run: locust -f tests/load/locustfile.py --host http://localhost:8000 -u 30 -r 3 -t 10m."""
import os

from locust import HttpUser, between, task


class RAGUser(HttpUser):
    wait_time = between(1, 4)

    def on_start(self):
        username = f"load-{os.getpid()}-{id(self)}"
        response = self.client.post("/auth/register", json={"username": username, "password": "LoadTest-Only-Password-123"})
        if response.status_code == 200:
            login = self.client.post("/auth/login", json={"username": username, "password": "LoadTest-Only-Password-123"})
            self.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        else:
            self.headers = {}

    @task(4)
    def chat(self):
        self.client.post("/chat", json={"question": "What documents are available?", "k": 3}, headers=self.headers, name="/chat")

    @task(1)
    def upload(self):
        self.client.post("/upload_file", files={"file": ("load.txt", b"This is a load-test document about RAG retrieval.", "text/plain")}, headers=self.headers, name="/upload_file")
