import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.encryption import KeyCipher
from app.db.base import as_utc, utcnow
from app.models import Job, KeyStatus, ProviderKey, UsageLog
from app.services.jobs import due_waiting_jobs
from app.services.key_pool import CONTINUE_PROMPT, KeyPool, recover_keys
from tests.conftest import ScriptedLLM, make_runner, register, send, setup_provider


async def _job(sessions, job_id):
    async with sessions() as s:
        return await s.get(Job, uuid.UUID(job_id))


async def _key(sessions, key_id):
    async with sessions() as s:
        return await s.get(ProviderKey, uuid.UUID(key_id))


async def _usage(sessions):
    async with sessions() as s:
        return (await s.scalars(select(UsageLog).order_by(UsageLog.created_at))).all()


async def test_429_on_key_a_rotates_to_key_b(client, sessions, runner, llm):
    headers = await register(client)
    provider = await setup_provider(client, headers, ["rl-aaaaaaaa", "ok-bbbbbbbb"])
    _, job_id = await send(client, headers, model="mock/mock-strong")
    assert await runner.run(uuid.UUID(job_id)) == "done"

    key_a = await _key(sessions, provider["key_ids"][0])
    assert key_a.status == KeyStatus.cooling_down
    assert as_utc(key_a.cooldown_until) > utcnow() + timedelta(seconds=20)
    usage = await _usage(sessions)
    assert str(usage[0].provider_key_id) == provider["key_ids"][1]
    job = await _job(sessions, job_id)
    assert job.partial_output == "halo dari model palsu"
    assert [c.api_key for c in llm.calls] == ["rl-aaaaaaaa", "ok-bbbbbbbb"]


async def test_quota_and_invalid_statuses(client, sessions, runner, notifier):
    headers = await register(client)
    provider = await setup_provider(client, headers, ["quota-aaaaaa", "bad-bbbbbbbb", "ok-cccccccc"])
    _, job_id = await send(client, headers)
    assert await runner.run(uuid.UUID(job_id)) == "done"
    key_a = await _key(sessions, provider["key_ids"][0])
    key_b = await _key(sessions, provider["key_ids"][1])
    assert key_a.status == KeyStatus.exhausted
    assert key_b.status == KeyStatus.invalid
    assert "key_invalid" in [e.kind for e in notifier.events]


async def test_all_keys_exhausted_then_recover(client, sessions, runner, cipher):
    headers = await register(client)
    provider = await setup_provider(client, headers, ["rl-aaaaaaaa", "quota-bbbbbb"])
    _, job_id = await send(client, headers)
    assert await runner.run(uuid.UUID(job_id)) == "waiting_quota"
    job = await _job(sessions, job_id)
    assert job.status == "waiting_quota" and job.retry_at is not None

    # Not due yet: the scheduler leaves it alone.
    assert await due_waiting_jobs(sessions) == []

    # Simulate the provider window resetting: cooldown passes and the account works again.
    async with sessions() as s:
        await s.execute(
            update(ProviderKey)
            .where(ProviderKey.id == uuid.UUID(provider["key_ids"][0]))
            .values(
                cooldown_until=utcnow() - timedelta(seconds=1),
                api_key_encrypted=cipher.encrypt("ok-aaaaaaaa"),
            )
        )
        await s.execute(
            update(Job).where(Job.id == uuid.UUID(job_id)).values(retry_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()
    assert await recover_keys(sessions) == 1
    assert await due_waiting_jobs(sessions) == [uuid.UUID(job_id)]
    assert await runner.run(uuid.UUID(job_id)) == "done"
    assert (await _key(sessions, provider["key_ids"][0])).status == KeyStatus.active


async def test_two_workers_do_not_share_a_key(client, sessions, redis, notifier):
    async def slow():
        await asyncio.sleep(0.02)

    llm = ScriptedLLM(reply="satu dua tiga empat lima", gate=slow)
    worker1 = make_runner(sessions, redis, llm, notifier, max_concurrency=1)
    worker2 = make_runner(sessions, redis, llm, notifier, max_concurrency=1)
    headers = await register(client)
    provider = await setup_provider(client, headers, ["ok-aaaaaaaa", "ok-bbbbbbbb"])
    _, job1 = await send(client, headers, content="pertanyaan satu")
    _, job2 = await send(client, headers, content="pertanyaan dua")
    results = await asyncio.gather(worker1.run(uuid.UUID(job1)), worker2.run(uuid.UUID(job2)))
    assert results == ["done", "done"]
    used = {str(u.provider_key_id) for u in await _usage(sessions)}
    assert used == set(provider["key_ids"])


async def test_both_workers_claim_same_job_only_once(client, sessions, redis, notifier, llm):
    w1 = make_runner(sessions, redis, llm, notifier)
    w2 = make_runner(sessions, redis, llm, notifier)
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, job_id = await send(client, headers)
    results = sorted(await asyncio.gather(w1.run(uuid.UUID(job_id)), w2.run(uuid.UUID(job_id))))
    assert results == ["done", "skipped"]
    assert len(await _usage(sessions)) == 1


async def test_status_marks_do_not_resurrect_invalid_key(client, sessions, redis, llm):
    headers = await register(client)
    provider = await setup_provider(client, headers, ["ok-aaaaaaaa"])
    pool = KeyPool(sessions, redis, KeyCipher(get_settings().master_encryption_key), llm)
    kid = uuid.UUID(provider["key_ids"][0])
    await pool.mark_invalid(kid, "401")
    await pool.mark_cooling(kid, 60, "429")
    await pool.mark_ok(kid, 10)
    assert (await _key(sessions, provider["key_ids"][0])).status == KeyStatus.invalid


async def test_mid_stream_cut_continues_with_next_key(client, sessions, runner, llm):
    llm.reply = "satu dua tiga empat"
    headers = await register(client)
    await setup_provider(client, headers, ["cut-aaaaaaaa", "ok-bbbbbbbb"])
    _, job_id = await send(client, headers)
    assert await runner.run(uuid.UUID(job_id)) == "done"
    second = llm.calls[1].messages
    assert second[-2] == {"role": "assistant", "content": "satu dua "}
    assert second[-1]["content"] == CONTINUE_PROMPT
    assert (await _job(sessions, job_id)).partial_output.startswith("satu dua satu dua tiga")


async def test_round_robin_and_least_used(client, sessions, runner, llm):
    headers = await register(client)
    provider = await setup_provider(client, headers, ["ok-aaaaaaaa", "ok-bbbbbbbb"], strategy="round_robin")
    for i in range(2):
        _, job_id = await send(client, headers, content=f"soal {i}")
        await runner.run(uuid.UUID(job_id))
    assert [c.api_key for c in llm.calls] == ["ok-aaaaaaaa", "ok-bbbbbbbb"]

    await client.patch(
        f"/api/v1/providers/{provider['id']}", json={"rotation_strategy": "least_used"}, headers=headers
    )
    async with sessions() as s:
        await s.execute(
            update(ProviderKey)
            .where(ProviderKey.id == uuid.UUID(provider["key_ids"][0]))
            .values(tokens_used_today=10_000)
        )
        await s.commit()
    _, job_id = await send(client, headers, content="soal 3")
    await runner.run(uuid.UUID(job_id))
    assert llm.calls[-1].api_key == "ok-bbbbbbbb"


async def test_daily_quota_skips_key(client, sessions, runner, llm):
    headers = await register(client)
    provider = await setup_provider(client, headers, ["ok-aaaaaaaa", "ok-bbbbbbbb"])
    await client.patch(
        f"/api/v1/providers/{provider['id']}/keys/{provider['key_ids'][0]}",
        json={"daily_token_quota": 5},
        headers=headers,
    )
    async with sessions() as s:
        await s.execute(
            update(ProviderKey)
            .where(ProviderKey.id == uuid.UUID(provider["key_ids"][0]))
            .values(tokens_used_today=5, usage_day=utcnow().date())
        )
        await s.commit()
    _, job_id = await send(client, headers)
    await runner.run(uuid.UUID(job_id))
    assert [c.api_key for c in llm.calls] == ["ok-bbbbbbbb"]


async def test_provider_fallback_respects_setting(client, sessions, runner, llm):
    headers = await register(client)
    await setup_provider(client, headers, ["rl-aaaaaaaa"], name="openai")
    await setup_provider(client, headers, ["ok-bbbbbbbb"], name="mock")

    await client.patch("/api/v1/settings", json={"allow_fallback": False}, headers=headers)
    _, job_id = await send(client, headers, model="openai/gpt-4o")
    assert await runner.run(uuid.UUID(job_id)) == "waiting_quota"

    await client.patch("/api/v1/settings", json={"allow_fallback": True}, headers=headers)
    _, job2 = await send(client, headers, content="lagi", model="openai/gpt-4o")
    assert await runner.run(uuid.UUID(job2)) == "done"
    assert (await _job(sessions, job2)).model_used.startswith("mock/")


async def test_no_keys_fails_cleanly(client, sessions, runner):
    headers = await register(client)
    _, job_id = await send(client, headers)
    assert await runner.run(uuid.UUID(job_id)) == "failed"
    assert "key aktif" in (await _job(sessions, job_id)).error
