"""FastAPI uygulaması: HTTP arayüzü, arka plan simülasyon döngüsü ve ön yüz dosyaları.

Çalıştırma:  uvicorn --factory makine_iz.api:create_app
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, alerts, baselines, csv_io, demo, series
from .config import (
    ANALYSIS,
    DEFAULT_DB_PATH,
    DEFAULT_FEATURE_FLOORS,
    DEFAULT_INTERVAL_S,
    DEFAULT_RANGES,
    DEFAULT_TRANSITION_S,
    FEATURE_LABELS,
    FEATURE_UNITS,
    FEATURES,
    FRONTEND_DIST,
    MODE_LABELS,
    SAMPLES_DIR,
    SOURCE_LABELS,
)
from .db import Database, get_meta
from .machines import SIM_PROFILES, MachineError, create_machine, get_machine, list_machines, update_machine
from .pipeline import IngestOptions, ingest
from .simulation import SPEEDS, SimulationError, SimulationManager, latest_runs_by_machine
from .simulator import PROFILE_LABELS, scenario_list
from .status import compute_status
from .timeutil import from_iso, now_epoch, to_iso

log = logging.getLogger("makine_iz")

FIELD_NAMES = {
    "name": "Makine adı", "machine_type": "Makine türü", "mode": "Çalışma modu", "start": "Başlangıç",
    "end": "Bitiş", "seconds": "Süre", "speed": "Hız", "seed": "Tohum", "content": "Dosya içeriği",
    "text": "Not metni", "machine_id": "Makine",
}


# ---------------------------------------------------------------------------
# İstek gövdeleri
# ---------------------------------------------------------------------------
class BaselineRequest(BaseModel):
    mode: str
    start: str
    end: str
    confirm_normal: bool = False
    note: str = ""


class ReviewRequest(BaseModel):
    review_status: str | None = None
    assessment: str | None = None
    clear_assessment: bool = False


class NoteRequest(BaseModel):
    machine_id: str
    text: str
    alert_id: int | None = None
    note_type: str = "inspection"
    author: str = ""
    assessment: str | None = None


class SimStartRequest(BaseModel):
    machine_id: str
    scenario: str
    seed: int = 42
    speed: float = 1.0
    start_mode: str = "loaded"
    onset_s: float = 120.0


class SpeedRequest(BaseModel):
    speed: float


class AdvanceRequest(BaseModel):
    seconds: float = Field(gt=0)


class ModeRequest(BaseModel):
    mode: str


class CsvRequest(BaseModel):
    content: str
    filename: str = "dosya.csv"
    create_missing_machines: bool = False


class ResetRequest(BaseModel):
    confirm: bool = False


# ---------------------------------------------------------------------------
# Uygulama
# ---------------------------------------------------------------------------
def create_app(
    db_path: str | Path | None = None,
    *,
    run_background: bool = True,
    seed_demo: bool = True,
    autostart_demo: bool = True,
) -> FastAPI:
    db = Database(db_path or DEFAULT_DB_PATH)
    manager = SimulationManager(db)

    def start_demo_runs() -> None:
        for spec in demo.DEMO_MACHINES:
            manager.start(spec["id"], "normal", seed=demo.RUN_SEEDS[spec["id"]], speed=1.0, start_mode="loaded", onset_s=120)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        paused = manager.pause_after_restart()
        if paused:
            log.info("%s simülasyon çalıştırması duraklatıldı (yeniden başlatma).", paused)
        first_seed = False
        if seed_demo:
            with db.write() as conn:
                if get_meta(conn, "demo_seeded_at") is None:
                    demo.seed_demo(conn)
                    first_seed = True
            if first_seed and autostart_demo:
                start_demo_runs()
        task = asyncio.create_task(_background_loop(manager)) if run_background else None
        try:
            yield
        finally:
            if task:
                task.cancel()

    app = FastAPI(title="Makine İz", version=__version__, lifespan=lifespan)
    app.state.db = db
    app.state.manager = manager

    # Sayfa dosyası (index.html) önbellekten eski haliyle gelmesin; derlenmiş dosyaların adı zaten değişir.
    @app.middleware("http")
    async def no_cache_pages(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith(("/api", "/assets")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # -- hata biçimi: her zaman {"detail": "Türkçe mesaj"} ------------------
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        parts = []
        for error in exc.errors()[:5]:
            location = [str(p) for p in error.get("loc", []) if p not in ("body", "query", "path")]
            field = FIELD_NAMES.get(location[-1], location[-1]) if location else "istek"
            parts.append(f"{field}: {_translate(error.get('type', ''), error.get('msg', ''))}")
        return JSONResponse(status_code=422, content={"detail": "Gönderilen veri geçersiz — " + "; ".join(parts)})

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception):
        log.exception("Beklenmeyen hata")
        return JSONResponse(status_code=500, content={"detail": f"Sunucuda beklenmeyen bir hata oluştu: {exc}"})

    def fail(exc: Exception) -> HTTPException:
        if isinstance(exc, LookupError):
            return HTTPException(404, str(exc).strip("'\""))
        return HTTPException(400, str(exc))

    def machine_or_404(conn, machine_id: str) -> dict:
        machine = get_machine(conn, machine_id)
        if machine is None:
            raise HTTPException(404, "Makine bulunamadı.")
        return machine

    def parse_range(start: str | None, end: str | None) -> tuple[str | None, str | None]:
        try:
            return series.normalize_range(start, end)
        except ValueError as exc:
            raise HTTPException(400, f"Tarih okunamadı: {exc}") from None

    # -- genel ---------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "time": to_iso(now_epoch())}

    @app.get("/api/config")
    def config():
        return {
            "version": __version__,
            "analysis": ANALYSIS.as_dict(),
            "features": [{"id": f, "label": FEATURE_LABELS[f], "unit": FEATURE_UNITS[f]} for f in FEATURES],
            "modes": MODE_LABELS,
            "sources": SOURCE_LABELS,
            "default_floors": DEFAULT_FEATURE_FLOORS,
            "default_ranges": DEFAULT_RANGES,
            "default_interval_s": DEFAULT_INTERVAL_S,
            "default_transition_s": DEFAULT_TRANSITION_S,
            "sim_profiles": [{"id": p, "label": PROFILE_LABELS[p]} for p in SIM_PROFILES],
            "scenarios": scenario_list(),
            "speeds": SPEEDS,
            "timezone": "Europe/Istanbul",
        }

    @app.get("/api/overview")
    def overview():
        with db.read() as conn:
            runs = latest_runs_by_machine(conn)
            cards = []
            for machine in list_machines(conn):
                status = compute_status(conn, machine, runs.get(machine["id"]))
                cards.append({"machine": machine, "status": status, "run": runs.get(machine["id"])})
            recent = alerts.list_alerts(conn, {}, limit=10)
        return {
            "counts": {
                "machines": len(cards),
                "ok": sum(1 for c in cards if c["status"]["category"] == "ok"),
                "needs_review": sum(1 for c in cards if c["status"]["needs_review"]),
                "data_issue": sum(1 for c in cards if c["status"]["data_issue"]),
            },
            "machines": cards,
            "recent_alerts": recent,
        }

    # -- makineler -----------------------------------------------------------
    @app.get("/api/machines")
    def machines_list():
        with db.read() as conn:
            return list_machines(conn)

    @app.post("/api/machines", status_code=201)
    def machines_create(payload: dict = Body(...)):
        try:
            with db.write() as conn:
                return create_machine(conn, payload)
        except MachineError as exc:
            raise fail(exc) from None

    @app.get("/api/machines/{machine_id}")
    def machine_detail(machine_id: str):
        with db.read() as conn:
            machine = machine_or_404(conn, machine_id)
            run = latest_runs_by_machine(conn).get(machine_id)
            return {
                "machine": machine,
                "status": compute_status(conn, machine, run),
                "run": run,
                "range": series.telemetry_range(conn, machine_id),
                "baselines": baselines.list_baselines(conn, machine_id),
            }

    @app.put("/api/machines/{machine_id}")
    def machines_update(machine_id: str, payload: dict = Body(...)):
        try:
            with db.write() as conn:
                return update_machine(conn, machine_id, payload)
        except (MachineError, LookupError) as exc:
            raise fail(exc) from None

    @app.get("/api/machines/{machine_id}/series")
    def machine_series(machine_id: str, start: str | None = None, end: str | None = None, max_points: int = 1500):
        with db.read() as conn:
            machine = machine_or_404(conn, machine_id)
            rng = series.telemetry_range(conn, machine_id)
            if rng["count"] == 0:
                return {"total": 0, "downsampled": False, "bucket_s": None, "points": [], "start": None, "end": None}
            start_iso, end_iso = parse_range(start, end)
            return series.query_series(
                conn, machine, start_iso or rng["first_ts"], end_iso or rng["last_ts"], max(100, min(max_points, 5000))
            )

    # -- ölçümler ------------------------------------------------------------
    @app.get("/api/telemetry")
    def telemetry_query(machine_id: str | None = None, start: str | None = None, end: str | None = None,
                        limit: int = 1000, offset: int = 0):
        start_iso, end_iso = parse_range(start, end)
        with db.read() as conn:
            return series.query_raw(conn, machine_id, start_iso, end_iso, max(1, min(limit, 10000)), max(0, offset))

    @app.post("/api/telemetry")
    def telemetry_ingest(payload: Any = Body(...)):
        """Tek kayıt (nesne) veya toplu kayıt ({"records": [...]} ya da liste). Kaynak: sensor."""
        single = isinstance(payload, dict) and "records" not in payload
        records = [payload] if single else (payload.get("records") if isinstance(payload, dict) else payload)
        if not isinstance(records, list) or not records:
            raise HTTPException(400, "Gövde bir ölçüm nesnesi, ölçüm listesi veya {\"records\": [...]} olmalı.")
        if len(records) > 10000:
            raise HTTPException(400, "Tek istekte en fazla 10000 kayıt gönderilebilir.")
        with db.write() as conn:
            results = ingest(conn, records, IngestOptions(source="sensor"))
        body = {
            "accepted": sum(1 for r in results if r.stored),
            "rejected": sum(1 for r in results if not r.stored),
            "results": [r.as_dict() for r in results],
        }
        if single and not results[0].stored:
            raise HTTPException(422, results[0].message)
        return body

    # -- referanslar ---------------------------------------------------------
    @app.get("/api/machines/{machine_id}/baselines")
    def baseline_list(machine_id: str):
        with db.read() as conn:
            machine_or_404(conn, machine_id)
            return baselines.list_baselines(conn, machine_id)

    @app.post("/api/machines/{machine_id}/baselines/preview")
    def baseline_preview(machine_id: str, request: BaselineRequest):
        with db.read() as conn:
            machine = machine_or_404(conn, machine_id)
            try:
                return baselines.preview(conn, machine, request.mode, request.start, request.end)
            except baselines.BaselineError as exc:
                raise fail(exc) from None

    @app.post("/api/machines/{machine_id}/baselines", status_code=201)
    def baseline_create(machine_id: str, request: BaselineRequest):
        try:
            with db.write() as conn:
                machine = machine_or_404(conn, machine_id)
                return baselines.create(conn, machine, request.mode, request.start, request.end,
                                        confirm_normal=request.confirm_normal, note=request.note)
        except baselines.BaselineError as exc:
            raise fail(exc) from None

    # -- uyarılar ve notlar --------------------------------------------------
    def alert_filters(machine_id, kind, level, review_status, measurement_status, start, end) -> dict:
        parse_range(start, end)
        return {"machine_id": machine_id, "kind": kind, "level": level, "review_status": review_status,
                "measurement_status": measurement_status, "start": start, "end": end}

    @app.get("/api/alerts")
    def alert_list(machine_id: str | None = None, kind: str | None = None, level: str | None = None,
                   review_status: str | None = None, measurement_status: str | None = None,
                   start: str | None = None, end: str | None = None, limit: int = 500):
        filters = alert_filters(machine_id, kind, level, review_status, measurement_status, start, end)
        with db.read() as conn:
            return alerts.list_alerts(conn, filters, limit=max(1, min(limit, 5000)))

    @app.get("/api/alerts/{alert_id}")
    def alert_detail(alert_id: int):
        with db.read() as conn:
            alert = alerts.get_alert(conn, alert_id)
            if alert is None:
                raise HTTPException(404, "Uyarı bulunamadı.")
            baseline = baselines.get_baseline(conn, alert["baseline_id"]) if alert["baseline_id"] else None
            active = baselines.active_baselines(conn, alert["machine_id"]).get(alert["mode"] or "")
            return {
                "alert": alert,
                "baseline": baseline,
                "current_baseline_version": active["version"] if active else None,
                "notes": alerts.list_notes(conn, alert_id=alert_id),
            }

    @app.patch("/api/alerts/{alert_id}")
    def alert_review(alert_id: int, request: ReviewRequest):
        try:
            with db.write() as conn:
                return alerts.update_review(conn, alert_id, request.review_status, request.assessment,
                                            request.clear_assessment)
        except (alerts.AlertError, LookupError) as exc:
            raise fail(exc) from None

    @app.get("/api/notes")
    def note_list(machine_id: str | None = None, alert_id: int | None = None):
        with db.read() as conn:
            return alerts.list_notes(conn, machine_id, alert_id)

    @app.post("/api/notes", status_code=201)
    def note_create(request: NoteRequest):
        try:
            with db.write() as conn:
                return alerts.add_note(conn, request.model_dump())
        except (alerts.AlertError, LookupError) as exc:
            raise fail(exc) from None

    # -- simülasyon ----------------------------------------------------------
    def sim_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (SimulationError, LookupError) as exc:
            raise fail(exc) from None

    @app.get("/api/sim/scenarios")
    def sim_scenarios():
        return scenario_list()

    @app.get("/api/sim/runs")
    def sim_runs(machine_id: str | None = None):
        return manager.list_runs(machine_id)

    @app.post("/api/sim/start", status_code=201)
    def sim_start(request: SimStartRequest):
        return sim_call(manager.start, request.machine_id, request.scenario, seed=request.seed, speed=request.speed,
                        start_mode=request.start_mode, onset_s=request.onset_s)

    @app.post("/api/sim/runs/{run_id}/pause")
    def sim_pause(run_id: int):
        return sim_call(manager.pause, run_id)

    @app.post("/api/sim/runs/{run_id}/resume")
    def sim_resume(run_id: int):
        return sim_call(manager.resume, run_id)

    @app.post("/api/sim/runs/{run_id}/stop")
    def sim_stop(run_id: int):
        return sim_call(manager.stop, run_id)

    @app.post("/api/sim/runs/{run_id}/speed")
    def sim_speed(run_id: int, request: SpeedRequest):
        return sim_call(manager.set_speed, run_id, request.speed)

    @app.post("/api/sim/runs/{run_id}/advance")
    def sim_advance(run_id: int, request: AdvanceRequest):
        return sim_call(manager.advance, run_id, request.seconds)

    @app.post("/api/sim/runs/{run_id}/mode")
    def sim_mode(run_id: int, request: ModeRequest):
        return sim_call(manager.set_mode, run_id, request.mode)

    @app.post("/api/sim/runs/{run_id}/remove-effect")
    def sim_remove_effect(run_id: int):
        return sim_call(manager.remove_effect, run_id)

    @app.post("/api/demo/reset")
    def demo_reset(request: ResetRequest):
        if not request.confirm:
            raise HTTPException(400, "Demo sıfırlaması için onay gerekli.")
        manager.forget_all()
        with db.write() as conn:
            counts = demo.reset_demo(conn)
        start_demo_runs()
        return {"deleted": counts, "message": "Demo verisi sıfırlandı. Kullanıcı verileri korunuyor."}

    # -- CSV ve dışa aktarım -------------------------------------------------
    @app.post("/api/csv/preview")
    def csv_preview(request: CsvRequest):
        with db.read() as conn:
            report = csv_io.validate_csv(conn, request.content, create_missing_machines=request.create_missing_machines)
        return csv_io.public_report(report)

    @app.post("/api/csv/import")
    def csv_import(request: CsvRequest):
        try:
            with db.write() as conn:
                return csv_io.import_csv(conn, request.content, request.filename,
                                         create_missing_machines=request.create_missing_machines)
        except csv_io.CsvValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": str(exc), "report": exc.report})

    @app.get("/api/csv/samples")
    def csv_samples():
        return [{"name": p.name, "size": p.stat().st_size} for p in sorted(SAMPLES_DIR.glob("*.csv"))]

    @app.get("/api/csv/samples/{name}")
    def csv_sample(name: str):
        path = SAMPLES_DIR / name
        if path.parent != SAMPLES_DIR or path.suffix != ".csv" or not path.exists():
            raise HTTPException(404, "Örnek dosya bulunamadı.")
        return FileResponse(path, media_type="text/csv", filename=name)

    @app.get("/api/export/telemetry.csv")
    def export_telemetry(machine_id: str | None = None, start: str | None = None, end: str | None = None):
        start_iso, end_iso = parse_range(start, end)
        with db.read() as conn:
            text = csv_io.export_telemetry(conn, machine_id, start_iso, end_iso)
        return _csv_response(text, f"olcumler_{machine_id or 'tumu'}.csv")

    @app.get("/api/export/alerts.csv")
    def export_alerts(machine_id: str | None = None, kind: str | None = None, level: str | None = None,
                      review_status: str | None = None, measurement_status: str | None = None,
                      start: str | None = None, end: str | None = None):
        filters = alert_filters(machine_id, kind, level, review_status, measurement_status, start, end)
        with db.read() as conn:
            text = csv_io.export_alerts(alerts.list_alerts(conn, filters, limit=100000))
        return _csv_response(text, "uyarilar.csv")

    # -- ön yüz --------------------------------------------------------------
    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:
        @app.get("/")
        def no_frontend():
            return JSONResponse({"detail": "Ön yüz derlenmemiş. 'cd frontend && npm run build' çalıştırın."})

    return app


def _csv_response(text: str, filename: str) -> Response:
    return Response(
        content=text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _translate(error_type: str, message: str) -> str:
    known = {
        "missing": "zorunlu alan eksik",
        "string_type": "metin olmalı",
        "int_parsing": "tam sayı olmalı",
        "float_parsing": "sayı olmalı",
        "bool_parsing": "evet/hayır değeri olmalı",
        "greater_than": "sıfırdan büyük olmalı",
        "json_invalid": "JSON biçimi bozuk",
        "model_attributes_type": "nesne olmalı",
        "dict_type": "nesne olmalı",
    }
    return known.get(error_type, message)


async def _background_loop(manager: SimulationManager) -> None:
    last = time.monotonic()
    while True:
        await asyncio.sleep(0.5)
        now = time.monotonic()
        try:
            await asyncio.to_thread(manager.tick, now - last)
        except Exception:  # döngü durmasın; hata kaydedilir
            log.exception("Simülasyon adımı başarısız")
        last = now
