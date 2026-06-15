"""MoneyLine HTTP/WebSocket API package."""

__all__ = ["app"]


def __getattr__(name: str):
    if name == "app":
        from moneyline.api.app import app

        return app
    raise AttributeError(name)
