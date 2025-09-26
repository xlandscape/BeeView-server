from sqlalchemy import Integer, String, LargeBinary, Sequence, ForeignKey, Date, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

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
