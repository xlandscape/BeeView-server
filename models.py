from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Sequence,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Run(Base):
    """An xPollinator run imported from a run/<SimID>/ folder."""
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("sim_id", name="unique_run_sim_id"),)

    id: Mapped[int] = mapped_column(Integer, Sequence("runs_id_seq"), primary_key=True)
    sim_id: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=True)
    scenario: Mapped[str] = mapped_column(String(200), nullable=True)
    hive_group_id: Mapped[str] = mapped_column(String(100), nullable=True)
    treatment_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    n_replicates: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=True)
    hive_x: Mapped[float] = mapped_column(Float, nullable=True)
    hive_y: Mapped[float] = mapped_column(Float, nullable=True)
    hive_lon: Mapped[float] = mapped_column(Float, nullable=True)
    hive_lat: Mapped[float] = mapped_column(Float, nullable=True)
    source_path: Mapped[str] = mapped_column(String, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class BeePopulationReplicate(Base):
    """A single BEEHAVE replicate's time series for one metric, owned by a Run."""
    __tablename__ = "bee_population_replicate"
    __table_args__ = (
        Index("ix_bee_pop_replicate_run_metric", "run_id", "metric_name"),
    )

    id: Mapped[int] = mapped_column(
        Integer, Sequence("bee_population_replicate_id_seq"), primary_key=True
    )
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id"), nullable=False)
    replicate_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    timeseries: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    run = relationship("Run")


class FeatureIds(Base):
    __tablename__ = "feature_ids"
    __table_args__ = (
        UniqueConstraint('feature_id', name='unique_feature_id'),
    )
    index: Mapped[int] = mapped_column(Integer, Sequence('feature_ids_index_seq'), primary_key=True)
    feature_id: Mapped[int] = mapped_column(Integer, nullable=False)

class VegetationClassMapping(Base):
    __tablename__ = "vegetation_class_mapping"
    id: Mapped[int] = mapped_column(Integer, Sequence('veg_class_mapping_id_seq'), primary_key=True)
    vegetation_name: Mapped[str] = mapped_column(String(100), unique=True)
    vegetation_class: Mapped[int] = mapped_column(Integer)

class Vegetation(Base):
    __tablename__ = "vegetation"
    id: Mapped[int] = mapped_column(Integer, Sequence('vegetation_id_seq'), primary_key=True)
    feature_index: Mapped[int] = mapped_column(Integer, ForeignKey("feature_ids.index"))
    vegetation_class: Mapped[int] = mapped_column(Integer)

    feature_id_ref = relationship("FeatureIds")

class Feature(Base):
    __tablename__ = "features"
    id: Mapped[int] = mapped_column(Integer, Sequence('feature_id_seq'), primary_key=True)
    feature_id: Mapped[int] = mapped_column(Integer, ForeignKey("feature_ids.feature_id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    l1_code: Mapped[int] = mapped_column(Integer, nullable=True)
    l1_label: Mapped[str] = mapped_column(String(100))
    l2_code: Mapped[int] = mapped_column(Integer, nullable=True)
    l2_label: Mapped[str] = mapped_column(String(100), nullable=True)
    l3_code: Mapped[int] = mapped_column(Integer, nullable=True)
    l3_label: Mapped[str] = mapped_column(String(200), nullable=True)
    area_hectares: Mapped[float] = mapped_column(Float, nullable=True)  # Area in hectares
    geometry: Mapped[str] = mapped_column(String)
    feature_id_ref = relationship("FeatureIds", foreign_keys=[feature_id])

class Nectar(Base):
    __tablename__ = "nectar"
    id: Mapped[int] = mapped_column(Integer, Sequence('nectar_id_seq'), primary_key=True)
    feature_index: Mapped[int] = mapped_column(Integer, ForeignKey("feature_ids.index"))
    timeseries: Mapped[bytes] = mapped_column(LargeBinary)
    feature_id_ref = relationship("FeatureIds")

class Pollen(Base):
    __tablename__ = "pollen"
    id: Mapped[int] = mapped_column(Integer, Sequence('pollen_id_seq'), primary_key=True)
    feature_index: Mapped[int] = mapped_column(Integer, ForeignKey("feature_ids.index"))
    timeseries: Mapped[bytes] = mapped_column(LargeBinary)
    feature_id_ref = relationship("FeatureIds")

class BeePopulation(Base):
    __tablename__ = "bee_population"
    id: Mapped[int] = mapped_column(Integer, Sequence('bee_population_id_seq'), primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(50))  # e.g., "totalEggs", "totalForagers"
    timeseries: Mapped[bytes] = mapped_column(LargeBinary)  # Pickled numpy array for 365 days
