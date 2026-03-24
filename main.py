#!/usr/bin/env python3
"""
main.py - CLI entry point for the AI Research Paper Analyzer.

Usage:
    python main.py [paper_url_or_path]
    python main.py                      # interactive mode

Examples:
    python main.py https://arxiv.org/abs/2310.06825
    python main.py https://arxiv.org/abs/1706.03762
    python main.py /path/to/paper.pdf
    python main.py https://example.com/paper.pdf
"""

import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.text import Text
from rich import print as rprint

load_dotenv()

console = Console()

BANNER = """
[bold cyan]╔═══════════════════════════════════════════════════════╗[/bold cyan]
[bold cyan]║      🔬 AI Research Paper Analyzer                   ║[/bold cyan]
[bold cyan]║         Three-Pass Approach | Powered by Claude      ║[/bold cyan]
[bold cyan]╚═══════════════════════════════════════════════════════╝[/bold cyan]
"""

PASS_LABELS = {
    "pass1": "[bold yellow]Pass 1[/bold yellow]: Quick Scan (개요 파악) ...",
    "pass2": "[bold blue]Pass 2[/bold blue]: Structural Understanding (구조 파악) ...",
    "pass3": "[bold magenta]Pass 3[/bold magenta]: Deep Dive (심층 분석) ...",
    "integrated": "[bold green]통합 리뷰[/bold green]: Integrated Review 생성 중 ...",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="AI Research Paper Analyzer using Three-Pass Approach",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="arXiv URL, PDF URL, or local PDF file path",
    )
    return parser.parse_args()


def get_source_interactively() -> str:
    console.print("\n[bold]논문 소스를 입력하세요:[/bold]")
    console.print("  • arXiv URL:  [dim]https://arxiv.org/abs/2310.06825[/dim]")
    console.print("  • PDF URL:    [dim]https://example.com/paper.pdf[/dim]")
    console.print("  • 로컬 파일: [dim]/path/to/paper.pdf[/dim]")
    console.print()
    source = console.input("[bold cyan]> [/bold cyan]").strip()
    if not source:
        console.print("[red]입력이 없습니다. 종료합니다.[/red]")
        sys.exit(1)
    return source


def run(source: str):
    from src.fetcher import fetch_paper
    from src.analyzer import analyze_paper
    from src.formatter import format_and_save

    # --- Step 1: Fetch paper ---
    console.print(f"\n[bold]📥 논문 가져오는 중...[/bold] [dim]{source}[/dim]")
    try:
        with console.status("[cyan]PDF 다운로드 및 텍스트 추출 중...[/cyan]", spinner="dots"):
            paper_data = fetch_paper(source)
    except FileNotFoundError as e:
        console.print(f"[red]파일 오류:[/red] {e}")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]입력 오류:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]논문 가져오기 실패:[/red] {e}")
        sys.exit(1)

    title = paper_data.get("title") or "제목 없음"
    authors = paper_data.get("authors", [])
    text_len = len(paper_data.get("text", ""))

    console.print(Panel(
        f"[bold]{title}[/bold]\n"
        + (f"[dim]{', '.join(authors[:3])}{'...' if len(authors) > 3 else ''}[/dim]\n" if authors else "")
        + f"\n[green]텍스트 추출 완료[/green]: {text_len:,} 자",
        title="논문 정보",
        border_style="cyan",
    ))

    # --- Step 2: Analyze ---
    console.print("\n[bold]🧠 Three-Pass Analysis 시작[/bold]\n")

    analysis = {}
    current_task_id = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task_ids = {}
        for key, label in PASS_LABELS.items():
            task_ids[key] = progress.add_task(label, total=None, start=False)

        def on_progress(pass_name: str):
            nonlocal current_task_id
            if current_task_id is not None:
                progress.update(current_task_id, completed=True)
                progress.stop_task(current_task_id)
            current_task_id = task_ids[pass_name]
            progress.start_task(current_task_id)

        try:
            analysis = analyze_paper(paper_data, progress_callback=on_progress)
        except EnvironmentError as e:
            console.print(f"\n[red]환경 오류:[/red] {e}")
            sys.exit(1)
        except Exception as e:
            console.print(f"\n[red]분석 실패:[/red] {e}")
            sys.exit(1)

        if current_task_id is not None:
            progress.update(current_task_id, completed=True)
            progress.stop_task(current_task_id)

    console.print("\n[green]✓[/green] 모든 패스 완료!\n")

    # --- Step 3: Save ---
    console.print("[bold]💾 결과 저장 중...[/bold]")
    try:
        output_path = format_and_save(paper_data, analysis)
    except Exception as e:
        console.print(f"[red]저장 실패:[/red] {e}")
        sys.exit(1)

    console.print(Panel(
        f"[bold green]분석 완료![/bold green]\n\n"
        f"[dim]저장 위치:[/dim]\n[bold cyan]{output_path}[/bold cyan]",
        title="완료",
        border_style="green",
    ))


def main():
    console.print(BANNER)

    args = parse_args()
    source = args.source

    if not source:
        source = get_source_interactively()

    run(source)


if __name__ == "__main__":
    main()
