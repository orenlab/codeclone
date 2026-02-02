from codeclone.fingerprint import bucket_loc, sha1


def test_sha1_stable() -> None:
    assert sha1("abc") == "a9993e364706816aba3e25717850c26c9cd0d89d"


def test_bucket_loc_ranges() -> None:
    assert bucket_loc(0) == "0-19"
    assert bucket_loc(19) == "0-19"
    assert bucket_loc(20) == "20-49"
    assert bucket_loc(49) == "20-49"
    assert bucket_loc(50) == "50-99"
    assert bucket_loc(99) == "50-99"
    assert bucket_loc(100) == "100+"
