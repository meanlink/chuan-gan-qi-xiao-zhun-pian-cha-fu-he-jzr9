from sqlalchemy import String, JSON, Double, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Station(Base):
    """一个回传全量台账的校准站。current_snapshot_id 只在发布成功后推进。"""
    __tablename__ = 'stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    current_generation: Mapped[int] = mapped_column(Integer, default=0)
    # 不设外键，避免 stations 与 station_snapshots 互相引用造成建表顺序问题。
    current_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[float] = mapped_column(Double)


class StationSnapshot(Base):
    """一次全量台账回传。staging 期间逐条落库并记录 progress，发布后不可变。"""
    __tablename__ = 'station_snapshots'
    __table_args__ = (
        UniqueConstraint('station_id', 'generation', name='uq_station_snapshot_generation'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey('stations.id'), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='staging')  # staging / published / rejected
    checksum: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(200), default='station-snapshot.json')
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    created_by: Mapped[str] = mapped_column(String(150), default='')
    created_at: Mapped[float] = mapped_column(Double)
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class LedgerRow(Base):
    """暂存的单条读数；同代重试时按 (snapshot_id, position) 幂等补齐。"""
    __tablename__ = 'ledger_rows'
    __table_args__ = (
        UniqueConstraint('snapshot_id', 'position', name='uq_ledger_row_position'),
        UniqueConstraint('snapshot_id', 'sample', name='uq_ledger_row_sample'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey('station_snapshots.id'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    sample: Mapped[str] = mapped_column(String(200))
    band: Mapped[str] = mapped_column(String(120))
    reference: Mapped[float] = mapped_column(Double)
    measured: Mapped[float] = mapped_column(Double)
