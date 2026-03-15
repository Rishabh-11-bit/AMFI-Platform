"""Run AMFI Platform."""
import uvicorn
from backend.config import get_settings

settings = get_settings()

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level="info",
    )
