"""
Processing algorithm handlers — list, help, execute algorithms.
"""


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
        result = processing.run(algorithm, parameters)
        return {
            "algorithm": algorithm,
            "result": {k: str(v) for k, v in result.items()},
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
    })
