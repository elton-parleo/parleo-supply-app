# main.py
import logging
import uvicorn
from api.api import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

if __name__ == "__main__":
    # log_config=None prevents uvicorn from overriding our logging setup
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)