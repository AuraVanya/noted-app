from pydantic import BaseModel, ConfigDict, Field


class Connections(BaseModel):
    google: bool
    atlassian: bool


class MeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    email: str
    display_name: str = Field(serialization_alias="displayName")
    avatar_initials: str = Field(serialization_alias="avatarInitials")
    connections: Connections
