# -*- coding: utf-8 -*-
"""Core processing logic for organizing project layers by HUB BOX."""

import os
import re
from collections import defaultdict

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtWidgets import QApplication, QProgressDialog
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsMapLayerStyle,
    QgsProject,
    QgsSpatialIndex,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)


CORE_KEYS = (
    "hub",
    "hub_boundary",
    "sub_box",
    "sub_boundary",
    "distribution_cable",
)
HOME_KEYS = ("sdus", "mdus", "church", "commercial", "hospitals", "institution")
ALL_KEYS = CORE_KEYS + HOME_KEYS
LAYER_LABELS = {
    "hub": "HUB BOX",
    "hub_boundary": "HUB BOX Boundary",
    "sub_box": "SUB BOX",
    "sub_boundary": "SUB BOX Boundary",
    "distribution_cable": "Distribution Cable",
    "sdus": "Sdus",
    "mdus": "Mdus",
    "church": "Church",
    "commercial": "Commercial",
    "hospitals": "Hospitals",
    "institution": "Institution",
}


class OrganizerError(Exception):
    """Expected processing error shown directly to the user."""


def source_file_path(layer):
    """Return the local datasource file path for SHP/GPKG layers."""
    if layer is None:
        return ""
    source = layer.source() or ""
    raw_path = source.split("|", 1)[0].strip()
    if raw_path.startswith("file:"):
        raw_path = QUrl(raw_path).toLocalFile()
    raw_path = raw_path.strip('"')
    return os.path.normpath(raw_path) if raw_path else ""


def safe_folder_name(value):
    """Make a filesystem-safe folder/file stem without losing normal names."""
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = text.rstrip(" .")
    return text or "HUB_BOX"


def _name_field(layer):
    for field in layer.fields():
        if field.name().casefold() == "name":
            return field.name()
    return None


def _name_matches(value, hub_name):
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and hub_name.casefold() in text.casefold()


def _collect_matching_features(layer, hub_name):
    field_name = _name_field(layer)
    if not field_name:
        raise OrganizerError("图层“{}”缺少 Name 字段。".format(layer.name()))
    matches = []
    scanned = 0
    for feature in layer.getFeatures():
        if _name_matches(feature[field_name], hub_name):
            matches.append(QgsFeature(feature))
        scanned += 1
        if scanned % 5000 == 0:
            QApplication.processEvents()
    return matches


def _collect_hub_features(layer):
    field_name = _name_field(layer)
    if not field_name:
        raise OrganizerError("HUB BOX 图层缺少 Name 字段，无法识别 HUB BOX。")
    result = []
    for feature in layer.getFeatures():
        value = feature[field_name]
        name = str(value).strip() if value is not None else ""
        if name:
            result.append((QgsFeature(feature), name))
    if not result:
        raise OrganizerError("HUB BOX 图层没有可用的要素，或 Name 字段全部为空。")
    return result


def _summarize_sub_box_types(layer, features):
    """Return per-Type feature counts for the SUB BOX validation report."""
    type_field = next(
        (field.name() for field in layer.fields() if field.name().casefold() == "type"),
        None,
    )
    if not type_field:
        return None
    counts = defaultdict(int)
    for feature in features:
        value = feature[type_field]
        label = "(空值)" if value is None or str(value).strip() == "" else str(value).strip()
        counts[label] += 1
    return dict(counts)


def _summarize_units(layer, features):
    """Sum UNITS and report invalid/missing values without silently counting them."""
    units_field = next(
        (field.name() for field in layer.fields() if field.name().casefold() == "units"),
        None,
    )
    if not units_field:
        return None
    total = 0.0
    valid = 0
    invalid = 0
    for feature in features:
        value = feature[units_field]
        if value is None or str(value).strip() == "":
            invalid += 1
            continue
        try:
            number = float(value)
            if not __import__("math").isfinite(number):
                raise ValueError("non-finite")
            total += number
            valid += 1
        except (TypeError, ValueError):
            invalid += 1
    if abs(total - round(total)) < 1e-9:
        display = str(int(round(total)))
    else:
        display = ("{:.6f}".format(total)).rstrip("0").rstrip(".")
    return {"total": display, "valid": valid, "invalid": invalid}


def _format_for_layer(layer):
    path = source_file_path(layer)
    extension = os.path.splitext(path)[1].lower()
    if extension == ".shp":
        return "ESRI Shapefile", ".shp"
    if extension == ".gpkg":
        return "GPKG", ".gpkg"
    raise OrganizerError(
        "图层“{}”的源文件格式不受支持：{}。目前只支持 SHP 和 GPKG。".format(
            layer.name(), path or layer.source()
        )
    )


def _memory_layer_with_features(source_layer, features):
    wkb_name = QgsWkbTypes.displayString(source_layer.wkbType())
    if not wkb_name or wkb_name.lower() in ("no geometry", "nogeometry"):
        uri = "None"
    else:
        crs_id = source_layer.crs().authid()
        uri = "{}?crs={}".format(wkb_name, crs_id) if crs_id else wkb_name

    memory_layer = QgsVectorLayer(uri, "_hub_box_export_tmp", "memory")
    if not memory_layer.isValid():
        raise OrganizerError(
            "无法为图层“{}”创建临时输出图层（{}）。".format(source_layer.name(), uri)
        )

    provider = memory_layer.dataProvider()
    provider.addAttributes(list(source_layer.fields()))
    memory_layer.updateFields()

    new_features = []
    for source_feature in features:
        feature = QgsFeature(memory_layer.fields())
        feature.setAttributes(source_feature.attributes())
        if source_feature.hasGeometry():
            feature.setGeometry(QgsGeometry(source_feature.geometry()))
        new_features.append(feature)
    if new_features:
        ok, _added = provider.addFeatures(new_features)
        if not ok:
            raise OrganizerError("向临时图层写入要素失败：{}。".format(source_layer.name()))
    memory_layer.updateExtents()
    return memory_layer


def _remove_shapefile_family(path):
    stem = os.path.splitext(path)[0]
    for extension in (
        ".shp", ".shx", ".dbf", ".prj", ".cpg",
        ".qix", ".sbn", ".sbx", ".shp.xml"
    ):
        candidate = stem + extension
        if os.path.exists(candidate):
            try:
                os.remove(candidate)
            except OSError:
                pass


def _write_subset(source_layer, features, output_path, driver, extension):
    """Write selected features and retain the source field schema."""
    memory_layer = _memory_layer_with_features(source_layer, features)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    options.layerName = source_layer.name()
    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

    if driver == "ESRI Shapefile" and os.path.exists(output_path):
        _remove_shapefile_family(output_path)

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        memory_layer,
        output_path,
        QgsProject.instance().transformContext(),
        options,
    )
    error_code = result[0]
    error_message = result[1] if len(result) > 1 else ""
    if error_code != QgsVectorFileWriter.NoError:
        raise OrganizerError(
            "写入“{}”失败：{}".format(source_layer.name(), error_message or error_code)
        )

    if driver == "GPKG":
        uri = "{}|layername={}".format(output_path, source_layer.name())
    else:
        uri = output_path
    output_layer = QgsVectorLayer(uri, source_layer.name(), "ogr")
    if not output_layer.isValid():
        raise OrganizerError("输出文件写入后无法重新打开：{}".format(output_path))

    # Copy the full QGIS layer style: renderer/categories, labels, diagrams,
    # blend/opacity and other style properties supported by QgsMapLayerStyle.
    style = QgsMapLayerStyle()
    style.readFromLayer(source_layer)
    style.writeToLayer(output_layer)

    # Layer-level presentation and form settings are not all part of the
    # renderer itself, so copy the common settings explicitly as well.
    try:
        output_layer.setDisplayExpression(source_layer.displayExpression())
        output_layer.setAttributeTableConfig(source_layer.attributeTableConfig())
        output_layer.setEditFormConfig(source_layer.editFormConfig())
        output_layer.setMapTipTemplate(source_layer.mapTipTemplate())
        for field_index in range(min(source_layer.fields().count(), output_layer.fields().count())):
            output_layer.setFieldAlias(field_index, source_layer.attributeAlias(field_index))
            output_layer.setEditorWidgetSetup(
                field_index, source_layer.editorWidgetSetup(field_index)
            )
            output_layer.setDefaultValueDefinition(
                field_index, source_layer.defaultValueDefinition(field_index)
            )
    except Exception:
        # Styling has already been copied; an unsupported auxiliary property
        # should not invalidate a correctly written dataset.
        pass

    try:
        # Persist the copied layer style in a QML sidecar next to the dataset.
        output_layer.saveNamedStyle(output_path + ".qml")
    except Exception:
        pass

    output_layer.setName(source_layer.name())
    return output_layer


def _spatially_select_home_features(boundary_layer, boundary_features, home_layer):
    """Select home features intersecting any matching HUB BOX polygon."""
    if not boundary_features:
        return []

    boundary_geometries = []
    transform = None
    if boundary_layer.crs() != home_layer.crs():
        transform = QgsCoordinateTransform(
            boundary_layer.crs(), home_layer.crs(), QgsProject.instance()
        )

    for feature in boundary_features:
        if (
            not feature.hasGeometry()
            or feature.geometry().isNull()
            or feature.geometry().isEmpty()
        ):
            continue
        geometry = QgsGeometry(feature.geometry())
        if transform is not None:
            try:
                geometry.transform(transform)
            except Exception:
                continue
        if not geometry.isEmpty():
            boundary_geometries.append(geometry)

    if not boundary_geometries:
        return []

    # Spatial index limits exact geometry tests to polygons whose bounding boxes
    # intersect each home feature's bounding box.
    spatial_index = QgsSpatialIndex()
    geometry_by_id = {}
    for index, geometry in enumerate(boundary_geometries, start=1):
        feature = QgsFeature()
        feature.setId(index)
        feature.setGeometry(geometry)
        spatial_index.addFeature(feature)
        geometry_by_id[index] = geometry

    selected = []
    scanned = 0
    for feature in home_layer.getFeatures():
        if (
            feature.hasGeometry()
            and not feature.geometry().isNull()
            and not feature.geometry().isEmpty()
        ):
            home_geometry = feature.geometry()
            candidate_ids = spatial_index.intersects(home_geometry.boundingBox())
            included = False
            for candidate_id in candidate_ids:
                polygon = geometry_by_id.get(candidate_id)
                if polygon is not None and polygon.intersects(home_geometry):
                    included = True
                    break
            if included:
                selected.append(QgsFeature(feature))
        scanned += 1
        if scanned % 5000 == 0:
            QApplication.processEvents()
    return selected


def _copy_selected_layer_tree(source_root, target_group, source_by_key, output_by_key):
    """Clone only selected layers while retaining their original group paths/order."""
    key_by_layer_id = {
        layer.id(): key
        for key, layer in source_by_key.items()
        if layer is not None and output_by_key.get(key) is not None
    }
    selected_ids = set(key_by_layer_id)
    added_ids = set()

    def contains_selected(node):
        for child in node.children():
            if hasattr(child, "layerId"):
                if child.layerId() in selected_ids:
                    return True
            elif contains_selected(child):
                return True
        return False

    def selected_ids_in_subtree(node):
        found = set()
        for child in node.children():
            if hasattr(child, "layerId"):
                if child.layerId() in selected_ids:
                    found.add(child.layerId())
            else:
                found.update(selected_ids_in_subtree(child))
        return found

    tree_selected_ids = selected_ids_in_subtree(source_root)

    def deepest_common_container(node):
        """
        Find the deepest source group containing every selected source layer.
        Its own name is intentionally not copied; only its children are copied
        into the new HUB BOX group. This removes project/file wrapper groups
        such as 'Kiwologoma 02=2418 HP' and the source 'HUB BOX' container.
        """
        if not tree_selected_ids:
            return node
        for child in node.children():
            if hasattr(child, "layerId"):
                continue
            if tree_selected_ids.issubset(selected_ids_in_subtree(child)):
                return deepest_common_container(child)
        return node

    def copy_children(source_group, destination_group):
        for child in source_group.children():
            if hasattr(child, "layerId"):
                source_id = child.layerId()
                key = key_by_layer_id.get(source_id)
                if key is None or source_id in added_ids:
                    continue
                output_layer = output_by_key.get(key)
                if output_layer is None:
                    continue

                # Keep each home layer directly under the same parent group
                # it had in the source project. Do not create a synthetic
                # "HOMES PASS" group or add a duplicate nesting level.
                new_node = destination_group.addLayer(output_layer)
                new_node.setItemVisibilityChecked(child.itemVisibilityChecked())
                new_node.setExpanded(child.isExpanded())
                added_ids.add(source_id)
                continue

            if not contains_selected(child):
                continue
            new_group = destination_group.addGroup(child.name())
            new_group.setExpanded(child.isExpanded())
            copy_children(child, new_group)
            if not new_group.children():
                destination_group.removeChildNode(new_group)

    # Flatten only the common outer source group. In a typical project the
    # selected ODN layers all live below:
    #   project/file group -> HUB BOX group -> (layers + HOMES PASS)
    # Starting from the deepest common container removes both outer wrappers,
    # while preserving HOMES PASS and any category subgroups below it.
    source_container = deepest_common_container(source_root)
    copy_children(source_container, target_group)

    # If a selected project layer was not present in the layer tree, append it
    # without dropping its exported dataset. Home categories remain under HOMES PASS.
    for key in CORE_KEYS:
        source_layer = source_by_key.get(key)
        output_layer = output_by_key.get(key)
        if source_layer and output_layer and source_layer.id() not in added_ids:
            target_group.addLayer(output_layer)
            added_ids.add(source_layer.id())

    for key in HOME_KEYS:
        source_layer = source_by_key.get(key)
        output_layer = output_by_key.get(key)
        if source_layer and output_layer and source_layer.id() not in added_ids:
            # If the source layer is absent from the layer tree, do not
            # invent a HOMES PASS wrapper; append it to the HUB group.
            target_group.addLayer(output_layer)
            added_ids.add(source_layer.id())


def _create_project_group(project, hub_name, source_by_key, output_by_key):
    root = project.layerTreeRoot()
    base_name = safe_folder_name(hub_name)
    group_name = base_name
    suffix = 2
    while root.findGroup(group_name) is not None:
        group_name = "{}_{}".format(base_name, suffix)
        suffix += 1

    hub_group = root.addGroup(group_name)
    hub_group.setExpanded(False)
    _copy_selected_layer_tree(root, hub_group, source_by_key, output_by_key)
    return hub_group

class HubBoxOrganizer:
    """Run the complete per-HUB-BOX export workflow."""

    def __init__(self, iface, selected_layers, output_root, load_results=True):
        self.iface = iface
        self.project = QgsProject.instance()
        self.selected_layers = selected_layers or {}
        self.output_root = os.path.abspath(output_root)
        self.load_results = bool(load_results)
        self.errors = []
        self.created_layers = []
        self.report_lines = []

    def run(self):
        hub_layer = self.selected_layers.get("hub")
        if not hub_layer or not hub_layer.isValid():
            raise OrganizerError("请先选择有效的 HUB BOX 图层。")
        if not os.path.isdir(self.output_root):
            try:
                os.makedirs(self.output_root, exist_ok=True)
            except OSError as exc:
                raise OrganizerError("无法创建输出目录：{}".format(exc))

        hubs = _collect_hub_features(hub_layer)
        # Sort HUB BOX names naturally so numeric suffixes are ordered as
        # HB01, HB02, ... HB09, HB10 (rather than lexicographically).
        def natural_hub_sort_key(item):
            name = str(item[1]).strip().casefold()
            return tuple(
                (1, int(part)) if part.isdigit() else (0, part)
                for part in re.split(r"(\d+)", name)
            )

        hubs.sort(key=natural_hub_sort_key)
        for key in ALL_KEYS:
            layer = self.selected_layers.get(key)
            if layer and not layer.isValid():
                raise OrganizerError("选择的图层无效：{}。".format(LAYER_LABELS[key]))
            if layer is None:
                self.errors.append(
                    "未选择源图层：{}（该类别不会生成输出文件）".format(LAYER_LABELS[key])
                )

        # Validate that all selected datasets can be represented as SHP/GPKG.
        format_by_key = {}
        for key in ALL_KEYS:
            layer = self.selected_layers.get(key)
            if layer:
                format_by_key[key] = _format_for_layer(layer)

        progress = QProgressDialog(
            "正在按 HUB BOX 拆分图层…",
            "",
            0,
            max(1, len(hubs) * len(ALL_KEYS)),
            self.iface.mainWindow(),
        )
        progress.setWindowTitle("HUB BOX 分组")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        folder_name_counts = defaultdict(int)
        completed_exports = 0
        total_output_layers = 0
        hub_group_count = 0

        try:
            for hub_index, (hub_feature, hub_name) in enumerate(hubs, start=1):
                safe_name = safe_folder_name(hub_name)
                folder_name_counts[safe_name.casefold()] += 1
                if folder_name_counts[safe_name.casefold()] > 1:
                    folder_name = "{}_{}".format(
                        safe_name, folder_name_counts[safe_name.casefold()]
                    )
                else:
                    folder_name = safe_name

                hub_dir = os.path.join(self.output_root, folder_name)
                os.makedirs(hub_dir, exist_ok=True)
                output_by_key = {}
                source_by_key = dict(self.selected_layers)

                # Boundary features are collected once and reused for the six home layers.
                boundary_layer = self.selected_layers.get("hub_boundary")
                boundary_features = []
                if boundary_layer:
                    try:
                        boundary_features = _collect_matching_features(boundary_layer, hub_name)
                    except Exception as exc:
                        self.errors.append(
                            "{} / HUB BOX Boundary：{}".format(hub_name, exc)
                        )

                for key in ALL_KEYS:
                    progress.setLabelText(
                        "HUB BOX {}/{}：{}".format(
                            hub_index, len(hubs), LAYER_LABELS[key]
                        )
                    )
                    QApplication.processEvents()
                    source_layer = self.selected_layers.get(key)
                    if source_layer is None:
                        self.report_lines.append(
                            "{} | {} | 未选择源图层".format(hub_name, LAYER_LABELS[key])
                        )
                        completed_exports += 1
                        progress.setValue(min(completed_exports, progress.maximum()))
                        continue

                    try:
                        if key == "hub":
                            features = [QgsFeature(hub_feature)]
                        elif key in CORE_KEYS:
                            features = _collect_matching_features(source_layer, hub_name)
                        else:
                            if boundary_layer is None:
                                features = []
                            else:
                                features = _spatially_select_home_features(
                                    boundary_layer, boundary_features, source_layer
                                )

                        driver, extension = format_by_key[key]
                        output_path = os.path.join(
                            hub_dir, safe_folder_name(LAYER_LABELS[key]) + extension
                        )
                        output_layer = _write_subset(
                            source_layer, features, output_path, driver, extension
                        )
                        output_by_key[key] = output_layer
                        total_output_layers += 1
                        self.report_lines.append(
                            "{} | {} | {} 个要素 | {}".format(
                                hub_name, LAYER_LABELS[key], len(features), output_path
                            )
                        )
                        if key not in HOME_KEYS:
                            self.report_lines.append(
                                "  {}={}".format(LAYER_LABELS[key], len(features))
                            )
                        if key == "sub_box":
                            type_counts = _summarize_sub_box_types(source_layer, features)
                            if type_counts is None:
                                self.report_lines.append(
                                    "  ODN统计校验：缺少 Type 字段，无法按 SUB BOX 类型统计"
                                )
                            else:
                                for type_name in sorted(type_counts):
                                    self.report_lines.append(
                                        "  SUB BOX({})={}".format(
                                            type_name, type_counts[type_name]
                                        )
                                    )
                        elif key in HOME_KEYS:
                            units = _summarize_units(source_layer, features)
                            if units is None:
                                self.report_lines.append(
                                    "  ODN统计校验：缺少 UNITS 字段，无法汇总"
                                )
                            else:
                                self.report_lines.append(
                                    "  {}={}（UNITS，有效值 {}，空值/非数字 {}）".format(
                                        LAYER_LABELS[key], units["total"],
                                        units["valid"], units["invalid"]
                                    )
                                )
                    except Exception as exc:
                        message = "{} / {}：{}".format(
                            hub_name, LAYER_LABELS[key], exc
                        )
                        self.errors.append(message)
                        self.report_lines.append(message)
                    finally:
                        completed_exports += 1
                        progress.setValue(min(completed_exports, progress.maximum()))
                        QApplication.processEvents()

                if self.load_results and output_by_key:
                    try:
                        # Register layers first, then create tree nodes pointing to them.
                        for layer in output_by_key.values():
                            self.project.addMapLayer(layer, False)
                            self.created_layers.append(layer)
                        _create_project_group(
                            self.project, folder_name, source_by_key, output_by_key
                        )
                        hub_group_count += 1
                    except Exception as exc:
                        self.errors.append(
                            "{} / 加载到工程失败：{}".format(hub_name, exc)
                        )

                self.report_lines.append("")
        finally:
            progress.close()

        report_path = os.path.join(self.output_root, "HUB_BOX_group_report.txt")
        try:
            with open(report_path, "w", encoding="utf-8") as report:
                report.write("HUB BOX 分组处理报告\n")
                report.write("输出目录：{}\n".format(self.output_root))
                report.write("HUB BOX 数量：{}\n".format(len(hubs)))
                report.write("成功输出图层数：{}\n".format(total_output_layers))
                report.write(
                    "加载到工程的分组数：{}\n\n".format(hub_group_count)
                )
                report.write("\n".join(self.report_lines))
                if self.errors:
                    report.write("\n\n处理异常：\n")
                    report.write("\n".join(self.errors))
        except OSError as exc:
            self.errors.append("无法写入汇总报告：{}".format(exc))

        summary = (
            "处理结束。\n"
            "HUB BOX：{} 个\n"
            "输出图层：{} 个\n"
            "加载到当前工程的分组：{} 个\n"
            "异常/缺失：{} 项\n\n"
            "输出目录：{}\n"
            "报告文件：{}"
        ).format(
            len(hubs),
            total_output_layers,
            hub_group_count,
            len(self.errors),
            self.output_root,
            report_path,
        )
        return {"summary": summary, "errors": self.errors, "report": report_path}
