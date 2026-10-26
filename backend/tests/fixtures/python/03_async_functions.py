"""Async top-level function and async method."""


async def fetch_data(url):
    result = await call_remote(url)
    return result


class Client:
    async def connect(self):
        await self.open_socket()
        return True
