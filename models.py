from sqlalchemy import Integer, String, LargeBinary, Sequence
from sqlalchemy.orm import Mapped, mapped_column
from database import Base

class Feature(Base):
    __tablename__ = "features"
    id: Mapped[int] = mapped_column(Integer, Sequence('feature_id_seq'), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    lulc_label: Mapped[str] = mapped_column(String(100))
    geometry: Mapped[str] = mapped_column(String)

class Nectar(Base):
    __tablename__ = "nectar"
    id: Mapped[int] = mapped_column(Integer, Sequence('nectar_id_seq'), primary_key=True)
    feature_id: Mapped[int] = mapped_column(Integer)
    timeseries: Mapped[bytes] = mapped_column(LargeBinary)
