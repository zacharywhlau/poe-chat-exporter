from poe_bulk_export.client import _payload_json, _poe_tag_id
from poe_bulk_export.gql_hashes import QUERIES


def test_poe_tag_id_is_stable_md5():
    payload = _payload_json(
        "ChatListPaginationQuery",
        {"count": 100, "cursor": None, "id": "Q2hhdDoxMjM0NQ=="},
    )
    assert '"queryName":"ChatListPaginationQuery"' in payload
    assert QUERIES["ChatListPaginationQuery"] in payload
    # Compact JSON: no spaces after separators
    assert ", " not in payload
    tag = _poe_tag_id(payload, "abc123formkey")
    assert len(tag) == 32
    assert tag == _poe_tag_id(payload, "abc123formkey")
    assert tag != _poe_tag_id(payload, "otherformkey")
