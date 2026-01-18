import asyncio
import sys

from rich.align import Align
from rich.box import DOUBLE, ROUNDED
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

# Local imports - direct because we are in the project root
from core.orchestrator import TravelOrchestrator

console = Console()
orchestrator = TravelOrchestrator()

# ASCII Art Banner
BANNER = """
[bold cyan]
     ╔═══════════════════════════════════════════════════════════╗
     ║                                                           ║
     ║      ✈️   █████╗ ████████╗██╗      █████╗ ███████╗        ║
     ║         ██╔══██╗╚══██╔══╝██║     ██╔══██╗██╔════╝        ║
     ║         ███████║   ██║   ██║     ███████║███████╗        ║
     ║         ██╔══██║   ██║   ██║     ██╔══██║╚════██║        ║
     ║         ██║  ██║   ██║   ███████╗██║  ██║███████║   🌍   ║
     ║         ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚══════╝        ║
     ║                                                           ║
     ║           [white]AI-Powered Travel Planning Assistant[/white]          ║
     ╚═══════════════════════════════════════════════════════════╝
[/bold cyan]"""

TOOL_ICONS = {
    "search_flights": "🛫",
    "search_hotels": "🏨",
    "search_activities": "🎯",
    "get_weather": "🌤️",
    "calculate_budget": "💰",
    "create_itinerary": "📋",
    "search_restaurants": "🍽️",
}


def print_header():
    console.print(BANNER)
    console.print(Align.center("[dim]Type your travel questions • 'exit' to quit[/dim]"))
    console.print()


def print_welcome():
    welcome_text = Text()
    welcome_text.append("👋 ", style="bold")
    welcome_text.append("Hello! I'm ", style="white")
    welcome_text.append("Atlas", style="bold cyan")
    welcome_text.append(", your personal travel companion.\n", style="white")
    welcome_text.append("   Tell me about your dream trip and I'll help you plan it!", style="dim")

    console.print(Panel(welcome_text, border_style="cyan", box=ROUNDED, padding=(0, 2)))
    console.print()


def print_user_message(text: str):
    console.print()
    console.print(
        Panel(
            text,
            title="[bold white]You[/bold white]",
            title_align="left",
            border_style="blue",
            box=ROUNDED,
            padding=(0, 1),
        )
    )


def get_tool_icon(status: str) -> str:
    """Extract tool icon from status message."""
    status_lower = status.lower()
    for tool, icon in TOOL_ICONS.items():
        if tool.replace("_", " ") in status_lower or tool.replace("_", "") in status_lower:
            return icon
    if "flight" in status_lower:
        return "🛫"
    if "hotel" in status_lower:
        return "🏨"
    if "weather" in status_lower:
        return "🌤️"
    if "activit" in status_lower:
        return "🎯"
    if "budget" in status_lower or "cost" in status_lower:
        return "💰"
    if "itinerary" in status_lower or "plan" in status_lower:
        return "📋"
    return "⚙️"


def print_goodbye():
    goodbye_text = """
[bold cyan]
    ╭──────────────────────────────────────────╮
    │                                          │
    │   ✨  Thanks for using Atlas!  ✨        │
    │                                          │
    │      Safe travels and happy trails!      │
    │                 🌍 ✈️ 🗺️                  │
    │                                          │
    ╰──────────────────────────────────────────╯
[/bold cyan]"""
    console.print(goodbye_text)


async def main():
    console.clear()
    print_header()
    print_welcome()

    chat_history = []

    while True:
        try:
            console.print(Rule(style="dim"))
            user_text = Prompt.ask("\n[bold cyan]✦[/bold cyan] [bold]Your message[/bold]")

            if user_text.lower() in ["exit", "quit", "bye", "q"]:
                break

            if not user_text.strip():
                continue

            print_user_message(user_text)

            full_response = ""
            current_status = "Atlas is thinking..."

            # Use Live to handle the combined spinner + streaming text
            with console.status(f"[dim cyan]🤔 {current_status}[/dim cyan]", spinner="dots") as status:
                async for event in orchestrator.stream_chat(user_text, chat_history):
                    if event["type"] == "reset":
                        full_response = ""  # Clear previous draft buffer
                        console.print()
                        console.print(
                            Panel(
                                "[bold]🔄 Refining the plan for better results...[/bold]",
                                border_style="magenta",
                                box=ROUNDED,
                            )
                        )
                        status.start()
                        status.update("[bold magenta]♻️  Optimizing itinerary...[/bold magenta]")

                    elif event["type"] == "status":
                        current_status = event["content"]
                        icon = get_tool_icon(current_status)
                        status.update(f"[cyan]{icon} {current_status}[/cyan]")

                    elif event["type"] == "token":
                        # Stop the spinner when tokens start arriving
                        if not full_response:
                            status.stop()
                            console.print()
                            console.print("[bold cyan]┌─ Atlas[/bold cyan]")
                            console.print("[cyan]│[/cyan]")
                            console.print("[cyan]│[/cyan]  ", end="")

                        token = event["content"]
                        full_response += token
                        # Handle newlines to maintain the visual border
                        if "\n" in token:
                            token = token.replace("\n", "\n[cyan]│[/cyan]  ")
                        console.print(token, end="")
                        sys.stdout.flush()

                # Finish the Atlas message box
                if full_response:
                    console.print()
                    console.print("[cyan]│[/cyan]")
                    console.print("[bold cyan]└────────────────────────────────────────[/bold cyan]")

                # If the stream ends and it's a markdown itinerary, reprint it pretty
                if "# Day 1" in full_response or "## Day" in full_response:
                    console.print()
                    console.print(
                        Panel(
                            Markdown(full_response),
                            title="[bold green]📋 Your Complete Trip Plan[/bold green]",
                            title_align="left",
                            border_style="green",
                            box=DOUBLE,
                            padding=(1, 2),
                        )
                    )

                # Update history
                chat_history.append({"role": "user", "content": user_text})
                chat_history.append({"role": "model", "content": full_response})
                console.print()

        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(Panel(f"[bold red]Error:[/bold red] {e}", border_style="red", box=ROUNDED))

    print_goodbye()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
