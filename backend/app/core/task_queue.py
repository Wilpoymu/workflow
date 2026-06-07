import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_executor = ThreadPoolExecutor(max_workers=2)

async def run_in_thread(fn: Callable[..., Any], *args: Any) -> Any:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)
