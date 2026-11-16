from pydantic import BaseModel, Field


class SnapshotInput(BaseModel):
    generation: int = Field(ge=1, le=1000000)
    station_name: str = Field(default='', max_length=160)
    source: str = Field(default='station-snapshot.json', max_length=200)
    records: list[dict] = Field(min_length=1, max_length=5000)
