from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.auth.security import hash_password
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import User, UserRole
from app.routers import auth, health, kb, llm, metrics, operations, tasks, users, workflows

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _seed_on_startup()
    yield


_SEED_DOMAINS = [
    ("Finance", "Financial policies, budgets, CFO guardrails, vendor approvals, and ROI requirements"),
    ("HR", "Human resources policies, onboarding, headcount planning, compensation, and performance management"),
    ("Operations", "Operational SOPs, process guides, supply chain, facilities, and project delivery standards"),
    ("Legal", "Compliance requirements, contract templates, regulatory guidelines, and risk policies"),
    ("Sales", "Sales pipeline processes, revenue targets, CRM guidelines, and customer engagement playbooks"),
]


async def _seed_on_startup() -> None:
    """Create the default client, admin user, and KB domains if they do not already exist."""
    async with AsyncSessionLocal() as session:
        try:
            # Default client
            await session.execute(
                text(
                    """
                    INSERT INTO clients (name)
                    VALUES (:name)
                    ON CONFLICT (name) DO NOTHING
                    """
                ),
                {"name": "Default Client"},
            )
            await session.commit()

            # Admin user
            existing = await session.execute(
                select(User).where(User.role == UserRole.admin)
            )
            if existing.scalar_one_or_none() is None:
                admin = User(
                    email=settings.seed_admin_email,
                    full_name=settings.seed_admin_name,
                    hashed_password=hash_password(settings.seed_admin_password),
                    role=UserRole.admin,
                    is_active=True,
                )
                session.add(admin)
                await session.commit()

            # KB domains for the Default Client
            client_row = await session.execute(
                text("SELECT id FROM clients WHERE name = 'Default Client'")
            )
            client_id = client_row.scalar_one()
            for domain_name, domain_desc in _SEED_DOMAINS:
                await session.execute(
                    text(
                        """
                        INSERT INTO kb_domains (client_id, name, description, is_active)
                        VALUES (:client_id, :name, :description, true)
                        ON CONFLICT (client_id, name) DO NOTHING
                        """
                    ),
                    {"client_id": str(client_id), "name": domain_name, "description": domain_desc},
                )
            await session.commit()
        except Exception:
            await session.rollback()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(kb.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(metrics.router)
app.include_router(operations.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(workflows.router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok"}
