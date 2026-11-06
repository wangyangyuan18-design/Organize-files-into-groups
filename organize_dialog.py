# -*- coding: utf-8 -*-
"""Layer selection dialog for the HUB BOX organizer."""

import os

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes

from .organize_processor import source_file_path


LAYER_SPECS = [
    ("hub", "HUB BOX", True),
    ("hub_boundary", "HUB BOX Boundary", False),
    ("sub_box", "SUB BOX", False),
    ("sub_boundary", "SUB BOX Boundary", False),
    ("distribution_cable", "Distribution Cable", False),
    ("sdus", "Sdus", False),
    ("mdus", "Mdus", False),
    ("church", "Church", False),
    ("commercial", "Commercial", False),
    ("hospitals", "Hospitals", False),
    ("institution", "Institution", False),
]


class OrganizeHubBoxDialog(QDialog):
    """Choose source layers and the output directory."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("按 HUB BOX 分组")
        self.setMinimumWidth(620)
        self.resize(720, 590)
        self.layer_combos = {}
        self._build_ui()
        self._populate_layers()

    def _build_ui(self):
        root = QVBoxLayout(self)
        intro = QLabel(
            "每个 HUB BOX 要素生成一个独立分组目录。基础图层按 Name 包含关系筛选；"
            "HOMES PASS 按 HUB BOX Boundary 多边形进行空间筛选。"
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        for key, label, required in LAYER_SPECS:
            row = QHBoxLayout()
            combo = QComboBox(self)
            combo.setMinimumWidth(430)
            combo.addItem("（未选择）", "")
            combo.setToolTip("选择工程中的“{}”矢量图层。".format(label))
            self.layer_combos[key] = combo
            row.addWidget(combo, 1)
            if required:
                note = QLabel("必选")
                note.setStyleSheet("color: #c0392b; font-weight: bold;")
                row.addWidget(note)
            form.addRow(label + "：", row)
        root.addLayout(form)

        folder_row = QHBoxLayout()
        self.output_edit = QLineEdit(self)
        self.output_edit.setPlaceholderText("默认使用 HUB BOX 源文件所在文件夹")
        browse_btn = QPushButton("浏览…", self)
        browse_btn.clicked.connect(self._browse_output)
        folder_row.addWidget(self.output_edit, 1)
        folder_row.addWidget(browse_btn)
        root.addWidget(QLabel("输出根目录："))
        root.addLayout(folder_row)

        self.load_checkbox = QCheckBox(
            "处理完成后，将输出图层加载到当前 QGIS 工程并建立分组", self
        )
        self.load_checkbox.setChecked(True)
        root.addWidget(self.load_checkbox)

        note = QLabel(
            "说明：支持 SHP 和 GPKG 输入；输出格式跟随各自源图层。\n"
            "已有同名输出文件将被本次结果覆盖，但不会修改源文件。缺少可选图层时会在报告中说明。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        root.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.run_btn = QPushButton("开始分组", self)
        self.run_btn.setDefault(True)
        cancel_btn = QPushButton("取消", self)
        self.run_btn.clicked.connect(self._validate_and_accept)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.run_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

    def _populate_layers(self):
        project_layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
        ]
        for key, expected_name, _required in LAYER_SPECS:
            combo = self.layer_combos[key]
            matches = []
            for layer in project_layers:
                combo.addItem(
                    "{}  [{} | {}]".format(
                        layer.name(), layer.providerType(), QgsWkbTypes.displayString(layer.wkbType())
                    ),
                    layer.id(),
                )
                if layer.name().strip().casefold() == expected_name.casefold():
                    matches.append(layer)
            if matches:
                selected_id = matches[0].id()
                index = combo.findData(selected_id)
                if index >= 0:
                    combo.setCurrentIndex(index)
                if len(matches) > 1:
                    combo.setToolTip(
                        "发现 {} 个同名图层，已默认选择第一个；请确认选择是否正确。".format(
                            len(matches)
                        )
                    )

        hub_layer = self._layer_for_combo("hub")
        if hub_layer:
            path = source_file_path(hub_layer)
            if path and os.path.isfile(path):
                self.output_edit.setText(os.path.dirname(path))
        if not self.output_edit.text().strip():
            home = QgsProject.instance().homePath()
            if home:
                self.output_edit.setText(home)

    def _layer_for_combo(self, key):
        layer_id = self.layer_combos[key].currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def _browse_output(self):
        start = self.output_edit.text().strip() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "选择分组输出目录", start)
        if folder:
            self.output_edit.setText(folder)

    def _validate_and_accept(self):
        hub = self._layer_for_combo("hub")
        if hub is None:
            QMessageBox.warning(self, "缺少必选图层", "请先选择 HUB BOX 点图层。")
            return
        if not self.output_edit.text().strip():
            QMessageBox.warning(self, "缺少输出目录", "请选择分组结果的输出目录。")
            return
        if not os.path.isdir(self.output_edit.text().strip()):
            try:
                os.makedirs(self.output_edit.text().strip(), exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(self, "输出目录不可用", str(exc))
                return
        self.accept()

    def selected_layers(self):
        return {key: self._layer_for_combo(key) for key, _name, _required in LAYER_SPECS}

    def output_directory(self):
        return self.output_edit.text().strip()

    def load_results(self):
        return self.load_checkbox.isChecked()
