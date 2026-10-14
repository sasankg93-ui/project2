import os

os.environ.setdefault("S3_BUCKET", "test-bucket")

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(s3_bucket="test-bucket", work_dir=str(tmp_path), watermark_text="© Test")
