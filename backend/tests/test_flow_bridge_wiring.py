"""Wiring tests for the batchexecute Flow bridge (no WS, no network).

These lock the glue between the vendored flow_batch envelope codec and the
bridge: the legacy save_image payload mapping, failure-text extraction from an
error-slot envelope, per-account project resolution, and the exact image
request slots our dispatch builds for Flow.
"""
import json

import pytest

from app.services import flow_batch as fb
from app.services import flow_projects
from app.services.forge_bridge import (
    _failure_text,
    _legacy_image_payload,
    _parse_generated_image,
)


def _error_envelope(rpcid: str = fb.RPC_GEN_IMAGE) -> str:
    """A batchexecute body carrying an error slot instead of a payload."""
    chunk = json.dumps([["wrb.fr", rpcid, None, None, None, [8]]])
    return f")]}}'\n{len(chunk)}\n{chunk}"


def _inner(freq: str):
    """The inner payload back out of an f.req envelope."""
    return json.loads(json.loads(freq)[0][0][1])


class TestLegacyImagePayload:
    def test_maps_generated_image_to_save_image_shape(self):
        img = fb.GeneratedImage(media_id="mid", url="https://flow-content.google/image/mid?x")
        assert _legacy_image_payload(img) == {
            "media": [
                {
                    "image": {
                        "generatedImage": {
                            "mediaId": "mid",
                            "fifeUrl": "https://flow-content.google/image/mid?x",
                        }
                    }
                }
            ]
        }


class TestFailureText:
    def test_error_slot_envelope_yields_readable_failure_text(self):
        raw = _error_envelope()
        with pytest.raises(fb.RpcError) as exc:
            _parse_generated_image(raw)
        assert "ogiZ0b" in _failure_text(raw, str(exc.value))

    def test_extension_error_text_wins_over_raw(self):
        assert _failure_text("raw body", "PUBLIC_ERROR_UNUSUAL_ACTIVITY") == "PUBLIC_ERROR_UNUSUAL_ACTIVITY"

    def test_empty_inputs_still_return_text(self):
        assert _failure_text("", "") != ""


class TestFlowProjects:
    def test_override_wins_over_store(self):
        assert flow_projects.resolve_project_id(
            "acct", settings_project_id="override", store={"acct": "stored"},
        ) == "override"

    def test_store_hit_and_miss(self):
        store = {"acct": "stored"}
        assert flow_projects.resolve_project_id("acct", settings_project_id="", store=store) == "stored"
        assert flow_projects.resolve_project_id("other", settings_project_id="", store=store) is None

    def test_missing_store_file_reads_empty(self, tmp_path):
        assert flow_projects.load_store(tmp_path / "missing.json") == {}

    def test_remember_roundtrip(self, tmp_path):
        path = tmp_path / "flow_projects.json"
        flow_projects.remember_project_id("acct", "proj-1", path)
        assert flow_projects.load_store(path) == {"acct": "proj-1"}
        assert flow_projects.resolve_project_id(
            "acct", settings_project_id="", store=flow_projects.load_store(path),
        ) == "proj-1"


class TestDispatchImageRequest:
    def test_slots_match_the_dispatch_builder_params(self):
        freq = fb.image_request(
            prompt="a cat",
            project_id="proj-1",
            aspect="IMAGE_ASPECT_RATIO_LANDSCAPE",
            model=fb.resolve_image_model("NANO_BANANA_2"),
            ref_media_ids=["ref-1"],
        )
        payload = _inner(freq)
        assert len(payload[1]) == 1
        item = payload[1][0]
        assert item[4] == fb.ASPECT_LANDSCAPE == 3
        assert item[5] == "NARWHAL"
        assert item[2] == [["ref-1", None, None, None, fb.REF_TYPE_IMAGE]]
        assert item[7][5] == "proj-1"
        assert fb.CAPTCHA_SLOT in freq
