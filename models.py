from sqlalchemy import Integer, String, LargeBinary, Sequence, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

class Feature(Base):
    __tablename__ = "features"
    id: Mapped[int] = mapped_column(Integer, Sequence('feature_id_seq'), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    lulc_label: Mapped[str] = mapped_column(String(100))
    geometry: Mapped[str] = mapped_column(String)
    nectar = relationship("Nectar", back_populates="feature", cascade="all, delete-orphan")
    pollen = relationship("Pollen", back_populates="feature", cascade="all, delete-orphan")

class Nectar(Base):
    __tablename__ = "nectar"
    id: Mapped[int] = mapped_column(Integer, Sequence('nectar_id_seq'), primary_key=True)
    feature_id: Mapped[int] = mapped_column(Integer, ForeignKey("features.id"))
    timeseries: Mapped[bytes] = mapped_column(LargeBinary)
    feature = relationship("Feature", back_populates="nectar")

class Pollen(Base):
    __tablename__ = "pollen"
    id: Mapped[int] = mapped_column(Integer, Sequence('pollen_id_seq'), primary_key=True)
    feature_id: Mapped[int] = mapped_column(Integer, ForeignKey("features.id"))
    timeseries: Mapped[bytes] = mapped_column(LargeBinary)
    feature = relationship("Feature", back_populates="pollen")

class BeePopulation(Base):
    __tablename__ = "bee_population"
    id: Mapped[int] = mapped_column(Integer, Sequence('bee_population_id_seq'), primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(50))  # e.g., "totalEggs", "totalForagers"
    timeseries: Mapped[bytes] = mapped_column(LargeBinary)  # Pickled numpy array for 365 days
