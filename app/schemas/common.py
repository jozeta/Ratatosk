from pydantic import BaseModel, Field


class BatchIds(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=1000)
