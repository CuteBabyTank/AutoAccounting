import asyncio

from app.services.accounting.jobs import JobSlots


def test_one_job_per_firm_and_a_global_cap():
    async def scenario():
        slots = JobSlots(total=2)
        running: dict[str, int] = {}
        peak = {"total": 0, "a": 0, "b": 0, "c": 0}

        async def job(firm: str):
            async with slots.slot(firm):
                running[firm] = running.get(firm, 0) + 1
                peak[firm] = max(peak[firm], running[firm])
                peak["total"] = max(peak["total"], sum(running.values()))
                await asyncio.sleep(0.01)
                running[firm] -= 1

        await asyncio.gather(job("a"), job("a"), job("a"), job("b"), job("c"))
        return peak

    peak = asyncio.run(scenario())
    assert peak["a"] == 1          # a firm's big drop never takes more than one slot
    assert peak["total"] == 2      # global cap holds
    assert peak["b"] == 1 and peak["c"] == 1


def test_other_firms_are_not_queued_behind_a_busy_firm():
    async def scenario():
        slots = JobSlots(total=2)
        order: list[str] = []

        async def job(firm: str, name: str, delay: float):
            async with slots.slot(firm):
                await asyncio.sleep(delay)
                order.append(name)

        await asyncio.gather(job("a", "a1", 0.05), job("a", "a2", 0.05), job("b", "b1", 0.01))
        return order

    assert asyncio.run(scenario())[0] == "b1"


def test_firm_lock_survives_handoff_between_waiters():
    async def scenario():
        slots = JobSlots(total=4)
        running = {"a": 0}
        peak = {"a": 0}

        async def job(start_after: float, hold: float):
            await asyncio.sleep(start_after)
            async with slots.slot("a"):
                running["a"] += 1
                peak["a"] = max(peak["a"], running["a"])
                await asyncio.sleep(hold)
                running["a"] -= 1

        # j1 holds 0-0.05; j2 waits and holds 0.05-0.10; j3 arrives at 0.07 while j2 runs.
        await asyncio.gather(job(0, 0.05), job(0.01, 0.05), job(0.07, 0.01))
        return peak["a"]

    assert asyncio.run(scenario()) == 1
