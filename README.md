# Organize Files into HUB BOX Groups（QGIS 插件）

按单个 `HUB BOX` 要素自动筛选并输出对应 ODN 图层。适用于 QGIS 3.28 及以上版本，建议在 QGIS 3.40 中使用。

## 功能

- `HUB BOX`：每个 HUB BOX 要素单独生成一组，只输出当前 HUB BOX 要素。
- `HUB BOX Boundary`、`SUB BOX`、`SUB BOX Boundary`、`Distribution Cable`：按各图层 `Name` 字段是否包含当前 HUB BOX 的 `Name` 值筛选，忽略大小写。
- `Sdus`、`Mdus`、`Church`、`Commercial`、`Hospitals`、`Institution`：按当前 HUB BOX 对应的 `HUB BOX Boundary` 多边形进行空间筛选。点落在多边形内部或边界线上均纳入。
- 每个 HUB BOX 输出到一个独立子文件夹；输出格式跟随对应源图层，支持 SHP 和 GPKG。
- 保留源图层字段和 QGIS 图层样式（渲染器/分类、标注等），并为输出数据写入 `.qml` 样式侧车文件。筛选结果为 0 时仍然输出空图层。
- 可将结果加载回当前工程，并按 HUB BOX 建立图层组；`HOMES PASS` 内优先沿用原工程中该组的子组结构和图层顺序。
- 输出 `HUB_BOX_group_report.txt`，记录每个 HUB BOX 各图层的要素数量和错误信息。

## 使用方法

1. 将源 SHP/GPKG 图层加载到 QGIS 工程。
2. 确认图层名称与功能对应，例如 `HUB BOX`、`HUB BOX Boundary`、`SUB BOX`、`SUB BOX Boundary`、`Distribution Cable`、`Sdus` 等。
3. 确认 `HUB BOX` 及用于名称筛选的基础图层具有 `Name` 字段。
4. 安装并启用插件，在菜单 **HUB BOX 分组工具 → 按 HUB BOX 分组** 打开对话框。
5. 检查自动识别的图层，设置输出根目录，然后点击 **开始分组**。

默认输出根目录为 `HUB BOX` 源文件所在目录。每个 HUB BOX 会生成一个同名子文件夹，例如：

```text
SourceFolder/
├─ KIM-HB10/
│  ├─ HUB BOX.shp
│  ├─ HUB BOX.shp.qml
│  ├─ HUB BOX Boundary.shp
│  ├─ SUB BOX.shp
│  ├─ SUB BOX Boundary.shp
│  ├─ Distribution Cable.gpkg
│  ├─ Sdus.shp
│  └─ ...
├─ KIM-HB11/
│  └─ ...
└─ HUB_BOX_group_report.txt
```

## 注意事项

- 当前版本仅支持 SHP 和 GPKG 源图层；不同输入图层可以混合使用 SHP/GPKG。
- 如果某个源图层未选择，该类别不会生成；如果已选择但筛选结果为 0，仍会生成空输出图层。
- HOMES PASS 的空间筛选以 `HUB BOX Boundary` 中 `Name` 包含当前 HUB BOX 名称的所有多边形为准。若未选择边界图层或没有匹配边界，六类 HOMES PASS 输出为空。
- 输出文件可以覆盖之前同路径的分组结果；源文件不会被修改。
- Shapefile 本身存在字段名长度、字段类型等格式限制；输出遵循 Shapefile 格式限制。若需完整保留复杂字段定义，优先使用 GPKG。

## 下载

在 GitHub 仓库的 **Actions → Build QGIS Plugin ZIP → Artifacts** 下载自动打包的 ZIP。ZIP 内部包含可直接放入 QGIS 插件目录的插件文件夹。
