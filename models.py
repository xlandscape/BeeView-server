from sqlalchemy import Integer, String, LargeBinary, Sequence, ForeignKey, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

class LandCoverVegetationMapping(Base):
    __tablename__ = "land_cover_vegetation_mapping"
    id: Mapped[int] = mapped_column(Integer, Sequence('lc_veg_mapping_id_seq'), primary_key=True)
    l1_code: Mapped[int] = mapped_column(Integer)
    l1_label: Mapped[str] = mapped_column(String(100))
    l2_code: Mapped[int] = mapped_column(Integer)
    l2_label: Mapped[str] = mapped_column(String(100))
    l3_code: Mapped[int] = mapped_column(Integer)
    l3_label: Mapped[str] = mapped_column(String(200))
    data_source: Mapped[str] = mapped_column(String(50), nullable=True)
    source_code: Mapped[str] = mapped_column(String(50), nullable=True)
    last_change: Mapped[str] = mapped_column(String(20), nullable=True)  # Store as string since format varies
    vegetation: Mapped[str] = mapped_column(String(100))
    vegetation_certainty: Mapped[str] = mapped_column(String(50), nullable=True)

class Feature(Base):
    __tablename__ = "features"
    id: Mapped[int] = mapped_column(Integer, Sequence('feature_id_seq'), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    l1_code: Mapped[int] = mapped_column(Integer, nullable=True)
    l1_label: Mapped[str] = mapped_column(String(100))
    l2_code: Mapped[int] = mapped_column(Integer, nullable=True)
    l2_label: Mapped[str] = mapped_column(String(100), nullable=True)
    l3_code: Mapped[int] = mapped_column(Integer, nullable=True)
    l3_label: Mapped[str] = mapped_column(String(200), nullable=True)
    geometry: Mapped[str] = mapped_column(String)
    nectar = relationship("Nectar", back_populates="feature", cascade="all, delete-orphan")
    pollen = relationship("Pollen", back_populates="feature", cascade="all, delete-orphan")
    
    # Add relationship to vegetation mapping via L1_code, L2_code, L3_code
    @property
    def vegetation_mapping(self):
        # This will be used to get vegetation info via code combination
        # We'll implement a method to query this in the application layer
        return None

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
