import json
from pathlib import Path


def test_hosting_targets_rewrite_each_portal_to_its_own_cloud_run_service():
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "firebase.json").read_text(encoding="utf-8"))
    targets = json.loads((root / ".firebaserc").read_text(encoding="utf-8"))[
        "targets"
    ]["travelmate2-30a8a"]["hosting"]

    expected = {
        "operator": ("travelmate-operator-ckx", "travelmate-operator"),
        "admin": ("travelmate-admin-ckx", "travelmate-admin"),
    }
    assert (root / "firebase" / "hosting" / "empty").is_dir()
    assert config["firestore"] == {"rules": "firebase/firestore.rules"}

    by_target = {entry["target"]: entry for entry in config["hosting"]}
    assert set(by_target) == set(expected)
    for target, (site_id, service_id) in expected.items():
        entry = by_target[target]
        assert targets[target] == [site_id]
        assert entry["public"] == "firebase/hosting/empty"
        assert entry["rewrites"] == [
            {
                "source": "**",
                "run": {"serviceId": service_id, "region": "asia-southeast1"},
            }
        ]
