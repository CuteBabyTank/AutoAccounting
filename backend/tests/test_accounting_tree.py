import uuid

from app.services.accounting.tree import TreeCompanyInput, build_tree, folder_counts

A, B = str(uuid.uuid4()), str(uuid.uuid4())


def test_build_tree_nests_years_and_quarters_newest_first():
    companies = [
        TreeCompanyInput(A, "Juan's Cloth Trading", "123456789", True, 12),
        TreeCompanyInput(B, "Maria's Bakery", "987654321", False, 6),
    ]
    rows = [
        (uuid.UUID(A), 2026, 2, 10, 0),
        (uuid.UUID(A), 2026, 3, 48, 5),
        (uuid.UUID(A), 2025, 4, 7, None),
        (uuid.UUID(A), None, None, 2, 2),
        (uuid.uuid4(), 2026, 1, 1, 0),  # company not in list → ignored
    ]
    tree = build_tree(companies, rows)
    juan, maria = tree
    assert [y["year"] for y in juan["years"]] == [2026, 2025]
    assert [q["quarter"] for q in juan["years"][0]["quarters"]] == [4, 3, 2, 1]
    assert [q["quarter"] for q in juan["years"][1]["quarters"]] == [4, 3, 2, 1]
    assert juan["years"][0]["quarters"][1] == {
        "year": 2026, "quarter": 3, "label": "Q3 (Jul–Sep)", "document_count": 48, "review_count": 5,
        "latest_version": None, "stale": False, "filed": False,
    }
    assert juan["years"][1]["quarters"][0]["review_count"] == 0
    assert juan["years"][0]["quarters"][0] == {
        "year": 2026, "quarter": 4, "label": "Q4 (Oct–Dec)", "document_count": 0, "review_count": 0,
        "latest_version": None, "stale": False, "filed": False,
    }
    assert juan["undated_count"] == 2
    assert maria["years"] == [] and maria["undated_count"] == 0 and maria["fiscal_year_end_month"] == 6


def test_folder_counts_skip_excluded_and_count_open_reviews():
    counts = folder_counts([
        ("sales", False, False, False),
        ("purchases", True, False, False),
        ("purchases", True, True, False),
        ("expenses", True, False, True),
    ])
    assert counts["sales"] == 1 and counts["purchases"] == 2 and counts["expenses"] == 0
    assert counts["review"] == 1
    assert counts["unsorted"] == 0


def test_build_tree_merges_quarter_status():
    companies = [TreeCompanyInput(A, "Juan's Cloth Trading", "123456789", False, 12)]
    tree = build_tree(companies, [(uuid.UUID(A), 2026, 3, 4, 0)],
                      {(A, 2026, 3): {"latest_version": 2, "stale": True, "filed": True}})
    quarter = next(q for q in tree[0]["years"][0]["quarters"] if q["quarter"] == 3)
    assert (quarter["latest_version"], quarter["stale"], quarter["filed"]) == (2, True, True)


def test_build_tree_adds_an_annual_node_per_year():
    companies = [TreeCompanyInput(A, "Juan's Cloth Trading", "123456789", False, 12)]
    tree = build_tree(companies, [(uuid.UUID(A), 2026, 3, 4, 0), (uuid.UUID(A), 2025, 1, 1, 0)],
                      {(A, 2026, 0): {"latest_version": 1, "stale": True, "filed": False}})
    y2026, y2025 = tree[0]["years"]
    assert y2026["annual"] == {"latest_version": 1, "stale": True, "filed": False}
    assert y2025["annual"] == {"latest_version": None, "stale": False, "filed": False}
    assert all(q["quarter"] != 0 for q in y2026["quarters"])


def test_build_tree_shows_a_year_that_only_has_outputs():
    companies = [TreeCompanyInput(A, "Juan's Cloth Trading", "123456789", False, 12)]
    tree = build_tree(companies, [], {(A, 2025, 2): {"latest_version": 1, "stale": False, "filed": True},
                                      (A, 2025, 0): {"latest_version": 1, "stale": False, "filed": False}})
    (year,) = tree[0]["years"]
    assert year["year"] == 2025 and [q["quarter"] for q in year["quarters"]] == [4, 3, 2, 1]
    q2 = next(q for q in year["quarters"] if q["quarter"] == 2)
    assert (q2["document_count"], q2["latest_version"], q2["filed"]) == (0, 1, True)
