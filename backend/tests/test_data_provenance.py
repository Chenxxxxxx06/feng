from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.data_provenance import DataProvenanceMixin
from app.services.data_provenance import build_data_provenance


def test_build_data_provenance_orders_and_normalizes_range():
    payload = build_data_provenance(
        source_type="historical",
        source_label="历史公开数据",
        source_description="test",
        is_demo=False,
        timestamps=[
            "2024-02-01T10:00:00",
            datetime(2022, 1, 1, tzinfo=timezone.utc),
            None,
        ],
    )

    assert payload["source_type"] == "historical"
    assert payload["is_demo"] is False
    assert payload["data_time_range"] == {
        "start": "2022-01-01T00:00:00+00:00",
        "end": "2024-02-01T10:00:00+00:00",
    }


def test_source_type_is_restricted_to_supported_values():
    with pytest.raises(ValidationError):
        DataProvenanceMixin.model_validate(
            {
                "source_type": "live",
                "data_time_range": {"start": None, "end": None},
                "is_demo": False,
                "source_label": "invalid",
                "source_description": "invalid",
            }
        )
