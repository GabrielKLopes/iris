import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

VOSK_MODEL_NAME = "vosk-model-small-pt-0.3"


def _default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "iris"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IRIS_",
        env_file=(".env", str(_default_data_dir() / "settings.env")),
        extra="ignore",
    )

    llm_backend: str = "auto"
    llm_model: str = "haiku"
    api_model: str = "claude-haiku-4-5-20251001"
    max_steps: int = 8
    data_dir: Path = _default_data_dir()
    app_executable: Path | None = None
    voice_cooldown_seconds: float = 5.0
    language: str = "en"
    voice_name: str = ""
    whisper_model: str = "base"
    user_name: str = ""
    local_model: str = "iris-1"
    ollama_host: str = "http://127.0.0.1:11434"
    input_device: str | None = None
    output_device: str | None = None
    library_vectors: bool = True
    search_provider: str = "auto"
    searxng_url: str = ""

    @property
    def dataset_file(self) -> Path:
        return self.data_dir / "dataset" / "interactions.jsonl"

    @property
    def dataset_db(self) -> Path:
        return self.data_dir / "dataset" / "iris.db"

    @property
    def memory_file(self) -> Path:
        return self.data_dir / "memory" / "facts.db"

    @property
    def library_db(self) -> Path:
        return self.data_dir / "knowledge" / "library.db"

    @property
    def voice(self) -> str:
        if self.voice_name:
            return self.voice_name
        return "pt-BR-FranciscaNeural" if self.language.lower().startswith("pt") else "en-US-AvaNeural"

    @property
    def usage_db(self) -> Path:
        return self.data_dir / "usage" / "usage.db"

    @property
    def embedding_cache(self) -> Path:
        return self.data_dir / "models" / "fastembed"

    @property
    def agent_workdir(self) -> Path:
        return self.data_dir / "workdir"

    @property
    def voice_model_dir(self) -> Path:
        return self.data_dir / "models" / VOSK_MODEL_NAME

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.env"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"
