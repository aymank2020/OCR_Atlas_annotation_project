import atlas_feedback_training_export as aft


class _FakeBrowser:
    def __init__(self):
        self.new_context_calls = []

    def new_context(self, **kwargs):
        self.new_context_calls.append(kwargs)
        return {"context_kwargs": kwargs}


class _FakeChromium:
    def __init__(self):
        self.launch_calls = []

    def launch(self, **kwargs):
        self.launch_calls.append(dict(kwargs))
        if kwargs.get("channel") == "chrome":
            raise RuntimeError("Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome")
        return _FakeBrowser()


class _FakePlaywright:
    def __init__(self):
        self.chromium = _FakeChromium()


def test_launch_context_falls_back_to_bundled_chromium_when_google_chrome_is_missing(tmp_path, monkeypatch):
    state_path = tmp_path / "atlas_auth.json"
    state_path.write_text("{}", encoding="utf-8")

    cfg = aft.deep_merge(
        aft.DEFAULTS,
        {
            "browser": {
                "storage_state_path": str(state_path),
            }
        },
    )

    fake_pw = _FakePlaywright()
    monkeypatch.chdir(tmp_path)
    context, browser = aft.launch_context(fake_pw, cfg, headless=True, force_no_profile=True)

    assert browser is not None
    assert context["context_kwargs"]["storage_state"] == str(state_path)
    assert fake_pw.chromium.launch_calls[0]["channel"] == "chrome"
    assert "channel" not in fake_pw.chromium.launch_calls[1]
