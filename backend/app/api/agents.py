import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.deps import DB, CurrentUser
from app.core.errors import ApiError, not_found
from app.models import Agent
from app.schemas import AgentIn, AgentOut, AgentPatch

router = APIRouter(prefix="/agents", tags=["agents"])
MAX_AGENTS = 100


async def _owned(db: DB, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.user_id != user_id:
        raise not_found("agent")
    return agent


@router.get("", response_model=list[AgentOut])
async def list_agents(db: DB, user: CurrentUser) -> list[Agent]:
    return list(
        (await db.scalars(select(Agent).where(Agent.user_id == user.id).order_by(Agent.created_at))).all()
    )


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(body: AgentIn, db: DB, user: CurrentUser) -> Agent:
    count = await db.scalar(select(func.count()).select_from(Agent).where(Agent.user_id == user.id))
    if (count or 0) >= MAX_AGENTS:
        raise ApiError(400, "too_many_agents", "Batas jumlah agent tercapai.")
    agent = Agent(user_id=user.id, **body.model_dump())
    db.add(agent)
    await db.commit()
    return agent


@router.patch("/{agent_id}", response_model=AgentOut)
async def patch_agent(agent_id: uuid.UUID, body: AgentPatch, db: DB, user: CurrentUser) -> Agent:
    agent = await _owned(db, user.id, agent_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(agent, field, value)
    await db.commit()
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    agent = await _owned(db, user.id, agent_id)
    await db.delete(agent)
    await db.commit()
