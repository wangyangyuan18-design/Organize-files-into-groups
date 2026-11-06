# -*- coding: utf-8 -*-
"""QGIS plugin: organize project layers into individual HUB BOX groups."""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsApplication

from .organize_dialog import OrganizeHubBoxDialog
from .organize_processor import HubBoxOrganizer, OrganizerError


class OrganizeHubBoxPlugin:
    """Plugin controller."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(QIcon(icon_path), "按 HUB BOX 分组", self.iface.mainWindow())
        self.action.setToolTip("按 HUB BOX 名称和 Boundary 空间范围拆分图层")
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("HUB BOX 分组工具", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu("HUB BOX 分组工具", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self):
        self.dialog = OrganizeHubBoxDialog(self.iface, self.iface.mainWindow())
        if self.dialog.exec_() != self.dialog.Accepted:
            return

        selections = self.dialog.selected_layers()
        output_root = self.dialog.output_directory()
        load_results = self.dialog.load_results()

        try:
            organizer = HubBoxOrganizer(self.iface, selections, output_root, load_results)
            result = organizer.run()
        except OrganizerError as exc:
            QMessageBox.critical(self.iface.mainWindow(), "HUB BOX 分组失败", str(exc))
            return
        except Exception as exc:
            QgsApplication.messageLog().logMessage(
                "HUB BOX 分组出现未处理异常：{}".format(exc),
                "HUB BOX 分组工具",
            )
            QMessageBox.critical(
                self.iface.mainWindow(),
                "HUB BOX 分组失败",
                "处理过程中出现未处理异常：\n{}".format(exc),
            )
            return

        text = result.get("summary", "处理完成。")
        if result.get("errors"):
            text += "\n\n未完成项目：\n" + "\n".join(result["errors"][:12])
            if len(result["errors"]) > 12:
                text += "\n……另有 {} 项，请查看输出目录中的报告。".format(
                    len(result["errors"]) - 12
                )
        QMessageBox.information(self.iface.mainWindow(), "HUB BOX 分组完成", text)
