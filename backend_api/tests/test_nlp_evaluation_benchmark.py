"""
Automated Pytest for TravelMate NLP Evaluation Benchmark
Validates quantitative accuracy and statistical superiority of TravelMate's
hybrid NLP subsystem over baseline models across Malaysia.
Covers Benchmark V1 historical reproducibility, Benchmark V2 dual-exclusion contract,
and the independent holdout protocol specifications.
"""
import os
import sys

# Ensure backend_api and project root are in sys.path
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(TEST_DIR)
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
for p in [BACKEND_DIR, PROJECT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from nlp_benchmark.benchmark_runner import (
    BATCH_21D_C2_HISTORICAL_RESULTS,
    evaluate_system,
    evaluate_v1,
    evaluate_v2,
)
from nlp_benchmark.holdout_protocol import (
    HOLDOUT_DATASET,
    HOLDOUT_EVALUATION_PROTOCOL,
    HOLDOUT_ANNOTATION_GUIDELINES,
)


def test_nlp_benchmark_intent_accuracy_and_f1():
    metrics = evaluate_system()
    tm = metrics["travelmate"]
    base = metrics["baseline"]

    # TravelMate intent accuracy must exceed 90%
    assert tm["intent_accuracy"] >= 0.90, f"Expected intent accuracy >= 0.90, got {tm['intent_accuracy']}"
    assert tm["intent_macro_f1"] >= 0.85, f"Expected intent macro F1 >= 0.85, got {tm['intent_macro_f1']}"

    # TravelMate must significantly outperform baseline model
    assert tm["intent_accuracy"] > base["intent_accuracy"] + 0.35, "TravelMate intent accuracy must exceed baseline by > 35%"
    assert tm["intent_macro_f1"] > base["intent_macro_f1"] + 0.50, "TravelMate intent F1 must exceed baseline by > 50%"


def test_nlp_benchmark_slot_extraction():
    metrics = evaluate_system()
    tm = metrics["travelmate"]
    base = metrics["baseline"]

    # Slot Macro F1 must exceed 80%
    assert tm["slot_macro_f1"] >= 0.80, f"Expected slot macro F1 >= 0.80, got {tm['slot_macro_f1']}"
    assert tm["slot_macro_f1"] > base["slot_macro_f1"] + 0.25, "TravelMate slot extraction must exceed baseline by > 25%"

    # Key slots must have near-perfect extraction
    slots = tm["slot_metrics"]
    assert slots["destinationState"]["f1"] == 1.0, "destinationState F1 must be 1.0"
    assert slots["budgetLimit"]["f1"] == 1.0, "budgetLimit F1 must be 1.0"
    assert slots["tripDays"]["f1"] >= 0.95, "tripDays F1 must be >= 0.95"
    assert slots["travellerCount"]["f1"] >= 0.95, "travellerCount F1 must be >= 0.95"
    assert slots["isForeign"]["f1"] == 1.0, "isForeign F1 must be 1.0"


def test_nlp_benchmark_multiturn_retention():
    metrics = evaluate_system()
    tm = metrics["travelmate"]
    base = metrics["baseline"]

    # State retention across turns must exceed 85%
    assert tm["multiturn_slot_retention_rate"] >= 0.85, f"Expected retention rate >= 0.85, got {tm['multiturn_slot_retention_rate']}"
    assert tm["multiturn_slot_retention_rate"] > base["multiturn_slot_retention_rate"], "TravelMate retention rate must exceed baseline"


def test_nlp_benchmark_v1_historical_snapshot_and_current_non_regression():
    """
    Keeps C2 measurements immutable while evaluating the current production extractor.
    """
    metrics = evaluate_v1()
    tm = metrics["travelmate"]
    historical = BATCH_21D_C2_HISTORICAL_RESULTS

    assert historical["git_sha"] == "276a930fc21c972818a83463a05d3a652da11cb3"
    assert historical["v1"] == {
        "intent_accuracy": 0.9333,
        "intent_macro_f1": 0.9205,
        "slot_macro_f1": 0.8346,
        "multiturn_slot_retention_rate": 0.8889,
        "multiturn_turn_accuracy": 0.5833,
    }
    assert metrics["dataset_version"] == "v1"
    assert tm["intent_accuracy"] >= historical["v1"]["intent_accuracy"]
    assert tm["intent_macro_f1"] >= historical["v1"]["intent_macro_f1"]
    assert tm["slot_macro_f1"] >= historical["v1"]["slot_macro_f1"]
    assert tm["multiturn_slot_retention_rate"] >= historical["v1"]["multiturn_slot_retention_rate"]
    assert tm["multiturn_turn_accuracy"] >= historical["v1"]["multiturn_turn_accuracy"]


def test_nlp_benchmark_v2_dual_exclusion_contract():
    """
    Validates Benchmark V2 with separated broad interest exclusions and specific venue exclusions.
    """
    metrics = evaluate_v2()
    tm = metrics["travelmate"]
    base = metrics["baseline"]

    assert metrics["dataset_version"] == "v2"
    assert len(tm["slot_metrics"]) == 10, "V2 must evaluate 10 distinct slot types"

    # Specific venue exclusions (Museum, Shopping Mall)
    act_metrics = tm["slot_metrics"]["excludedActivityTypes"]
    assert act_metrics["f1"] == 1.0
    assert act_metrics["tp"] == 3
    assert act_metrics["fp"] == 0
    assert act_metrics["fn"] == 0
    assert act_metrics["support"] == 3

    # Broad travel interest exclusions (Food, Beach)
    int_metrics = tm["slot_metrics"]["excludedInterests"]
    assert BATCH_21D_C2_HISTORICAL_RESULTS["v2_excluded_interests"] == {
        "f1": 0.6667,
        "tp": 1,
        "fp": 0,
        "fn": 1,
        "support": 2,
    }
    assert int_metrics["f1"] == 1.0
    assert int_metrics["tp"] == 2
    assert int_metrics["fp"] == 0
    assert int_metrics["fn"] == 0
    assert int_metrics["support"] == 2

    # Overall slot macro F1 must improve to ~90.0% due to repaired contract
    assert tm["slot_macro_f1"] >= 0.89, f"Expected V2 slot macro F1 >= 0.89, got {tm['slot_macro_f1']}"

    # Multi-turn state retention with excludedActivityTypes preservation
    historical_mt = BATCH_21D_C2_HISTORICAL_RESULTS["v2_multiturn"]
    assert historical_mt == {
        "slots_retained": 71,
        "slots_checked": 75,
        "slot_retention_rate": 0.9467,
        "state_perfect_matches": 8,
        "turns": 12,
        "turn_accuracy": 0.6667,
    }
    assert tm["multiturn_slots_checked"] == historical_mt["slots_checked"]
    assert tm["multiturn_turns"] == historical_mt["turns"]
    assert tm["multiturn_slots_retained"] >= historical_mt["slots_retained"]
    assert tm["multiturn_slot_retention_rate"] >= historical_mt["slot_retention_rate"]
    assert tm["multiturn_state_perfect_matches"] >= historical_mt["state_perfect_matches"]
    assert tm["multiturn_turn_accuracy"] >= historical_mt["turn_accuracy"]


def test_nlp_benchmark_v2_taxonomy_breakdown():
    """
    Validates the transparent taxonomy audit classification for all 135 items in V2.
    """
    metrics = evaluate_v2()
    tax = metrics["taxonomy_summary"]

    assert tax["verified_v2"] == 122
    assert tax["unambiguous_mapped"] == 7
    assert tax["ambiguous_pending_adjudication"] == 2
    assert tax["unsupported_in_production"] == 4
    assert sum(tax.values()) == 135


def test_nlp_benchmark_holdout_protocol_integrity():
    """
    Validates that the 50-item holdout dataset strictly maintains independent evaluation integrity:
    1. Status is PENDING_INDEPENDENT_HUMAN_ANNOTATION (no fake human labels).
    2. Exactly 50 diverse Malaysian tourism queries across 7 challenge categories.
    3. Multi-annotator agreement standard specifies Cohen's Kappa >= 0.80.
    """
    assert HOLDOUT_EVALUATION_PROTOCOL["status"] == "PENDING_INDEPENDENT_HUMAN_ANNOTATION"
    assert len(HOLDOUT_DATASET) == 50
    assert HOLDOUT_EVALUATION_PROTOCOL["dataset_size"] == 50

    categories = {item["category"] for item in HOLDOUT_DATASET}
    assert len(categories) == 7

    for item in HOLDOUT_DATASET:
        assert len(item["text"].strip()) > 5
        assert "id" in item
        assert "category" in item

    rules = HOLDOUT_EVALUATION_PROTOCOL["evaluation_rules"]
    assert rules["production_tuning_prohibited"] is True
    assert rules["human_annotators_required"] >= 2
    assert "0.80" in rules["agreement_metric_categorical"]
