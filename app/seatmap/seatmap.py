from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Optional

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None


def _layout_data_any(seats_raw: Any) -> dict[str, Any]:
    if isinstance(seats_raw, dict):
        data = seats_raw.get("data")
        if isinstance(data, dict):
            return data
        return seats_raw
    return {}


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def iter_layout_cells(seats_raw: Any) -> list[dict[str, Any]]:
    data = _layout_data_any(seats_raw)
    if not data:
        return []
    cells: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def add_cell(cell: Any, floor_no: Any = None) -> None:
        if not isinstance(cell, dict):
            return
        obj = str(cell.get("object_code") or "").lower().strip()
        seat_obj = cell.get("object_code_seat") if isinstance(cell.get("object_code_seat"), dict) else {}
        label = str(seat_obj.get("seat_number") or cell.get("seat_number") or "").strip()
        status = str(seat_obj.get("seat_status") or cell.get("seat_status") or "").lower().strip()
        x = _coerce_int(
            seat_obj.get("seat_column")
            or seat_obj.get("seat_col")
            or cell.get("column")
            or cell.get("x")
            or cell.get("pos_x")
            or cell.get("position_x"),
            0,
        )
        y = _coerce_int(
            seat_obj.get("seat_row")
            or cell.get("row")
            or cell.get("y")
            or cell.get("pos_y")
            or cell.get("position_y"),
            0,
        )
        z = _coerce_int(cell.get("z") or cell.get("floor") or floor_no or 1, 1)
        key = (z, x, y, obj, label, status)
        if key in seen:
            return
        seen.add(key)
        cells.append({
            "object_code": obj,
            "seat": label,
            "status": status,
            "x": x,
            "y": y,
            "z": z,
            "raw": cell,
        })

    for cell in data.get("seat_layout_details", []) or []:
        add_cell(cell)
    for floor in data.get("floor_details", []) or []:
        if not isinstance(floor, dict):
            continue
        floor_no = floor.get("floor") or floor.get("floor_number") or floor.get("z") or floor.get("level") or 1
        for cell in floor.get("seat_layout_details", []) or []:
            add_cell(cell, floor_no=floor_no)
    return cells


def extract_available_seats(seats_raw: Any) -> list[str]:
    seats: list[str] = []
    seen: set[str] = set()
    if isinstance(seats_raw, list):
        for x in seats_raw:
            sx = str(x or "").strip()
            if sx and sx not in seen:
                seats.append(sx)
                seen.add(sx)
        return seats
    if not isinstance(seats_raw, dict):
        return seats
    for row in seats_raw.get("rows", []) or []:
        for seat in row.get("seats", []) or []:
            if seat.get("available"):
                label = str(seat.get("label") or seat.get("id") or "").strip()
                if label and label not in seen:
                    seats.append(label)
                    seen.add(label)
    for cell in iter_layout_cells(seats_raw):
        if cell.get("object_code") != "seat":
            continue
        label = str(cell.get("seat") or "").strip()
        status = str(cell.get("status") or "").lower().strip()
        if label and status in {"1", "available"} and label not in seen:
            seats.append(label)
            seen.add(label)
    return seats


def _extract_layout_points(seats_raw: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for cell in iter_layout_cells(seats_raw):
        if cell.get("object_code") != "seat":
            continue
        label = str(cell.get("seat") or "").strip()
        if not label:
            continue
        points.append({
            "seat": label,
            "status": str(cell.get("status") or "").lower().strip(),
            "row": _coerce_int(cell.get("y"), 0),
            "col": _coerce_int(cell.get("x"), 0),
            "floor": _coerce_int(cell.get("z"), 1),
        })
    return points


def recommended_seats(seats_raw: Any, available_seats: list[str]) -> list[str]:
    points = _extract_layout_points(seats_raw)
    if points:
        avail = [p for p in points if p["status"] in {"1", "available"}]
        avail.sort(key=lambda p: (p.get("floor", 1), p["row"], p["col"], len(str(p["seat"])), str(p["seat"])))
        return [str(p["seat"]) for p in avail[:6]]

    def seat_key(s: str):
        m = re.match(r"([A-Z]*)(\d+)([A-Z]*)", str(s))
        if m:
            return (int(m.group(2)), m.group(1), m.group(3))
        return (9999, str(s), "")

    return sorted([str(x) for x in available_seats], key=seat_key)[:6]


def seatmap_image_file(seats_raw: Any, prompt: str = "") -> Optional[Path]:
    if Image is None or ImageDraw is None or ImageFont is None:
        return None

    available = set(extract_available_seats(seats_raw))
    recommended = set(recommended_seats(seats_raw, list(available))[:4])

    def _load_font(size: int, bold: bool = False) -> Any:
        candidates = []
        if bold:
            candidates += [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/segoeuib.ttf",
            ]
        else:
            candidates += [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
            ]
        for path in candidates:
            try:
                if Path(path).exists():
                    return ImageFont.truetype(path, size=size)
            except Exception:
                pass
        return ImageFont.load_default()

    font = _load_font(16)
    title_font = _load_font(28, bold=True)
    subtitle_font = _load_font(18)
    legend_font = _load_font(18, bold=True)
    floor_font = _load_font(22, bold=True)
    seat_font = _load_font(44, bold=True)
    fixture_font = _load_font(18, bold=True)
    cells = iter_layout_cells(seats_raw)

    def seat_sort_key(s: str) -> tuple[Any, ...]:
        m = re.match(r"([A-Z]*)(\d+)([A-Z]*)", str(s))
        if m:
            return (int(m.group(2)), m.group(1), m.group(3))
        return (9999, str(s), "")

    def draw_multiline(draw: Any, x: int, y: int, text: str, fill: Any, max_lines: int = 3, line_gap: int = 5) -> int:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return 0
        words = cleaned.split(" ")
        lines: list[str] = []
        line = ""
        for word in words:
            candidate = word if not line else f"{line} {word}"
            if len(candidate) <= 52:
                line = candidate
            else:
                lines.append(line)
                line = word
                if len(lines) >= max_lines - 1:
                    break
        if line and len(lines) < max_lines:
            lines.append(line)
        if len(lines) == max_lines and len(words) > sum(len(x.split()) for x in lines):
            lines[-1] = (lines[-1][:48] + "...") if len(lines[-1]) > 48 else lines[-1] + "..."
        yy = y
        for ln in lines:
            draw.text((x, yy), ln, fill=fill, font=font)
            yy += 16 + line_gap
        return yy - y

    if cells:
        floors = sorted({max(1, _coerce_int(c.get("z"), 1)) for c in cells}) or [1]
        grouped: dict[int, list[dict[str, Any]]] = {floor: [] for floor in floors}
        for c in cells:
            grouped.setdefault(max(1, _coerce_int(c.get("z"), 1)), []).append(c)

        cell_w, cell_h = 132, 118
        margin = 34
        section_gap = 40
        header_h = 150
        footer_h = 70
        floor_blocks = []
        max_width = 700
        total_height = header_h + footer_h

        for floor in floors:
            floor_cells = grouped.get(floor) or []
            xs = sorted({c.get("x", 0) for c in floor_cells}) or [0]
            ys = sorted({c.get("y", 0) for c in floor_cells}) or [0]
            x_index = {x: i for i, x in enumerate(xs)}
            y_index = {y: i for i, y in enumerate(ys)}
            block_w = margin * 2 + max(1, len(xs)) * cell_w
            block_h = 62 + max(1, len(ys)) * cell_h
            max_width = max(max_width, block_w)
            total_height += block_h + section_gap
            floor_blocks.append((floor, floor_cells, x_index, y_index, block_w, block_h))

        img = Image.new("RGB", (max_width, total_height), "white")
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((16, 14, max_width - 16, total_height - 18), radius=18, outline=(225, 228, 235), width=2)
        draw.text((30, 22), "Seat map", fill="black", font=title_font)
        draw.text((max_width - 190, 28), "Front of bus →", fill="black", font=subtitle_font)

        legend_y = 66
        legend_items = [
            ((203, 241, 206), (54, 132, 74), "Available"),
            ((203, 241, 206), (176, 133, 24), "Best"),
            ((229, 229, 229), (150, 150, 150), "Taken"),
        ]
        lx = 30
        for fill, outline, label in legend_items:
            draw.rounded_rectangle((lx, legend_y, lx + 32, legend_y + 24), radius=8, fill=fill, outline=outline, width=3)
            draw.text((lx + 42, legend_y + 1), label, fill=(45, 45, 45), font=legend_font)
            lx += 138 if label != "Available" else 158
        if prompt:
            draw_multiline(draw, 30, 104, prompt, (60, 60, 60), max_lines=2)

        current_y = header_h
        for floor, floor_cells, x_index, y_index, block_w, block_h in floor_blocks:
            draw.text((30, current_y - 30), f"Floor {floor}", fill="black", font=floor_font)
            for cell in floor_cells:
                gx = 30 + x_index.get(cell.get("x", 0), 0) * cell_w
                gy = current_y + y_index.get(cell.get("y", 0), 0) * cell_h
                obj = str(cell.get("object_code") or "").lower()
                label = str(cell.get("seat") or "").strip()
                status = str(cell.get("status") or "").lower().strip()
                box = (gx, gy, gx + cell_w - 12, gy + cell_h - 14)

                if obj == "walkway":
                    continue
                if obj == "seat":
                    is_open = label in available or status in {"1", "available"}
                    is_reco = label in recommended
                    fill = (203, 241, 206) if is_open else (229, 229, 229)
                    outline = (176, 133, 24) if is_reco else ((54, 132, 74) if is_open else (150, 150, 150))
                    draw.rounded_rectangle(box, radius=16, fill=fill, outline=outline, width=4 if is_reco else 3)
                    bbox = draw.textbbox((0, 0), label, font=seat_font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                    tx = gx + ((cell_w - 12) - text_w) / 2
                    ty = gy + ((cell_h - 14) - text_h) / 2 - 6
                    draw.text((tx, ty), label, fill="black", font=seat_font)
                    continue

                fixture_fill = (240, 244, 248)
                fixture_outline = (160, 168, 178)
                fixture_label = {
                    "driver": "DRV",
                    "toilet": "WC",
                    "stair": "STAIR",
                    "wheel": "WHEEL",
                    "wheel_seat": label or "WHEEL",
                    "handycapped_seat": label or "ACCESS",
                    "extra_seat": label or "+",
                    "empty": "",
                }.get(obj, (label or obj.upper()[:8]))
                draw.rounded_rectangle(box, radius=16, fill=fixture_fill, outline=fixture_outline, width=2)
                if fixture_label:
                    bbox = draw.textbbox((0, 0), fixture_label, font=fixture_font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                    tx = gx + ((cell_w - 12) - text_w) / 2
                    ty = gy + ((cell_h - 14) - text_h) / 2 - 2
                    draw.text((tx, ty), fixture_label, fill=(75, 80, 88), font=fixture_font)

            current_y += block_h + section_gap

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        img.save(tmp.name, format="PNG")
        tmp.close()
        return Path(tmp.name)

    seats = sorted(extract_available_seats(seats_raw), key=seat_sort_key)
    if not seats:
        return None
    per_row = 4
    rows = [seats[i:i+per_row] for i in range(0, min(len(seats), 24), per_row)]
    cell_w, cell_h = 132, 96
    margin = 36
    title_h = 120
    width = max(680, margin*2 + per_row*cell_w + 50)
    height = title_h + margin + len(rows)*cell_h + 100
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((margin, 18), "Seat map", fill="black", font=title_font)
    draw.text((margin, 54), "Green = available   Gold = best   Grey = taken", fill=(70,70,70), font=legend_font)
    draw.text((width-170, 24), "Front of bus →", fill="black", font=subtitle_font)
    for r, row in enumerate(rows):
        for c, seat in enumerate(row):
            x = margin + c*cell_w + (30 if c >= 2 else 0)
            y = title_h + r*cell_h
            outline = (176, 133, 24) if seat in recommended else (70,130,70)
            draw.rounded_rectangle((x, y, x+cell_w-14, y+cell_h-10), radius=14, fill=(202,240,200), outline=outline, width=4 if seat in recommended else 3)
            label = str(seat)
            bbox = draw.textbbox((0, 0), label, font=seat_font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            tx = x + ((cell_w - 14) - text_w) / 2
            ty = y + ((cell_h - 10) - text_h) / 2 - 6
            draw.text((tx, ty), label, fill="black", font=seat_font)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    img.save(tmp.name, format="PNG")
    tmp.close()
    return Path(tmp.name)


# Backward-compatible aliases for older call sites.
_iter_layout_cells = iter_layout_cells
_extract_available_seats = extract_available_seats
_recommended_seats = recommended_seats
_seatmap_image_file = seatmap_image_file
