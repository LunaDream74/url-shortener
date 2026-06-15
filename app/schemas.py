from datetime import datetime
from pydantic import BaseModel, HttpUrl


class URLCreate(BaseModel):
    url: HttpUrl


class URLResponse(BaseModel):
    short_code: str
    original_url: str
    short_url: str
    clicks: int
    created_at: datetime

    model_config = {"from_attributes": True}


class URLStats(BaseModel):
    short_code: str
    original_url: str
    clicks: int
    created_at: datetime

    model_config = {"from_attributes": True}
