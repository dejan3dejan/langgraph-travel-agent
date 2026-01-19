import json
import os
import random

from datasets import load_dataset

random.seed(42)


def convert_hf_dataset(output_path="tests/dataset.json", num_samples=200):
    print("Loading osunlp/TravelPlanner (validation set)...")
    try:
        ds = load_dataset("osunlp/TravelPlanner", "validation", split="validation")
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return

    total_rows = len(ds)
    print(f"Dataset loaded. Total rows: {total_rows}")

    # Adjust sample size if dataset is smaller
    if num_samples > total_rows:
        print(f"Requested {num_samples} samples, but dataset only has {total_rows}. Using all available rows.")
        num_samples = total_rows

    # Select random samples
    indices = random.sample(range(total_rows), num_samples)
    selected_data = [ds[i] for i in indices]

    converted_scenarios = []

    for i, row in enumerate(selected_data):
        # Extract fields
        query = row["query"]
        days = row["days"]
        dest = row["dest"]
        org = row["org"]

        # Create criteria based on dataset metadata
        criteria = [
            f"Trip destination is {dest}",
            f"Trip duration is {days} days",
            f"Start location is {org}" if org else None,
            "Includes hotel recommendations",
            "Includes restaurant recommendations",
        ]
        criteria = [c for c in criteria if c]  # Remove None

        scenario = {
            "id": f"HF_{i+1:03d}",
            "conversation": [query],  # The dataset query is the user input
            "expected_criteria": criteria,
            "meta": {"original_days": days, "original_dest": dest, "difficulty": row.get("level", "unknown")},
        }
        converted_scenarios.append(scenario)

    # Save to JSON
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(converted_scenarios, f, indent=2)

    print(f"Successfully converted {num_samples} samples to {output_path}")
    print("Example Scenario:")
    print(json.dumps(converted_scenarios[0], indent=2))


if __name__ == "__main__":
    convert_hf_dataset()
