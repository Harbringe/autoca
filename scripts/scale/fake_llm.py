"""A stand-in model for the scale test of the assistant worker: answers at once (after a short pretend network wait) with a ledger from
the client's own list, so the whole claim, apply and auto-post path runs and only the provider's thinking time is missing.

Used only in the scratch environment (scale.sh passes ``LLM_BACKEND=fake_llm.FakeLLMAdapter``). It answers every row, sure enough
(0.96) that the app posts it, so the cost of posting is part of what is measured.
"""

from __future__ import annotations

import json
import os
import time

from integrations.llm.base import LLMAdapter, LLMResponse


class FakeLLMAdapter(LLMAdapter):
    is_available = True

    def __init__(self, **_ignored):
        self.wait = float(os.environ.get("FAKE_LLM_SECONDS", "0.4"))

    def complete_json(self, system, user, *, max_tokens=2048):
        time.sleep(self.wait)
        prompt = json.loads(user)
        ledgers = prompt.get("ledgers") or []
        names = [item["name"] if isinstance(item, dict) else str(item) for item in ledgers]
        pick = names[0] if names else None
        suggestions = [
            {
                "key": row["key"],
                "ledger": pick,
                "fit": True,
                "new_ledger": None,
                "narration": "",
                "question": "",
                "party_alias": None,
                "party_guess": None,
                "rcm": False,
                "tds_section": "",
                "confidence": 0.96,
                "rationale": "scale test",
            }
            for row in prompt.get("transactions", [])
        ]
        return LLMResponse(text=json.dumps({"suggestions": suggestions}), model="scale-fake")
