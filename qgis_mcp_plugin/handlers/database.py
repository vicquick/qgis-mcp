"""
Database connection handlers — list connections, add DB layers, execute SQL, list tables.
"""

from qgis.core import (
    Qgis,
    QgsDataSourceUri,
    QgsProject,
    QgsSettings,
    QgsVectorLayer,
)


def register(server):
    """Register database handlers."""
    s = server

    def list_db_connections(**_):
        """List configured database connections (PostgreSQL, GeoPackage, SpatiaLite, MSSQL, Oracle)."""
        settings = QgsSettings()
        connections = []

        # PostgreSQL / PostGIS
        settings.beginGroup("PostgreSQL/connections")
        for name in settings.childGroups():
            settings.beginGroup(name)
            connections.append({
                "name": name,
                "provider": "postgres",
                "host": settings.value("host", ""),
                "database": settings.value("database", ""),
                "port": settings.value("port", "5432"),
            })
            settings.endGroup()
        settings.endGroup()

        # GeoPackage / OGR
        settings.beginGroup("ogr/connections")
        for name in settings.childGroups():
            settings.beginGroup(name)
            connections.append({
                "name": name,
                "provider": "ogr",
                "host": "",
                "database": settings.value("path", ""),
                "port": "",
            })
            settings.endGroup()
        settings.endGroup()

        # SpatiaLite
        settings.beginGroup("SpatiaLite/connections")
        for name in settings.childGroups():
            settings.beginGroup(name)
            connections.append({
                "name": name,
                "provider": "spatialite",
                "host": "",
                "database": settings.value("sqlitepath", ""),
                "port": "",
            })
            settings.endGroup()
        settings.endGroup()

        # MS SQL Server
        settings.beginGroup("MSSQL/connections")
        for name in settings.childGroups():
            settings.beginGroup(name)
            connections.append({
                "name": name,
                "provider": "mssql",
                "host": settings.value("host", ""),
                "database": settings.value("database", ""),
                "port": settings.value("port", ""),
            })
            settings.endGroup()
        settings.endGroup()

        # Oracle
        settings.beginGroup("Oracle/connections")
        for name in settings.childGroups():
            settings.beginGroup(name)
            connections.append({
                "name": name,
                "provider": "oracle",
                "host": settings.value("host", ""),
                "database": settings.value("database", ""),
                "port": settings.value("port", "1521"),
            })
            settings.endGroup()
        settings.endGroup()

        return connections

    def add_db_layer(connection_name: str, schema: str, table: str,
                     geometry_column: str, provider: str = "postgres",
                     name: str = None, sql: str = None, **_):
        """Add a database layer to the project using a named connection.

        provider: postgres, spatialite, mssql, oracle.
        sql: optional SQL WHERE clause to filter.
        """
        settings = QgsSettings()
        display_name = name or table

        if provider == "postgres":
            prefix = f"PostgreSQL/connections/{connection_name}"
            host = settings.value(f"{prefix}/host", "")
            port = settings.value(f"{prefix}/port", "5432")
            database = settings.value(f"{prefix}/database", "")
            username = settings.value(f"{prefix}/username", "")
            password = settings.value(f"{prefix}/password", "")

            if not host or not database:
                raise RuntimeError(
                    f"PostgreSQL connection '{connection_name}' not found or incomplete"
                )

            uri = QgsDataSourceUri()
            uri.setConnection(host, str(port), database, username, password)
            uri.setDataSource(schema, table, geometry_column, sql or "")
            layer = QgsVectorLayer(uri.uri(False), display_name, "postgres")

        elif provider == "spatialite":
            prefix = f"SpatiaLite/connections/{connection_name}"
            db_path = settings.value(f"{prefix}/sqlitepath", "")
            if not db_path:
                raise RuntimeError(f"SpatiaLite connection '{connection_name}' not found")

            uri = QgsDataSourceUri()
            uri.setDatabase(db_path)
            uri.setDataSource(schema, table, geometry_column, sql or "")
            layer = QgsVectorLayer(uri.uri(False), display_name, "spatialite")

        elif provider == "mssql":
            prefix = f"MSSQL/connections/{connection_name}"
            host = settings.value(f"{prefix}/host", "")
            database = settings.value(f"{prefix}/database", "")
            if not host or not database:
                raise RuntimeError(f"MSSQL connection '{connection_name}' not found")

            uri = QgsDataSourceUri()
            uri.setConnection(host, "", database, "", "")
            uri.setDataSource(schema, table, geometry_column, sql or "")
            layer = QgsVectorLayer(uri.uri(False), display_name, "mssql")

        else:
            raise RuntimeError(f"Unsupported provider: {provider}")

        if not layer.isValid():
            raise RuntimeError(
                f"Invalid layer from {provider} connection '{connection_name}': "
                f"{schema}.{table}"
            )

        QgsProject.instance().addMapLayer(layer)
        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": s.layer_type_str(layer),
            "feature_count": layer.featureCount(),
        }

    def execute_sql(connection_name: str, sql: str, provider: str = "postgres",
                    limit: int = 100, **_):
        """Execute SQL on a database connection and return results.

        Returns rows as list of dicts. Limited to prevent huge responses.
        """
        settings = QgsSettings()

        if provider == "postgres":
            prefix = f"PostgreSQL/connections/{connection_name}"
            host = settings.value(f"{prefix}/host", "")
            port = settings.value(f"{prefix}/port", "5432")
            database = settings.value(f"{prefix}/database", "")
            username = settings.value(f"{prefix}/username", "")
            password = settings.value(f"{prefix}/password", "")

            if not host or not database:
                raise RuntimeError(f"PostgreSQL connection '{connection_name}' not found")

            uri = QgsDataSourceUri()
            uri.setConnection(host, str(port), database, username, password)

            # Use a memory layer with SQL query to get results
            query_uri = QgsDataSourceUri()
            query_uri.setConnection(host, str(port), database, username, password)
            query_uri.setDataSource("", f"({sql})", None, "", "ctid")

            layer = QgsVectorLayer(query_uri.uri(False), "sql_query", "postgres")
            if not layer.isValid():
                raise RuntimeError(f"SQL query failed or returned no geometry column")

            rows = []
            for i, feat in enumerate(layer.getFeatures()):
                if i >= limit:
                    break
                row = {}
                for field in layer.fields():
                    val = feat.attribute(field.name())
                    if not isinstance(val, (str, int, float, bool, type(None))):
                        val = str(val)
                    row[field.name()] = val
                rows.append(row)

            return {
                "connection": connection_name,
                "row_count": len(rows),
                "fields": [f.name() for f in layer.fields()],
                "rows": rows,
            }
        else:
            raise RuntimeError(
                f"execute_sql currently supports postgres. Provider: {provider}"
            )

    def list_db_tables(connection_name: str, provider: str = "postgres",
                       schema: str = "public", **_):
        """List tables and views in a database connection."""
        settings = QgsSettings()

        if provider == "postgres":
            prefix = f"PostgreSQL/connections/{connection_name}"
            host = settings.value(f"{prefix}/host", "")
            port = settings.value(f"{prefix}/port", "5432")
            database = settings.value(f"{prefix}/database", "")
            username = settings.value(f"{prefix}/username", "")
            password = settings.value(f"{prefix}/password", "")

            if not host or not database:
                raise RuntimeError(f"PostgreSQL connection '{connection_name}' not found")

            uri = QgsDataSourceUri()
            uri.setConnection(host, str(port), database, username, password)

            from qgis.core import QgsProviderRegistry
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            if not md:
                raise RuntimeError("PostgreSQL provider not available")

            conn = md.createConnection(uri.uri(False), {})
            if not conn:
                raise RuntimeError(f"Failed to connect to {connection_name}")

            tables = []
            for table_info in conn.tables(schema):
                tables.append({
                    "schema": schema,
                    "name": table_info.tableName(),
                    "geometry_column": table_info.geometryColumn(),
                    "type": str(table_info.geometryColumnTypes()),
                })
            return {"connection": connection_name, "schema": schema, "tables": tables}
        else:
            raise RuntimeError(
                f"list_db_tables currently supports postgres. Provider: {provider}"
            )

    def get_db_table_info(connection_name: str, schema: str, table: str,
                          provider: str = "postgres", **_):
        """Get detailed table info: columns, types, geometry column, geometry type, SRID, row count.

        Currently supports PostgreSQL/PostGIS.
        """
        settings = QgsSettings()

        if provider == "postgres":
            prefix = f"PostgreSQL/connections/{connection_name}"
            host = settings.value(f"{prefix}/host", "")
            port = settings.value(f"{prefix}/port", "5432")
            database = settings.value(f"{prefix}/database", "")
            username = settings.value(f"{prefix}/username", "")
            password = settings.value(f"{prefix}/password", "")

            if not host or not database:
                raise RuntimeError(f"PostgreSQL connection '{connection_name}' not found")

            uri = QgsDataSourceUri()
            uri.setConnection(host, str(port), database, username, password)

            from qgis.core import QgsProviderRegistry
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            if not md:
                raise RuntimeError("PostgreSQL provider not available")

            conn = md.createConnection(uri.uri(False), {})
            if not conn:
                raise RuntimeError(f"Failed to connect to {connection_name}")

            # Find the table in the connection
            table_info = None
            for ti in conn.tables(schema):
                if ti.tableName() == table:
                    table_info = ti
                    break

            if not table_info:
                raise RuntimeError(f"Table not found: {schema}.{table}")

            # Get column info by loading the table as a layer
            uri2 = QgsDataSourceUri()
            uri2.setConnection(host, str(port), database, username, password)
            geom_col = table_info.geometryColumn() or ""
            uri2.setDataSource(schema, table, geom_col if geom_col else None, "", "")
            temp_layer = QgsVectorLayer(uri2.uri(False), "temp", "postgres")

            columns = []
            if temp_layer.isValid():
                for field in temp_layer.fields():
                    columns.append({
                        "name": field.name(),
                        "type": field.typeName(),
                        "length": field.length(),
                        "precision": field.precision(),
                    })

            result = {
                "connection": connection_name,
                "schema": schema,
                "table": table,
                "geometry_column": geom_col or None,
                "geometry_type": str(table_info.geometryColumnTypes()) if geom_col else None,
                "columns": columns,
            }

            if temp_layer.isValid():
                result["row_count"] = temp_layer.featureCount()
                result["crs"] = temp_layer.crs().authid()

            return result
        else:
            raise RuntimeError(
                f"get_db_table_info currently supports postgres. Provider: {provider}"
            )

    s._HANDLERS.update({
        "list_db_connections": list_db_connections,
        "add_db_layer": add_db_layer,
        "execute_sql": execute_sql,
        "list_db_tables": list_db_tables,
        "get_db_table_info": get_db_table_info,
    })
