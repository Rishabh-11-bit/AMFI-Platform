"""
AMFI Agent v4 - Single command start
Run: python run.py
"""
import sys
import os
import asyncio
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    print("\n" + "="*52)
    print("  AMFI Agent v4 — Autonomous NOC Agent")
    print("="*52)

    # Load settings
    try:
        from backend.config import get_settings
        settings = get_settings()
    except Exception as e:
        print(f"\nERROR: Cannot load settings: {e}")
        print("Make sure .env file exists. Copy from .env.example")
        sys.exit(1)

    print(f"\n  Port:     {settings.api_port}")
    print(f"  Database: {settings.database_url.split('@')[-1]}")
    print(f"  AI:       {'Claude API' if settings.anthropic_api_key else f'Ollama ({settings.ollama_model})'}")
    print(f"  NMS poll: every {settings.nms_poll_seconds}s")
    print("\n  Starting...")

    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host      = settings.api_host,
        port      = settings.api_port,
        reload    = settings.debug,
        log_level = "info",
    )

if __name__ == "__main__":
    main()
