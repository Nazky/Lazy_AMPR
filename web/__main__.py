"""Run the Lazy_AMPR web front end: python -m web"""
import os

import uvicorn

from utils.logging_utils import setup_logging


def main():
    setup_logging()
    uvicorn.run(
        "web.app:app",
        host=os.environ.get("LAZY_AMPR_HOST", "0.0.0.0"),  # nosec B104 - container service
        port=int(os.environ.get("LAZY_AMPR_PORT", "8080")),
        proxy_headers=True,
        log_level=os.environ.get("LAZY_AMPR_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
