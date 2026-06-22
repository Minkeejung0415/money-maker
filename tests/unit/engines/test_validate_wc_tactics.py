from scripts.validate_wc_tactics import _binary_metrics, _brier, _log_loss


def test_multiclass_metrics_reward_correct_confidence():
    assert _brier([0.8, 0.1, 0.1], 0) < _brier([0.4, 0.3, 0.3], 0)
    assert _log_loss([0.8, 0.1, 0.1], 0) < _log_loss([0.4, 0.3, 0.3], 0)


def test_binary_metrics_use_half_probability_threshold():
    correct, brier, logloss = _binary_metrics(0.7, 1)
    assert correct == 1
    assert brier == (0.7 - 1.0) ** 2
    assert logloss > 0

