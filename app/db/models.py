from sqlalchemy import Column, String, Integer, DateTime, func
from app.db.base import Base

class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    short_id = Column(String(32), unique=True, index=True, nullable=False)
    origin = Column(String(2048), nullable=False)
    click_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)

