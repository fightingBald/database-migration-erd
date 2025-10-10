#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
gen_drawio_erd_table.py
从 Postgres 风格迁移 SQL 目录生成 draw.io (.drawio) ER 图，使用 `shape=table` + 行单元格结构。
示例：
  python gen_drawio_erd_table.py --migrations ./db/migration --out schema.drawio --show-types
"""

import argparse
import glob
import os
import re
import xml.etree.ElementTree as ET

# ---------------------------
# 简陋 SQL 解析（Postgres 方言为主）
# ---------------------------
CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][\w\.]*)\s*\((.*?)\);",
    re.IGNORECASE | re.DOTALL,
    )
ALTER_FK_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([a-zA-Z_][\w\.]*)\s+ADD\s+CONSTRAINT\s+[a-zA-Z_][\w]*\s+FOREIGN\s+KEY\s*\((.*?)\)\s+REFERENCES\s+([a-zA-Z_][\w\.]*)\s*\((.*?)\)",
    re.IGNORECASE | re.DOTALL,
    )
TABLE_LEVEL_PK_RE = re.compile(r"PRIMARY\s+KEY\s*\((.*?)\)", re.IGNORECASE | re.DOTALL)
COMMENT_LINE_RE = re.compile(r"--.*?$", re.MULTILINE)
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

def strip_comments(sql: str) -> str:
    sql = COMMENT_BLOCK_RE.sub("", sql)
    sql = COMMENT_LINE_RE.sub("", sql)
    return sql

def split_top_level_commas(s: str):
    parts, buf, depth = [], [], 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts

def parse_column_def(item: str):
    toks = item.strip().split()
    if not toks:
        return None
    if toks[0].upper() in ("CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK"):
        return None
    col = {"name": toks[0].strip('"'), "type": None, "nullable": True, "pk": False, "fk": None}
    stop_words = {"PRIMARY","REFERENCES","NOT","NULL","DEFAULT","UNIQUE","CHECK","CONSTRAINT"}
    type_parts = []
    for tk in toks[1:]:
        if tk.upper() in stop_words:
            break
        type_parts.append(tk)
    col["type"] = " ".join(type_parts) if type_parts else ""
    up = item.upper()
    if "NOT NULL" in up:
        col["nullable"] = False
    if "PRIMARY KEY" in up:
        col["pk"] = True
    m = re.search(r"REFERENCES\s+([a-zA-Z_][\w\.]*)\s*\(([\w_]+)\)", item, re.IGNORECASE)
    if m:
        col["fk"] = {"ref_table": m.group(1), "ref_col": m.group(2)}
    return col

def parse_schema_from_sql(sql: str, schema):
    sql = strip_comments(sql)

    for m in CREATE_TABLE_RE.finditer(sql):
        table = m.group(1)
        body = m.group(2)
        items = split_top_level_commas(body)
        t = schema.setdefault(table, {"columns": [], "pks": set(), "fks": []})

        for it in items:
            col = parse_column_def(it)
            if col:
                t["columns"].append(col)
                if col["pk"]:
                    t["pks"].add(col["name"])
                if col["fk"]:
                    t["fks"].append({"column": col["name"], **col["fk"]})

        for it in items:
            mm = TABLE_LEVEL_PK_RE.search(it)
            if mm:
                cols = [c.strip().strip('"') for c in mm.group(1).split(",")]
                for c in cols:
                    t["pks"].add(c)

        for it in items:
            if re.search(r"FOREIGN\s+KEY", it, re.IGNORECASE):
                cm = re.search(
                    r"FOREIGN\s+KEY\s*\((.*?)\)\s*REFERENCES\s+([a-zA-Z_][\w\.]*)\s*\((.*?)\)",
                    it, re.IGNORECASE | re.DOTALL,
                        )
                if cm:
                    src_cols = [c.strip().strip('"') for c in cm.group(1).split(",")]
                    ref_table = cm.group(2)
                    ref_cols = [c.strip().strip('"') for c in cm.group(3).split(",")]
                    for sc, rc in zip(src_cols, ref_cols):
                        t["fks"].append({"column": sc, "ref_table": ref_table, "ref_col": rc})

    for m in ALTER_FK_RE.finditer(sql):
        table = m.group(1)
        src_cols = [c.strip().strip('"') for c in m.group(2).split(",")]
        ref_table = m.group(3)
        ref_cols = [c.strip().strip('"') for c in m.group(4).split(",")]
        t = schema.setdefault(table, {"columns": [], "pks": set(), "fks": []})
        for sc, rc in zip(src_cols, ref_cols):
            t["fks"].append({"column": sc, "ref_table": ref_table, "ref_col": rc})

def gather_schema(migrations_dir: str):
    schema = {}
    files = sorted(glob.glob(os.path.join(migrations_dir, "**/*.sql"), recursive=True))
    for fp in files:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            sql = f.read()
        parse_schema_from_sql(sql, schema)
    return schema

# ---------------------------
# draw.io XML 构造（table 形状）
# ---------------------------
class IdGen:
    def __init__(self, start=2):
        self.n = start
    def next(self):
        self.n += 1
        return f"mx{self.n}"

TABLE_STYLE = (
    "shape=table;startSize=30;container=1;collapsible=1;"
    "childLayout=tableLayout;fixedRows=1;rowLines=0;fontStyle=1;"
    "align=center;resizeLast=1;labelBackgroundColor=none;"
    "fillColor=#dae8fc;strokeColor=#6c8ebf;"
)
ROW_STYLE = (
    "shape=partialRectangle;collapsible=0;dropTarget=0;pointerEvents=0;"
    "fillColor=none;top=0;left=0;bottom=0;right=0;"
    "points=[[0,0.5],[1,0.5]];portConstraint=eastwest;"
    "strokeColor=#000000;"
)
CELL_LEFT_STYLE = (
    "shape=partialRectangle;connectable=0;fillColor=none;top=0;left=0;bottom=0;right=0;"
    "editable=1;overflow=hidden;fontStyle=1"
)
CELL_RIGHT_STYLE = (
    "shape=partialRectangle;connectable=0;fillColor=none;top=0;left=0;bottom=0;right=0;"
    "align=left;spacingLeft=6;overflow=hidden;"
)

def build_drawio(schema: dict, show_types: bool) -> ET.ElementTree:
    # 顶层 <mxfile><diagram><mxGraphModel>
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0",
            "version": "28.2.3",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"name": "Page-1", "id": "auto-gen"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1372",
            "dy": "773",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "850",
            "pageHeight": "1100",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    idg = IdGen()
    table_id_map = {}

    # 简单宫格布局
    per_row = 3
    table_w = 290
    row_h = 30
    pad_x, pad_y = 80, 40
    gap_x, gap_y = 60, 60

    # 稳定顺序
    for idx, tname in enumerate(sorted(schema.keys())):
        cols = schema[tname]["columns"]
        num_rows = max(1, len(cols))
        table_h = 30 + row_h * num_rows  # header + rows

        col = idx % per_row
        row = idx // per_row
        x = pad_x + col * (table_w + gap_x)
        y = pad_y + row * (table_h + gap_y)

        # 表容器
        tid = idg.next()
        table_id_map[tname] = tid
        tcell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": tid,
                "value": tname.upper(),
                "style": TABLE_STYLE,
                "vertex": "1",
                "parent": "1",
            },
        )
        tgeo = ET.SubElement(
            tcell,
            "mxGeometry",
            {"x": str(x), "y": str(y), "width": str(table_w), "height": f"{table_h:.2f}", "as": "geometry"},
        )
        ET.SubElement(tgeo, "mxRectangle", {"x": "80", "y": "10", "width": "50", "height": "30", "as": "alternateBounds"})

        # 行们
        y_offset = 30
        for i, c in enumerate(cols):
            row_id = idg.next()
            row_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": row_id,
                    "value": "",
                    "style": ROW_STYLE,
                    "vertex": "1",
                    "parent": tid,
                },
            )
            ET.SubElement(
                row_cell,
                "mxGeometry",
                {"y": str(y_offset + i * row_h), "width": str(table_w), "height": str(row_h), "as": "geometry"},
            )

            # 左侧 PK 小格
            left_id = idg.next()
            left_val = "PK" if (c["name"] in schema[tname]["pks"] or c.get("pk")) else ""
            left_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": left_id,
                    "value": left_val,
                    "style": CELL_LEFT_STYLE if left_val else CELL_LEFT_STYLE.replace("fontStyle=1", ""),
                    "vertex": "1",
                    "parent": row_id,
                },
            )
            ET.SubElement(left_cell, "mxGeometry", {"width": "30", "height": "30", "as": "geometry"})
            ET.SubElement(left_cell, "mxRectangle", {"width": "30", "height": "30", "as": "alternateBounds"})

            # 右侧 列名(+类型)
            right_id = idg.next()
            label = c["name"].upper()
            if show_types and c["type"]:
                label = f"{label} ({c['type']})"
            right_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": right_id,
                    "value": label,
                    "style": CELL_RIGHT_STYLE,
                    "vertex": "1",
                    "parent": row_id,
                },
            )
            ET.SubElement(
                right_cell,
                "mxGeometry",
                {"x": "30", "width": str(table_w - 30), "height": "30", "as": "geometry"},
            )
            ET.SubElement(right_cell, "mxRectangle", {"width": str(table_w - 30), "height": "30", "as": "alternateBounds"})

    # 画外键连线（连到表容器即可，够用）
    for tname, tmeta in schema.items():
        for fk in tmeta["fks"]:
            src = table_id_map.get(tname)
            dst = table_id_map.get(fk["ref_table"])
            if not src or not dst:
                continue
            eid = idg.next()
            edge = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": eid,
                    "value": "",
                    "style": "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;strokeColor=#999999;",
                    "edge": "1",
                    "parent": "1",
                    "source": src,
                    "target": dst,
                },
            )
            ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})

    return ET.ElementTree(mxfile)

# ---------------------------
# CLI
# ---------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--migrations", required=True, help="迁移 SQL 根目录")
    ap.add_argument("--out", required=True, help="输出 .drawio 路径")
    ap.add_argument("--show-types", action="store_true", help="列名后附上 (type)")
    args = ap.parse_args()

    schema = gather_schema(args.migrations)
    if not schema:
        raise SystemExit("没扫到任何表。检查迁移目录或你的 DDL 别太花活。")

    tree = build_drawio(schema, show_types=args.show_types)
    # 写文件，缩进一下，省得你肉眼流血
    ET.indent(tree, space="  ")
    tree.write(args.out, encoding="utf-8", xml_declaration=False)
    print(f"OK: {args.out}")

if __name__ == "__main__":
    main()
