"""The review-setting calibration evaluation: authored sequences, simulated coordinators, arms.

SYNTHETIC. See `runner.py` for how the real repository is driven, `metrics.py` for the definitions
and `report.py` for `docs/evaluation/review-calibration.{json,md}`.

Never imported by `silverloop.evaluation` itself, and importing this package loads no repository,
configuration or agent module: the runner imports those lazily, per run.
"""
