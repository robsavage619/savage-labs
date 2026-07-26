from __future__ import annotations

import pytest

# Frequently-trained movements that migration 0064 curated off the recency
# fallback. Guards against a later schema change silently dropping their
# exercise_science rows (which would send them back to blind recency selection).
_CURATED_BY_0064 = [
    ("Hammerstrength Incline Chest Press", "chest"),
    ("Hammerstrength Incline Chest Press", "front_delts"),
    ("Hammerstrength Shoulder Press", "front_delts"),
    ("Seated Dumbbell Curl", "biceps"),
    ("Hammer Curls", "biceps"),
    ("Hammer Curls", "forearms"),
    ("Triceps Rope Pushdown", "triceps"),
    ("Machine Tricep Dip", "triceps"),
    ("Overhead Triceps Extension (Cable)", "triceps"),
    ("Cable Rope Overhead Triceps Extension", "triceps"),
    ("Cable Fly Crossovers", "chest"),
    ("Low Cable Fly Crossovers", "chest"),
    ("Seated Leg Curl (Machine)", "hamstrings"),
    ("Standing Machine Calf Press", "calves"),
    ("Iso-Lateral Row (Machine)", "lats"),
]


@pytest.mark.parametrize("exercise,muscle", _CURATED_BY_0064)
def test_movement_is_science_curated(conn, exercise: str, muscle: str) -> None:
    row = conn.execute(
        "SELECT region, length_bias, rep_low, rep_high, citation, citation_url "
        "FROM exercise_science WHERE exercise_name = ? AND muscle = ?",
        [exercise, muscle],
    ).fetchone()
    assert row is not None, f"{exercise} / {muscle} lost its exercise_science row"
    region, length_bias, rep_low, rep_high, citation, citation_url = row
    assert region and length_bias
    assert 1 <= rep_low <= rep_high <= 30
    # Inherited from a vetted canonical row — the citation must be real, not blank.
    # `http` alone is no longer the test: migration 0080 re-grounded these rows
    # from unverifiable paper names onto vault notes, and 0081 pointed them at
    # `obsidian://` URIs. A vault note IS the authoritative source here, so
    # requiring a web URL would fail the rows with the BEST provenance while
    # passing a consensus.app link to a paper nobody can check. The property
    # being guarded is unchanged: a citation that is present and resolvable.
    assert citation, f"{exercise}/{muscle} lost its citation"
    assert citation_url and citation_url.startswith(("http", "obsidian://")), (
        f"{exercise}/{muscle} citation_url is not resolvable: {citation_url!r}"
    )


def test_low_cable_fly_biases_upper_chest(conn) -> None:
    # A low-to-high cable fly must inherit the UPPER-chest row, not mid-chest —
    # the mechanics-matching source choice, not a blind copy.
    region = conn.execute(
        "SELECT region FROM exercise_science "
        "WHERE exercise_name = 'Low Cable Fly Crossovers' AND muscle = 'chest'"
    ).fetchone()
    assert region[0] == "upper_chest"


# Claims the vault actively CONTRADICTS. These movements still credit volume —
# they involve the muscle — but must never be SELECTABLE as a builder for it,
# and must never carry a citation, because the note that would be cited refutes
# the claim. Migration 0080 keyed its drops on (exercise_name, citation) while
# simultaneously rewriting `citation`, so two of three drops landed and one
# silently did not; 0082 fixed it. This guards the outcome, not the mechanism.
_VAULT_CONTRADICTED = [
    ("Arnold Press (Dumbbell)", "side_delts"),  # ch8: press is primarily ANTERIOR head
    ("Overhead Press (Dumbbell)", "side_delts"),  # same
    ("Step Up (Dumbbell)", "glutes"),  # ch8: glute med is frontal-plane abduction only
]


@pytest.mark.parametrize("exercise,muscle", _VAULT_CONTRADICTED)
def test_vault_contradicted_claims_are_not_selectable(conn, exercise: str, muscle: str) -> None:
    sci = conn.execute(
        "SELECT citation FROM exercise_science WHERE exercise_name = ? AND muscle = ?",
        [exercise, muscle],
    ).fetchall()
    assert not sci, f"{exercise}/{muscle} is selectable on a claim the vault contradicts: {sci}"

    # The crediting row must survive — dropping it would lose real volume.
    still_credits = conn.execute(
        "SELECT 1 FROM exercise_muscle WHERE exercise_name = ? AND muscle = ?",
        [exercise, muscle],
    ).fetchone()
    assert still_credits, f"{exercise}/{muscle} lost its volume crediting, not just its science"


def test_no_curated_row_cites_an_unverifiable_paper(conn) -> None:
    """Every citation is a vault filename or is explicitly marked UNGROUNDED.

    The planner's own rule is to cite only real catalogue notes; 113 of 126 rows
    broke it with paper names appearing nowhere in the vault. A claim that can't
    be grounded is now labelled as such rather than dressed in a citation that
    looks real — the row stays usable and the gap stays greppable.
    """
    bad = conn.execute(
        "SELECT DISTINCT citation FROM exercise_science "
        "WHERE citation NOT LIKE '%.md' AND citation NOT LIKE 'UNGROUNDED%'"
    ).fetchall()
    assert not bad, f"citations that are neither a vault note nor marked ungrounded: {bad}"


def test_preacher_curl_variants_agree_on_length_bias(conn) -> None:
    """The same movement pattern cannot be both lengthened- and shortened-biased.

    `Preacher Curl (Dumbbell)` claimed `shortened` while `(Barbell)` and
    `(Machine)` claimed `lengthened`. length_bias is a ranking key in
    `_select_grounded`, so the disagreement changed which curl got selected
    depending on which variant the menu happened to surface — a coin-flip
    dressed as evidence.

    Settled against the literature rather than by picking one: Zabaleta-Korta
    2023 found the only growth in a 9-week incline-vs-preacher trial was
    DISTAL, in the preacher group, attributed to peak strain landing where the
    elbow flexors are most elongated; Kassiano 2024 replicated the
    distal-vs-proximal split at n=63. `lengthened` is correct.
    """
    biases = conn.execute(
        "SELECT DISTINCT length_bias FROM exercise_science "
        "WHERE exercise_name LIKE 'Preacher Curl%' AND length_bias IS NOT NULL"
    ).fetchall()
    assert len(biases) == 1, f"preacher curl variants disagree on length_bias: {biases}"
    assert biases[0][0] == "lengthened"


def test_every_vault_citation_resolves_to_a_real_note(conn) -> None:
    """A `.md` citation must name a file that actually exists in the vault.

    The whole point of re-grounding was that 113 rows cited papers nobody could
    check. A citation that looks like a vault note but resolves to nothing is
    the same failure wearing the fix's clothing.

    Skips when the vault isn't on this machine — the assertion is about the
    citations, and CI shouldn't fail for not having Rob's Obsidian folder.
    """
    import pathlib

    vault = pathlib.Path.home() / "Vault" / "savage_vault" / "wiki"
    if not vault.is_dir():
        pytest.skip("vault not present on this machine")

    cited = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT citation FROM exercise_science WHERE citation LIKE '%.md'"
        ).fetchall()
    }
    missing = sorted(c for c in cited if not (vault / c).is_file())
    assert not missing, f"citations naming a note that does not exist in the vault: {missing}"
