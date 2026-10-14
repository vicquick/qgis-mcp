"""
Background jobs and scratch-layer checkpoints.

Jobs: a call that would block the socket for minutes returns a job id at once
instead.
  - Processing runs as a QgsProcessingAlgRunnerTask on a worker thread, so
    QGIS stays usable and get_job can be polled while it runs. Outputs are
    loaded into the project on the main thread when the task finishes.
  - Layout and atlas exports must render on the main thread. They are queued
    on the event loop: the call returns before the export starts, QGIS is busy
    while it runs, and get_job reports the result afterwards.

Checkpoints: project revert restores everything saved in the .qgz, but memory
layers keep their features only in RAM, so a revert loses them. A checkpoint
copies fields, features, style and filter of memory layers so they can be put
back. Nothing else is snapshotted; nothing runs unless these tools are called.
Both stores live in module state: a plugin reload clears them.
"""

import itertools
import os
import time

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFeature,
    QgsFields,
    QgsGeometry,
    QgsLayoutExporter,
    QgsMapLayerStyle,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingUtils,
    QgsProject,
    QgsRenderContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QTimer

_JOBS: dict = {}
_JOB_SEQ = itertools.count(1)
_KEEP_JOBS = 50

_CHECKPOINTS: dict = {}
_CP_SEQ = itertools.count(1)
_KEEP_CHECKPOINTS = 10
_MAX_CHECKPOINT_FEATURES = 500_000

_LAYER_OUTPUTS = ("QgsProcessingOutputVectorLayer", "QgsProcessingOutputRasterLayer",
                  "QgsProcessingOutputMapLayer", "QgsProcessingOutputPointCloudLayer",
                  "QgsProcessingOutputVectorTileLayer")


def _no_threading(alg) -> bool:
    flag = getattr(getattr(Qgis, "ProcessingAlgorithmFlag", None), "NoThreading", None)
    if flag is None:
        from qgis.core import QgsProcessingAlgorithm
        flag = getattr(QgsProcessingAlgorithm, "FlagNoThreading", None)
    try:
        return bool(flag is not None and alg.flags() & flag)
    except TypeError:
        return False


def _prune(store: dict, keep: int):
    finished = [k for k, v in store.items() if v.get("state") not in ("queued", "running")]
    for k in finished[:-keep] if len(finished) > keep else []:
        store.pop(k, None)


def _public(job: dict) -> dict:
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    if job.get("started") and job.get("state") in ("queued", "running"):
        out["elapsed_s"] = round(time.time() - job["started"], 1)
    return out


class _JobFeedback(QgsProcessingFeedback):
    """Keeps the algorithm's errors and warnings for get_job. Called on the
    worker thread; appending to a list is safe under the GIL."""

    def __init__(self, notices):
        super().__init__()
        self._notices = notices

    def _keep(self, text):
        if len(self._notices) < 20:
            self._notices.append(str(text)[:300])

    def reportError(self, error, fatalError=False):
        self._keep(error)
        super().reportError(error, fatalError)

    def pushWarning(self, warning):
        self._keep(warning)
        super().pushWarning(warning)


def _pdf_settings(dpi):
    s = QgsLayoutExporter.PdfExportSettings()
    s.dpi = dpi
    s.rasterizeWholeImage = False
    # forceVectorOutput drops paint effects (drop shadows) without a warning;
    # AlwaysText keeps text as text anyway.
    s.forceVectorOutput = False
    try:
        s.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    except AttributeError:
        s.textRenderFormat = QgsRenderContext.TextFormatAlwaysText
    return s


def register(server):
    s = server

    # ── Jobs ──────────────────────────────────────────────────────

    def _load_outputs(alg, results, context):
        added = []
        project = QgsProject.instance()
        store = context.temporaryLayerStore()
        for out in alg.outputDefinitions():
            if type(out).__name__ not in _LAYER_OUTPUTS:
                continue
            value = results.get(out.name())
            if not isinstance(value, str) or not value:
                continue
            layer = QgsProcessingUtils.mapLayerFromString(value, context)
            if layer is None:
                continue
            if store.mapLayer(layer.id()) is not None:
                layer = store.takeMapLayer(layer)
            if layer is None or project.mapLayer(layer.id()) is not None:
                continue
            if layer.name() in ("", "output", "OUTPUT") or layer.name() == layer.id():
                layer.setName(out.description() or alg.displayName())
            project.addMapLayer(layer)
            added.append({"id": layer.id(), "name": layer.name()})
        return added

    def _start_processing(job, algorithm, parameters, load_outputs):
        registry = QgsApplication.processingRegistry()
        alg = registry.algorithmById(algorithm)
        if alg is None:
            raise RuntimeError(f"Algorithm not found: {algorithm}")
        if _no_threading(alg):
            raise RuntimeError(
                f"{algorithm} cannot run on a background thread (NoThreading); "
                "use execute_processing instead")
        known = {d.name() for d in alg.parameterDefinitions()}
        ignored = sorted(k for k in (parameters or {}) if k not in known)
        if ignored:
            job["ignored_parameters"] = ignored
            job["valid_parameters"] = sorted(known)

        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        feedback = _JobFeedback(job["notices"])
        task = QgsProcessingAlgRunnerTask(alg, parameters or {}, context, feedback)

        def on_progress(p):
            job["progress"] = round(float(p), 1)

        def on_executed(ok, results):
            # Emitted on the main thread once the worker is done.
            job["finished"] = time.time()
            job["duration_s"] = round(job["finished"] - job["started"], 1)
            job["_task"] = None
            if feedback.isCanceled():
                job["state"] = "canceled"
                return
            if not ok:
                job["state"] = "failed"
                job["error"] = "algorithm reported failure; see notices"
                return
            job["result"] = {k: str(v) for k, v in (results or {}).items()}
            if load_outputs:
                try:
                    job["layers_added"] = _load_outputs(alg, results or {}, context)
                except Exception as e:  # results stay reported even if loading fails
                    job["load_error"] = str(e)
            job["progress"] = 100.0
            job["state"] = "done"

        feedback.progressChanged.connect(on_progress)
        task.executed.connect(on_executed)
        job.update(_task=task, _context=context, _feedback=feedback, state="running",
                   progress=0.0, algorithm=algorithm)
        QgsApplication.taskManager().addTask(task)

    def _start_export(job, kind, layout_name, path, dpi):
        layout = QgsProject.instance().layoutManager().layoutByName(layout_name)
        if layout is None:
            raise RuntimeError(f"Layout not found: {layout_name}")
        if kind.startswith("atlas") and not layout.atlas().enabled():
            raise RuntimeError("Atlas is not enabled on this layout")
        folder = path if kind == "atlas_pdfs" else os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        job.update(state="queued", layout=layout_name, path=path)

        def run():
            job["state"] = "running"
            job["started"] = time.time()
            try:
                lay = QgsProject.instance().layoutManager().layoutByName(layout_name)
                if lay is None:
                    raise RuntimeError(f"Layout not found: {layout_name}")
                if kind == "layout_pdf":
                    res = QgsLayoutExporter(lay).exportToPdf(path, _pdf_settings(dpi))
                    err = ""
                elif kind == "layout_image":
                    st = QgsLayoutExporter.ImageExportSettings()
                    st.dpi = dpi
                    res = QgsLayoutExporter(lay).exportToImage(path, st)
                    err = ""
                elif kind == "atlas_pdf":
                    res, err = QgsLayoutExporter.exportToPdf(lay.atlas(), path, _pdf_settings(dpi))
                else:  # atlas_pdfs: one file per page, named by the atlas filename expression
                    res, err = QgsLayoutExporter.exportToPdfs(lay.atlas(), path, _pdf_settings(dpi))
                ok = res == QgsLayoutExporter.ExportResult.Success
                job["state"] = "done" if ok else "failed"
                if not ok:
                    job["error"] = f"export result {res} {err}".strip()
                elif os.path.isfile(path):
                    job["size_mb"] = round(os.path.getsize(path) / 1e6, 1)
            except Exception as e:
                job["state"] = "failed"
                job["error"] = str(e)
            job["finished"] = time.time()
            job["duration_s"] = round(job["finished"] - job["started"], 1)

        # The reply to start_job goes out first; the export runs on the next
        # pass of the event loop.
        QTimer.singleShot(0, run)

    def start_job(kind: str = "processing", algorithm: str = None, parameters: dict = None,
                  load_outputs: bool = True, layout_name: str = None, path: str = None,
                  dpi: int = 300, **_):
        """Start a long-running job and return its id at once; poll with get_job.

        kind=processing: algorithm + parameters, run on a worker thread;
            layer outputs are added to the project when done (load_outputs).
        kind=layout_pdf | layout_image: layout_name + path.
        kind=atlas_pdf: one PDF with every atlas page; atlas_pdfs: path is a
            folder, one PDF per page. Exports render on the main thread, so
            QGIS is busy until they finish; PDFs keep text as text and paint
            effects (forceVectorOutput off).
        """
        job_id = f"job{next(_JOB_SEQ)}"
        job = {"id": job_id, "kind": kind, "state": "queued", "started": time.time(),
               "notices": []}
        if kind == "processing":
            if not algorithm:
                raise RuntimeError("kind=processing needs algorithm")
            _start_processing(job, algorithm, parameters, load_outputs)
        elif kind in ("layout_pdf", "layout_image", "atlas_pdf", "atlas_pdfs"):
            if not layout_name or not path:
                raise RuntimeError(f"kind={kind} needs layout_name and path")
            _start_export(job, kind, layout_name, path, int(dpi))
        else:
            raise RuntimeError("kind must be processing, layout_pdf, layout_image, "
                               "atlas_pdf or atlas_pdfs")
        _JOBS[job_id] = job
        _prune(_JOBS, _KEEP_JOBS)
        return _public(job)

    def get_job(job_id: str, **_):
        """State of one job: queued | running | done | failed | canceled, with
        progress, result, layers_added and notices."""
        job = _JOBS.get(job_id)
        if job is None:
            raise RuntimeError(f"No job {job_id} (jobs are cleared by a plugin reload)")
        return _public(job)

    def list_jobs(**_):
        """All jobs of this QGIS session, newest last."""
        return {"jobs": [_public(j) for j in _JOBS.values()]}

    def cancel_job(job_id: str, **_):
        """Cancel a running Processing job. Exports cannot be interrupted once
        they started rendering."""
        job = _JOBS.get(job_id)
        if job is None:
            raise RuntimeError(f"No job {job_id}")
        if job["state"] not in ("queued", "running"):
            return {"id": job_id, "state": job["state"], "note": "already finished"}
        fb = job.get("_feedback")
        if fb is None:
            return {"id": job_id, "state": job["state"],
                    "note": "exports cannot be canceled"}
        fb.cancel()
        task = job.get("_task")
        if task is not None:
            try:
                task.cancel()
            except RuntimeError:  # C++ task already deleted
                pass
        return {"id": job_id, "state": "canceling"}

    # ── Checkpoints ───────────────────────────────────────────────

    def _memory_layers(layer_ids):
        out = []
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() != Qgis.LayerType.Vector or layer.providerType() != "memory":
                continue
            if layer_ids and layer.id() not in layer_ids:
                continue
            out.append(layer)
        return out

    def create_checkpoint(name: str = None, layer_ids: list = None, **_):
        """Copy memory (scratch) layers — fields, features, style, filter — so
        restore_checkpoint can put them back. Saved layers need no checkpoint:
        reverting the project restores them; memory layers it cannot."""
        layers = _memory_layers(layer_ids)
        if layer_ids:
            missing = sorted(set(layer_ids) - {l.id() for l in layers})
            if missing:
                raise RuntimeError(f"Not memory layers or not found: {missing}")
        total = sum(l.featureCount() for l in layers)
        if total > _MAX_CHECKPOINT_FEATURES:
            raise RuntimeError(f"{total} features exceed the checkpoint limit of "
                               f"{_MAX_CHECKPOINT_FEATURES}; save those layers to a file")
        snap = []
        for layer in layers:
            style = QgsMapLayerStyle()
            style.readFromLayer(layer)
            snap.append({
                "id": layer.id(),
                "name": layer.name(),
                "uri": layer.dataProvider().dataSourceUri(),
                "fields": QgsFields(layer.fields()),
                "features": [(QgsGeometry(f.geometry()), f.attributes())
                             for f in layer.getFeatures()],
                "style": style.xmlData(),
                "subset": layer.subsetString(),
            })
        cp_id = f"cp{next(_CP_SEQ)}"
        _CHECKPOINTS[cp_id] = {"id": cp_id, "name": name or cp_id, "created": time.time(),
                               "state": "saved", "_layers": snap}
        while len(_CHECKPOINTS) > _KEEP_CHECKPOINTS:
            _CHECKPOINTS.pop(next(iter(_CHECKPOINTS)))
        return {"checkpoint": cp_id, "name": name or cp_id,
                "layers": [{"id": x["id"], "name": x["name"], "features": len(x["features"])}
                           for x in snap]}

    def list_checkpoints(**_):
        """Checkpoints of this QGIS session (cleared by a plugin reload)."""
        return {"checkpoints": [{
            "id": c["id"], "name": c["name"],
            "created": time.strftime("%H:%M:%S", time.localtime(c["created"])),
            "layers": [{"id": x["id"], "name": x["name"], "features": len(x["features"])}
                       for x in c["_layers"]],
        } for c in _CHECKPOINTS.values()]}

    def _refill(layer, snap):
        if layer.isEditable():
            layer.rollBack()
        pr = layer.dataProvider()
        pr.truncate()
        want = snap["fields"]
        have = layer.fields()
        drop = [i for i, f in enumerate(have) if want.indexFromName(f.name()) < 0]
        if drop:
            pr.deleteAttributes(drop)
        add = [f for f in want if layer.fields().indexFromName(f.name()) < 0]
        if add:
            pr.addAttributes(add)
        layer.updateFields()
        fields = layer.fields()
        feats = []
        for geom, attrs in snap["features"]:
            f = QgsFeature(fields)
            if geom is not None and not geom.isNull():
                f.setGeometry(QgsGeometry(geom))
            for i, value in enumerate(attrs):
                idx = fields.indexFromName(want.at(i).name())
                if idx >= 0:
                    f.setAttribute(idx, value)
            feats.append(f)
        pr.addFeatures(feats)
        layer.updateExtents()

    def restore_checkpoint(checkpoint: str, **_):
        """Put memory layers back to a checkpoint: features, fields, style and
        filter. A layer removed since is re-created (with a new id). Feature
        ids are renumbered."""
        cp = _CHECKPOINTS.get(checkpoint)
        if cp is None:
            raise RuntimeError(f"No checkpoint {checkpoint}")
        project = QgsProject.instance()
        restored = []
        for snap in cp["_layers"]:
            layer = project.mapLayer(snap["id"])
            recreated = layer is None
            if recreated:
                layer = QgsVectorLayer(snap["uri"], snap["name"], "memory")
                if not layer.isValid():
                    restored.append({"name": snap["name"], "error": "could not re-create"})
                    continue
            _refill(layer, snap)
            layer.setName(snap["name"])
            QgsMapLayerStyle(snap["style"]).writeToLayer(layer)
            layer.setSubsetString(snap["subset"])
            if recreated:
                project.addMapLayer(layer)
            layer.triggerRepaint()
            restored.append({"id": layer.id(), "name": snap["name"],
                             "features": len(snap["features"]), "recreated": recreated})
        return {"checkpoint": checkpoint, "layers": restored}

    def delete_checkpoint(checkpoint: str, **_):
        """Drop a checkpoint and free its memory."""
        if _CHECKPOINTS.pop(checkpoint, None) is None:
            raise RuntimeError(f"No checkpoint {checkpoint}")
        return {"deleted": checkpoint}

    s._HANDLERS.update({
        "start_job": start_job,
        "get_job": get_job,
        "list_jobs": list_jobs,
        "cancel_job": cancel_job,
        "create_checkpoint": create_checkpoint,
        "list_checkpoints": list_checkpoints,
        "restore_checkpoint": restore_checkpoint,
        "delete_checkpoint": delete_checkpoint,
    })
