"""AMFI v4 — Shared slowapi rate limiter instance.

Import this in any router that needs per-endpoint rate limiting.
The global app.state.limiter is set in main.py.

Usage in a route:
    from backend.utils.rate_limit import limiter

    @router.post("/login")
    @limiter.limit("10/minute")
    async def login(request: Request, ...):
        ...
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# No default_limits — we apply limits per-endpoint only.
# This avoids slowing down every request with a rate-check overhead
# and won't trip up dev/test workloads that hammer a single IP.
limiter = Limiter(key_func=get_remote_address)
