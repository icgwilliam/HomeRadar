from metrocuadrado import parse_listing


def test_records_are_not_mixed_and_built_area_is_used() -> None:
    html = r'''initialResults\":{\"results\":[
    {\"contactPhone\":\"1\",\"title\":\"Primero\",\"link\":\"/uno\",
    \"mvalorventa\":385000000,\"marea\":42.31,\"mareac\":46.9,
    \"mnrocuartos\":\"1\",\"mnrobanos\":\"2\",\"mnrogarajes\":\"1\",
    \"mbarrio\":\"CHAPINERO CENTRAL\"},
    {\"contactPhone\":\"2\",\"title\":\"Segundo\",\"link\":\"/dos\",
    \"mvalorventa\":500000000,\"marea\":108,\"mareac\":108,
    \"mnrocuartos\":\"3\",\"mnrobanos\":\"3\",\"mnrogarajes\":\"2\",
    \"mbarrio\":\"OTRO\"}] }'''

    result = parse_listing(html, "chapinero")

    assert len(result) == 2
    assert result[0].link.endswith("/uno")
    assert result[0].area == "46.9 m2"
    assert result[0].habitaciones == "1"
    assert result[0].parqueaderos == "1"
    assert result[1].area == "108 m2"
