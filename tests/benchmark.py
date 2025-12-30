import sys
import os
import json
import time
from typing import List, Dict, Any, Literal
import asyncio
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from core.orchestrator import TravelOrchestrator
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

# Initialize
console = Console()
orchestrator = TravelOrchestrator()
judge_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite", 
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0
)

# --- DATASET LOADER ---
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

# --- SIMULATOR ---
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

# --- WEIGHTED JUDGE ---
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

# --- MAIN ---
async def main():
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
    
    results = []
    
    # Tables
    table = Table(title="Benchmark Results (Weighted Scoring)")
    table.add_column("ID", style="cyan")
    table.add_column("Score", style="magenta")
    table.add_column("Time (s)", style="green")
    table.add_column("Notes")

    for i, scenario in enumerate(scenarios):
        try:
            sim_result = await run_simulation(scenario)
            grade = grade_output(sim_result["output"], sim_result["expected_criteria"])
            
            # Serialize logs (remove non-serializable if any)
            clean_logs = []
            for log in sim_result.get("logs", []):
                clean_logs.append({k: str(v) for k, v in log.items()})

            result_entry = {**sim_result, "grade": grade, "logs": clean_logs}
            results.append(result_entry)
            
            # Save Checkpoint
            with open(results_path, "w") as f:
                json.dump(results, f, indent=2)
            
            table.add_row(
                str(scenario["id"]), 
                str(grade["score"]), 
                f"{sim_result['duration']:.2f}", 
                grade["explanation"][:50] + "..."
            )
            
            # Small Sleep to be polite to API
            time.sleep(2)
            
        except Exception as e:
            console.print(f"[red]Error running {scenario['id']}: {e}[/red]")

    console.print(table)
    
    if results:
        avg_score = sum(r["grade"]["score"] for r in results) / len(results)
        console.print(f"\n[bold]Average Score: {avg_score:.2f}/100[/bold]")
        console.print(f"Full results saved to {results_path}")

if __name__ == "__main__":
    asyncio.run(main())
