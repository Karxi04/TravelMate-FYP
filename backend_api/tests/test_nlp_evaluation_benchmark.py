"""
Automated Pytest for TravelMate NLP Evaluation Benchmark
Validates quantitative accuracy and statistical superiority of TravelMate's
hybrid NLP subsystem over baseline models across Malaysia.
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

from nlp_benchmark.benchmark_runner import evaluate_system


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
