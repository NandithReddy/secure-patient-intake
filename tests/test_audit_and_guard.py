"""The audit log must actually be readable, and the guard must fail closed."""

from __future__ import annotations

import json

import pytest

from deid.audit import AuditLog
from deid.guard import EgressGuard, PhiLeakBlocked
from deid.redactors.rules import RuleRedactor
from deid.types import PhiSpan


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


class TestAuditLog:
    def test_entries_are_on_separate_lines(self, log):
        """The original bug: `'\\\\n'` wrote a literal backslash-n, so 130
        records shared one line and `wc -l` reported zero."""
        log.record("A")
        log.record("B")
        raw = log.path.read_text()
        assert raw.count("\n") == 2
        assert "\\n" not in raw
        assert len(raw.strip().splitlines()) == 2

    def test_every_line_is_valid_json(self, log):
        log.record("VIEW_PATIENT", actor_id=2, actor_role="clinician", patient_id="x")
        for line in log.path.read_text().splitlines():
            json.loads(line)

    def test_chain_verifies_when_untouched(self, log):
        for i in range(5):
            log.record("ACTION", actor_id=i)
        result = log.verify()
        assert result.ok and result.entries == 5

    def test_edited_record_breaks_the_chain(self, log):
        log.record("CREATE", actor_id=1)
        log.record("DELETE", actor_id=1)
        log.record("VIEW", actor_id=1)

        lines = log.path.read_text().splitlines()
        tampered = json.loads(lines[1])
        tampered["actor_id"] = 999           # cover someone's tracks
        lines[1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
        log.path.write_text("\n".join(lines) + "\n")

        result = log.verify()
        assert not result.ok
        assert result.broken_at == 2  # the *next* record's prev-hash no longer matches

    def test_deleted_record_breaks_the_chain(self, log):
        for i in range(4):
            log.record("ACTION", actor_id=i)
        lines = log.path.read_text().splitlines()
        del lines[1]
        log.path.write_text("\n".join(lines) + "\n")

        assert not log.verify().ok

    def test_egress_records_a_hash_not_the_payload(self, log):
        secret = "Patient Nandith Reddy, SSN 123-45-6789"
        log.record_egress(destination="anthropic", payload=secret,
                          redactions={"NAME": 1, "ID": 1})
        raw = log.path.read_text()
        assert "Nandith" not in raw
        assert "123-45-6789" not in raw
        entry = json.loads(raw.strip())
        assert len(entry["payload_sha256"]) == 64
        assert entry["payload_chars"] == len(secret)


class TestEgressGuard:
    def test_blocks_text_that_still_contains_phi(self, log):
        guard = EgressGuard(RuleRedactor(), log)
        with pytest.raises(PhiLeakBlocked) as exc:
            guard.send("Contact 555-123-4567", destination="anthropic",
                       fn=lambda t: "sent")
        assert "CONTACT" in str(exc.value)

    def test_allows_clean_text_and_audits_it(self, log):
        guard = EgressGuard(RuleRedactor(), log)
        out = guard.send("Patient has [**CONTACT**] on file.",
                         destination="anthropic", fn=lambda t: "sent")
        assert out == "sent"
        entries = list(log.read())
        assert entries[-1]["action"] == "EGRESS"

    def test_blocked_send_never_calls_the_downstream(self, log):
        guard = EgressGuard(RuleRedactor(), log)
        called = []
        with pytest.raises(PhiLeakBlocked):
            guard.send("SSN 123-45-6789", destination="x",
                       fn=lambda t: called.append(t))
        assert called == []
        assert list(log.read())[-1]["action"] == "EGRESS_BLOCKED"

    def test_fails_closed_when_the_detector_raises(self, log):
        class Broken(RuleRedactor):
            def find(self, text):
                raise RuntimeError("model unavailable")

        guard = EgressGuard(Broken(), log)
        called = []
        with pytest.raises(PhiLeakBlocked):
            guard.send("anything", destination="x", fn=lambda t: called.append(t))
        # A detector outage must not become a disclosure.
        assert called == []

    def test_refuses_an_offsite_detector(self, log):
        class Offsite(RuleRedactor):
            transmits_offsite = True

        with pytest.raises(ValueError, match="off-machine"):
            EgressGuard(Offsite(), log)

    def test_placeholder_false_positive_does_not_block(self, log):
        """A detector that flags a bracket inside [**NAME**] must not block a
        fully-redacted note. This reproduces a real bug: the transformer, run on
        its own redaction markers, flagged the '[' of a placeholder as a name."""
        from deid.types import PhiSpan, PhiCategory

        redacted = "Patient: [**NAME**] seen on [**DATE**]."
        bracket = redacted.index("[")  # first '[' of [**NAME**]

        class FlagsABracket(RuleRedactor):
            def find(self, text):
                return (PhiSpan(bracket, bracket + 1, PhiCategory.NAME, "["),)

        guard = EgressGuard(FlagsABracket(), log)
        out = guard.send(redacted, destination="anthropic", fn=lambda t: "sent")
        assert out == "sent"  # not blocked — the '[' is inside a placeholder

    def test_real_name_next_to_a_placeholder_still_blocks(self, log):
        """The placeholder filter must not hide a genuinely missed name."""
        from deid.types import PhiSpan, PhiCategory

        # "Reddy" was missed; "[**DATE**]" was redacted.
        text = "Reddy seen on [**DATE**]."
        start = text.index("Reddy")

        class MissesAName(RuleRedactor):
            def find(self, text):
                return (PhiSpan(start, start + 5, PhiCategory.NAME, "Reddy"),)

        guard = EgressGuard(MissesAName(), log)
        with pytest.raises(PhiLeakBlocked, match="NAME"):
            guard.send(text, destination="anthropic", fn=lambda t: "sent")
