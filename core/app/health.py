"""Health endpoint and reachability probes for the core service.

`GET /api/health` probes Postgres and RabbitMQ and reports each result. All
checks ok -> 200 with status "ok". Any check failing -> 503 with status
"degraded" and that check marked "error". Each probe is wrapped so a failure
is reported as "error" rather than crashing the endpoint.
"""

import asyncpg
import aio_pika
from fastapi import APIRouter, Response, status

from .config import settings

router = APIRouter()

CHECK_OK = "ok"
CHECK_ERROR = "error"


async def check_database() -> str:
    """Open a Postgres connection, run SELECT 1, and close it.

    Returns "ok" on a successful round trip, "error" on any failure.
    """
    connection = None
    try:
        connection = await asyncpg.connect(settings.database_url)
        await connection.execute("SELECT 1")
        return CHECK_OK
    except Exception:
        return CHECK_ERROR
    finally:
        if connection is not None:
            await connection.close()


async def check_broker() -> str:
    """Open and close an AMQP connection to RabbitMQ.

    A full connect/close validates credentials and reachability, not just an
    open TCP port. Returns "ok" on success, "error" on any failure.
    """
    connection = None
    try:
        connection = await aio_pika.connect(settings.rabbitmq_url)
        return CHECK_OK
    except Exception:
        return CHECK_ERROR
    finally:
        if connection is not None:
            await connection.close()


@router.get("/api/health")
async def get_health(response: Response) -> dict:
    """Report DB and broker reachability.

    200 "ok" when both checks pass; 503 "degraded" when any check fails.
    """
    database_status = await check_database()
    broker_status = await check_broker()

    checks = {"db": database_status, "broker": broker_status}
    are_all_checks_ok = all(result == CHECK_OK for result in checks.values())

    if are_all_checks_ok:
        overall_status = "ok"
    else:
        overall_status = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall_status,
        "version": settings.app_version,
        "checks": checks,
    }
