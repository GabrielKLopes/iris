import keyring

SERVICE = "iris"
ANTHROPIC_KEY = "anthropic_api_key"
TYPESAFE_KEY = "typesafe_api_key"
TAVILY_KEY = "tavily_api_key"
BRAVE_KEY = "brave_api_key"


PROVIDERS = {
    "anthropic": (ANTHROPIC_KEY, "console.anthropic.com"),
    "tavily": (TAVILY_KEY, "tavily.com"),
    "brave": (BRAVE_KEY, "brave.com/search/api"),
}


def delete_secret(name: str) -> bool:
    try:
        keyring.delete_password(SERVICE, name)
        return True
    except keyring.errors.PasswordDeleteError:
        return False


def masked(value: str | None) -> str:
    if not value:
        return ""
    return f"{value[:6]}…{value[-4:]}" if len(value) > 12 else "…"


def get_secret(name: str) -> str | None:
    return keyring.get_password(SERVICE, name)


def set_secret(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value)
