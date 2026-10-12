import keyring

SERVICE = "iris"
ANTHROPIC_KEY = "anthropic_api_key"
TYPESAFE_KEY = "typesafe_api_key"
TAVILY_KEY = "tavily_api_key"
BRAVE_KEY = "brave_api_key"


def get_secret(name: str) -> str | None:
    return keyring.get_password(SERVICE, name)


def set_secret(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value)
