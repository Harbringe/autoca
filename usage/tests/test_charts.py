"""The chart geometry: round axes, bars that scale to the biggest value, lines that break on a missing day, rings that sum to a whole."""

from __future__ import annotations

import pytest

from usage import charts

DAYS = [f"{i + 1:02d} Oct" for i in range(5)]
TITLES = [f"t{i}" for i in range(5)]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 1),
        (0.87, 1),
        (1, 1),
        (1.4, 2),
        (2.2, 2.5),
        (3, 5),
        (7.5, 10),
        (45, 50),
        (0.0031, 0.005),
        (180, 200),
    ],
)
def test_an_axis_tops_out_at_a_round_number(value, expected):
    assert charts.nice_max(value) == pytest.approx(expected)


def test_bars_scale_to_the_biggest_value_and_flag_the_last():
    result = charts.bars([0, 5, 10, 5, 2], DAYS, TITLES, fmt=lambda v: f"{v:.0f}", every=2)

    assert result["empty"] is False and len(result["bars"]) == 5
    heights = [float(b["h"]) for b in result["bars"]]
    assert (
        heights[0] == 0 and heights[2] == max(heights) and heights[1] == pytest.approx(heights[3])
    )
    assert [b["is_last"] for b in result["bars"]] == [False] * 4 + [True]
    assert result["grid"][-1]["label"] == "10" and result["grid"][0]["label"] == "0"


def test_nothing_to_show_is_reported_as_empty_not_drawn():
    assert charts.bars([0, 0], ["a", "b"], ["x", "y"])["empty"] is True
    assert charts.stacked([("a", [0, 0])], ["a", "b"], ["x", "y"])["empty"] is True
    assert charts.line([None, None], ["a", "b"], ["x", "y"])["empty"] is True
    assert charts.donut([("a", 0, "0")])["empty"] is True


def test_a_tiny_value_still_shows_as_a_visible_sliver():
    result = charts.bars([1, 1000], ["a", "b"], ["x", "y"])

    assert float(result["bars"][0]["h"]) >= 2


def test_stacked_segments_sit_on_top_of_each_other_from_the_bottom():
    result = charts.stacked(
        [("ok", [4, 0]), ("limited", [1, 0]), ("failed", [0, 2])],
        ["a", "b"],
        ["x", "y"],
        fmt=lambda v: f"{v:.0f}",
    )

    first, second = result["bars"]
    assert [s["cls"] for s in first["segments"]] == ["ok", "limited"]
    assert float(first["segments"][1]["y"]) < float(
        first["segments"][0]["y"]
    )  # the second sits above the first
    assert [s["cls"] for s in second["segments"]] == ["failed"]


def test_a_line_breaks_on_a_day_with_no_value_instead_of_dropping_to_zero():
    result = charts.line([10, 20, None, 15, 25], DAYS, TITLES, fmt=lambda v: f"{v:.0f}")

    assert len(result["runs"]) == 2 and len(result["dots"]) == 4
    assert result["dots"][-1]["is_last"] is True


def test_a_lone_point_is_a_dot_with_no_line():
    result = charts.line([None, 7, None], ["a", "b", "c"], ["x", "y", "z"])

    assert result["runs"] == [] and len(result["dots"]) == 1


def test_a_percentage_line_keeps_the_axis_at_one_hundred():
    result = charts.line([40, 80], ["a", "b"], ["x", "y"], fmt=lambda v: f"{v:.0f}%", top=100)

    assert result["grid"][-1]["label"] == "100%"


def test_a_ring_adds_up_to_the_whole_and_leaves_out_empty_parts():
    ring = charts.donut(
        [("Input", 600, "600"), ("Cached", 300, "300"), ("Output", 100, "100"), ("None", 0, "0")],
        radius=60,
    )

    assert [s["label"] for s in ring["slices"]] == ["Input", "Cached", "Output"]
    assert sum(s["percent"] for s in ring["slices"]) == 100
    circumference = 2 * 3.141592653589793 * 60
    assert sum(float(s["dash"]) for s in ring["slices"]) == pytest.approx(circumference, abs=0.1)
    offsets = [abs(float(s["offset"])) for s in ring["slices"]]
    assert offsets == sorted(offsets) and offsets[0] == 0
