import json
import os
import sys
from collections import Counter
from rich.console import Console
from rich.table import Table

console = Console()

def analyze_results():
    # Robust Path Finding: Always look in the same folder as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_path = os.path.join(script_dir, "benchmark_results.json")

    if not os.path.exists(results_path):
        console.print(f"[red]No results found at {results_path}[/red]")
        return

    with open(results_path, "r") as f:
        try:
            results = json.load(f)
        except json.JSONDecodeError:
            console.print("[red]Results file is empty or corrupted.[/red]")
            return

    total = len(results)
    if total == 0:
        return

    # 1. High Level Stats
    avg_score = sum(r["grade"]["score"] for r in results) / total
    perfect_runs = sum(1 for r in results if r["grade"]["score"] == 100)
    failed_runs = sum(1 for r in results if r["grade"]["score"] < 50)
    
    console.print(f"\n[bold underline]Benchmark Analysis ({total} runs)[/bold underline]")
    console.print(f"Average Score: [magenta]{avg_score:.2f}[/magenta]")
    console.print(f"Perfect Runs: [green]{perfect_runs}[/green]")
    console.print(f"Failed Runs (<50): [red]{failed_runs}[/red]")

    # 2. Failure Analysis
    console.print("\n[bold]Top Failure Explanations:[/bold]")
    explanations = [r["grade"]["explanation"] for r in results if r["grade"]["score"] < 100]
    
    # Simple keyword clustering
    clusters = Counter()
    for exp in explanations:
        if "Judge Error" in exp: clusters["Judge Error (LLM Failed)"] += 1
        elif "Passed" in exp: 
            # Parse "Passed X/Y criteria" to find what failed
            # We can group by percentage roughly
            clusters[exp] += 1
        else:
            clusters[exp[:50] + "..."] += 1
            
    for failure, count in clusters.most_common(10):
        console.print(f"- {failure}: [red]{count}[/red]")

    # 3. Worst Scenarios Table
    table = Table(title="Worst Performing Scenarios")
    table.add_column("ID", style="cyan")
    table.add_column("Score", style="red")
    table.add_column("Judge Explanation")

    # Sort by score ascending
    sorted_results = sorted(results, key=lambda x: x["grade"]["score"])
    
    for r in sorted_results[:10]: # Top 10 worst
        table.add_row(
            str(r["id"]),
            str(r["grade"]["score"]),
            r["grade"]["explanation"][:100] + "..."
        )

    console.print(table)
    
    # 4. Latency Outliers
    console.print("\n[bold]Slowest Runs (>60s):[/bold]")
    slow_runs = [r for r in results if r["duration"] > 60]
    for r in slow_runs:
        console.print(f"- {r['id']}: {r['duration']:.2f}s")

if __name__ == "__main__":
    analyze_results()
