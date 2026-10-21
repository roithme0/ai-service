"""Schemas describing complete serialized responses rather than model inputs."""

from pydantic import BaseModel, ConfigDict


def _without_defaults(schema: dict[str, object]) -> None:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for property_schema in properties.values():
            if isinstance(property_schema, dict):
                property_schema.pop("default", None)


class ResponseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_serialization_defaults_required=True,
        json_schema_extra=_without_defaults,
    )
