from atlas_discord_master_sync import fetch_guild_channels


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_guild_channels_keeps_text_channels_of_type_zero(monkeypatch):
    payload = [
        {"id": "cat", "name": "Text Channels", "type": 4, "position": 0},
        {"id": "txt", "name": "atlas-rules", "type": 0, "position": 1},
        {"id": "voice", "name": "General", "type": 2, "position": 2},
    ]

    monkeypatch.setattr(
        "atlas_discord_master_sync._discord_get",
        lambda url, headers, params=None: payload,
    )

    rows = fetch_guild_channels("token", 123)
    assert [row["name"] for row in rows] == ["atlas-rules"]
