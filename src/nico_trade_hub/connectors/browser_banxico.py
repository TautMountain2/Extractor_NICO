"""Conector Playwright para el cubo de comercio exterior de Banxico.

Estrategia implementada:
- usar Matriz Producto-Región;
- una extracción por mes y por flujo;
- fijar filtros con los combos buscables visibles en la UI;
- expandir a nivel País en regiones;
- expandir a nivel Fracción en productos;
- desplegar masivamente los nodos visibles antes de exportar Excel.

La UI del cubo puede cambiar; por eso las acciones son deliberadamente
conservadoras y basadas en textos visibles, geometría del widget y varios
fallbacks al mismo tiempo.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import ElementHandle, Page, async_playwright

LOGGER = logging.getLogger(__name__)

SPANISH_MONTHS = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


@dataclass(slots=True)
class BanxicoJob:
    year: int
    month: int
    flow_code: str
    metric: str  # value | volume

    @property
    def month_label(self) -> str:
        return f"{SPANISH_MONTHS[self.month]} {self.year}"

    @property
    def job_id(self) -> str:
        return f"banxico_{self.metric}_{self.flow_code.lower()}_{self.year}_{self.month:02d}"


@dataclass(slots=True)
class BanxicoJobResult:
    job: BanxicoJob
    output_path: Path | None = None
    error_message: str | None = None
    error_traceback: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_message is None and self.output_path is not None


class BanxicoMatrixBrowserConnector:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.config = settings.raw["sources"]["banxico"]

    def run_job(self, job: BanxicoJob) -> Path:
        result = self.run_jobs([job])[0]
        if not result.ok or result.output_path is None:
            raise RuntimeError(result.error_message or f"Falló el job {job.job_id}")
        return result.output_path

    def run_jobs(self, jobs: list[BanxicoJob]) -> list[BanxicoJobResult]:
        return asyncio.run(self._run_jobs(jobs))

    async def _run_jobs(self, jobs: list[BanxicoJob]) -> list[BanxicoJobResult]:
        if not jobs:
            return []

        first_metric = jobs[0].metric
        if any(job.metric != first_metric for job in jobs):
            raise ValueError("Todos los jobs del batch Banxico deben compartir el mismo metric")

        url = self.config["value_matrix_url"] if first_metric == "value" else self.config["volume_matrix_url"]
        results: list[BanxicoJobResult] = []
        expanded_once = False
        previous_flow: str | None = None
        previous_month: str | None = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=bool(self.config.get("headless", True)))
            context = await browser.new_context(accept_downloads=True)
            try:
                await context.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://www.banxico.org.mx")
            except Exception:
                pass
            page = await context.new_page()
            page.set_default_timeout(int(self.config.get("timeout_ms", 90000)))

            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            for job in jobs:
                output_path = self.settings.bronze_dir / f"{job.job_id}.xlsx"
                screenshot_path = self.settings.log_dir / f"{job.job_id}_failure.png"
                try:
                    if previous_flow != job.flow_code:
                        await self._set_flow(page, job.flow_code)
                        previous_flow = job.flow_code
                    if previous_month != job.month_label:
                        await self._set_period(page, job.month_label)
                        previous_month = job.month_label

                    if not expanded_once:
                        await self._expand_axis_to_level(page, axis_text="Todas las regiones", level_text="País")
                        await self._expand_axis_to_level(
                            page,
                            axis_text="Todos los productos",
                            level_text=self.config.get("default_level", "Fracción"),
                        )
                        if self.config.get("expand_visible_nodes", True):
                            await self._expand_all_product_and_region_nodes(page)
                        expanded_once = True

                    await page.wait_for_timeout(1800)
                    await self._export_excel(page, output_path)
                    LOGGER.info("Archivo Banxico descargado: %s", output_path)
                    results.append(BanxicoJobResult(job=job, output_path=output_path))
                except Exception as exc:
                    try:
                        await page.screenshot(path=str(screenshot_path), full_page=True)
                        LOGGER.error("Screenshot de fallo Banxico guardado en: %s", screenshot_path)
                    except Exception:
                        LOGGER.exception("No se pudo guardar screenshot de Banxico")
                    results.append(
                        BanxicoJobResult(
                            job=job,
                            error_message=str(exc),
                            error_traceback=traceback.format_exc(),
                        )
                    )

            await browser.close()
        return results

    async def _set_flow(self, page: Page, flow_code: str) -> None:
        label = "Exportación" if flow_code.upper() == "EXPORT" else "Importación"
        await self._select_filter_option(page, filter_name="Tipo de Operación", option_text=label)
        await self._wait_until_page_mentions(page, label)

    async def _set_period(self, page: Page, month_label: str) -> None:
        await self._select_filter_option(page, filter_name="Mes", option_text=month_label)
        await self._wait_until_page_mentions(page, month_label)

    async def _select_filter_option(self, page: Page, filter_name: str, option_text: str) -> None:
        if await self._select_via_select(page, option_text):
            await page.wait_for_timeout(1200)
            return

        if await self._select_via_searchable_combo(page, filter_name=filter_name, option_text=option_text):
            await page.wait_for_timeout(1200)
            return

        opened = await self._click_text(page, [filter_name])
        if opened and await self._click_option_below(page, option_text):
            await self._click_outside_combo(page)
            await page.wait_for_timeout(1200)
            return
        if await self._click_option_below(page, option_text):
            await self._click_outside_combo(page)
            await page.wait_for_timeout(1200)
            return

        raise RuntimeError(f"No se pudo fijar el filtro '{filter_name}' con la opción '{option_text}'")

    async def _select_via_select(self, page: Page, option_text: str) -> bool:
        selects = page.locator("select")
        count = await selects.count()
        for idx in range(count):
            select = selects.nth(idx)
            try:
                await select.select_option(label=option_text)
                return True
            except Exception:
                continue
        return False

    async def _select_via_searchable_combo(self, page: Page, *, filter_name: str, option_text: str) -> bool:
        control = await self._find_input_near_filter_label(page, filter_name)
        target_box = None

        if control is not None:
            try:
                await control.click(force=True)
                await page.wait_for_timeout(500)
                target_box = await control.bounding_box()
            except Exception:
                control = None

        if control is None:
            target_box = await self._open_combo_by_geometry(page, filter_name)
            if target_box is None:
                return False

        # En la práctica, el fallo recurrente estaba aquí: el input de búsqueda del
        # combo no siempre expone placeholder ni es un <input> clásico. Se usa una
        # búsqueda mixta por rol/bounding box y, si aún así no aparece, un click por
        # geometría dentro de la caja "Buscar" seguido de tipeo por teclado.
        search_box = await self._focus_combo_search_box(page, target_box)
        typed = False
        # En la interacción manual más estable del filtro Mes se escribe el texto exacto
        # de la opción (por ejemplo, 'Enero 2022') y luego se hace clic sobre la única
        # coincidencia disponible. Se intenta primero con el texto exacto; si no filtra,
        # se prueba con el año como apoyo adicional.
        attempted_terms = [option_text]
        if filter_name == "Mes":
            year_token = option_text.split()[-1]
            if year_token not in attempted_terms:
                attempted_terms.append(year_token)

        for search_term in attempted_terms:
            dom_typed = await self._set_search_value_via_dom(page, target_box, search_term)
            if dom_typed:
                typed = True
            if search_box is not None:
                typed = await self._clear_and_type_into_search(page, search_box, search_term) or typed
            else:
                typed = await self._clear_and_type_into_active_combo(page, target_box, search_term) or typed
            if typed:
                await page.wait_for_timeout(700)
            if await self._click_option_below(page, option_text, anchor_box=target_box):
                clicked = True
                break
        else:
            clicked = False

        if not clicked:
            clicked = await self._scroll_open_combo_until_option(page, option_text, anchor_box=target_box)
        if not clicked:
            await self._close_combo(page, filter_name, target_box)
            return False

        await self._close_combo(page, filter_name, target_box)
        await page.wait_for_timeout(1200)
        return await self._page_reflects_filter_selection(page, filter_name, option_text)

    async def _focus_combo_search_box(self, page: Page, target_box: dict | None):
        search = await self._find_search_input(page, target_box)
        if search is not None:
            try:
                await search.click(force=True)
                await page.wait_for_timeout(120)
                return search
            except Exception:
                pass

        if target_box is None:
            return None

        # fallback por geometría: click dentro del rectángulo "Buscar".
        try:
            await page.mouse.click(float(target_box["x"] + 62), float(target_box["y"] + 34))
            await page.wait_for_timeout(150)
        except Exception:
            return None
        return None

    async def _find_input_near_filter_label(self, page: Page, filter_name: str):
        label = await self._first_visible_text(page, [filter_name])
        if label is None:
            return None
        label_box = await label.bounding_box()
        if not label_box:
            return None

        best_locator = None
        best_score = None
        candidates = page.locator("input, [role='textbox'], textarea, [contenteditable='true']")
        count = await candidates.count()
        for idx in range(count):
            candidate = candidates.nth(idx)
            try:
                if not await candidate.is_visible():
                    continue
                box = await candidate.bounding_box()
                if not box:
                    continue
                vertical_gap = box["y"] - (label_box["y"] + label_box["height"])
                if vertical_gap < -8 or vertical_gap > 120:
                    continue
                horizontal_gap = abs(box["x"] - label_box["x"])
                if horizontal_gap > 280:
                    continue
                score = vertical_gap + horizontal_gap / 10.0
                if best_score is None or score < best_score:
                    best_score = score
                    best_locator = candidate
            except Exception:
                continue
        return best_locator

    async def _find_search_input(self, page: Page, target_box: dict | None = None):
        selectors = [
            "input[placeholder*='Buscar']",
            "input[placeholder*='buscar']",
            "[role='textbox']",
            "input[type='text']",
            "input",
            "textarea",
            "[contenteditable='true']",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:
                continue
            for idx in range(count):
                candidate = locator.nth(idx)
                try:
                    if not await candidate.is_visible():
                        continue
                    box = await candidate.bounding_box()
                    if not box:
                        continue
                    if target_box is not None:
                        if box["y"] < target_box["y"] - 5 or box["y"] > target_box["y"] + 90:
                            continue
                        if box["x"] < target_box["x"] - 5 or box["x"] > target_box["x"] + 260:
                            continue
                    return candidate
                except Exception:
                    continue
        return None

    async def _set_search_value_via_dom(self, page: Page, target_box: dict | None, text_value: str) -> bool:
        try:
            result = await page.evaluate(
                """({ anchorBox, textValue }) => {
                    const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = window.getComputedStyle(el);
                        return r.width > 20 && r.height > 12 && s.display !== 'none' && s.visibility !== 'hidden';
                    };
                    const nearAnchor = (r) => {
                        if (!anchorBox) return true;
                        return r.top >= anchorBox.y - 12 && r.top <= anchorBox.y + 120 && r.left >= anchorBox.x - 20 && r.left <= anchorBox.x + 320;
                    };
                    const setNativeValue = (el, value) => {
                        const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                        if (desc && desc.set) desc.set.call(el, value);
                        else el.value = value;
                    };
                    const dispatchTyping = (el, value) => {
                        try { el.focus(); } catch (_) {}
                        if ('value' in el) setNativeValue(el, value);
                        else if (el.isContentEditable) el.textContent = value;
                        for (const ev of ['input', 'change', 'keyup']) {
                            try { el.dispatchEvent(new Event(ev, { bubbles: true })); } catch (_) {}
                        }
                        try { el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '2' })); } catch (_) {}
                        return ('value' in el) ? el.value : el.textContent || '';
                    };
                    const candidates = Array.from(document.querySelectorAll("input, textarea, [role='textbox'], [contenteditable='true']"))
                        .filter(visible)
                        .filter((el) => nearAnchor(el.getBoundingClientRect()))
                        .sort((a, b) => {
                            const ra = a.getBoundingClientRect();
                            const rb = b.getBoundingClientRect();
                            return (ra.top - rb.top) || (ra.left - rb.left);
                        });
                    let target = candidates.find((el) => {
                        const ph = (el.getAttribute('placeholder') || '').toLowerCase();
                        const al = (el.getAttribute('aria-label') || '').toLowerCase();
                        return ph.includes('buscar') || al.includes('buscar');
                    }) || candidates[0] || null;
                    if (!target) return { ok: false, reason: 'no-target' };
                    const finalValue = dispatchTyping(target, textValue);
                    return { ok: true, tag: target.tagName, value: finalValue, placeholder: target.getAttribute('placeholder') || '' };
                }""",
                { 'anchorBox': target_box, 'textValue': text_value },
            )
            return bool(result and result.get('ok'))
        except Exception:
            return False

    async def _clear_and_type_into_search(self, page: Page, search_box, text: str) -> bool:
        try:
            await search_box.press("ControlOrMeta+A")
            await search_box.press("Delete")
        except Exception:
            pass
        try:
            await search_box.fill(text)
            return True
        except Exception:
            pass
        try:
            await page.keyboard.type(text, delay=20)
            return True
        except Exception:
            return False

    async def _clear_and_type_into_active_combo(self, page: Page, target_box: dict | None, text: str) -> bool:
        if target_box is not None:
            try:
                await page.mouse.click(float(target_box["x"] + 62), float(target_box["y"] + 34))
                await page.wait_for_timeout(120)
            except Exception:
                pass
        try:
            await page.keyboard.press("ControlOrMeta+A")
        except Exception:
            pass
        try:
            await page.keyboard.press("Delete")
        except Exception:
            pass
        try:
            await page.keyboard.type(text, delay=20)
            return True
        except Exception:
            return False

    async def _find_open_dropdown_container(self, page: Page, anchor_box: dict | None = None):
        handle = await page.evaluate_handle(
            """(anchorBox) => {
                const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 150 && r.height > 80 && s.display !== 'none' && s.visibility !== 'hidden';
                };
                const nearAnchor = (r, anchor) => {
                    if (!anchor) return true;
                    const vertical = r.top >= anchor.y - 10 && r.top <= anchor.y + 90;
                    const horizontal = r.left >= anchor.x - 30 && r.left <= anchor.x + 60;
                    return vertical && horizontal;
                };
                let best = null;
                let bestScore = Infinity;
                for (const el of document.querySelectorAll('*')) {
                    try {
                        if (!visible(el)) continue;
                        if (!(el.scrollHeight > el.clientHeight + 10)) continue;
                        const r = el.getBoundingClientRect();
                        if (!nearAnchor(r, anchorBox)) continue;
                        if (r.width > 420 || r.height > 700) continue;
                        const txt = (el.innerText || '');
                        const score = Math.abs(r.width - 300) + Math.abs(r.height - 420) - (txt.includes('Buscar') ? 60 : 0);
                        if (score < bestScore) {
                            bestScore = score;
                            best = el;
                        }
                    } catch (_) {}
                }
                return best;
            }""",
            anchor_box,
        )
        try:
            return handle.as_element()
        except Exception:
            return None

    async def _scroll_open_combo_until_option(self, page: Page, option_text: str, anchor_box: dict | None = None, max_steps: int = 100) -> bool:
        container = await self._find_open_dropdown_container(page, anchor_box)
        if container is None:
            return False

        try:
            await container.evaluate("el => { el.scrollTop = 0; el.dispatchEvent(new Event('scroll')); }")
            await page.wait_for_timeout(250)
        except Exception:
            pass

        for _ in range(max_steps):
            if await self._click_option_below(page, option_text, anchor_box=anchor_box):
                return True
            try:
                current = await container.evaluate("el => el.scrollTop")
                max_scroll = await container.evaluate("el => Math.max(0, el.scrollHeight - el.clientHeight)")
                step = await container.evaluate("el => Math.max(120, Math.floor(el.clientHeight * 0.8))")
            except Exception:
                return False
            if current >= max_scroll:
                break
            next_scroll = min(max_scroll, current + step)
            try:
                await container.evaluate("(el, value) => { el.scrollTop = value; el.dispatchEvent(new Event('scroll')); }", next_scroll)
                await page.wait_for_timeout(220)
            except Exception:
                try:
                    box = await container.bounding_box()
                    if box:
                        await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                        await page.mouse.wheel(0, 500)
                        await page.wait_for_timeout(220)
                    else:
                        return False
                except Exception:
                    return False
        return await self._click_option_below(page, option_text, anchor_box=anchor_box)

    async def _click_option_below(self, page: Page, option_text: str, anchor_box: dict | None = None) -> bool:
        locators = [
            page.get_by_text(option_text, exact=True),
            page.get_by_text(option_text, exact=False),
            page.locator(f"text={option_text}"),
        ]
        for locator in locators:
            try:
                count = await locator.count()
            except Exception:
                continue
            for idx in range(count):
                candidate = locator.nth(idx)
                try:
                    if not await candidate.is_visible():
                        continue
                    if anchor_box is not None:
                        box = await candidate.bounding_box()
                        if box and box["y"] + box["height"] < anchor_box["y"]:
                            continue
                    await candidate.click(force=True)
                    return True
                except Exception:
                    continue
        return False

    async def _click_outside_combo(self, page: Page) -> None:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.wait_for_timeout(150)
        await page.mouse.click(80, 80)
        await page.wait_for_timeout(300)

    async def _close_combo(self, page: Page, filter_name: str, target_box: dict | None) -> None:
        if target_box is not None:
            try:
                await page.mouse.click(target_box["x"] + max(22, target_box["width"] - 10), target_box["y"])
                await page.wait_for_timeout(260)
                return
            except Exception:
                pass

        reopened_box = await self._open_combo_by_geometry(page, filter_name, allow_if_already_open=True)
        if reopened_box is not None:
            await page.wait_for_timeout(260)
            return

        await self._click_outside_combo(page)

    async def _open_combo_by_geometry(self, page: Page, filter_name: str, allow_if_already_open: bool = False) -> dict | None:
        label = await self._first_visible_text(page, [filter_name])
        if label is None:
            return None
        label_box = await label.bounding_box()
        if not label_box:
            return None

        click_points = [
            (label_box["x"] + 34, label_box["y"] + label_box["height"] + 24),
            (label_box["x"] + 110, label_box["y"] + label_box["height"] + 24),
            (label_box["x"] + 170, label_box["y"] + label_box["height"] + 24),
            (label_box["x"] + 210, label_box["y"] + label_box["height"] + 24),
        ]

        for x, y in click_points:
            try:
                await page.mouse.click(float(x), float(y))
                await page.wait_for_timeout(350)
                if await self._combo_looks_open(page, float(x), float(y)):
                    return {"x": float(x), "y": float(y), "width": 220.0, "height": 32.0}
                if allow_if_already_open:
                    return {"x": float(x), "y": float(y), "width": 220.0, "height": 32.0}
            except Exception:
                continue
        return None

    async def _combo_looks_open(self, page: Page, x: float, y: float) -> bool:
        search = await self._find_search_input(page, {"x": x, "y": y, "width": 220.0, "height": 32.0})
        if search is not None:
            return True
        # fallback visual: suele aparecer un panel de opciones debajo del combo.
        for month in ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]:
            loc = page.get_by_text(month, exact=False)
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _page_reflects_filter_selection(self, page: Page, filter_name: str, option_text: str) -> bool:
        if filter_name == "Mes":
            body = (await page.text_content("body") or "").lower()
            return option_text.lower() in body

        body = (await page.text_content("body") or "").lower()
        return option_text.lower() in body

    async def _wait_until_page_mentions(self, page: Page, text: str, timeout_ms: int | None = None) -> None:
        timeout_ms = timeout_ms or int(self.config.get("timeout_ms", 90000))
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000.0
        while asyncio.get_running_loop().time() < deadline:
            content = (await page.text_content("body") or "").lower()
            if text.lower() in content:
                return
            await page.wait_for_timeout(400)
        raise RuntimeError(f"La página no reflejó la selección esperada: {text}")

    async def _expand_axis_to_level(self, page: Page, axis_text: str, level_text: str) -> None:
        anchor = await self._first_visible_text(page, [axis_text])
        if anchor is None:
            raise RuntimeError(f"No se localizó el eje '{axis_text}' para expandir a '{level_text}'")

        await anchor.click(button="right")
        await page.wait_for_timeout(700)

        clicked = await self._click_text(page, ["Explorar hasta nivel", "Explorar hasta nivel "])
        if not clicked:
            try:
                await page.get_by_text("Explorar hasta nivel", exact=False).first.hover()
                await page.wait_for_timeout(350)
            except Exception:
                pass

        if not await self._click_text(page, [level_text], timeout_ms=6000):
            raise RuntimeError(f"No se pudo seleccionar el nivel '{level_text}' en el eje '{axis_text}'")
        await page.wait_for_timeout(2200)

    async def _expand_all_product_and_region_nodes(self, page: Page) -> None:
        # 1) productos: columna izquierda, escaneo vertical.
        await self._scan_table_for_expands(page, mode="vertical", max_passes=int(self.config.get("max_expand_passes", 6)))
        # 2) regiones/países: encabezados por columnas, escaneo horizontal.
        await self._scan_table_for_expands(page, mode="horizontal", max_passes=max(2, int(self.config.get("max_expand_passes", 6)) // 2))
        # 3) un último barrido visible, por si aparecieron nodos nuevos tras los scrolls.
        await self._expand_visible_plus_icons(page, max_clicks=int(self.config.get("max_visible_expands", 220)))

    async def _scan_table_for_expands(self, page: Page, mode: str, max_passes: int) -> int:
        container = await self._find_main_scrollable(page)
        if container is None:
            return await self._expand_visible_plus_icons(page, max_clicks=int(self.config.get("max_visible_expands", 220)))

        total_clicks = 0
        for _ in range(max_passes):
            if mode == "vertical":
                await container.evaluate("el => { el.scrollLeft = 0; el.scrollTop = 0; }")
                await page.wait_for_timeout(200)
                max_scroll = await container.evaluate("el => Math.max(0, el.scrollHeight - el.clientHeight)")
                step = max(120, int(await container.evaluate("el => Math.max(120, Math.floor(el.clientHeight * 0.7))")))
                scroll = 0
                while True:
                    await container.evaluate("(el, value) => { el.scrollTop = value; }", scroll)
                    await page.wait_for_timeout(180)
                    total_clicks += await self._expand_visible_plus_icons(page, max_clicks=60)
                    if scroll >= max_scroll:
                        break
                    scroll = min(max_scroll, scroll + step)
            else:
                await container.evaluate("el => { el.scrollTop = 0; el.scrollLeft = 0; }")
                await page.wait_for_timeout(200)
                max_scroll = await container.evaluate("el => Math.max(0, el.scrollWidth - el.clientWidth)")
                step = max(180, int(await container.evaluate("el => Math.max(180, Math.floor(el.clientWidth * 0.75))")))
                scroll = 0
                while True:
                    await container.evaluate("(el, value) => { el.scrollLeft = value; }", scroll)
                    await page.wait_for_timeout(180)
                    total_clicks += await self._expand_visible_plus_icons(page, max_clicks=30)
                    if scroll >= max_scroll:
                        break
                    scroll = min(max_scroll, scroll + step)
        if total_clicks:
            LOGGER.info("Expansiones masivas aplicadas en Banxico (%s): %s", mode, total_clicks)
        return total_clicks

    async def _find_main_scrollable(self, page: Page) -> ElementHandle | None:
        handle = await page.evaluate_handle(
            """() => {
                const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return r.width > 300 && r.height > 120 && r.top >= 180 && r.bottom <= (window.innerHeight + 5)
                        && style.display !== 'none' && style.visibility !== 'hidden';
                };
                let best = null;
                let bestScore = -1;
                for (const el of document.querySelectorAll('*')) {
                    try {
                        if (!visible(el)) continue;
                        const hasScroll = (el.scrollHeight > el.clientHeight + 40) || (el.scrollWidth > el.clientWidth + 40);
                        if (!hasScroll) continue;
                        const r = el.getBoundingClientRect();
                        const score = (Math.min(el.scrollHeight, 4000) - el.clientHeight) + (Math.min(el.scrollWidth, 4000) - el.clientWidth) + (r.width * r.height / 1000);
                        if (score > bestScore) {
                            bestScore = score;
                            best = el;
                        }
                    } catch (_) {}
                }
                return best;
            }"""
        )
        if handle is None:
            return None
        try:
            element = handle.as_element()
        except Exception:
            element = None
        return element

    async def _expand_visible_plus_icons(self, page: Page, max_clicks: int = 120) -> int:
        clicked = 0
        for _ in range(max_clicks):
            plus = await self._find_next_visible_plus(page)
            if plus is None:
                break
            try:
                await plus.click(force=True)
                clicked += 1
                await page.wait_for_timeout(90)
            except Exception:
                break
        return clicked

    async def _find_next_visible_plus(self, page: Page):
        table_anchor = await self._first_visible_text(page, ["Todos los productos", "Todas las regiones"])
        region = None
        if table_anchor is not None:
            try:
                box = await table_anchor.bounding_box()
                if box:
                    region = {"top": box["y"] - 30, "left": box["x"] - 30}
            except Exception:
                region = None

        candidates = [
            page.get_by_text("+", exact=True),
            page.locator("text=+"),
            page.locator("[title='+']"),
            page.locator("[aria-label='+']"),
        ]
        for locator in candidates:
            try:
                count = await locator.count()
            except Exception:
                continue
            for idx in range(count):
                candidate = locator.nth(idx)
                try:
                    if not await candidate.is_visible():
                        continue
                    if region is not None:
                        box = await candidate.bounding_box()
                        if box is None:
                            continue
                        if box["y"] < region["top"] or box["x"] < region["left"]:
                            continue
                    return candidate
                except Exception:
                    continue
        return None

    async def _export_excel(self, page: Page, output_path: Path) -> None:
        anchor = await self._first_visible_text(page, ["Todos los productos", "Todas las regiones"])
        if anchor is None:
            raise RuntimeError("No se encontró un ancla visible para abrir el menú contextual de exportación")

        async with page.expect_download(timeout=int(self.config.get("timeout_ms", 90000))) as download_info:
            await anchor.click(button="right")
            await page.wait_for_timeout(650)
            printed = await self._click_text(page, ["Imprimir"], timeout_ms=5000)
            if not printed:
                try:
                    await page.get_by_text("Imprimir", exact=False).first.hover()
                    await page.wait_for_timeout(400)
                except Exception:
                    pass
            await self._click_text(page, ["Excel"], timeout_ms=5000)
        download = await download_info.value
        await download.save_as(str(output_path))

    async def _first_visible_text(self, page: Page, candidates: list[str]):
        for candidate in candidates:
            try:
                locator = page.get_by_text(candidate, exact=False)
                count = await locator.count()
                for idx in range(count):
                    item = locator.nth(idx)
                    if await item.is_visible():
                        return item
            except Exception:
                continue
        return None

    async def _click_text(self, page: Page, candidates: list[str], timeout_ms: int = 8000) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000.0
        while asyncio.get_running_loop().time() < deadline:
            for candidate in candidates:
                for locator_factory in [
                    lambda: page.get_by_text(candidate, exact=False),
                    lambda: page.locator(f"text={candidate}"),
                ]:
                    try:
                        locator = locator_factory()
                        count = await locator.count()
                        if count > 0:
                            for idx in range(count):
                                item = locator.nth(idx)
                                if await item.is_visible():
                                    await item.click(force=True)
                                    return True
                    except Exception:
                        continue
            await page.wait_for_timeout(220)
        return False
