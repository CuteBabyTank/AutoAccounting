"""Bound streamed request bodies before handing bytes to the body parser."""

from collections.abc import Awaitable, Callable

Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int, multipart_max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.multipart_max_bytes = multipart_max_bytes

    async def __call__(self, scope: dict, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Starlette reads the first Content-Type; refuse duplicates so the limit and the parser agree.
        types = [v for k, v in scope.get("headers", []) if k.lower() == b"content-type"]
        if len(types) > 1:
            body = b'{"detail":"Duplicate Content-Type header"}'
            await send({"type": "http.response.start", "status": 400, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        multipart = (types[0] if types else b"").lower().startswith(b"multipart/form-data")
        limit = self.multipart_max_bytes if multipart else self.max_bytes
        received = 0
        exceeded = rejected = started = False

        async def reject() -> None:
            nonlocal rejected
            if rejected:
                return
            if started:
                raise _BodyTooLarge()  # a streaming response has already sent its status
            rejected = True
            body = b'{"detail":"Request body too large"}'
            await send({"type": "http.response.start", "status": 413, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        async def limited_receive() -> dict:
            nonlocal received, exceeded
            if exceeded:
                raise _BodyTooLarge()
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLarge()
            return message

        async def limited_send(message: dict) -> None:
            nonlocal started
            # Some parsers turn receive errors into 400s; keep the actual 413.
            if exceeded:
                await reject()
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except Exception:
            if not exceeded:
                raise
            await reject()

