"""Compatibility boundary for the existing synthetic API, not the future model."""
from ml import forecast


SUPPORTED_CONTRACT_VERSION = "synthetic-v1"


class IncompatibleForecastContract(RuntimeError):
    """The provider cannot be used by the current API consumer."""


def predict_for_api_v1() -> dict:
    """Check compatibility before inference; leave payload validation to the API."""
    if getattr(forecast, "CONTRACT_VERSION", None) != SUPPORTED_CONTRACT_VERSION:
        raise IncompatibleForecastContract("Unsupported synthetic forecast contract")
    return forecast.predict_mock()
