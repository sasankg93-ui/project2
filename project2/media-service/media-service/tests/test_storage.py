from app.storage import new_source_key, safe_filename


def test_safe_filename_strips_paths_and_odd_chars():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("my photo (1).jpg") == "my_photo__1_.jpg"
    assert safe_filename("") == "file"


def test_source_key_under_prefix(settings):
    k = new_source_key(settings, "a.jpg")
    assert k.startswith(settings.s3_upload_prefix) and k.endswith("/a.jpg")
