"""
Processing algorithm handlers — list, help, search, execute algorithms.
"""

# search_algorithms' word index over every registered algorithm.
_ALG_INDEX: dict = {}


def register(server):
    """Register processing handlers."""
    s = server

    def list_algorithms(provider: str = None, keyword: str = None, limit: int = 50, **_):
        """List available processing algorithms. Filter by provider name or keyword.

        provider: native, qgis, gdal, grass, saga, etc.
        keyword: search string to match algorithm ID or display name.
        """
        import processing
        from qgis.core import QgsApplication

        registry = QgsApplication.processingRegistry()
        algorithms = []

        for alg in registry.algorithms():
            # Filter by provider
            if provider and alg.provider().id().lower() != provider.lower():
                continue

            # Filter by keyword
            if keyword:
                kw = keyword.lower()
                if (kw not in alg.id().lower()
                        and kw not in alg.displayName().lower()
                        and kw not in alg.shortDescription().lower()):
                    continue

            algorithms.append({
                "id": alg.id(),
                "name": alg.displayName(),
                "provider": alg.provider().id(),
                "short_description": alg.shortDescription(),
            })

            if len(algorithms) >= limit:
                break

        return {"count": len(algorithms), "algorithms": algorithms}

    def algorithm_help(algorithm: str, **_):
        """Get detailed help for a specific processing algorithm, including parameters."""
        import processing
        from qgis.core import QgsApplication

        registry = QgsApplication.processingRegistry()
        alg = registry.algorithmById(algorithm)
        if not alg:
            raise RuntimeError(f"Algorithm not found: {algorithm}")

        params = []
        for param in alg.parameterDefinitions():
            params.append({
                "name": param.name(),
                "description": param.description(),
                "type": type(param).__name__,
                "default": str(param.defaultValue()) if param.defaultValue() is not None else None,
                "optional": not (param.flags() & param.Flag.FlagOptional == 0),
            })

        outputs = []
        for out in alg.outputDefinitions():
            outputs.append({
                "name": out.name(),
                "description": out.description(),
                "type": type(out).__name__,
            })

        return {
            "id": alg.id(),
            "name": alg.displayName(),
            "provider": alg.provider().id(),
            "short_description": alg.shortDescription(),
            "help_string": alg.shortHelpString(),
            "parameters": params,
            "outputs": outputs,
        }

    def execute_processing(algorithm: str, parameters: dict, **_):
        """Run a processing algorithm with the given parameters.

        Parameters should reference layers by ID, file paths, or values as required.
        Returns algorithm outputs as strings.
        """
        import processing
        from qgis.core import QgsApplication
        # processing.run() drops parameter names the algorithm doesn't define
        # and runs on defaults, so a misspelt key (INPUT_LAYER for INPUT)
        # silently produced a different result. Report them instead.
        ignored = []
        alg = QgsApplication.processingRegistry().algorithmById(algorithm)
        if alg is not None:
            known = {d.name() for d in alg.parameterDefinitions()}
            ignored = sorted(k for k in (parameters or {}) if k not in known)
        result = processing.run(algorithm, parameters)
        out = {
            "algorithm": algorithm,
            "result": {k: str(v) for k, v in result.items()},
        }
        if ignored:
            out["ignored_parameters"] = ignored
            out["valid_parameters"] = sorted(known)
        return out

    def search_algorithms(query: str, limit: int = 10, **_):
        """Find Processing algorithms by what they do ("points in polygon",
        "raster to vector", "dissolve by attribute"). Ranks id, name, tags,
        group, descriptions and parameter names; returns the parameters too so
        execute_processing can follow without an algorithm_help call."""
        import re
        from qgis.core import QgsApplication

        registry = QgsApplication.processingRegistry()
        algs = registry.algorithms()
        # The index is rebuilt only when the provider set changes (plugins
        # adding providers); otherwise every search reuses it.
        if _ALG_INDEX.get("count") != len(algs):
            entries = []
            for alg in algs:
                try:
                    params = [p.name() for p in alg.parameterDefinitions()]
                    entries.append({
                        "id": alg.id(),
                        "name": alg.displayName(),
                        "group": alg.group(),
                        "summary": alg.shortDescription() or "",
                        "params": params,
                        "f": (
                            (alg.id() + " " + alg.displayName()).lower(),
                            (" ".join(alg.tags()) + " " + alg.group()).lower(),
                            (alg.shortDescription() + " " + alg.shortHelpString()[:600]
                             + " " + " ".join(params)).lower(),
                        ),
                    })
                except Exception:
                    continue
            _ALG_INDEX.clear()
            _ALG_INDEX.update(count=len(algs), entries=entries)

        words = []
        for w in re.split(r"[^0-9a-zäöüß]+", (query or "").lower()):
            if len(w) > 3 and w.endswith("s"):
                w = w[:-1]
            if len(w) > 1:
                words.append(w)
        if not words:
            raise RuntimeError("query needs at least one word")
        hits = []
        for e in _ALG_INDEX["entries"]:
            score = sum(max((wt for wt, f in zip((3, 2, 1), e["f"]) if w in f), default=0)
                        for w in words)
            if score:
                # Prefer native/qgis algorithms on ties: no external binaries.
                native = e["id"].startswith(("native:", "qgis:"))
                hits.append((score, native, e))
        hits.sort(key=lambda h: (-h[0], not h[1], h[2]["id"]))
        limit = max(1, min(int(limit or 10), 40))
        return {
            "matches": len(hits),
            "algorithms": [{k: e[k] for k in ("id", "name", "group", "summary", "params")}
                           for _, _, e in hits[:limit]],
        }

    def list_processing_providers(**_):
        """List available processing providers (native, GDAL, GRASS, etc.)."""
        from qgis.core import QgsApplication
        registry = QgsApplication.processingRegistry()
        providers = []
        for provider in registry.providers():
            providers.append({
                "id": provider.id(),
                "name": provider.name(),
                "algorithm_count": len(provider.algorithms()),
            })
        return {"providers": providers}

    s._HANDLERS.update({
        "list_algorithms": list_algorithms,
        "algorithm_help": algorithm_help,
        "execute_processing": execute_processing,
        "list_processing_providers": list_processing_providers,
        "search_algorithms": search_algorithms,
    })
