"""Aplicación Streamlit."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import date
from typing import Any

import streamlit as st

from .database import Database
from .logging_utils import configure_logging
from .settings import load_settings
from .sync import Synchronizer


@st.cache_resource
def bootstrap() -> tuple:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    syncer = Synchronizer(settings, db)
    return settings, db, syncer


def _run_cli_command(settings, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Ejecuta la CLI del proyecto en un proceso separado."""
    cmd = [sys.executable, "-m", "nico_trade_hub.cli", *args]
    return subprocess.run(
        cmd,
        cwd=str(settings.root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _digit_groups(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def _format_seconds(value: float) -> str:
    return f"{value:.2f} s"


def _store_run_report(
    key: str,
    *,
    title: str,
    ok: bool,
    normalized: dict[str, Any] | None = None,
    timings: dict[str, float] | None = None,
    stdout: str = "",
    stderr: str = "",
    error_message: str = "",
) -> None:
    st.session_state[key] = {
        "title": title,
        "ok": ok,
        "normalized": normalized or {},
        "timings": timings or {},
        "stdout": stdout,
        "stderr": stderr,
        "error_message": error_message,
    }


def _render_run_report(key: str) -> None:
    report = st.session_state.get(key)
    if not report:
        return

    st.markdown("### Última ejecución")
    if report["ok"]:
        st.success(f"{report['title']} finalizó correctamente.")
    else:
        st.error(f"{report['title']} falló.")
        if report["error_message"]:
            st.warning(report["error_message"])

    normalized = report.get("normalized") or {}
    if normalized:
        st.markdown("**Entradas normalizadas**")
        st.json(normalized)

    timings = report.get("timings") or {}
    if timings:
        st.markdown("**Tiempos de ejecución**")
        tcols = st.columns(min(len(timings), 4) or 1)
        ordered_keys = ["validacion", "subprocess", "refresco_ui", "total"]
        visible = [k for k in ordered_keys if k in timings] + [
            k for k in timings.keys() if k not in ordered_keys
        ]
        for idx, name in enumerate(visible):
            tcols[idx % len(tcols)].metric(name.replace("_", " ").title(), _format_seconds(timings[name]))

    stdout = (report.get("stdout") or "").strip()
    stderr = (report.get("stderr") or "").strip()

    if stdout:
        st.markdown("**Salida estándar**")
        st.code(stdout, language="text")
    if stderr:
        st.markdown("**Salida de error / advertencias**")
        st.code(stderr, language="text")


def _parse_month_input(raw: str, *, required: bool = True) -> tuple[str | None, str | None]:
    """
    Normaliza entradas como:
    2022-01, 2022/01, 2022   - 1, 202201
    -> 2022-01
    """
    text = _collapse_spaces(raw)

    if not text:
        if required:
            return None, "Este campo es obligatorio. Usa año y mes numéricos, por ejemplo: 2022-01."
        return None, None

    groups = _digit_groups(text)
    year: int
    month: int

    try:
        if len(groups) == 1 and len(groups[0]) == 6:
            year = int(groups[0][:4])
            month = int(groups[0][4:6])
        elif len(groups) >= 2:
            year = int(groups[0])
            month = int(groups[1])
        else:
            return None, "Formato inválido. Usa año y mes numéricos, por ejemplo: 2022-01."
    except ValueError:
        return None, "Solo se admiten caracteres numéricos para año y mes."

    if not (1900 <= year <= 2100):
        return None, "El año debe estar entre 1900 y 2100."
    if not (1 <= month <= 12):
        return None, "El mes debe estar entre 1 y 12."

    return f"{year:04d}-{month:02d}", None


def _parse_date_input(raw: str, *, required: bool = False) -> tuple[str | None, str | None]:
    """
    Normaliza entradas como:
    2022/01/01, 2022-1-1, 2022   - 01 - 01, 20220101
    -> 2022-01-01
    """
    text = _collapse_spaces(raw)

    if not text:
        if required:
            return None, "Este campo es obligatorio. Usa fecha numérica, por ejemplo: 2022-01-01."
        return None, None

    groups = _digit_groups(text)
    year: int
    month: int
    day: int

    try:
        if len(groups) == 1 and len(groups[0]) == 8:
            digits = groups[0]
            year = int(digits[:4])
            month = int(digits[4:6])
            day = int(digits[6:8])
        elif len(groups) >= 3:
            year = int(groups[0])
            month = int(groups[1])
            day = int(groups[2])
        else:
            return None, "Formato inválido. Usa fecha numérica, por ejemplo: 2022-01-01."
    except ValueError:
        return None, "Solo se admiten caracteres numéricos para año, mes y día."

    if not (1900 <= year <= 2100):
        return None, "El año debe estar entre 1900 y 2100."

    try:
        normalized = date(year, month, day)
    except ValueError as exc:
        return None, f"Fecha inválida: {exc}"

    return normalized.isoformat(), None


def _normalize_country(raw: str) -> str | None:
    text = _collapse_spaces(raw)
    return text or None


def _normalize_prefix(raw: str) -> tuple[str | None, str | None]:
    """
    Permite entradas como:
    73.06.1999 -> 73061999
    73 06 19 99 -> 73061999
    """
    text = _collapse_spaces(raw)
    if not text:
        return None, None

    digits = "".join(_digit_groups(text))
    if not digits:
        return None, "El prefijo arancelario debe contener al menos un dígito."
    return digits, None


def _show_field_feedback(
    *,
    normalized: str | None,
    error: str | None,
    accepted_hint: str,
    optional: bool = False,
) -> None:
    if error:
        st.warning(error)
        st.caption(accepted_hint)
        return

    if normalized:
        st.caption(f"Valor interpretado: `{normalized}`")
    elif optional:
        st.caption(f"{accepted_hint}")
    else:
        st.caption(accepted_hint)


def main() -> None:
    settings, db, syncer = bootstrap()

    st.set_page_config(
        page_title=settings.raw["app"]["page_title"],
        page_icon=settings.raw["app"]["page_icon"],
        layout="wide",
    )

    st.title("📦 NICO Trade Hub")
    st.caption("Base local de comercio exterior de México a nivel fracción y NICO")

    with st.sidebar:
        st.subheader("Rutas")
        st.write(f"**Base:** `{settings.database_path}`")
        st.write(f"**Bronze:** `{settings.bronze_dir}`")
        st.write(f"**Inbox:** `{settings.inbox_dir}`")
        st.write(f"**Exports:** `{settings.export_dir}`")

    overview_tab, update_tab, export_tab, diagnostics_tab = st.tabs(
        ["Resumen", "Actualizar", "Exportar", "Diagnóstico"]
    )

    with overview_tab:
        status = db.status()
        nico_status = db.nico_catalog_status()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Filas", int(status.get("rows_count") or 0))
        c2.metric("Meses", int(status.get("months_count") or 0))
        c3.metric("Países", int(status.get("countries_count") or 0))
        c4.metric("Códigos", int(status.get("product_count") or 0))
        d1, d2 = st.columns(2)
        d1.metric("NICO cargados", int(nico_status.get("nicos") or 0))
        d2.metric("Fracciones con NICO", int(nico_status.get("fracciones") or 0))
        st.subheader("Últimas cargas")
        st.dataframe(db.recent_load_runs(), width="stretch")

    with update_tab:
        st.subheader("Banxico")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            metric = st.selectbox("Métrica", ["both", "value", "volume"], key="banxico_metric")

        with col2:
            flow = st.selectbox("Flujo", ["both", "EXPORT", "IMPORT"], key="banxico_flow")

        with col3:
            start_raw = st.text_input("Inicio", "2022-01", key="banxico_start")
            start_norm, start_error = _parse_month_input(start_raw, required=True)
            _show_field_feedback(
                normalized=start_norm,
                error=start_error,
                accepted_hint="Admite formatos como 2022-01, 2022/01, 2022 01 o 202201.",
            )

        with col4:
            end_raw = st.text_input("Fin", "2022-01", key="banxico_end")
            end_norm, end_error = _parse_month_input(end_raw, required=True)
            _show_field_feedback(
                normalized=end_norm,
                error=end_error,
                accepted_hint="Admite formatos como 2022-01, 2022/01, 2022 01 o 202201.",
            )

        if st.button("Sincronizar Banxico", key="btn_sync_banxico"):
            total_start = time.perf_counter()
            timings: dict[str, float] = {}

            try:
                validation_start = time.perf_counter()
                start_norm, start_error = _parse_month_input(start_raw, required=True)
                end_norm, end_error = _parse_month_input(end_raw, required=True)

                if start_error:
                    raise ValueError(f"Inicio: {start_error}")
                if end_error:
                    raise ValueError(f"Fin: {end_error}")
                if start_norm is None or end_norm is None:
                    raise ValueError("No se pudieron interpretar las fechas de inicio y fin.")

                if start_norm > end_norm:
                    raise ValueError("El mes de inicio no puede ser mayor que el mes de fin.")

                timings["validacion"] = time.perf_counter() - validation_start

                with st.spinner("Ejecutando sincronización Banxico..."):
                    subprocess_start = time.perf_counter()
                    result = _run_cli_command(
                        settings,
                        [
                            "sync-banxico",
                            "--metric",
                            metric,
                            "--flow",
                            flow,
                            "--start",
                            start_norm,
                            "--end",
                            end_norm,
                        ],
                    )
                    timings["subprocess"] = time.perf_counter() - subprocess_start

                refresh_start = time.perf_counter()
                # Limpiamos el recurso cacheado para reabrir la DB en el próximo rerun.
                bootstrap.clear()
                timings["refresco_ui"] = time.perf_counter() - refresh_start
                timings["total"] = time.perf_counter() - total_start

                if result.returncode == 0:
                    _store_run_report(
                        "banxico_last_run",
                        title="Sincronización Banxico",
                        ok=True,
                        normalized={
                            "metric": metric,
                            "flow": flow,
                            "start": start_norm,
                            "end": end_norm,
                        },
                        timings=timings,
                        stdout=result.stdout,
                        stderr=result.stderr,
                    )
                    st.rerun()

                _store_run_report(
                    "banxico_last_run",
                    title="Sincronización Banxico",
                    ok=False,
                    normalized={
                        "metric": metric,
                        "flow": flow,
                        "start": start_norm,
                        "end": end_norm,
                    },
                    timings=timings,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    error_message="La CLI devolvió un código de salida distinto de cero.",
                )
                _render_run_report("banxico_last_run")

            except Exception as exc:
                timings["total"] = time.perf_counter() - total_start
                _store_run_report(
                    "banxico_last_run",
                    title="Sincronización Banxico",
                    ok=False,
                    normalized={
                        "metric": metric,
                        "flow": flow,
                        "start": start_norm,
                        "end": end_norm,
                    },
                    timings=timings,
                    error_message=str(exc),
                )
                _render_run_report("banxico_last_run")

        _render_run_report("banxico_last_run")

        st.markdown("---")
        st.subheader("INEGI / manual")

        if st.button("Procesar inbox manual", key="btn_ingest_inbox"):
            total_start = time.perf_counter()
            timings: dict[str, float] = {}
            try:
                with st.spinner("Procesando inbox manual..."):
                    action_start = time.perf_counter()
                    result_message = syncer.ingest_inbox()
                    timings["proceso"] = time.perf_counter() - action_start

                refresh_start = time.perf_counter()
                bootstrap.clear()
                timings["refresco_ui"] = time.perf_counter() - refresh_start
                timings["total"] = time.perf_counter() - total_start

                _store_run_report(
                    "inbox_last_run",
                    title="Procesamiento de inbox manual",
                    ok=True,
                    timings=timings,
                    stdout=result_message,
                )
                st.rerun()

            except Exception as exc:
                timings["total"] = time.perf_counter() - total_start
                _store_run_report(
                    "inbox_last_run",
                    title="Procesamiento de inbox manual",
                    ok=False,
                    timings=timings,
                    error_message=str(exc),
                )
                _render_run_report("inbox_last_run")

        _render_run_report("inbox_last_run")

    with export_tab:
        st.subheader("Exportación filtrada")

        flow_export = st.selectbox("Flujo", [None, "IMPORT", "EXPORT"], index=0, key="export_flow")
        country_raw = st.text_input("País (nombre exacto opcional)", key="export_country")
        country_norm = _normalize_country(country_raw)
        st.caption("Opcional. Se buscará por nombre exacto si lo proporcionas.")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            export_start_raw = st.text_input("Inicio", key="export_start")
            export_start_norm, export_start_error = _parse_date_input(export_start_raw, required=False)
            _show_field_feedback(
                normalized=export_start_norm,
                error=export_start_error,
                accepted_hint="Admite 2022-01-01, 2022/01/01, 2022 1 1 o 20220101.",
                optional=True,
            )

        with col2:
            export_end_raw = st.text_input("Fin", key="export_end")
            export_end_norm, export_end_error = _parse_date_input(export_end_raw, required=False)
            _show_field_feedback(
                normalized=export_end_norm,
                error=export_end_error,
                accepted_hint="Admite 2022-01-01, 2022/01/01, 2022 1 1 o 20220101.",
                optional=True,
            )

        with col3:
            level = st.selectbox("Nivel arancelario", [None, 2, 4, 6, 8, 10], index=0, key="export_level")

        with col4:
            fmt = st.selectbox("Formato", ["csv", "parquet", "dta"], key="export_format")

        prefix_raw = st.text_input("Prefijo arancelario", key="export_prefix")
        prefix_norm, prefix_error = _normalize_prefix(prefix_raw)
        _show_field_feedback(
            normalized=prefix_norm,
            error=prefix_error,
            accepted_hint="Solo se usarán dígitos. Ejemplo: 73.06.1999 se interpreta como 73061999.",
            optional=True,
        )

        if st.button("Preparar exportación", key="btn_prepare_export"):
            total_start = time.perf_counter()
            timings: dict[str, float] = {}

            try:
                validation_start = time.perf_counter()

                export_start_norm, export_start_error = _parse_date_input(export_start_raw, required=False)
                export_end_norm, export_end_error = _parse_date_input(export_end_raw, required=False)
                prefix_norm, prefix_error = _normalize_prefix(prefix_raw)
                country_norm = _normalize_country(country_raw)

                if export_start_error:
                    raise ValueError(f"Fecha inicio: {export_start_error}")
                if export_end_error:
                    raise ValueError(f"Fecha fin: {export_end_error}")
                if prefix_error:
                    raise ValueError(f"Prefijo arancelario: {prefix_error}")

                if export_start_norm and export_end_norm and export_start_norm > export_end_norm:
                    raise ValueError("La fecha de inicio no puede ser mayor que la fecha de fin.")

                timings["validacion"] = time.perf_counter() - validation_start

                query_start = time.perf_counter()
                df = db.query_export(
                    flow=flow_export,
                    country=country_norm,
                    start=export_start_norm,
                    end=export_end_norm,
                    level=level,
                    prefix=prefix_norm,
                )
                timings["consulta"] = time.perf_counter() - query_start
                timings["total"] = time.perf_counter() - total_start

                st.success("Consulta preparada correctamente.")
                st.markdown("**Filtros normalizados**")
                st.json(
                    {
                        "flow": flow_export,
                        "country": country_norm,
                        "start": export_start_norm,
                        "end": export_end_norm,
                        "level": level,
                        "prefix": prefix_norm,
                        "format": fmt,
                    }
                )

                tcols = st.columns(3)
                for idx, (name, value) in enumerate(timings.items()):
                    tcols[idx % 3].metric(name.replace("_", " ").title(), _format_seconds(value))

                st.write(f"Registros encontrados: {len(df):,}")
                st.dataframe(df.head(200), width="stretch")

                export_start = time.perf_counter()
                payload, mime, filename = db.export_dataframe(df, fmt)
                export_elapsed = time.perf_counter() - export_start
                st.metric("Generación de archivo", _format_seconds(export_elapsed))

                st.download_button(
                    "Descargar archivo",
                    data=payload,
                    file_name=filename,
                    mime=mime,
                    width="stretch",
                )

            except Exception as exc:
                st.error(f"No se pudo preparar la exportación: {exc}")

    with diagnostics_tab:
        st.subheader("Archivos en bronze")
        bronze_files = sorted(p.name for p in settings.bronze_dir.iterdir() if p.is_file())
        st.write(bronze_files[:200] if bronze_files else "Sin archivos")

        st.subheader("Archivos en inbox")
        inbox_files = sorted(p.name for p in settings.inbox_dir.iterdir() if p.is_file())
        st.write(inbox_files[:200] if inbox_files else "Sin archivos")