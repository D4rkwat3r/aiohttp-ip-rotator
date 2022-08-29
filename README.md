# aiohttp-ip-rotator
An asynchronous alternative to the requests-ip-rotator  (https://github.com/Ge0rg3/requests-ip-rotator) library based on aiohttp, completely copying its functionality

## Example
```python3
from asyncio import get_event_loop
from aiohttp_ip_rotator import RotatingClientSession


async def main():
    session = RotatingClientSession("https://api.ipify.org", "aws access key id", "aws access key secret")
    await session.start()
    for i in range(5):
        response = await session.get("https://api.ipify.org")
        print(f"Your ip: {await response.text()}")
    await session.close()


if __name__ == "__main__":
    get_event_loop().run_until_complete(main())
```
## Example 2
```python3
from asyncio import get_event_loop
from aiohttp_ip_rotator import RotatingClientSession


async def main():
    async with RotatingClientSession(
        "https://api.ipify.org",
        "aws access key id",
        "aws access key secret"
    ) as session:
        for i in range(5):
            response = await session.get("https://api.ipify.org")
            print(f"Your ip: {await response.text()}")


if __name__ == "__main__":
    get_event_loop().run_until_complete(main())
```
