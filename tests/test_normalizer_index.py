from moneyline.markets.normalizer import MarketNormalizer
from moneyline.models.schemas import Sport


def test_sub_type_186_maps_to_prematch_match_winner():
    normalizer = MarketNormalizer()
    hit = normalizer._betika_index.get((Sport.TENNIS, "186"))
    assert hit is not None
    assert hit[0] == "match_winner"
    assert not hit[1].get("live_only")
