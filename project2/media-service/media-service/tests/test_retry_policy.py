from botocore.exceptions import ClientError, EndpointConnectionError

from app.tasks import is_transient


def _err(code, status):
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "GetObject")


def test_transient_vs_permanent():
    assert is_transient(EndpointConnectionError(endpoint_url="x"))
    assert is_transient(_err("InternalError", 500))
    assert is_transient(_err("SlowDown", 503))
    assert not is_transient(_err("NoSuchKey", 404))
    assert not is_transient(_err("AccessDenied", 403))
    assert not is_transient(ValueError("bad"))
