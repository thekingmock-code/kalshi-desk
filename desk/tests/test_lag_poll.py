from desk.engine.paper import lag_on_right_side


def test_lag_up_needs_positive():
    assert lag_on_right_side("UP", 0.5)
    assert not lag_on_right_side("UP", -0.1)
    assert not lag_on_right_side("UP", None)


def test_lag_down_needs_negative():
    assert lag_on_right_side("DOWN", -0.25)
    assert not lag_on_right_side("DOWN", 0.01)
