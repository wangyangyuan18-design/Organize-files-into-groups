# -*- coding: utf-8 -*-
"""QGIS plugin entry point."""


def classFactory(iface):
    from .organize_hub_box import OrganizeHubBoxPlugin
    return OrganizeHubBoxPlugin(iface)
