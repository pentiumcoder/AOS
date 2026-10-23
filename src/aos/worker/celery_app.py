from celery import Celery
from celery.signals import setup_logging as celery_setup_logging
from celery.signals import worker_init

from aos.config import get_settings
from aos.logging import setup_logging

settings = get_settings()

celery_app = Celery("aos", broker=settings.redis_url, include=["aos.worker.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_default_queue="aos",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
)


@celery_setup_logging.connect
def _configure_logging(**_: object) -> None:
    setup_logging(settings.log_level)


@worker_init.connect
def _init_worker(**_: object) -> None:
    from aos.db import init_db
    from aos.db.session import dispose

    init_db()
    # Forked pool children must open their own connections.
    dispose()
