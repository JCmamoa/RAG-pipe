from celery import Celery
from celery.signals import setup_logging

from config import settings
from logging_conf import configure_logging

celery_app = Celery("worker", broker=settings.redis_url, backend=settings.redis_url, include=["tasks"])
celery_app.conf.update(
    timezone="UTC",
    task_acks_late=True,                 # só confirma ao terminar: se o worker cair, a tarefa volta
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,        # tarefas pesadas: uma por vez por processo
    task_track_started=True,
    result_expires=3600,
    # Redis reentrega tarefas não confirmadas após o visibility_timeout: precisa ser maior que a
    # tarefa mais longa (OCR de PDFs grandes), senão o mesmo job roda duas vezes.
    broker_transport_options={"visibility_timeout": 7200},
    beat_schedule={"reap-stuck-documents": {"task": "reap_stuck_documents", "schedule": 3600.0}},
)


@setup_logging.connect
def _configure(**_kwargs):
    configure_logging(settings.log_level)
