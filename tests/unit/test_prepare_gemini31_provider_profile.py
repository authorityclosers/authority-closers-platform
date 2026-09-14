from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.database.test_conversation_authority_postgresql import _registry_config
from tests.unit.conversation_intelligence.test_provider_activation import _approved_bundle

_SCRIPT = Path(__file__).parents[2] / "scripts" / "prepare_gemini31_provider_profile.py"
_SPEC = importlib.util.spec_from_file_location("prepare_gemini31_provider_profile", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

PRO_C4_MAX_COST_PAISE = _MODULE.PRO_C4_MAX_COST_PAISE
PRO_MODEL_ID = _MODULE.PRO_MODEL_ID
build_alternate_profile = _MODULE.build_alternate_profile
build_alternate_registry = _MODULE.build_alternate_registry
pro_c4_cost_bound_paise = _MODULE.pro_c4_cost_bound_paise


def test_pro_c4_bound_is_below_the_rounded_candidate_cap() -> None:
    assert pro_c4_cost_bound_paise() == 559
    assert PRO_C4_MAX_COST_PAISE == 700


def test_preparer_binds_pro_c4_and_flash_c5_to_new_registry_digest() -> None:
    base = _registry_config(
        "prepared-gemini-base-v1", funded=True, text_provider="gemini", text_cost_paise=40
    )
    alternate = build_alternate_registry(
        base,
        revision="prepared-gemini-base-v1-gemini31-c4",
    )
    bundle = _approved_bundle(base, funded=True, text_provider="gemini", text_cost_paise=40)
    profile = build_alternate_profile(
        bundle,
        configuration_sha256=alternate.digest,
        pricing_evidence_sha256="e" * 64,
    )
    assert alternate.digest != base.digest
    assert alternate.routes[1].model_id == PRO_MODEL_ID
    assert alternate.routes[2].model_id == "gemini-3.8-flash"
    assert profile.stages[1].model_id == PRO_MODEL_ID
    assert profile.stages[1].max_cost_paise == PRO_C4_MAX_COST_PAISE
    assert profile.stages[1].max_input_bytes == _MODULE.PRO_C4_MAX_INPUT_BYTES
    assert profile.stages[2].model_id == "gemini-3.8-flash"
    assert profile.stages[0].configuration_sha256 == alternate.digest
