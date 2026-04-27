"""CLI del proyecto."""

from __future__ import annotations

import cProfile
from pathlib import Path
import pstats

import typer
from rich import print

from .database import Database
from .logging_utils import configure_logging
from .nico_catalog import NicoCatalogLoader
from .perf_trace import PerfTrace
from .settings import load_settings
from .sync import Synchronizer

app = typer.Typer(add_completion=False, help="CLI para NICO Trade Hub")


def build_db() -> Database:
    settings = load_settings()
    configure_logging(settings.log_dir)
    return Database(settings.database_path, settings.root / "migrations")


@app.command("init-db")
def init_db() -> None:
    db = build_db()
    db.init_db()
    print("[green]Base inicializada correctamente.[/green]")


@app.command("status")
def status() -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    print(db.status())
    print(db.nico_catalog_status())


@app.command("load-nico-catalog")
def load_nico_catalog(path: str = typer.Option(..., help="Ruta al Excel maestro de NICO")) -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    loader = NicoCatalogLoader()
    rows = loader.load(Path(path))
    loaded = db.replace_nico_catalog([r.as_record() for r in rows], source_file=path)
    print(f"[green]Catálogo NICO cargado:[/green] {loaded} filas")


@app.command("ingest-inbox")
def ingest_inbox() -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    sync = Synchronizer(settings, db)
    print(sync.ingest_inbox())


@app.command("sync-banxico")
def sync_banxico(
    metric: str = typer.Option("both", help="value, volume o both"),
    flow: str = typer.Option("both", help="IMPORT, EXPORT o both"),
    start: str = typer.Option("2022-01", help="Mes inicial YYYY-MM"),
    end: str = typer.Option("2022-01", help="Mes final YYYY-MM"),
    trace_json: str | None = typer.Option(None, help="Ruta para guardar la traza JSON"),
    profile_out: str | None = typer.Option(None, help="Ruta para guardar profiling .prof"),
    profile_top: int = typer.Option(40, help="Cantidad de funciones a mostrar si se activa profiling"),
) -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)

    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()

    trace = PerfTrace(
        run_name="sync-banxico",
        output_path=Path(trace_json) if trace_json else None,
    )
    trace.set_meta(metric=metric, flow=flow, start=start, end=end)

    syncer = Synchronizer(settings, db)

    if profile_out:
        profiler = cProfile.Profile()
        profiler.enable()
        result = syncer.sync_banxico(
            metric=metric,
            flow=flow,
            start_month=start,
            end_month=end,
            trace=trace,
        )
        profiler.disable()

        profile_path = Path(profile_out)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(str(profile_path))

        stats = pstats.Stats(profiler).sort_stats("cumtime")
        stats.print_stats(profile_top)

        print(f"[cyan]Perfil guardado en:[/cyan] {profile_path}")
    else:
        result = syncer.sync_banxico(
            metric=metric,
            flow=flow,
            start_month=start,
            end_month=end,
            trace=trace,
        )

    dumped = trace.dump()
    print(result)
    if dumped:
        print(f"[cyan]Traza guardada en:[/cyan] {dumped}")


@app.command("export")
def export_data(
    flow: str | None = typer.Option(None, help="IMPORT o EXPORT"),
    country: str | None = typer.Option(None, help="Nombre canónico del país"),
    start: str | None = typer.Option(None, help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, help="YYYY-MM-DD"),
    level: int | None = typer.Option(None, help="2, 4, 6, 8 o 10"),
    prefix: str | None = typer.Option(None, help="Prefijo arancelario"),
    format: str = typer.Option("csv", help="csv, parquet o dta"),
    output: str | None = typer.Option(None, help="Ruta de salida opcional"),
) -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    df = db.query_export(flow=flow, country=country, start=start, end=end, level=level, prefix=prefix)
    payload, _mime, filename = db.export_dataframe(df, format)
    output_path = Path(output) if output else settings.export_dir / filename
    output_path.write_bytes(payload)
    print(f"[green]Exportado:[/green] {output_path}")


def run() -> None:
    app()


if __name__ == "__main__":
    run()