import sys
import os
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown

# Local imports - direct because we are in the project root
from core.orchestrator import TravelOrchestrator

console = Console()
orchestrator = TravelOrchestrator()

def print_header():
    console.print(Panel.fit(
        "[bold cyan]✈️  AI Travel Companion[/bold cyan]\n"
        "[dim]Your personal travel planning assistant[/dim]",
        border_style="cyan"
    ))

def main():
    print_header()
    
    console.print("\n[bold yellow]Hello! I'm Atlas. Let's chat about your trip.[/bold yellow]\n")

    chat_history = []

    while True:
        try:
            user_text = Prompt.ask("[bold]You[/bold]")
            
            if user_text.lower() in ['exit', 'quit']:
                break

            with console.status("[dim]Thinking...[/dim]", spinner="dots"):
                response, chat_history, _, _ = orchestrator.chat(user_text, chat_history)
                
                # Check if it's the final plan (Markdown) or just chat
                if "# Day 1" in response or "##" in response:
                    console.print("\n")
                    console.print(Panel(
                        Markdown(response),
                        title="Your Trip Plan",
                        border_style="green"
                    ))
                    console.print("\n[bold green]Atlas:[/bold green] Let me know if you want to change anything!\n")
                else:
                    console.print(f"\n[bold cyan]Atlas:[/bold cyan] {response}\n")
                    
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    console.print("\n[bold cyan]Safe travels! 🌍[/bold cyan]")

if __name__ == "__main__":
    main()

