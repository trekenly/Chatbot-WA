import React, { useMemo, useState } from "react";

type AnyObj = Record<string, any>;

function seatId(s: AnyObj): string {
  return String(s.seat_event_id ?? s.id ?? s.value ?? s.code ?? s.seat_id ?? "");
}
function seatLabel(s: AnyObj): string {
  return String(s.label ?? s.seat_label ?? s.name ?? s.seat_no ?? s.seat_number ?? seatId(s));
}
function isAvailableSeatStatus(status: string): boolean {
  const st = String(status || "").toLowerCase();
  return st === "available" || st === "open" || st === "free";
}

type LayoutFloor = { z: number; rows: number; cols: number };
type LayoutMeta = {
  floors: LayoutFloor[];
  byFloor: Map<number, Map<string, AnyObj>>;
  avail: Set<string>;
};

function isLayoutObj(seats: any): seats is AnyObj {
  return !!seats && typeof seats === "object" && !Array.isArray(seats) && Array.isArray(seats.seat_layout_details);
}

function buildLayoutMeta(layout: AnyObj): LayoutMeta {
  const floors: LayoutFloor[] =
    Array.isArray(layout.floor_details) && layout.floor_details.length
      ? layout.floor_details.map((f: AnyObj) => ({
          z: parseInt(f.floor ?? f.z ?? 1, 10) || 1,
          rows: parseInt(f.row_amount ?? f.rows ?? 0, 10) || 0,
          cols: parseInt(f.col_amount ?? f.cols ?? 0, 10) || 0,
        }))
      : [{ z: 1, rows: 0, cols: 0 }];

  const byFloor = new Map<number, Map<string, AnyObj>>();
  const details: AnyObj[] = Array.isArray(layout.seat_layout_details) ? layout.seat_layout_details : [];
  for (const it of details) {
    const z = parseInt(it.z ?? it.floor ?? 1, 10) || 1;
    const y = parseInt(it.y ?? it.row ?? 1, 10) || 1;
    const x = parseInt(it.x ?? it.col ?? 1, 10) || 1;
    if (!byFloor.has(z)) byFloor.set(z, new Map());
    byFloor.get(z)!.set(`${y},${x}`, it);
  }

  // infer rows/cols if missing
  for (const f of floors) {
    if (f.rows && f.cols) continue;
    let maxY = 0,
      maxX = 0;
    const m = byFloor.get(f.z);
    if (m) {
      for (const k of m.keys()) {
        const [yy, xx] = k.split(",").map((n) => parseInt(n, 10) || 0);
        if (yy > maxY) maxY = yy;
        if (xx > maxX) maxX = xx;
      }
    }
    f.rows = f.rows || maxY || 1;
    f.cols = f.cols || maxX || 1;
  }

  const avail = new Set<string>();
  for (const it of details) {
    if (String(it.object_code || "").toLowerCase() !== "seat") continue;
    const s = it.object_code_seat || it.seat || null;
    const num = s?.seat_number ? String(s.seat_number).toUpperCase() : "";
    const status = s?.seat_status ? String(s.seat_status) : "";
    if (num && isAvailableSeatStatus(status)) avail.add(num);
  }

  return { floors, byFloor, avail };
}

function cellKind(it?: AnyObj): { kind: "empty" | "seat" | "object"; label?: string; seatNum?: string; available?: boolean } {
  if (!it) return { kind: "empty" };
  const code = String(it.object_code || "").toLowerCase();
  if (code === "seat") {
    const s = it.object_code_seat || it.seat || {};
    const seatNum = s?.seat_number ? String(s.seat_number).toUpperCase() : "";
    const status = s?.seat_status ? String(s.seat_status) : "";
    return { kind: "seat", seatNum, label: seatNum || "Seat", available: isAvailableSeatStatus(status) };
  }
  // common non-seat objects: driver/toilet/stairs/door
  const label = code ? code.toUpperCase() : "OBJ";
  return { kind: "object", label };
}

export function SeatMapPicker({
  title,
  seats,
  pax = 1,
  selected = [],
  disabled,
  onSubmit,
}: {
  title?: string;
  seats: any;
  pax?: number;
  selected?: string[];
  disabled?: boolean;
  onSubmit: (picked: string[]) => void;
}) {
  const want = Math.max(1, parseInt(String(pax || 1), 10) || 1);

  const layoutMeta = useMemo(() => (isLayoutObj(seats) ? buildLayoutMeta(seats) : null), [seats]);
  const list: AnyObj[] = useMemo(() => (Array.isArray(seats) ? seats : []), [seats]);

  const [floorZ, setFloorZ] = useState<number>(() => layoutMeta?.floors?.[0]?.z ?? 1);
  const [pick, setPick] = useState<string[]>(Array.isArray(selected) ? selected.map(String) : []);

  // keep picked within availability
  React.useEffect(() => {
    if (!layoutMeta) return;
    setPick((cur) => cur.map((x) => String(x).toUpperCase()).filter((x) => layoutMeta.avail.has(x)));
  }, [layoutMeta]);

  function toggleSeat(num: string, ok: boolean) {
    if (!num || !ok || disabled) return;
    const id = String(num).toUpperCase();
    setPick((cur) => {
      const has = cur.includes(id);
      if (has) return cur.filter((x) => x !== id);
      if (cur.length >= want) return cur;
      return [...cur, id];
    });
  }

  // Legacy fallback: a flat list of seat labels.
  if (!layoutMeta) {
    const normalized: AnyObj[] = useMemo(() => (Array.isArray(list) ? list : []), [list]);
    return (
      <div>
        {title ? <div style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div> : null}
        <div className="chips">
          {normalized.map((s) => {
            const id = seatId(s);
            const lbl = seatLabel(s);
            // If it is a plain string/number list, id may be empty
            const key = id || lbl;
            const ok =
              typeof s === "string" || typeof s === "number"
                ? true
                : typeof (s as AnyObj).available === "boolean"
                  ? (s as AnyObj).available
                  : true;
            const active = pick.includes(String(lbl).toUpperCase());
            return (
              <button
                key={key}
                type="button"
                className={active ? "chip chipSelected" : "chip"}
                disabled={disabled || !ok}
                onClick={() => toggleSeat(lbl, ok)}
                title={!ok ? "Unavailable" : undefined}
              >
                {lbl}
              </button>
            );
          })}
        </div>

        <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
          <button
            type="button"
            className="btn btnPrimary"
            disabled={disabled || pick.length !== want}
            onClick={() => onSubmit(pick)}
          >
            Confirm seats
          </button>
          <div className="muted" style={{ fontSize: 12 }}>
            Pick {want} seat{want === 1 ? "" : "s"} ({pick.length}/{want})
          </div>
        </div>
      </div>
    );
  }

  const floors = layoutMeta.floors;
  const floor = floors.find((f) => f.z === floorZ) || floors[0];
  const grid = layoutMeta.byFloor.get(floor.z) || new Map<string, AnyObj>();

  return (
    <div>
      {title ? <div style={{ fontWeight: 700, marginBottom: 12, fontSize: 15 }}>{title}</div> : null}

      {floors.length > 1 && (
        <div className="seatTabs">
          {floors.map((f) => (
            <button
              key={f.z}
              type="button"
              className={"seatTab" + (f.z === floorZ ? " active" : "")}
              onClick={() => setFloorZ(f.z)}
              disabled={disabled}
            >
              Floor {f.z}
            </button>
          ))}
        </div>
      )}

      <div className="seatMapWrap">
        <div className="seatFrontLabel">Front of bus</div>
        <div
          className="seatGrid"
          style={{
            gridTemplateColumns: `repeat(${floor.cols}, max-content)`,
          }}
        >
          {Array.from({ length: floor.rows }).flatMap((_, rIdx) => {
            const y = rIdx + 1;
            return Array.from({ length: floor.cols }).map((_, cIdx) => {
              const x = cIdx + 1;
              const it = grid.get(`${y},${x}`);
              const ck = cellKind(it);
              const key = `${floor.z}:${y},${x}`;
              if (ck.kind === "empty") return <div key={key} className="seatCell empty" />;
              if (ck.kind === "object") return <div key={key} className="seatCell obj">{ck.label}</div>;

              const num = ck.seatNum || "";
              const ok = !!ck.available && layoutMeta.avail.has(num);
              const active = pick.includes(num);
              return (
                <button
                  key={key}
                  type="button"
                  className={"seatCell seat" + (ok ? " ok" : " bad") + (active ? " active" : "")}
                  disabled={disabled || !ok}
                  onClick={() => toggleSeat(num, ok)}
                  title={!ok ? "Taken" : "Available — click to select"}
                >
                  {num || "•"}
                </button>
              );
            });
          })}
        </div>

        {/* Legend */}
        <div className="seatLegend">
          <div className="seatLegendItem">
            <div className="seatLegendSwatch swatchOk" />
            Available
          </div>
          <div className="seatLegendItem">
            <div className="seatLegendSwatch swatchBad" />
            Taken
          </div>
          <div className="seatLegendItem">
            <div className="seatLegendSwatch swatchActive" />
            Selected
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16, display: "flex", gap: 12, alignItems: "center" }}>
        <button
          type="button"
          className="btn btnPrimary"
          disabled={disabled || pick.length !== want}
          onClick={() => onSubmit(pick)}
        >
          Confirm {pick.length}/{want} seat{want === 1 ? "" : "s"}
        </button>
        {pick.length < want && (
          <div className="muted" style={{ fontSize: 13 }}>
            Select {want - pick.length} more seat{want - pick.length === 1 ? "" : "s"}
          </div>
        )}
      </div>
    </div>
  );
}
