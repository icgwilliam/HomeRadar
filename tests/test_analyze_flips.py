import pandas as pd

from analyze_flips import analyze, build_report


def sample_frame() -> pd.DataFrame:
    rows = []
    for index, value_m2 in enumerate([5_000_000, 5_200_000, 5_400_000, 5_600_000, 5_800_000]):
        rows.append({
            "link": f"https://example.com/comp-{index}",
            "title": "Apartamento en venta en Usaquén",
            "ubicacion": "Usaquén",
            "precio": value_m2 * 70,
            "area_m2": 70,
            "valor_m2": value_m2,
        })
    rows.append({
        "link": "https://example.com/oportunidad",
        "title": "Oportunidad para remodelar en Usaquén",
        "ubicacion": "Usaquén",
        "precio": 280_000_000,
        "area_m2": 70,
        "valor_m2": 4_000_000,
    })
    return pd.DataFrame(rows)


def test_detects_discounted_candidate() -> None:
    result = analyze(sample_frame())
    assert len(result) == 1
    assert result.iloc[0]["link"].endswith("/oportunidad")
    assert result.iloc[0]["descuento_mercado"] > 0.20
    assert result.iloc[0]["puntaje"] >= 60


def test_excludes_property_over_budget() -> None:
    frame = sample_frame()
    frame.loc[frame["link"].str.endswith("/oportunidad"), "precio"] = 550_000_000
    result = analyze(frame)
    assert result.empty


def test_report_is_empty_without_candidates() -> None:
    assert build_report(pd.DataFrame()).strip() == ""


def test_property_without_comparables_does_not_crash() -> None:
    frame = pd.DataFrame([{
        "link": "https://example.com/sin-comparables",
        "title": "Apartamento en venta en Suba",
        "ubicacion": "Suba",
        "precio": 300_000_000,
        "area_m2": 70,
        "valor_m2": 4_285_714,
    }])

    result = analyze(frame)

    assert result.empty


def test_explicitly_no_elevator_is_excluded() -> None:
    frame = sample_frame()
    frame["ascensor"] = "si"
    frame.loc[frame["link"].str.endswith("/oportunidad"), "ascensor"] = "no"

    result = analyze(frame)

    assert result.empty


def test_report_displays_property_criteria() -> None:
    result = analyze(sample_frame())
    report = build_report(result)

    assert "*Criterios:*" in report
    assert "Ascensor:" in report
    assert "Administración:" in report
    assert "Buena vista:" in report
