from desk.engine.modular_bot.strategies.s1_stale_quote_lag import evaluate_s1
from desk.engine.modular_bot.strategies.s2_fair_value import evaluate_s2
from desk.engine.modular_bot.strategies.s3_settlement_lock import evaluate_s3
from desk.engine.modular_bot.strategies.s4_cross_side_arb import evaluate_s4
from desk.engine.modular_bot.strategies.s5_cross_venue import evaluate_s5
from desk.engine.modular_bot.strategies.s6_fade import evaluate_s6

EVALUATORS = [
    evaluate_s1,
    evaluate_s2,
    evaluate_s3,
    evaluate_s4,
    evaluate_s5,
    evaluate_s6,
]
