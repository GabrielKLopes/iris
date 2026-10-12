from typing import Any

import httpx


class JevClient:
    def __init__(self, api_key: str, model: str = "jev-latest", base_url: str = "https://api.typesafe.ai", timeout: float = 2.0):
        self.model = model
        self.client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    def decide(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        response = self.client.post("/v1/systemone", json={"state": state, "model": self.model, "questions": questions})
        response.raise_for_status()
        return response.json()["answers"]
