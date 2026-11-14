from __future__ import annotations

from fastapi import status

from opal_look_yolo.errors import OpalException
from opal_look_yolo.models import ModelRepository
from opal_look_yolo.schemas.models import Model


class ModelService:
    def __init__(self, repository: ModelRepository) -> None:
        self.repository = repository

    def list_models(self) -> list[Model]:
        return [record.to_model() for record in self.repository.list_records()]

    def get_model(self, model_id: str) -> Model:
        record = self.repository.get_record(model_id)
        if record is None:
            raise OpalException(
                status.HTTP_404_NOT_FOUND,
                "not_found",
                "Model not found",
                {"model_id": model_id},
            )
        return record.to_model()
