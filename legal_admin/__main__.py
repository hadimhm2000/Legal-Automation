"""اجرا: python -m legal_admin"""
import logging
import sys

import uvicorn

from legal_bot import config as _cfg  # noqa: F401
from . import settings


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"🛡 پنل مدیریت در http://{settings.HOST}:{settings.PORT} بالا می‌آید "
          f"(پورت‌های ۳۰۰۰ و ۳۱۰۰ آزاد می‌مانند)")
    uvicorn.run("legal_admin.server:app", host=settings.HOST, port=settings.PORT,
                log_level="warning", access_log=False)


if __name__ == "__main__":
    main()

