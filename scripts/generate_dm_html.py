#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剧本杀 DM 工具 HTML 生成器
扫描素材文件夹，自动生成单文件 HTML DM 开本工具。
"""

import os
import sys
import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ---------------------------------------------------------------------------
# 扫描素材
# ---------------------------------------------------------------------------

def find_prepared_folder(root: Path) -> Optional[Path]:
    """查找已整理的素材子文件夹"""
    candidates = ["准备好的素材", "prepared_materials", "素材", "materials"]
    for name in candidates:
        p = root / name
        if p.exists() and p.is_dir():
            return p
    return None

def scan_folder(folder: Path) -> dict:
    """
    扫描文件夹，识别各类素材。
    返回结构化的素材信息。
    """
    result = {
        "source_folder": str(folder),
        "prepared_folder": None,
        "scripts": [],      # [(name, relative_path), ...]
        "clues": {},        # {area: [filenames], ...}
        "clue_base_path": "./准备好的素材/切分后的线索/",
        "manual": None,     # relative_path
        "map": None,        # relative_path
        "organizer_pages": [],  # 组织者手册分页图片 [(page_num, path), ...]
        "script_folders": [],   # 原始剧本文件夹 [(char_name, folder_path), ...]
        "clue_originals": [],   # 原始线索图片 [(name, path), ...]
    }

    # 先检查是否有已整理的素材
    prepared = find_prepared_folder(folder)
    if prepared:
        result["prepared_folder"] = str(prepared)
        _scan_prepared(prepared, result, folder)
        return result

    # 扫描根目录
    _scan_root(folder, result)
    return result


def _scan_prepared(prepared: Path, result: dict, root: Path):
    """扫描已整理的素材文件夹"""
    for f in prepared.iterdir():
        if not f.is_file():
            continue
        lower = f.name.lower()
        rel = os.path.relpath(f, root)

        if lower.endswith(".pdf"):
            if "组织者" in lower or "手册" in lower or "dm" in lower:
                result["manual"] = rel
            else:
                name = f.stem
                result["scripts"].append((name, rel))

        elif lower.endswith((".jpg", ".jpeg", ".png")):
            if "地图" in lower:
                result["map"] = rel

    # 扫描切分后的线索
    clues_dir = prepared / "切分后的线索"
    if clues_dir.exists():
        result["clue_base_path"] = os.path.relpath(clues_dir, root).replace("\\", "/") + "/"
        for f in sorted(clues_dir.iterdir()):
            if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                area = _extract_area_name(f.stem)
                if area not in result["clues"]:
                    result["clues"][area] = []
                result["clues"][area].append(f.name)


def _scan_root(root: Path, result: dict):
    """扫描根目录下的原始素材"""
    for f in root.iterdir():
        if not f.is_file():
            # 检查子文件夹
            if "组织者手册" in f.name or "organizer" in f.name.lower():
                pages = []
                for img in sorted(f.iterdir()):
                    if img.suffix.lower() in (".jpg", ".jpeg", ".png"):
                        m = re.search(r'(\d+)', img.stem)
                        num = int(m.group(1)) if m else 999
                        pages.append((num, img.name))
                pages.sort(key=lambda x: x[0])
                result["organizer_pages"] = [(n, str(f / p)) for n, p in pages]

            elif "剧本" in f.name or "script" in f.name.lower():
                for char_dir in f.iterdir():
                    if char_dir.is_dir():
                        result["script_folders"].append((char_dir.name, str(char_dir)))

            elif "线索" in f.name or "clue" in f.name.lower():
                for img in sorted(f.iterdir()):
                    if img.suffix.lower() in (".jpg", ".jpeg", ".png"):
                        result["clue_originals"].append((img.name, str(img)))

            elif "地图" in f.name or "map" in f.name.lower():
                for img in f.iterdir():
                    if img.suffix.lower() in (".jpg", ".jpeg", ".png"):
                        result["map"] = str(img)

            continue

        lower = f.name.lower()
        rel = os.path.relpath(f, root)

        if lower.endswith(".pdf"):
            if "组织者" in lower or "手册" in lower or "dm" in lower:
                result["manual"] = rel
            else:
                result["scripts"].append((f.stem, rel))

        elif lower.endswith((".jpg", ".jpeg", ".png")):
            if "地图" in lower:
                result["map"] = rel


def _extract_area_name(stem: str) -> str:
    """从文件名提取区域名称（去除序号后缀如 _2, _3）"""
    # 匹配末尾的 _数字 或 -数字
    area = re.sub(r'[_\-]\d+$', '', stem)
    return area


# ---------------------------------------------------------------------------
# 素材整理
# ---------------------------------------------------------------------------

def try_import_pymupdf():
    """尝试导入 PyMuPDF"""
    try:
        import fitz
        return fitz
    except ImportError:
        return None


def merge_images_to_pdf(image_files: List[Path], output_path: Path, sort_key=None):
    """将图片按顺序拼接成 PDF"""
    fitz = try_import_pymupdf()
    if fitz is None:
        print("[警告] 缺少 PyMuPDF，无法拼接 PDF。请安装: pip install pymupdf")
        return False

    if sort_key:
        image_files = sorted(image_files, key=sort_key)

    doc = fitz.open()
    for img_path in image_files:
        img = fitz.open(img_path)
        rect = img[0].rect
        pdf_page = doc.new_page(width=rect.width, height=rect.height)
        pdf_page.insert_image(rect, filename=str(img_path))
        img.close()

    doc.save(str(output_path))
    doc.close()
    print(f"[OK] 已生成 PDF: {output_path}")
    return True


def split_clue_image(image_path: Path, output_dir: Path, area_name: str):
    """
    将线索图片从中间切开（假设正反两面拼接）。
    通过分析图片宽高比来判断切分方向。
    返回 [(filename, is_front), ...]
    """
    from PIL import Image
    try:
        img = Image.open(image_path)
        w, h = img.size

        # 判断拼接方向：宽高比 > 1.3 认为是横向拼接，< 0.7 认为是纵向拼接
        ratio = w / h
        results = []

        if ratio > 1.3:
            # 横向拼接，从中间竖切
            mid = w // 2
            front = img.crop((0, 0, mid, h))
            back = img.crop((mid, 0, w, h))
        elif ratio < 0.7:
            # 纵向拼接，从中间横切
            mid = h // 2
            front = img.crop((0, 0, w, mid))
            back = img.crop((0, mid, w, h))
        else:
            # 无法判断，保存原图
            out = output_dir / f"{area_name}.jpg"
            img.save(out)
            results.append((out.name, True))
            return results

        # 保存切分后的图片
        front_path = output_dir / f"{area_name}_正.jpg"
        back_path = output_dir / f"{area_name}_反.jpg"
        front.save(front_path)
        back.save(back_path)
        results.append((front_path.name, True))
        results.append((back_path.name, False))
        return results

    except Exception as e:
        print(f"[警告] 切分失败 {image_path}: {e}")
        return []


# ---------------------------------------------------------------------------
# 生成 HTML
# ---------------------------------------------------------------------------

def build_game_data(scan_result: dict, user_config: dict) -> dict:
    """
    构建 GAME_DATA 对象，用于注入到 HTML 模板中。
    user_config 是用户提供的高级配置，覆盖自动扫描的结果。
    """
    root = Path(scan_result["source_folder"])

    # 角色列表
    characters = []
    for name, rel_path in scan_result["scripts"]:
        characters.append({
            "name": name,
            "role": user_config.get("character_roles", {}).get(name, ""),
            "pdf": rel_path.replace("\\", "/")
        })

    # 线索（确保每个区域的文件列表按自然顺序排序）
    clue_areas = {}
    for area, files in scan_result["clues"].items():
        # 自然排序：书房_2.jpg 应该在书房_10.jpg 之前
        def natural_key(f):
            parts = re.split(r'(\d+)', f)
            return [int(p) if p.isdigit() else p.lower() for p in parts]
        clue_areas[area] = sorted(files, key=natural_key)

    # 轮次分配（默认全部在第一轮，可由用户配置覆盖）
    round_areas = user_config.get("round_areas", {1: list(clue_areas.keys())})
    round_info = user_config.get("round_info", {
        1: {"total": sum(len(v) for v in clue_areas.values()), "perPerson": "?", "rule": "请根据组织者手册配置"}
    })

    # 流程阶段
    flow_stages = user_config.get("flow_stages", [
        {"title": "准备阶段", "desc": "检查人数、确认角色、准备素材", "badge": "准备"},
        {"title": "第一阶段：分发剧本", "desc": "分发角色剧本，玩家阅读至自我介绍部分", "badge": "分发剧本"},
        {"title": "第二阶段：自我介绍", "desc": "玩家根据剧本内容进行自我介绍", "badge": "自我介绍"},
        {"title": "第三阶段：继续阅读", "desc": "继续阅读剧本至指定位置", "badge": "阅读"},
        {"title": "第四阶段：案件公布", "desc": "主持人告知案件情况", "badge": "案件公布"},
        {"title": "第五阶段：第一轮搜证", "desc": "开启第一轮搜证", "badge": "第一轮搜证"},
        {"title": "第六阶段：第一轮讨论", "desc": "集中讨论", "badge": "第一轮讨论"},
        {"title": "第七阶段：第二轮搜证", "desc": "开启第二轮搜证", "badge": "第二轮搜证"},
        {"title": "第八阶段：第二轮讨论", "desc": "集中讨论", "badge": "第二轮讨论"},
        {"title": "第九阶段：最终投票", "desc": "玩家进行最终投票，阐述推理", "badge": "最终投票"},
        {"title": "第十阶段：结局揭晓", "desc": "总结故事，揭晓结局", "badge": "结局揭晓"},
    ])

    # 资料参考
    reference = user_config.get("reference", {
        "characters": [],
        "locations": [],
        "rules": [
            "请勿在未经允许的情况下翻看剧本下一页",
            "搜证时不可搜查自己的房间",
            "请尽量代入角色进行扮演",
            "讨论环节请积极分享信息"
        ]
    })

    # 突发事件
    events = user_config.get("events", [])

    # 真相复盘
    review = user_config.get("review", {
        "cases": [],
        "endings": [],
        "notes": ""
    })

    # DM 提示
    dm_tips = user_config.get("dm_tips", {
        "script": [
            f"确认玩家人数，本剧本为 <strong>{len(characters)}人</strong> 本",
            "建议玩家按角色性别分配（如可能），但不强制",
            "分发剧本后，请提醒玩家不要互相查看剧本内容",
            "告知玩家先阅读到「自我介绍」部分即停止"
        ]
    })

    game_data = {
        "title": user_config.get("title", root.name or "剧本杀"),
        "password": user_config.get("password", "zxy666"),
        "characters": characters,
        "clueAreas": clue_areas,
        "clueBasePath": scan_result.get("clue_base_path", "./切分后的线索/"),
        "roundAreas": round_areas,
        "roundInfo": round_info,
        "flowStages": flow_stages,
        "reference": reference,
        "events": events,
        "review": review,
        "dmTips": dm_tips,
        "manualPath": scan_result["manual"].replace("\\", "/") if scan_result["manual"] else None,
        "mapPath": scan_result["map"].replace("\\", "/") if scan_result["map"] else None,
    }

    return game_data


def generate_html(scan_result: dict, user_config: dict, template_path: Path, output_path: Path):
    """读取模板，注入数据，生成最终的 HTML 文件"""
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    game_data = build_game_data(scan_result, user_config)
    data_json = json.dumps(game_data, ensure_ascii=False, indent=2)

    # 替换占位符
    html = template.replace("/* GAME_DATA_PLACEHOLDER */", data_json)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML 已生成: {output_path}")
    print(f"     文件大小: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"     角色数: {len(game_data['characters'])}")
    print(f"     线索区域: {len(game_data['clueAreas'])}")
    print(f"     总线索数: {sum(len(v) for v in game_data['clueAreas'].values())}")
    return output_path


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def print_scan_report(scan_result: dict):
    """打印素材扫描报告"""
    print("=" * 60)
    print("素材扫描报告")
    print("=" * 60)
    print(f"素材文件夹: {scan_result['source_folder']}")

    if scan_result["prepared_folder"]:
        print(f"已整理素材: {scan_result['prepared_folder']}")

    print(f"\n📄 剧本 ({len(scan_result['scripts'])}):")
    for name, path in scan_result["scripts"]:
        print(f"   • {name}")

    print(f"\n📖 组织者手册: {'✓ ' + scan_result['manual'] if scan_result['manual'] else '✗ 未找到'}")
    print(f"🗺️ 地图: {'✓ ' + scan_result['map'] if scan_result['map'] else '✗ 未找到'}")

    print(f"\n🔍 线索区域 ({len(scan_result['clues'])}):")
    for area, files in sorted(scan_result["clues"].items()):
        print(f"   • {area}: {len(files)} 条")

    if scan_result["organizer_pages"]:
        print(f"\n📑 组织者手册分页 ({len(scan_result['organizer_pages'])} 页):")
        for num, path in scan_result["organizer_pages"]:
            print(f"   • 第 {num} 页")

    if scan_result["script_folders"]:
        print(f"\n🎭 原始剧本文件夹 ({len(scan_result['script_folders'])}):")
        for name, path in scan_result["script_folders"]:
            print(f"   • {name}")

    if scan_result["clue_originals"]:
        print(f"\n🧩 原始线索图片 ({len(scan_result['clue_originals'])}):")
        for name, path in scan_result["clue_originals"]:
            print(f"   • {name}")

    print("=" * 60)


def main_cli():
    import argparse
    parser = argparse.ArgumentParser(description="剧本杀 DM 工具 HTML 生成器")
    parser.add_argument("folder", help="剧本杀素材文件夹路径")
    parser.add_argument("-t", "--template", default=None, help="HTML 模板路径")
    parser.add_argument("-o", "--output", default=None, help="输出 HTML 文件路径")
    parser.add_argument("-c", "--config", default=None, help="用户配置文件 (JSON)")
    parser.add_argument("--report", action="store_true", help="仅打印扫描报告，不生成 HTML")
    args = parser.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.exists():
        print(f"[错误] 文件夹不存在: {folder}")
        sys.exit(1)

    # 扫描素材
    scan_result = scan_folder(folder)
    print_scan_report(scan_result)

    if args.report:
        return

    # 加载用户配置
    user_config = {}
    if args.config and Path(args.config).exists():
        with open(args.config, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        print(f"[OK] 已加载配置文件: {args.config}")

    # 确定模板路径
    if args.template:
        template_path = Path(args.template)
    else:
        # 尝试从 skill 目录找模板
        skill_dir = Path(__file__).parent.parent
        template_path = skill_dir / "assets" / "template.html"
        if not template_path.exists():
            # 尝试当前目录
            template_path = Path("template.html")

    if not template_path.exists():
        print(f"[错误] 模板文件不存在: {template_path}")
        print("请通过 --template 指定模板路径，或确保 template.html 在当前目录")
        sys.exit(1)

    # 确定输出路径
    if args.output:
        output_path = Path(args.output)
    else:
        title = user_config.get("title", folder.name or "剧本杀")
        output_path = folder / f"{title}-DM工具.html"

    # 生成 HTML
    generate_html(scan_result, user_config, template_path, output_path)


if __name__ == "__main__":
    main_cli()
