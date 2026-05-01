from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "manage_ai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.celery_tasks"],
)

celery_app.conf.task_queues = {
    "default": {"exchange": "default", "routing_key": "default"},
    "tasks.hr": {"exchange": "tasks", "routing_key": "tasks.hr"},
    "tasks.finance": {"exchange": "tasks", "routing_key": "tasks.finance"},
    "tasks.operations": {"exchange": "tasks", "routing_key": "tasks.operations"},
    "tasks.legal": {"exchange": "tasks", "routing_key": "tasks.legal"},
    "tasks.sales": {"exchange": "tasks", "routing_key": "tasks.sales"},
}

celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

_DEPARTMENT_QUEUE_MAP: dict[str, str] = {
    "hr": "tasks.hr",
    "human resources": "tasks.hr",
    "finance": "tasks.finance",
    "accounting": "tasks.finance",
    "operations": "tasks.operations",
    "ops": "tasks.operations",
    "legal": "tasks.legal",
    "compliance": "tasks.legal",
    "sales": "tasks.sales",
    "marketing": "tasks.sales",
}


def queue_for_department(department: str) -> str:
    """Return the Celery queue name for a given department label."""
    return _DEPARTMENT_QUEUE_MAP.get(department.lower().strip(), "default")


celery_app.conf.beat_schedule = {
    "approval-expiry-check": {
        "task": "app.celery_tasks.check_approval_expiry",
        "schedule": 300.0,
    },
}
celery_app.conf.timezone = "UTC"
