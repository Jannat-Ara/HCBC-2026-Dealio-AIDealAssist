from app.routers.tasks import _json_list


def test_json_list_handles_list_and_json_string() -> None:
    assert _json_list(["a"]) == ["a"]
    assert _json_list('["a", "b"]') == ["a", "b"]
    assert _json_list("{}") == []
