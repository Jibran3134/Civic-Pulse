import asyncio

import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)
settings = get_settings()


COMPLAINTS = [
    (
        "Water main burst on Mall Road since fajr, water entering ground floors of houses",
        "Mall Road, Lahore",
        "0300-1234567",
        "water",
        "high",
    ),
    (
        "Streetlight not working at intersection of Ferozepur Road and Canal Bank",
        "Ferozepur Road, Lahore",
        "0301-2345678",
        "streetlights",
        "normal",
    ),
    (
        "Garbage not collected for 3 days in Model Town block B",
        "Model Town, Lahore",
        "0302-3456789",
        "sanitation",
        "normal",
    ),
    (
        "Large pothole on Main Boulevard Gulberg causing traffic jams",
        "Main Boulevard Gulberg, Lahore",
        "0303-4567890",
        "roads",
        "high",
    ),
    (
        "Electricity outage in DHA Phase 5 since last night",
        "DHA Phase 5, Lahore",
        "0304-5678901",
        "electricity",
        "high",
    ),
    (
        "Sewage overflow near Data Darbar, foul smell everywhere",
        "Data Darbar, Lahore",
        "0305-6789012",
        "sanitation",
        "high",
    ),
    (
        "Water supply contaminated in Johar Town, yellow color coming from taps",
        "Johar Town, Lahore",
        "0306-7890123",
        "water",
        "high",
    ),
    (
        "Broken traffic signal at Kalma Chowk causing accidents",
        "Kalma Chowk, Lahore",
        "0307-8901234",
        "roads",
        "high",
    ),
    (
        "Streetlight flickering on MM Alam Road for past week",
        "MM Alam Road, Lahore",
        "0308-9012345",
        "streetlights",
        "low",
    ),
    (
        "Trash piling up near Liberty Market parking area",
        "Liberty Market, Lahore",
        "0309-0123456",
        "sanitation",
        "normal",
    ),
    (
        "Water pressure very low in Bahria Town sector C",
        "Bahria Town, Lahore",
        "0310-1234567",
        "water",
        "normal",
    ),
    (
        "Exposed electrical wires on College Road, danger to pedestrians",
        "College Road, Lahore",
        "0311-2345678",
        "electricity",
        "high",
    ),
    (
        "Road construction debris left on Canal Road service lane",
        "Canal Road, Lahore",
        "0312-3456789",
        "roads",
        "normal",
    ),
    (
        "Public toilet in Race Course Park extremely dirty",
        "Race Course Park, Lahore",
        "0313-4567890",
        "sanitation",
        "normal",
    ),
    (
        "Water leaking from underground pipe near Shadman Chowk",
        "Shadman Chowk, Lahore",
        "0314-5678901",
        "water",
        "normal",
    ),
    (
        "Streetlight completely out on Jail Road stretch",
        "Jail Road, Lahore",
        "0315-6789012",
        "streetlights",
        "normal",
    ),
    (
        "Garbage truck not coming to Wapda Town for 5 days",
        "Wapda Town, Lahore",
        "0316-7890123",
        "sanitation",
        "normal",
    ),
    (
        "Deep pothole on Bedian Road damaging car suspensions",
        "Bedian Road, Lahore",
        "0317-8901234",
        "roads",
        "high",
    ),
    (
        "Transformer sparking in Askari 10, fire risk",
        "Askari 10, Lahore",
        "0318-9012345",
        "electricity",
        "high",
    ),
    (
        "Water supply stopped in Valencia Town since morning",
        "Valencia Town, Lahore",
        "0319-0123456",
        "water",
        "high",
    ),
    (
        "Missing manhole cover on Main Boulevard Defence",
        "Defence, Lahore",
        "0320-1234567",
        "roads",
        "high",
    ),
    (
        "Streetlight pole leaning dangerously on Ferozepur Road",
        "Ferozepur Road, Lahore",
        "0321-2345678",
        "streetlights",
        "high",
    ),
    (
        "Illegal dumping of construction waste in Green Town",
        "Green Town, Lahore",
        "0322-3456789",
        "sanitation",
        "normal",
    ),
    (
        "Water meter reading wrong, bill inflated in Iqbal Town",
        "Iqbal Town, Lahore",
        "0323-4567890",
        "water",
        "low",
    ),
    (
        "Traffic lights not synchronized on Mall Road causing congestion",
        "Mall Road, Lahore",
        "0324-5678901",
        "roads",
        "normal",
    ),
    (
        "Power fluctuation damaging appliances in Township",
        "Township, Lahore",
        "0325-6789012",
        "electricity",
        "normal",
    ),
    (
        "Drainage choked near Anarkali Bazaar, water logging",
        "Anarkali Bazaar, Lahore",
        "0326-7890123",
        "sanitation",
        "high",
    ),
    (
        "Streetlight timer not working in Model Town extension",
        "Model Town, Lahore",
        "0327-8901234",
        "streetlights",
        "low",
    ),
    (
        "Water supply timing changed without notice in Sabzazar",
        "Sabzazar, Lahore",
        "0328-9012345",
        "water",
        "normal",
    ),
    (
        "Road sign missing at junction of Raiwind Road and Thokar Niaz Baig",
        "Raiwind Road, Lahore",
        "0329-0123456",
        "roads",
        "normal",
    ),
    (
        "Electricity meter running fast in Garden Town",
        "Garden Town, Lahore",
        "0330-1234567",
        "electricity",
        "low",
    ),
]


SEED_MARKER = "seed"


async def seed() -> None:
    """Load the demo dataset, idempotently.

    Idempotency here is content-based, not count-based. The previous version
    returned early if the table held ANY row, so a single user-created complaint
    permanently blocked the seed: the dashboard stayed near-empty and the demo
    became unwatchable, with no way to recover except dropping the volume.
    Instead each seeded row is identified by its own text plus the `seed` marker
    in triaged_by, and only the genuinely missing rows are inserted. Running
    this twice inserts nothing the second time, which is the property that
    actually matters.

    Note the absence of ON CONFLICT DO NOTHING: there is no unique constraint
    on `complaints` for it to act on, so it was a no-op that read as protection.
    The existence check below is what makes the insert idempotent.

    The inserts run inside one explicit transaction. With autocommit the
    connection commits each row separately, so a failure halfway through left a
    partially seeded database -- and the count guard would then refuse to ever
    finish the job.
    """
    conn = await psycopg.AsyncConnection.connect(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://"),
        row_factory=dict_row,
    )
    try:
        async with conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                "SELECT text FROM complaints WHERE triaged_by = %s",
                (SEED_MARKER,),
            )
            existing = {row["text"] for row in await cur.fetchall()}

            missing = [c for c in COMPLAINTS if c[0] not in existing]
            if not missing:
                logger.info("Seed already applied; nothing to do", extra={"rows": len(existing)})
                return

            for text, location, contact, category, priority in missing:
                await cur.execute(
                    """
                    INSERT INTO complaints (text, location, reporter_contact, category, priority,
                                            ai_summary, triaged_by, triage_latency_ms, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open')
                    """,
                    (
                        text,
                        location,
                        contact,
                        category,
                        priority,
                        f"Auto-seeded: {text[:100]}",
                        SEED_MARKER,
                        0,
                    ),
                )

            await cur.execute("SELECT COUNT(*) as total FROM complaints")
            total = (await cur.fetchone())["total"]
            logger.info(
                "Seed applied",
                extra={
                    "inserted": len(missing),
                    "skipped": len(COMPLAINTS) - len(missing),
                    "total": total,
                },
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
