from sqlalchemy import String, JSON, Double, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Dataset(Base):
    """一份不可变台账。站点发布快照时生成，分析任务和简报都绑定它的指纹。"""
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
    station_id: Mapped[int | None] = mapped_column(ForeignKey('stations.id'), nullable=True, index=True)
    generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
