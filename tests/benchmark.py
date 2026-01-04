import sys
import os
import json
import time
import argparse
from typing import List, Dict, Any, Literal
import asyncio
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from core.orchestrator import TravelOrchestrator
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

# Initialize
console = Console()
orchestrator = TravelOrchestrator()
judge_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-pro", 
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0
)

class MetricsAggregator:
    """Aggregates metrics across all benchmark runs."""
    def __init__(self):
        self.node_latencies = {}  # node_name -> list of latencies
        self.total_tokens = 0
        self.geocoding_totals = {"exact": 0, "neighborhood": 0, "failed": 0, "api_calls": 0}
        self.scores = []
        self.total_duration = 0
        
    def add_logs(self, logs: List[Dict]):
        """Process logs from a single scenario."""
        for log in logs:
            node = log.get("node", "unknown")
            latency = log.get("latency_sec", 0)
            
            if node not in self.node_latencies:
                self.node_latencies[node] = []
            self.node_latencies[node].append(latency)
            
            # Token tracking
            self.total_tokens += log.get("total_tokens", 0)
            
            # Geocoding stats (only from logistics node)
            if node == "logistics" and "geocoding" in log:
                geo = log["geocoding"]
                self.geocoding_totals["exact"] += geo.get("exact", 0)
                self.geocoding_totals["neighborhood"] += geo.get("neighborhood", 0)
                self.geocoding_totals["failed"] += geo.get("failed", 0)
                self.geocoding_totals["api_calls"] += geo.get("api_calls", 0)
    
    def add_score(self, score: int):
        self.scores.append(score)
        
    def add_duration(self, duration: float):
        self.total_duration += duration
        
    def get_summary(self) -> Dict:
        """Generate summary statistics."""
        summary = {
            "scenarios_run": len(self.scores),
            "avg_score": round(sum(self.scores) / len(self.scores), 1) if self.scores else 0,
            "min_score": min(self.scores) if self.scores else 0,
            "max_score": max(self.scores) if self.scores else 0,
            "total_duration_sec": round(self.total_duration, 1),
            "avg_duration_sec": round(self.total_duration / len(self.scores), 1) if self.scores else 0,
            "total_tokens": self.total_tokens,
            "geocoding": self.geocoding_totals,
            "node_avg_latency": {}
        }
        
        for node, latencies in self.node_latencies.items():
            summary["node_avg_latency"][node] = round(sum(latencies) / len(latencies), 2) if latencies else 0
            
        return summary

class CriterionResult(BaseModel):
    status: Literal["True", "False", "Partial"] = Field(description="Status of the criterion check.")

class JudgeResponse(BaseModel):
    results: List[CriterionResult] = Field(description="List of results for each criterion provided, in the same order.")

def load_dataset(path: str) -> List[Dict]:
    if not os.path.exists(path):
        console.print(f"[red]Dataset not found at {path}[/red]")
        return []
    with open(path, "r") as f:
        return json.load(f)

async def run_simulation(scenario: Dict) -> Dict:
    """
    Runs a scenario. If the bot asks for clarification, it tries to answer.
    """
    history = []
    #Start with the predefined conversation
    messages = list(scenario["conversation"]) 
    
    start_time = time.time()
    final_output = ""
    all_logs = []
    
    print(f"Running Scenario {scenario['id']}...")
    
    # We allow up to 3 extra turns for clarification
    max_turns = len(messages) + 3 
    turn = 0
    
    while turn < max_turns:
        # Determine user input
        if turn < len(messages):
            user_msg = messages[turn]
        else:
            # Automatic Fallback if bot is still asking questions
            # Check if we already have a plan
            if "# Day 1" in final_output or "##" in final_output:
                break
            
            # SMART FALLBACK using Metadata
            meta = scenario.get("meta", {})
            dest = meta.get("original_dest", "Los Angeles")
            days = meta.get("original_days", "3")
            
            print(f"   [Auto-Reply] Bot is asking clarification. Injecting fallback: {dest}, {days} days.")
            user_msg = f"I want to go to {dest} for {days} days. Surprise me with the rest."
            
        # Simulate User Input
        response, history, logs, _ = orchestrator.chat(user_msg, history)
        final_output = response
        if logs: all_logs.extend(logs)
        
        turn += 1
        
        # Stop if we got a plan
        if "# Day 1" in response or "##" in response:
            break
            
    duration = time.time() - start_time
    
    return {
        "id": scenario["id"],
        "output": final_output,
        "history": history,
        "duration": duration,
        "logs": all_logs,
        "expected_criteria": scenario.get("expected_criteria", [])
    }

def grade_output(output: str, criteria: List[str]) -> Dict:
    """
    Uses LLM to grade with partial credit and weights using structured output.
    """
    count = len(criteria)
    
    # Initialize structured LLM
    structured_judge = judge_llm.with_structured_output(JudgeResponse)
    
    prompt = f"""
    You are a meticulous Travel Agent Supervisor.
    
    ITINERARY TO CHECK:
    {output}
    
    CRITERIA CHECKLIST ({count} items):
    {json.dumps(criteria)}
    
    INSTRUCTIONS:
    1. For EACH of the {count} items, check if it is met (True), partially met (Partial), or failed (False).
    2. "Partial" means it's mentioned but maybe slightly off (e.g. "Japanese food" instead of "Sushi").
    3. Return a structured JSON response with a "results" list containing EXACTLY {count} entries.
    """
    
    try:
        response = structured_judge.invoke([HumanMessage(content=prompt)])
        
        # Convert response to the format the rest of the function expects
        results = [item.status for item in response.results]
        
        # Fallback if length mismatch: Pad with "False"
        if len(results) < count:
            results.extend(["False"] * (count - len(results)))
        elif len(results) > count:
            results = results[:count]
            
        # Calculate Weighted Score
        total_weight = 0
        earned_score = 0
        
        breakdown = []
        
        for i, status in enumerate(results):
            criterion_text = criteria[i].lower()
            
            # Assign Weights
            if "destination" in criterion_text: weight = 40
            elif "duration" in criterion_text: weight = 20
            elif "budget" in criterion_text: weight = 20
            elif "start location" in criterion_text: weight = 5 # Less important
            else: weight = 15 # Hotels/Food
            
            total_weight += weight
            
            # Assign Points
            if status == "True": earned_score += weight
            elif status == "Partial": earned_score += (weight * 0.5)
            
            breakdown.append(f"{criteria[i]}: {status} ({weight}pts)")
            
        final_score = int((earned_score / total_weight) * 100) if total_weight > 0 else 0
        
        return {
            "score": final_score,
            "explanation": ", ".join(breakdown)
        }
        
    except Exception as e:
        return {"score": 0, "explanation": f"Grading failed: {e}"}

def extract_node_breakdown(logs: List[Dict]) -> str:
    """Extract latency breakdown by node."""
    breakdown = []
    for log in logs:
        node = log.get("node", "?")
        latency = log.get("latency_sec", 0)
        # Special handling for logistics node
        if node == "logistics" and "geocoding" in log:
            geo = log["geocoding"]
            breakdown.append(f"{node}:{latency}s (geo:{geo.get('success_rate', 0)}%)")
        else:
            breakdown.append(f"{node}:{latency}s")
    return " → ".join(breakdown) if breakdown else "N/A"


def print_summary_panel(metrics: MetricsAggregator):
    """Print a beautiful summary panel."""
    summary = metrics.get_summary()
    
    # Score Table
    score_table = Table(show_header=False, box=None)
    score_table.add_column("Metric", style="cyan")
    score_table.add_column("Value", style="bold white")
    score_table.add_row("Scenarios Run", str(summary["scenarios_run"]))
    score_table.add_row("Average Score", f"{summary['avg_score']}/100")
    score_table.add_row("Score Range", f"{summary['min_score']} - {summary['max_score']}")
    score_table.add_row("Total Duration", f"{summary['total_duration_sec']}s")
    score_table.add_row("Avg Duration/Scenario", f"{summary['avg_duration_sec']}s")
    score_table.add_row("Total Tokens", str(summary["total_tokens"]))
    
    console.print(Panel(score_table, title="📊 Overall Metrics", border_style="green"))
    
    # Node Latency Table
    if summary["node_avg_latency"]:
        node_table = Table(title="⏱️ Average Latency by Node")
        node_table.add_column("Node", style="cyan")
        node_table.add_column("Avg Latency (s)", style="yellow")
        
        for node, latency in sorted(summary["node_avg_latency"].items()):
            style = "red" if latency > 5 else "yellow" if latency > 2 else "green"
            node_table.add_row(node, f"[{style}]{latency}[/{style}]")
        
        console.print(node_table)
    
    # Geocoding Stats
    geo = summary["geocoding"]
    if geo["api_calls"] > 0:
        geo_table = Table(title="🌍 Geocoding Statistics")
        geo_table.add_column("Metric", style="cyan")
        geo_table.add_column("Count", style="white")
        geo_table.add_column("Rate", style="yellow")
        
        total_attempts = geo["exact"] + geo["neighborhood"] + geo["failed"]
        if total_attempts > 0:
            geo_table.add_row("Exact Matches", str(geo["exact"]), f"{geo['exact']/total_attempts*100:.1f}%")
            geo_table.add_row("Neighborhood Fallback", str(geo["neighborhood"]), f"{geo['neighborhood']/total_attempts*100:.1f}%")
            geo_table.add_row("Failed", str(geo["failed"]), f"[red]{geo['failed']/total_attempts*100:.1f}%[/red]")
            geo_table.add_row("Total API Calls", str(geo["api_calls"]), "-")
        
        console.print(geo_table)


async def main():
    # Argument parsing
    parser = argparse.ArgumentParser(description="Travel Companion Benchmark")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of scenarios to run")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash-lite", help="Judge model to use")
    args = parser.parse_args()
    
    dataset_path = os.path.join(os.path.dirname(__file__), "dataset.json")
    results_path = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    
    # Create dummy if missing
    if not os.path.exists(dataset_path):
        dummy_data = [{
            "id": "TOK_01",
            "conversation": ["I want to go to Tokyo for 3 days."],
            "expected_criteria": ["Destination is Tokyo", "Duration is 3 days"]
        }]
        with open(dataset_path, "w") as f:
            json.dump(dummy_data, f, indent=2)
            
    scenarios = load_dataset(dataset_path)
    
    # Apply limit if specified
    if args.limit:
        scenarios = scenarios[:args.limit]
        console.print(f"[yellow]Running limited benchmark: {args.limit} scenarios[/yellow]\n")
    
    results = []
    metrics = MetricsAggregator()
    
    # Results Table
    table = Table(title=f"🧳 Benchmark Results ({len(scenarios)} scenarios)")
    table.add_column("#", style="dim", width=3)
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Score", style="magenta", width=6)
    table.add_column("Time", style="green", width=8)
    table.add_column("Node Breakdown", style="dim", width=50)

    console.print(f"[bold]Starting benchmark with {len(scenarios)} scenarios...[/bold]\n")

    for i, scenario in enumerate(scenarios):
        try:
            console.print(f"[dim]({i+1}/{len(scenarios)}) Running {scenario['id']}...[/dim]")
            
            sim_result = await run_simulation(scenario)
            grade = grade_output(sim_result["output"], sim_result["expected_criteria"])
            
            # Process logs - keep original structure for JSON
            logs = sim_result.get("logs", [])
            clean_logs = []
            for log in logs:
                # Convert to JSON-serializable format
                clean_log = {}
                for k, v in log.items():
                    if isinstance(v, dict):
                        clean_log[k] = v
                    else:
                        clean_log[k] = str(v) if not isinstance(v, (int, float)) else v
                clean_logs.append(clean_log)
            
            # Update metrics
            metrics.add_logs(logs)
            metrics.add_score(grade["score"])
            metrics.add_duration(sim_result["duration"])

            result_entry = {**sim_result, "grade": grade, "logs": clean_logs}
            results.append(result_entry)
            
            # Save Checkpoint
            with open(results_path, "w") as f:
                json.dump(results, f, indent=2)
            
            # Extract node breakdown for display
            node_breakdown = extract_node_breakdown(logs)
            
            # Color score based on value
            score = grade["score"]
            score_style = "green" if score >= 80 else "yellow" if score >= 50 else "red"
            
            table.add_row(
                str(i+1),
                str(scenario["id"]), 
                f"[{score_style}]{score}[/{score_style}]", 
                f"{sim_result['duration']:.1f}s",
                node_breakdown[:50] + "..." if len(node_breakdown) > 50 else node_breakdown
            )
            
            # Small Sleep to be polite to API
            time.sleep(2)
            
        except Exception as e:
            console.print(f"[red]Error running {scenario['id']}: {e}[/red]")
            import traceback
            traceback.print_exc()

    # Print Results
    console.print("\n")
    console.print(table)
    console.print("\n")
    
    # Print Summary Panel
    if results:
        print_summary_panel(metrics)
        
        # Save summary to file
        summary = metrics.get_summary()
        summary_path = os.path.join(os.path.dirname(__file__), "benchmark_summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        
        console.print(f"\n[dim]Results saved to: {results_path}[/dim]")
        console.print(f"[dim]Summary saved to: {summary_path}[/dim]")

if __name__ == "__main__":
    asyncio.run(main())
