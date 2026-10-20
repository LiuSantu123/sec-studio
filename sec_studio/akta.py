"""Parse Cytiva / Aekta UNICORN "Result" export ZIP archives into curves.

An UNICORN result export is a ZIP archive that contains, among other files:

* ``Chrom.<n>.Xml``      -- describes every recorded curve of a chromatogram.
* ``Chrom.<n>_<k>_True`` -- the raw samples of one curve.  These are *themselves*
  small ZIP archives (without a central directory, hence plain ``zipfile`` refuses
  them) holding two little-endian float32 arrays:

      CoordinateData.Amplitudes  -> the y values (mAU / mS/cm / ...)
      CoordinateData.Volumes     -> the x values (mL)

  Payload layout of those arrays::

      bytes 0..21   : fixed 22 byte header
      bytes 22..25  : uint32  count  (number of float32 samples)
      byte  26      : 0x0b separator
      bytes 27..    : count * float32, little endian
      final byte    : 0x0b trailer

Run metadata (run name, date, column, flow rate) lives in ``Result.xml``.
"""

from __future__ import annotations

import base64
import csv
import io
import struct
import zlib
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

import numpy as np

import re

_WELL_RE = re.compile(r"^\d+\.[A-H]\.\d+$")

__all__ = ["Curve", "Fractionation", "Run", "parse_result_zip", "parse_many"]

_LOCAL_SIG = b"PK\x03\x04"

# UNICORN UV channels we care about, mapped to a friendly key + label.
UV_CHANNELS = {
    "UV 1_280": ("A280", "A280 (mAU)"),
    "UV 2_230": ("A230", "A230 (mAU)"),
    "UV 3_455": ("A455", "A455 (mAU)"),
    "UV 1_260": ("A260", "A260 (mAU)"),
    "UV 2_260": ("A260", "A260 (mAU)"),
    "UV 3_260": ("A260", "A260 (mAU)"),
}


# --------------------------------------------------------------------------- #
# Low level helpers
# --------------------------------------------------------------------------- #
def _read_zip_stream(raw: bytes) -> Dict[str, bytes]:
    """Read a ZIP byte string that may lack an end-of-central-directory record.

    UNICORN writes the per-curve ``Chrom.*_True`` files as a bare stream of
    local file headers, so ``zipfile`` cannot open them.  We walk the local
    headers and inflate each deflate stream ourselves.
    """
    entries: Dict[str, bytes] = {}
    n = len(raw)
    i = 0
    while True:
        i = raw.find(_LOCAL_SIG, i)
        if i < 0 or i + 30 > n:
            break
        (ver, flags, method, mtime, mdate, crc, csize, usize, fnlen, exlen) = \
            struct.unpack_from("<HHHHHIIIHH", raw, i + 4)
        name = raw[i + 30:i + 30 + fnlen].decode("utf-8", "replace")
        dstart = i + 30 + fnlen + exlen
        if method == 8:  # deflate (raw, negative window)
            try:
                d = zlib.decompressobj(-15)
                out = d.decompress(raw[dstart:])
                out += d.flush()
                consumed = (n - dstart) - len(d.unused_data)
                entries[name] = out
                i = dstart + consumed
            except zlib.error:
                i = dstart
        elif method == 0:  # stored
            size = csize if csize != 0xFFFFFFFF else (usize if usize != 0xFFFFFFFF else 0)
            entries[name] = raw[dstart:dstart + size]
            i = dstart + size
        else:
            i = dstart
    return entries


def _read_member(zf: zipfile.ZipFile, name: str) -> Optional[bytes]:
    try:
        return zf.read(name)
    except KeyError:
        return None


def _decode_float_array(blob: bytes) -> Optional[np.ndarray]:
    """Decode a ``CoordinateData.*`` payload into a float64 numpy array."""
    if blob is None or len(blob) < 28:
        return None
    count = struct.unpack_from("<I", blob, 22)[0]
    if blob[26] != 0x0B or 27 + count * 4 > len(blob) or count == 0:
        # Fallback for unexpected layouts: trust the available bytes.
        avail = (len(blob) - 28) // 4
        if avail <= 0:
            return None
        count = avail
    return np.frombuffer(blob, dtype="<f4", offset=27, count=int(count)).astype(np.float64)


def _extract_curve(zf: zipfile.ZipFile, fname: str):
    """Return (volume_ml, amplitude) for one ``Chrom.*_True`` member."""
    blob = _read_member(zf, fname)
    if blob is None:
        return None
    if blob[:2] == b"PK":
        members = _read_zip_stream(blob)
    else:
        members = {}
    amp_blob = members.get("CoordinateData.Amplitudes")
    vol_blob = members.get("CoordinateData.Volumes")
    if amp_blob is None and vol_blob is None:
        return None
    amp = _decode_float_array(amp_blob) if amp_blob is not None else None
    vol = _decode_float_array(vol_blob) if vol_blob is not None else None
    return vol, amp


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Fractionation:
    """Fraction-collector activity recorded in the chromatogram (if any)."""

    size_ml: float = 0.0          # nominal fraction volume (0.5 mL here)
    plate: str = ""               # e.g. "96 deep well plate"
    wells: List[dict] = field(default_factory=list)   # {well, i, volume, time}
    waste_volume: Optional[float] = None              # volume where it switched to waste
    out_volume: Optional[float] = None                # "Out-Waste"

    @property
    def start_volume(self) -> Optional[float]:
        return self.wells[0]["volume"] if self.wells else None

    @property
    def end_volume(self) -> Optional[float]:
        return self.wells[-1]["volume"] if self.wells else None

    @property
    def count(self) -> int:
        return len(self.wells)

    def to_dict(self) -> dict:
        return {
            "size_ml": self.size_ml,
            "plate": self.plate,
            "count": self.count,
            "start_volume": self.start_volume,
            "end_volume": self.end_volume,
            "waste_volume": self.waste_volume,
            "out_volume": self.out_volume,
            "wells": self.wells,
        }


@dataclass
class Curve:
    """A single recorded signal."""

    name: str                      # e.g. "UV 1_280"
    unit: str                      # e.g. "mAU"
    y: np.ndarray                  # amplitude
    volume: np.ndarray             # x axis in mL (length == len(y))
    time: np.ndarray               # x axis in min (length == len(y))
    channel: Optional[str] = None  # "A280" / "A230" / "A455" if a known UV channel

    @property
    def label(self) -> str:
        if self.channel:
            return self.channel
        return self.name

    def x(self, kind: str = "volume", column_volume: Optional[float] = None) -> np.ndarray:
        if kind == "time":
            return self.time
        if kind == "cv" and column_volume:
            return self.volume / float(column_volume)
        return self.volume

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "channel": self.channel,
            "unit": self.unit,
            "n": int(self.y.size),
            "y_min": float(self.y.min()),
            "y_max": float(self.y.max()),
            "v_min": float(self.volume.min()),
            "v_max": float(self.volume.max()),
            "t_min": float(self.time.min()),
            "t_max": float(self.time.max()),
        }


@dataclass
class Run:
    """One UNICORN result (one ZIP archive)."""

    id: str
    name: str
    source: str
    meta: Dict[str, str] = field(default_factory=dict)
    curves: Dict[str, Curve] = field(default_factory=dict)
    fractionation: Optional[Fractionation] = None

    def curve_list(self) -> List[Curve]:
        return list(self.curves.values())

    def uv_curves(self) -> List[Curve]:
        return [c for c in self.curves.values() if c.channel is not None]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "meta": self.meta,
            "column_volume": float(self.meta.get("column_volume") or 0) or None,
            "curves": [c.to_dict() for c in self.curves.values()],
            "fractionation": self.fractionation.to_dict() if self.fractionation else None,
        }


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
def _parse_metadata(zf: zipfile.ZipFile) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    raw = _read_member(zf, "Result.xml")
    if raw is not None:
        try:
            root = ET.fromstring(raw.decode("utf-8-sig", "replace"))
            meta["name"] = (root.findtext("Name") or "").strip()
            meta["system"] = (root.findtext("SystemName") or "").strip()
            meta["folder"] = (root.findtext("FolderPath") or "").strip()
            for crit in root.findall(".//ResultSearchCriteria"):
                k = (crit.findtext("Keyword1") or "").strip()
                v = (crit.findtext("Keyword2") or "").strip()
                extra = (crit.findtext("ExtraDisplayInformation") or "").strip()
                if k == "Column type":
                    meta["column"] = v
                elif k == "Flow rate":
                    meta["flow"] = v
                    meta["flow_unit"] = extra
                elif k == "Frac volume (Elution)":
                    meta["frac_volume"] = v
                    meta["frac_volume_unit"] = extra
                elif k == "Frac tube type (Elution)":
                    meta["frac_plate"] = v
                elif k == "Sample_ID":
                    meta["sample_id"] = v
            # Creation date is base64 RunInformation entry #3.
            infos = root.findall("ResultRunInformation/RunInformation")
            if len(infos) >= 3:
                try:
                    meta["created"] = base64.b64decode(infos[2].text or "").decode("utf-8", "replace")
                except Exception:
                    pass
        except Exception:
            pass
    return meta


# --------------------------------------------------------------------------- #
# Top level
# --------------------------------------------------------------------------- #
def parse_result_zip(data: bytes, source: str = "", run_id: str = "") -> Run:
    """Parse one UNICORN result ZIP given as ``bytes``."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    meta = _parse_metadata(zf)
    name = meta.get("name") or source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    run = Run(id=run_id or name, name=name, source=source, meta=meta)

    chrom_names = sorted(
        (n for n in zf.namelist() if n.lower().startswith("chrom.") and n.lower().endswith(".xml")),
        key=lambda s: (len(s), s),
    )
    multi = len(chrom_names) > 1
    frac = Fractionation()

    for chrom in chrom_names:
        try:
            root = ET.fromstring(zf.read(chrom).decode("utf-8-sig", "replace"))
        except Exception:
            continue
        prefix = chrom.replace(".Xml", "").replace(".xml", "") + " " if multi else ""

        # --- fraction collector events ------------------------------------ #
        for ec in root.findall("EventCurves/EventCurve"):
            if ec.get("EventCurveType") != "Fraction":
                continue
            idx = 0
            for ev in ec.findall("Events/Event"):
                text = (ev.findtext("EventText") or "").strip()
                try:
                    vol = float(ev.findtext("EventVolume"))
                    tm = float(ev.findtext("EventTime"))
                except (TypeError, ValueError):
                    continue
                if _WELL_RE.match(text):
                    idx += 1
                    frac.wells.append({"well": text, "i": idx, "volume": vol, "time": tm})
                elif text.startswith("Waste(Frac)"):
                    frac.waste_volume = vol
                elif text.startswith("Out-Waste"):
                    frac.out_volume = vol

        for curve_el in root.findall("Curves/Curve"):
            cname = (curve_el.findtext("Name") or "").strip()
            if not cname:
                continue
            unit = (curve_el.findtext("AmplitudeUnit") or "").strip()
            fname = curve_el.findtext("CurvePoints/CurvePoint/BinaryCurvePointsFileName")
            if not fname:
                continue
            try:
                res = _extract_curve(zf, fname)
            except Exception:
                res = None
            if not res:
                continue
            vol, amp = res
            if amp is None:
                continue
            n = amp.size

            # Time axis from the XML scan settings.
            dt = 0.0
            try:
                dt = float(curve_el.findtext("DistanceBetweenPoints") or 0.0)
            except Exception:
                dt = 0.0
            try:
                t0 = float(curve_el.findtext("DistanceToStartPoint") or 0.0)
            except Exception:
                t0 = 0.0
            time = t0 + dt * np.arange(n, dtype=np.float64)

            if vol is None or vol.size != n:
                # Reconstruct a volume axis from the flow rate if we must.
                try:
                    flow = float(meta.get("flow") or 0.0)
                except Exception:
                    flow = 0.0
                vol = time * flow if flow else np.arange(n, dtype=np.float64)

            channel = UV_CHANNELS.get(cname, (None, None))[0]
            key = prefix + cname
            run.curves[key] = Curve(
                name=key,
                unit=unit,
                y=amp,
                volume=np.asarray(vol, dtype=np.float64),
                time=time,
                channel=channel,
            )

    # A convenient column volume for "CV" axes (from the first curve that has it).
    for chrom in chrom_names:
        try:
            root = ET.fromstring(zf.read(chrom).decode("utf-8-sig", "replace"))
            cv = root.findtext("Curves/Curve/ColumnVolume")
            if cv:
                run.meta["column_volume"] = str(float(cv))
                break
        except Exception:
            continue

    if frac.wells:
        try:
            frac.size_ml = float(meta.get("frac_volume") or 0.0)
        except ValueError:
            frac.size_ml = 0.0
        frac.plate = meta.get("frac_plate", "")
        run.fractionation = frac

    return run


def parse_many(items) -> List[Run]:
    """``items`` is an iterable of ``(id, source, bytes)``."""
    out: List[Run] = []
    for rid, source, data in items:
        out.append(parse_result_zip(data, source=source, run_id=rid))
    return out


def parse_csv(data: bytes, source: str = "", run_id: str = "") -> Run:
    """Parse a generic wide CSV/TSV table as one run (X column + numeric Y columns).

    The X column is selected from common volume/time header names when possible,
    otherwise the first column is used. Every other numeric column becomes a
    curve; rows with missing/non-numeric values are skipped per curve.
    """
    decoded = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            decoded = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("无法识别 CSV 文件编码")
    sample = decoded[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(decoded), dialect))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise ValueError("CSV 至少需要一行表头和一行数据")
    headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[0])]
    width = len(headers)
    rows = [r[:width] + [""] * max(0, width - len(r)) for r in rows[1:]]
    if width < 2:
        raise ValueError("CSV 需要至少两列：X 坐标和一列或多列信号")

    def number(text):
        text = text.strip().replace("\u2212", "-")
        if not text:
            return None
        # Accept decimal-comma values in semicolon/tab-delimited files.
        if "," in text and "." not in text and dialect.delimiter != ",":
            text = text.replace(",", ".")
        try:
            value = float(text)
            return value if np.isfinite(value) else None
        except ValueError:
            return None

    normalized = [h.lower().replace(" ", "").replace("_", "") for h in headers]
    x_idx = next((i for i, h in enumerate(normalized)
                  if h in ("x", "volume", "time", "minutes", "minute")
                  or any(token in h for token in ("volume(ml)", "elutionvolume", "time(min)", "time(m", "minutes"))), 0)
    x_header = headers[x_idx]
    is_time = any(token in normalized[x_idx] for token in ("time", "min"))
    x_values = [number(r[x_idx]) for r in rows]
    curves = {}
    value_idx = next((i for i, h in enumerate(normalized) if h in ("value", "intensity", "signal")), None)
    group_idxs = [i for i, h in enumerate(normalized)
                  if h in ("run", "series", "curve", "channel", "label") and i != x_idx]
    long_rows = value_idx is not None and bool(group_idxs)
    if long_rows:
        grouped = {}
        for row, xval in zip(rows, x_values):
            yval = number(row[value_idx])
            if xval is None or yval is None:
                continue
            parts = [row[i].strip() for i in group_idxs if row[i].strip()]
            label = " / ".join(parts) or "Signal"
            grouped.setdefault(label, ([], []))[0].append(xval)
            grouped[label][1].append(yval)
        candidates = [(label, xs, ys, value_idx) for label, (xs, ys) in grouped.items()]
    else:
        candidates = []
        for col_idx, header in enumerate(headers):
            if col_idx == x_idx:
                continue
            xs, ys = [], []
            for row, xval in zip(rows, x_values):
                yval = number(row[col_idx])
                if xval is not None and yval is not None:
                    xs.append(xval)
                    ys.append(yval)
            candidates.append((header, xs, ys, col_idx))
    for header, xs, ys, col_idx in candidates:
        if len(xs) < 2:
            continue
        # Curve.volume/time are the app's existing coordinate slots. Preserve
        # the original coordinate name in run metadata for display/export.
        xarr = np.asarray(xs, dtype=np.float64)
        yarr = np.asarray(ys, dtype=np.float64)
        # The current rendering API chooses one global X kind. Keep the CSV
        # coordinate available whichever existing X kind is selected; its true
        # name and semantic kind are also retained in run.meta.
        volume = xarr
        time = xarr
        key = header
        if key in curves:
            key = f"{header} [{col_idx + 1}]"
        unit = ""
        if long_rows:
            unit_idx = next((i for i, h in enumerate(normalized) if h == "unit"), None)
            if unit_idx is not None:
                unit = next((row[unit_idx].strip() for row in rows if row[unit_idx].strip()), "")
        elif header.endswith(")") and "(" in header:
            unit = header.rsplit("(", 1)[1][:-1].strip()
        curves[key] = Curve(name=key, unit=unit, y=yarr, volume=volume,
                             time=time, channel=None)
    if not curves:
        raise ValueError("没有找到包含至少两个有效数据点的数值信号列")
    label = source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0] or "CSV import"
    meta = {"format": "csv", "x_column": x_header, "csv_layout": "long" if long_rows else "wide",
            "x_kind": "time" if is_time else "volume"}
    return Run(id=run_id or label, name=label, source=source, meta=meta, curves=curves)
