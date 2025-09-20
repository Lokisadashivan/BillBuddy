#!/usr/bin/env python3
"""
CLI interface for Standard Chartered eStatement parser.
"""
import typer
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from core.runner import parse_statement
from core.detectors import detect_template
from tools.debug_overlay import create_debug_overlay

app = typer.Typer(help="Standard Chartered eStatement Parser")
console = Console()

@app.command()
def parse(
    pdf_path: Path = typer.Argument(..., help="Path to PDF file"),
    output: Optional[Path] = typer.Option(None, "--out", "-o", help="Output JSON file path"),
    template: Optional[str] = typer.Option(None, "--template", "-t", help="Template ID to use"),
    fallback_camelot: bool = typer.Option(False, "--fallback-camelot", help="Enable Camelot fallback"),
    debug_overlay: Optional[Path] = typer.Option(None, "--debug-overlay", help="Create debug overlay images"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output")
):
    """Parse a Standard Chartered eStatement PDF into structured JSON."""
    
    if not pdf_path.exists():
        console.print(f"[red]Error: PDF file not found: {pdf_path}[/red]")
        raise typer.Exit(1)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Parsing PDF...", total=None)
            
            # Detect template if not specified
            if not template:
                progress.update(task, description="Detecting template...")
                template = detect_template(pdf_path)
                if not template:
                    console.print("[red]Error: Could not detect template for this PDF[/red]")
                    raise typer.Exit(1)
            
            # Parse the statement
            progress.update(task, description="Extracting data...")
            result = parse_statement(
                pdf_path=pdf_path,
                template_id=template,
                fallback_camelot=fallback_camelot,
                verbose=verbose
            )
            
            # Output results
            if output:
                progress.update(task, description="Writing output...")
                output.write_text(result.model_dump_json(indent=2))
                console.print(f"[green]✓ Parsed successfully! Output written to: {output}[/green]")
            else:
                console.print(result.model_dump_json(indent=2))
            
            # Create debug overlay if requested
            if debug_overlay:
                progress.update(task, description="Creating debug overlay...")
                debug_overlay.mkdir(parents=True, exist_ok=True)
                create_debug_overlay(pdf_path, template, debug_overlay)
                console.print(f"[blue]Debug overlay created in: {debug_overlay}[/blue]")
                
    except Exception as e:
        console.print(f"[red]Error parsing PDF: {e}[/red]")
        if verbose:
            import traceback
            console.print(traceback.format_exc())
        raise typer.Exit(1)

@app.command()
def detect(
    pdf_path: Path = typer.Argument(..., help="Path to PDF file")
):
    """Detect which template matches a PDF file."""
    try:
        template = detect_template(pdf_path)
        if template:
            console.print(f"[green]Detected template: {template}[/green]")
        else:
            console.print("[red]No matching template found[/red]")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error detecting template: {e}[/red]")
        raise typer.Exit(1)

@app.command()
def validate(
    json_path: Path = typer.Argument(..., help="Path to JSON file to validate")
):
    """Validate a JSON file against the schema."""
    from models.schema import StatementData
    
    try:
        data = StatementData.model_validate_json(json_path.read_text())
        console.print("[green]✓ JSON is valid[/green]")
        console.print(f"Bank: {data.meta.bank}")
        console.print(f"Statement Date: {data.meta.statement_date}")
        console.print(f"Transactions: {len(data.transactions)}")
        console.print(f"Instalments: {len(data.instalments)}")
    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/red]")
        raise typer.Exit(1)

if __name__ == "__main__":
    app()