import logging

BROWSER_TITLES = ("Google Chrome", "Microsoft Edge", "Brave", "Mozilla Firefox", "Opera")


def _address(window) -> str | None:
    edit = window.EditControl(searchDepth=16)
    if not edit.Exists(maxSearchSeconds=1.5):
        return None
    value = edit.GetValuePattern().Value.strip()
    if not value or " " in value or "." not in value:
        return None
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


def current_browser_url() -> str | None:
    import uiautomation as auto

    try:
        with auto.UIAutomationInitializerInThread():
            foreground = auto.GetForegroundControl()
            windows = [foreground.GetTopLevelControl()] if foreground else []
            windows += auto.GetRootControl().GetChildren()
            for window in windows:
                if window and any(title in (window.Name or "") for title in BROWSER_TITLES):
                    url = _address(window)
                    if url:
                        return url
    except Exception as exc:
        logging.warning("Could not read the browser address: %s", exc)
    return None
