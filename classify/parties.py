"""Working out which party a narration is about.

A bank prints the same payee differently on every channel it touches --
``RAMESH TRADRS PVT`` on an RTGS line, ``Ramesh Traders`` on a cheque,
``RAMESH TRADERS-SETTL`` when the counterparty's own system appends a note.
Exact matching on a canonical name recognises the first one a firm typed and
none of the rest, which is why, before this module, ``party_for`` found almost
nothing outside a management command.

The rule this module is built on:

    **Deterministic signals resolve. Similarity only ever suggests.**

Two accounts quoting the same number are the same counterparty; two GSTINs that
are equal are the same legal entity. Those are facts, and facts may resolve a
party with nobody in the loop. A similarity score is not a fact. Acting on one
means merging two parties' histories, and the failure is silent and expensive:
one person's receipts land in another person's ledger, both balances are wrong,
and nothing downstream reports it. There is no threshold high enough to make
that safe, so there is no threshold at which this module returns AUTO on a
fuzzy match -- the ceiling is in code, not in settings, because it is a
correctness boundary rather than a tuning knob.

What a person confirms, though, is remembered exactly. ``confirm_alias`` turns
one human decision into a ``PartyAlias`` that resolves deterministically
forever after -- the same shape as ``engine.learn_rule_from``, and the reason
the queue shrinks: a firm is asked about a spelling once, not every month.

``resolve`` writes nothing. It is asked speculatively, including for rows
nobody will ever review, and a resolver with a side effect would be building a
party master out of guesses.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from django.conf import settings

from classify.models import AliasSource, Party, PartyAlias, PartyBankAccount
from classify.narration import normalise

#: Above this, a similar name is worth putting in front of a person first.
#: Below the weak threshold it is not worth mentioning at all -- a wrong
#: suggestion costs more attention than no suggestion.
STRONG = getattr(settings, "PARTY_FUZZY_STRONG", 0.92)
WEAK = getattr(settings, "PARTY_FUZZY_WEAK", 0.80)

#: How many suggestions to carry. A person choosing between three names is
#: choosing; a person choosing between twelve is reading a list.
MAX_CANDIDATES = 3


#: Legal-entity words that say what *kind* of business something is, not *which*
#: one. "Ramesh Traders" and "Ramesh Traders Pvt Ltd" are one relationship with
#: or without them, so they are set aside when judging whether two names look
#: alike. Used only for suggesting a match -- the exact paths (alias, canonical
#: name) still compare the whole name via ``narration.normalise``.
_ENTITY_WORDS = frozenset({"PVT", "PRIVATE", "LTD", "LIMITED", "LLP", "CO", "COMPANY"})


def _similarity_key(name: str) -> str:
    """A name reduced to what identifies it, for judging resemblance only.

    Two things carry no identity and are removed. **Corporate suffixes**, above.
    And **word order**: "Traders Ramesh" and "Ramesh Traders" are the same words,
    but joined space-free they share almost no letters in sequence, so a plain
    character comparison would call them strangers. Sorting the words first
    makes the order irrelevant.

    ``narration.normalise`` strips spaces entirely, which is right for exact
    matching (a PDF wraps names mid-word) and wrong here, where the words are
    exactly the thing being compared -- so this tokenises from the raw text.
    """
    words = [w for w in re.findall(r"[A-Z0-9]+", (name or "").upper()) if w not in _ENTITY_WORDS]
    return "".join(sorted(words))


class Kind:
    #: A deterministic signal identified the party. Safe to use unasked.
    AUTO = "AUTO"
    #: Something looks close. A person decides; nothing is written until they do.
    CANDIDATE = "CANDIDATE"
    #: Nothing matched. Either a genuinely new party or one whose first
    #: appearance this is.
    NEW = "NEW"


class Signal:
    ACCOUNT_HASH = "ACCOUNT_HASH"
    GSTIN = "GSTIN"
    ALIAS_CONFIRMED = "ALIAS_CONFIRMED"
    CANONICAL_NAME = "CANONICAL_NAME"
    FUZZY = "FUZZY"
    NONE = "NONE"


@dataclass(frozen=True)
class PartyCandidate:
    party: object
    score: float
    #: Shown to the person being asked. "Looks like" with no reason is a
    #: request to rubber-stamp; the reason is what makes it a decision.
    why: str


@dataclass(frozen=True)
class PartyResolution:
    kind: str
    party: object = None
    score: float = 0.0
    signal: str = Signal.NONE
    candidates: tuple[PartyCandidate, ...] = field(default_factory=tuple)
    #: True when two deterministic signals disagreed -- the account says one
    #: party, the GSTIN another. Never resolved by a tiebreak: a disagreement
    #: between two facts is exactly the case a person must look at.
    conflict: bool = False

    @property
    def is_certain(self) -> bool:
        return self.kind == Kind.AUTO


class PartyBook:
    """One client's parties and confirmed spellings, loaded once.

    Resolving a statement's worth of rows one call at a time meant several
    queries per row -- the alias, the party list, the alias list again for the
    fuzzy pass -- which is hundreds of round trips for something that reads the
    same two small tables. Loading them once and answering from memory makes it
    two queries however many rows there are. Account and GSTIN lookups are still
    per-call, because they are only asked when the row actually carries one.

    Read-only: nothing here writes, and a book built before ``confirm_alias``
    does not see it. Build a new one after recording a decision.
    """

    def __init__(self, client):
        self.client = client
        self.firm_id = client.firm_id
        self.parties = list(
            Party.objects.filter(firm_id=self.firm_id, client=client, is_active=True)
        )
        by_pk = {party.pk: party for party in self.parties}
        self._by_canonical = {normalise(p.canonical_name): p for p in self.parties}
        self._by_alias = {}
        self._spellings: dict = {}
        for row in PartyAlias.objects.filter(firm_id=self.firm_id, client=client):
            party = by_pk.get(row.party_id)
            if party is not None:
                self._by_alias[row.alias_normalised] = party
                self._spellings.setdefault(party.pk, []).append(row.alias_display)

    def resolve(
        self,
        *,
        counterparty: str,
        counterparty_account: str = "",
        gstin: str = "",
        own_accounts: tuple[str, ...] = (),
    ) -> PartyResolution:
        """Which party this counterparty is, or who it might be. Writes nothing.

        ``own_accounts`` are the client's own account hashes. A transfer between
        two of the client's accounts names a counterparty account that is theirs,
        and resolving that to a party would invent a supplier out of the client.
        """
        client, firm_id = self.client, self.firm_id

        account_match = None
        if counterparty_account:
            account_hash = PartyBankAccount.hash_for(counterparty_account, firm_id)
            if account_hash and account_hash not in own_accounts:
                row = (
                    PartyBankAccount.objects.filter(
                        firm_id=firm_id, client=client, account_hash=account_hash
                    )
                    .select_related("party")
                    .first()
                )
                account_match = row.party if row else None

        gstin_match = None
        if gstin:
            from classify.models import CRYPTO_PURPOSE
            from core.crypto import blind_index

            cleaned = (gstin or "").strip().upper()
            if cleaned:
                gstin_match = Party.objects.filter(
                    firm_id=firm_id,
                    client=client,
                    gstin_hash=blind_index(cleaned, firm_id, CRYPTO_PURPOSE),
                ).first()

        # Two facts that disagree. The GSTIN is the stronger of the two -- it is
        # issued against one legal entity, while an account number can be shared
        # across a group or reassigned after a bank merger -- but "stronger" is
        # not "right", and quietly picking a winner would bury the one signal
        # that something is wrong. Both go to a person.
        if account_match and gstin_match and account_match.pk != gstin_match.pk:
            return PartyResolution(
                kind=Kind.CANDIDATE,
                party=None,
                signal=Signal.GSTIN,
                conflict=True,
                candidates=(
                    PartyCandidate(gstin_match, 1.0, "the GSTIN on this transaction is theirs"),
                    PartyCandidate(
                        account_match, 1.0, "the account number on this transaction is theirs"
                    ),
                ),
            )

        if gstin_match is not None:
            return PartyResolution(
                kind=Kind.AUTO, party=gstin_match, score=1.0, signal=Signal.GSTIN
            )
        if account_match is not None:
            return PartyResolution(
                kind=Kind.AUTO, party=account_match, score=1.0, signal=Signal.ACCOUNT_HASH
            )

        key = normalise(counterparty)
        if not key:
            return PartyResolution(kind=Kind.NEW)

        if key in self._by_alias:
            return PartyResolution(
                kind=Kind.AUTO,
                party=self._by_alias[key],
                score=1.0,
                signal=Signal.ALIAS_CONFIRMED,
            )
        if key in self._by_canonical:
            return PartyResolution(
                kind=Kind.AUTO,
                party=self._by_canonical[key],
                score=1.0,
                signal=Signal.CANONICAL_NAME,
            )

        found = self._similar(counterparty)
        return PartyResolution(
            kind=Kind.CANDIDATE if found else Kind.NEW,
            signal=Signal.FUZZY if found else Signal.NONE,
            candidates=found,
        )

    def _similar(self, counterparty: str) -> tuple[PartyCandidate, ...]:
        """Parties whose name or a confirmed spelling of it looks like ``counterparty``.

        Each name is scored two ways and the better score kept: the space-free
        form ``narration.normalise`` gives (right when a PDF wrapped a name
        mid-word, so word boundaries are not information), and
        ``_similarity_key`` (right when the words are all there but in another
        order, or wear a different corporate suffix). Neither is uniformly
        better, so neither is dropped.
        """
        key = normalise(counterparty)
        loose = _similarity_key(counterparty)

        def score(candidate: str) -> float:
            strict = difflib.SequenceMatcher(None, key, normalise(candidate)).ratio()
            if not loose:
                return strict
            return max(
                strict,
                difflib.SequenceMatcher(None, loose, _similarity_key(candidate)).ratio(),
            )

        scored: list[PartyCandidate] = []
        for party in self.parties:
            best, why = 0.0, ""
            if normalise(party.canonical_name):
                best = score(party.canonical_name)
                why = f"the name looks like {party.canonical_name}"
            for spelling in self._spellings.get(party.pk, ()):
                ratio = score(spelling)
                if ratio > best:
                    best = ratio
                    why = f"a confirmed spelling of {party.canonical_name} looks like this"
            if best >= WEAK:
                scored.append(PartyCandidate(party, round(best, 4), why))

        scored.sort(key=lambda c: c.score, reverse=True)
        return tuple(scored[:MAX_CANDIDATES])


def candidates_as_json(resolution: PartyResolution) -> list[dict]:
    """A resolution's suggestions in the shape stored on a classification."""
    return [
        {
            "party": str(c.party.pk),
            "name": c.party.canonical_name,
            "score": c.score,
            "why": c.why,
            "source": "SIMILAR_NAME" if resolution.signal == Signal.FUZZY else resolution.signal,
        }
        for c in resolution.candidates
    ]


def add_suggestion(existing: list[dict], party, why: str, *, source: str, score: float = 0.0) -> list[dict]:
    """Add one more suggestion for who this is, without duplicating a party.

    A party already suggested keeps its entry, and gains the new reason -- two
    independent clues pointing at the same party is worth showing as such, and
    a list naming one party twice is not.
    """
    merged = [dict(item) for item in existing or []]
    for item in merged:
        if item.get("party") == str(party.pk):
            if why not in item.get("why", ""):
                item["why"] = f"{item['why']}; {why}".strip("; ")
            item["source"] = f"{item.get('source', '')}+{source}".strip("+")
            return merged
    merged.append(
        {"party": str(party.pk), "name": party.canonical_name, "score": score, "why": why, "source": source}
    )
    return merged[:MAX_CANDIDATES]


def resolve(client, **kwargs) -> PartyResolution:
    """One-off resolution. See :meth:`PartyBook.resolve` for the arguments.

    Builds a fresh :class:`PartyBook` per call, which is right for a single
    counterparty and wrong for a statement -- use a ``PartyBook`` for those.
    """
    return PartyBook(client).resolve(**kwargs)


def confirm_alias(client, party, spelling: str, *, source=AliasSource.BANK_NARRATION, user=None):
    """Remember that ``spelling`` means ``party``, so it is never asked again.

    Idempotent, and deliberately tolerant of the spelling already being known:
    two reviewers placing two rows for the same payee in the same minute is
    ordinary, and the second one is not an error to report.

    Returns ``None`` when the spelling is already claimed by a *different*
    party. That is not a conflict to resolve here -- reassigning a spelling
    silently would move history from one party to another, which is the merge
    this module refuses to do on its own.
    """
    key = normalise(spelling)
    if not key or party is None:
        return None

    existing = PartyAlias.objects.filter(
        firm_id=client.firm_id, client=client, alias_normalised=key
    ).first()
    if existing is not None:
        return existing if existing.party_id == party.pk else None

    return PartyAlias.objects.create(
        firm_id=client.firm_id,
        client=client,
        party=party,
        alias_normalised=key,
        alias_display=(spelling or "").strip()[:255],
        source=source,
        confirmed_by=user,
    )


def remember_account(client, party, account_number: str, *, source=AliasSource.BANK_NARRATION, user=None):
    """Remember an account number as this party's. Same contract as ``confirm_alias``."""
    account_hash = PartyBankAccount.hash_for(account_number, client.firm_id)
    if not account_hash or party is None:
        return None

    existing = PartyBankAccount.objects.filter(
        firm_id=client.firm_id, client=client, account_hash=account_hash
    ).first()
    if existing is not None:
        return existing if existing.party_id == party.pk else None

    digits = "".join(ch for ch in (account_number or "") if ch.isdigit())
    return PartyBankAccount.objects.create(
        firm_id=client.firm_id,
        client=client,
        party=party,
        account_hash=account_hash,
        last4=digits[-4:],
        source=source,
        confirmed_by=user,
    )
