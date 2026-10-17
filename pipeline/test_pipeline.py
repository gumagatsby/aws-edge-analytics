import math
import os

import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-2")
for k, v in {"CLEAN_DB": "c", "CURATED_DB": "k", "LAKE_BUCKET": "lake", "ARTIFACTS_BUCKET": "art"}.items():
    os.environ.setdefault(k, v)

import handler  # noqa: E402
from publish import ab_test, price_class_scenarios  # noqa: E402


def test_days_are_validated_before_reaching_sql():
    assert handler.valid_day("2026-10-16") == "2026-10-16"
    for bad in ["2026-13-01", "2026-10-16'; DROP TABLE x; --", "yesterday", None]:
        with pytest.raises(ValueError):
            handler.valid_day(bad)


def test_resolve_forms():
    assert handler.resolve({"day": "2026-10-16"}) == {"days": ["2026-10-16"]}
    assert handler.resolve({"start": "2026-10-10", "end": "2026-10-12"})["days"] == ["2026-10-10", "2026-10-11", "2026-10-12"]
    assert len(handler.resolve({})["days"]) == 1
    with pytest.raises(ValueError):
        handler.resolve({"start": "2026-01-01", "end": "2026-03-01"})


def test_sql_files_render_with_every_placeholder_filled():
    for name, day in [("ensure", None), ("fact", "2026-10-16"), ("aggregates", "2026-10-16")]:
        statements = handler.render(name, day)
        assert statements and all("${" not in s for s in statements)
    assert any("DATE '2026-10-16'" in s for s in handler.render("fact", "2026-10-16"))


def test_ab_test_matches_a_hand_calculation():
    r = ab_test(10000, 300, 10000, 360)
    pooled = 660 / 20000
    z = (0.036 - 0.03) / math.sqrt(pooled * (1 - pooled) * 2 / 10000)
    assert r["z"] == pytest.approx(z)
    assert r["relative_lift"] == pytest.approx(0.2)
    assert r["significant"] is True
    assert ab_test(100, 3, 100, 4)["significant"] is False


def test_price_class_scenarios_reprice_excluded_regions():
    rows = [{"pricing_region": "Europe", "price_class": "PriceClass_100", "gb": 100, "usd_per_gb": 0.085},
            {"pricing_region": "Australia", "price_class": "PriceClass_All", "gb": 10, "usd_per_gb": 0.114},
            {"pricing_region": "India", "price_class": "PriceClass_200", "gb": 10, "usd_per_gb": 0.109}]
    s = price_class_scenarios(rows, {"Europe": 0.085})
    assert s["PriceClass_All"]["usd"] == pytest.approx(8.5 + 1.14 + 1.09)
    assert s["PriceClass_200"]["usd"] == pytest.approx(8.5 + 0.85 + 1.09)
    assert s["PriceClass_100"]["usd"] == pytest.approx(8.5 + 0.85 + 0.85)
    assert s["PriceClass_100"]["gb_served_from_further_away"] == 20
