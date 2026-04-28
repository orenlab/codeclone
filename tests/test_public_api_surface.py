from __future__ import annotations

import inspect
from typing import cast

import codeclone
import codeclone.main as main_module
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests._contract_snapshots import load_json_snapshot


def test_public_api_surface_snapshot() -> None:
    snapshot = {
        "codeclone_exports": list(getattr(codeclone, "__all__", ())),
        "main_exports": list(getattr(main_module, "__all__", ())),
        "main_signature": str(inspect.signature(main_module.main)),
        "mcp_service_public_methods": [
            {
                "name": name,
                "signature": str(inspect.signature(member)),
            }
            for name, member in inspect.getmembers(
                CodeCloneMCPService,
                predicate=inspect.isfunction,
            )
            if not name.startswith("_")
        ],
    }
    expected = cast(
        "dict[str, object]",
        load_json_snapshot("public_api_surface.json"),
    )
    assert snapshot == expected
