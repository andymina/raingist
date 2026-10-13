import pytest
from raingist.extract.common import classify_ytdlp_error, PermanentFailure, TransientFailure

@pytest.mark.parametrize("msg,kind", [
    ("Video is private", PermanentFailure),
    ("Unable to extract webpage video data", TransientFailure),
    ("Your IP address is blocked from accessing this post", TransientFailure),
    ("This video is unavailable", PermanentFailure),
])
def test_classify(msg, kind):
    assert type(classify_ytdlp_error(msg)) is kind
