from celery import Celery

from .config import settings

# Cliente só para publicar tarefas (o código das tasks vive no serviço worker).
celery_client = Celery("api", broker=settings.redis_url)
