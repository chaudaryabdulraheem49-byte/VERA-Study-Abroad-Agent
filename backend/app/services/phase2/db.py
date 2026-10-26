"""Postgres access for Phase 2: engine, session factory and the courses table.

SQLAlchemy 2.0 async style throughout. The table carries only what the hard
filter needs to be fast — numbers, booleans and categoricals — plus the
syllabus text so results can be rendered without a second round trip. The
vectors live in Qdrant, keyed by the `course_id` assigned here.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ...config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Course(Base):
    """One course row. `(university_name, course_title)` is the natural key."""

    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint(
            "university_name", "course_title", name="uq_courses_university_title"
        ),
        Index(
            "ix_courses_country_degree_tuition",
            "country",
            "degree_level",
            "tuition_fee_usd",
        ),
        Index("ix_courses_degree_tuition", "degree_level", "tuition_fee_usd"),
        Index(
            "ix_courses_filter",
            "country",
            "degree_level",
            "tuition_fee_usd",
            "min_ielts_score",
        ),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_title: Mapped[str] = mapped_column(String(300), nullable=False)
    university_name: Mapped[str] = mapped_column(String(300), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    degree_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    tuition_fee_amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tuition_fee_usd: Mapped[float] = mapped_column(Float, nullable=False, index=True)

    # NULL means "the source does not state one", which is not the same as a
    # requirement of zero. The register states none at all, and storing that
    # as 0.0 made 9,845 courses look as though they had published a bar of
    # zero percent. The filter treats NULL as no barrier, exactly as it
    # already does for an unstated deadline.
    min_gpa_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_ielts_score: Mapped[float | None] = mapped_column(
        Float, nullable=True, index=True
    )

    # Stored as text, not DATE: pages give partial or absent deadlines, and a
    # NULL-versus-unknown distinction matters more here than date arithmetic.
    deadline_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    post_study_work_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    syllabus_description: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Populated by bulk imports from official registers (see
    # scripts/ingest_cricos.py). All nullable: a course crawled from a page
    # carries none of them, and the hard filter does not read them.
    university_id: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("universities.university_id"), nullable=True, index=True
    )
    external_course_code: Mapped[str | None] = mapped_column(
        String(30), nullable=True, index=True
    )
    duration_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The fee in the currency the register publishes, kept beside the USD
    # figure so a converted number can always be traced back to its source.
    tuition_fee_aud: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The register's own wording for the award ("Bachelor Honours Degree"),
    # preserved because `degree_level` flattens twenty levels onto three.
    course_level_raw: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # ASCED Field of Education, stored verbatim as the register writes it -
    # "02 - Information Technology", code and label together. Splitting them
    # here would throw away the code, which is the part a facet groups on;
    # a caller that wants only the label can split on " - ".
    #
    # Broad is indexed because it is the level a facet or a relaxed filter
    # would group by; narrow and detailed are carried for display and for
    # finer filtering later.
    field_broad: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    field_narrow: Mapped[str | None] = mapped_column(String(160), nullable=True)
    field_detailed: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Intake and deadline, kept as three fields because "we do not know" and
    # "applications never close" are different answers and a student plans
    # around them differently.
    #   published    - next_deadline holds a real date from the source
    #   rolling      - the source says applications are accepted continuously
    #   not_published - the source is silent; nothing here is inferred
    deadline_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    next_deadline: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Free text as the source words it ("February and July"), never invented.
    intakes: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tuition_fee_cad: Mapped[float | None] = mapped_column(Float, nullable=True)
    tuition_fee_eur: Mapped[float | None] = mapped_column(Float, nullable=True)


class University(Base):
    """One registered provider (CRICOS, IRCC DLI, or international).

    The primary key is the provider's code (CRICOS code or IRCC DLI number)
    rather than a surrogate: it is stable across releases and makes a row
    traceable back to the source register without a lookup.
    """

    __tablename__ = "universities"

    university_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    institution_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    trading_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    institution_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    institution_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="Australia")
    offers_pgwp: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dli_number: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)


class Institution(Base):
    """Designated Learning Institution (DLI) or foreign education provider."""

    __tablename__ = "institutions"
    __table_args__ = (
        UniqueConstraint(
            "dli_number", "campus_location", "city", name="uq_institutions_dli_campus_city"
        ),
    )

    institution_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dli_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    institution_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    campus_location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    city: Mapped[str | None] = mapped_column(String(150), nullable=True)
    offers_pgwp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_public: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="Canada", index=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)


# Composite indexes for the shapes the hard filter and discovery actually run:
# country and degree narrow the set, then numeric ranges and fee sorting are checked.
_DDL_INDEXES: Final[tuple[str, ...]] = (
    "CREATE INDEX IF NOT EXISTS ix_courses_country_degree_tuition "
    "ON courses (country, degree_level, tuition_fee_usd)",
    "CREATE INDEX IF NOT EXISTS ix_courses_degree_tuition "
    "ON courses (degree_level, tuition_fee_usd)",
    "CREATE INDEX IF NOT EXISTS ix_courses_filter "
    "ON courses (country, degree_level, tuition_fee_usd, min_ielts_score)",
)

# `create_all` creates missing tables but never alters an existing one, so a
# database built before these columns existed would keep the old shape and the
# importer would fail on the first insert. Adding them explicitly - and
# idempotently - is enough while the schema changes this rarely; the moment one
# needs a backfill or a type change, this should become Alembic.
_DDL_COLUMNS: Final[tuple[str, ...]] = (
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS university_id VARCHAR(20)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS external_course_code VARCHAR(30)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS duration_weeks INTEGER",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS tuition_fee_aud DOUBLE PRECISION",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_level_raw VARCHAR(60)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS field_broad VARCHAR(120)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS field_narrow VARCHAR(160)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS field_detailed VARCHAR(200)",
    "CREATE INDEX IF NOT EXISTS ix_courses_field_broad ON courses (field_broad)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS deadline_type VARCHAR(20)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS next_deadline VARCHAR(10)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS intakes VARCHAR(200)",
    # An unstated requirement must be storable as unknown rather than as zero.
    "ALTER TABLE courses ALTER COLUMN min_gpa_percent DROP NOT NULL",
    "ALTER TABLE courses ALTER COLUMN min_ielts_score DROP NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_courses_university_id ON courses (university_id)",
    "CREATE INDEX IF NOT EXISTS ix_courses_external_code "
    "ON courses (external_course_code)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS tuition_fee_cad DOUBLE PRECISION",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS tuition_fee_eur DOUBLE PRECISION",
    "ALTER TABLE universities ADD COLUMN IF NOT EXISTS offers_pgwp BOOLEAN",
    "ALTER TABLE universities ADD COLUMN IF NOT EXISTS dli_number VARCHAR(30)",
    "CREATE INDEX IF NOT EXISTS ix_universities_dli ON universities (dli_number)",
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazily build the shared engine so importing this module needs no DB."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,  # survive Postgres dropping idle connections
            pool_size=5,
            max_overflow=10,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """A transactional session: commit on success, roll back on failure."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_schema() -> None:
    """Create the table and indexes if they do not exist.

    Idempotent, so it is safe to call on startup. Swap for Alembic once the
    schema starts changing in ways that need real migrations.
    """
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for statement in (*_DDL_COLUMNS, *_DDL_INDEXES):
            await connection.execute(text(statement))
    logger.info("Phase 2 schema ready (courses + universities, indexes)")


async def dispose_engine() -> None:
    """Close pooled connections; call on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
