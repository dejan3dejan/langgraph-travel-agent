import json
import os
import random

def generate_report():
    results_path = "tests/benchmark_results.json"
    report_path = "tests/HUMAN_REVIEW_REPORT.md"
    
    if not os.path.exists(results_path):
        print(f"Error: {results_path} not found.")
        return

    with open(results_path, "r") as f:
        results = json.load(f)

    # Sort results
    failures = [r for r in results if r['grade']['score'] < 85]
    perfect = [r for r in results if r['grade']['score'] == 100]
    score_84 = [r for r in results if r['grade']['score'] == 84]

    # Sample some good ones
    sampled_perfect = random.sample(perfect, min(len(perfect), 5))
    sampled_84 = random.sample(score_84, min(len(score_84), 5))

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 🕵️ HUMAN REVIEW REPORT\n\n")
        f.write(f"Total Runs Analyzed: {len(results)}\n")
        f.write(f"Average Score: {sum(r['grade']['score'] for r in results)/len(results):.2f}\n\n")
        
        f.write("## 🚩 FAILURES & LOW SCORES (< 85)\n")
        for r in failures:
            write_scenario(f, r)

        f.write("\n## ⚠️ THE '84' SAMPLES (Potential Start Location issues)\n")
        for r in sampled_84:
            write_scenario(f, r)

        f.write("\n## ✅ PERFECT SAMPLES (Check for Over-generous Judge)\n")
        for r in sampled_perfect:
            write_scenario(f, r)

    print(f"Report generated: {report_path}")

def write_scenario(f, r):
    f.write(f"### Scenario {r['id']} (Score: {r['grade']['score']})\n")
    user_input = r['history'][0]['content'] if r['history'] else "N/A"
    f.write(f"**User Request:** {user_input}\n\n")
    f.write(f"**Judge Explanation:** {r['grade']['explanation']}\n\n")
    f.write("<details>\n<summary>View Full Itinerary</summary>\n\n")
    f.write(f"{r['output']}\n\n")
    f.write("</details>\n\n")
    f.write("---\n\n")

if __name__ == "__main__":
    generate_report()

