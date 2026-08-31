"""
Spatial bookmark handlers — list, add, navigate, delete.
"""

from qgis.core import (
    QgsBookmark,
    QgsBookmarkManager,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
)


def register(server):
    """Register bookmark handlers."""
    s = server

    def list_bookmarks(**_):
        """List all spatial bookmarks (project and application-level)."""
        result = []

        # Project bookmarks
        proj_manager = QgsProject.instance().bookmarkManager()
        for bm in proj_manager.bookmarks():
            extent = bm.extent()
            result.append({
                "id": bm.id(),
                "name": bm.name(),
                "group": bm.group(),
                "extent": s.extent_to_dict(extent),
                "crs": extent.crs().authid() if hasattr(extent, 'crs') else "",
                "scope": "project",
            })

        # Application-level bookmarks
        from qgis.core import QgsApplication
        app_manager = QgsApplication.bookmarkManager()
        for bm in app_manager.bookmarks():
            extent = bm.extent()
            result.append({
                "id": bm.id(),
                "name": bm.name(),
                "group": bm.group(),
                "extent": s.extent_to_dict(extent),
                "crs": extent.crs().authid() if hasattr(extent, 'crs') else "",
                "scope": "application",
            })

        return {"bookmarks": result, "count": len(result)}

    def add_bookmark(name: str, xmin: float, ymin: float, xmax: float, ymax: float,
                     crs: str = "EPSG:4326", group: str = "", scope: str = "project", **_):
        """Create a spatial bookmark from an extent and CRS.

        scope: 'project' (saved in project file) or 'application' (global).
        """
        crs_obj = QgsCoordinateReferenceSystem(crs)
        if not crs_obj.isValid():
            raise RuntimeError(f"Invalid CRS: {crs}")

        rect = QgsRectangle(xmin, ymin, xmax, ymax)
        ref_rect = QgsReferencedRectangle(rect, crs_obj)

        bookmark = QgsBookmark()
        bookmark.setName(name)
        bookmark.setGroup(group)
        bookmark.setExtent(ref_rect)

        if scope == "project":
            manager = QgsProject.instance().bookmarkManager()
        else:
            from qgis.core import QgsApplication
            manager = QgsApplication.bookmarkManager()

        bm_id = manager.addBookmark(bookmark)
        return {"id": bm_id, "name": name, "scope": scope}

    def zoom_to_bookmark(bookmark_id: str = None, name: str = None, **_):
        """Navigate to a bookmark by ID or name. Searches project first, then application."""
        bookmark = None

        # Search by ID
        if bookmark_id:
            proj_manager = QgsProject.instance().bookmarkManager()
            bookmark = proj_manager.bookmarkById(bookmark_id)
            if not bookmark.id():
                from qgis.core import QgsApplication
                bookmark = QgsApplication.bookmarkManager().bookmarkById(bookmark_id)

        # Search by name
        elif name:
            proj_manager = QgsProject.instance().bookmarkManager()
            for bm in proj_manager.bookmarks():
                if bm.name() == name:
                    bookmark = bm
                    break
            if not bookmark or not bookmark.id():
                from qgis.core import QgsApplication
                for bm in QgsApplication.bookmarkManager().bookmarks():
                    if bm.name() == name:
                        bookmark = bm
                        break

        if not bookmark or not bookmark.id():
            raise RuntimeError(
                f"Bookmark not found: {bookmark_id or name}"
            )

        # Zoom to bookmark extent
        extent = bookmark.extent()
        canvas = s.iface.mapCanvas()
        dst_crs = canvas.mapSettings().destinationCrs()
        rect = QgsRectangle(extent)

        if hasattr(extent, 'crs') and extent.crs().isValid() and extent.crs() != dst_crs:
            xform = QgsCoordinateTransform(extent.crs(), dst_crs, QgsProject.instance())
            rect = xform.transformBoundingBox(rect)

        canvas.setExtent(rect)
        canvas.refresh()
        return {"name": bookmark.name(), "extent": s.extent_to_dict(canvas.extent())}

    def delete_bookmark(bookmark_id: str, scope: str = "project", **_):
        """Remove a bookmark by ID."""
        if scope == "project":
            manager = QgsProject.instance().bookmarkManager()
        else:
            from qgis.core import QgsApplication
            manager = QgsApplication.bookmarkManager()

        if not manager.removeBookmark(bookmark_id):
            raise RuntimeError(f"Failed to remove bookmark: {bookmark_id}")
        return {"deleted": bookmark_id}

    s._HANDLERS.update({
        "list_bookmarks": list_bookmarks,
        "add_bookmark": add_bookmark,
        "zoom_to_bookmark": zoom_to_bookmark,
        "delete_bookmark": delete_bookmark,
    })
