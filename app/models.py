from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text

from app.database import Base


class URL(Base):
    __tablename__ = "urls"

    id = Column(Integer, primary_key=True, index=True)
    short_code = Column(String(20), unique=True, index=True, nullable=False)
    original_url = Column(Text, nullable=False)
    clicks = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
