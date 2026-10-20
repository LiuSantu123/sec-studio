"""Versioned, portable SEC Studio project archive format."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Iterable

import numpy as np

from akta import Curve, Fractionation, Run

PROJECT_FORMAT = "sec-studio-project"
PROJECT_VERSION = 1
MAX_PROJECT_BYTES = 512 * 1024 * 1024
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024


def write_project(state: dict, runs: Iterable[Run]) -> bytes:
    """Serialize the current UI state and full run arrays into a .secproj ZIP."""
    output = io.BytesIO()
    run_rows = []
    payloads = []
    for run_index, run in enumerate(runs):
        archive_path = f"runs/run_{run_index:04d}.npz"
        arrays = {}
        curve_rows = []
        for curve_index, curve in enumerate(run.curves.values()):
            prefix = f"c{curve_index}_"
            arrays[prefix + "y"] = np.asarray(curve.y, dtype=np.float64)
            arrays[prefix + "volume"] = np.asarray(curve.volume, dtype=np.float64)
            arrays[prefix + "time"] = np.asarray(curve.time, dtype=np.float64)
            curve_rows.append({
                "name": curve.name,
                "unit": curve.unit,
                "channel": curve.channel,
                "array_prefix": prefix,
            })
        npz = io.BytesIO()
        np.savez_compressed(npz, **arrays)
        payload = npz.getvalue()
        payloads.append((archive_path, payload))
        run_rows.append({
            "id": run.id,
            "name": run.name,
            "source": run.source,
            "meta": run.meta,
            "fractionation": run.fractionation.to_dict() if run.fractionation else None,
            "curves": curve_rows,
            "data": archive_path,
        })

    manifest = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "state": state,
        "runs": run_rows,
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("project.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
        for archive_path, payload in payloads:
            zf.writestr(archive_path, payload, compress_type=zipfile.ZIP_STORED)
    result = output.getvalue()
    if len(result) > MAX_PROJECT_BYTES:
        raise ValueError("项目文件超过 512 MB 限制")
    return result


def read_project(data: bytes) -> tuple[dict, list[Run]]:
    """Read and validate a .secproj archive without extracting filesystem paths."""
    if len(data) > MAX_PROJECT_BYTES:
        raise ValueError("项目文件超过 512 MB 限制")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("项目文件不是有效的 SEC Studio 项目 ZIP") from exc
    with zf:
        names = zf.namelist()
        if len(names) > 10001 or len(names) != len(set(names)):
            raise ValueError("项目文件成员数量异常或包含重名")
        if sum(item.file_size for item in zf.infolist()) > MAX_UNPACKED_BYTES:
            raise ValueError("项目解压后的数据超过 1 GB 限制")
        if "project.json" not in names:
            raise ValueError("项目缺少 project.json")
        info = zf.getinfo("project.json")
        if info.file_size > 32 * 1024 * 1024:
            raise ValueError("项目索引文件过大")
        try:
            manifest = json.loads(zf.read("project.json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("项目索引无法读取") from exc
        if manifest.get("format") != PROJECT_FORMAT:
            raise ValueError("这不是 SEC Studio 项目")
        if manifest.get("version") != PROJECT_VERSION:
            raise ValueError(f"暂不支持项目版本：{manifest.get('version')}")
        state = manifest.get("state")
        run_rows = manifest.get("runs")
        if not isinstance(state, dict) or not isinstance(run_rows, list):
            raise ValueError("项目索引结构不完整")
        if len(run_rows) > 10000:
            raise ValueError("项目中的 Run 数量过多")

        runs = []
        seen_ids = set()
        for row in run_rows:
            if not isinstance(row, dict) or not isinstance(row.get("curves"), list):
                raise ValueError("项目中的 Run 信息格式错误")
            run_id = str(row.get("id") or "")
            if not run_id or run_id in seen_ids:
                raise ValueError("项目中的 Run ID 缺失或重复")
            seen_ids.add(run_id)
            data_path = row.get("data")
            if data_path not in names or not str(data_path).startswith("runs/run_"):
                raise ValueError("项目曲线数据文件缺失")
            if zf.getinfo(data_path).file_size > MAX_PROJECT_BYTES:
                raise ValueError("项目曲线数据块过大")
            try:
                archive = np.load(io.BytesIO(zf.read(data_path)), allow_pickle=False)
            except Exception as exc:
                raise ValueError("项目曲线数据无法读取") from exc
            curves = {}
            with archive:
                for curve_row in row["curves"]:
                    prefix = curve_row.get("array_prefix", "")
                    try:
                        y = np.asarray(archive[prefix + "y"], dtype=np.float64)
                        volume = np.asarray(archive[prefix + "volume"], dtype=np.float64)
                        time = np.asarray(archive[prefix + "time"], dtype=np.float64)
                    except Exception as exc:
                        raise ValueError("项目缺少曲线数组") from exc
                    if y.ndim != 1 or volume.shape != y.shape or time.shape != y.shape or y.size == 0:
                        raise ValueError("项目曲线坐标和信号长度不一致")
                    curve_name = str(curve_row.get("name") or "")
                    if not curve_name or curve_name in curves:
                        raise ValueError("项目曲线名称缺失或重复")
                    curves[curve_name] = Curve(
                        name=curve_name,
                        unit=str(curve_row.get("unit") or ""),
                        y=y,
                        volume=volume,
                        time=time,
                        channel=curve_row.get("channel"),
                    )
            frac_row = row.get("fractionation")
            frac = None
            if isinstance(frac_row, dict):
                frac = Fractionation(
                    size_ml=float(frac_row.get("size_ml") or 0),
                    plate=str(frac_row.get("plate") or ""),
                    wells=list(frac_row.get("wells") or []),
                    waste_volume=frac_row.get("waste_volume"),
                    out_volume=frac_row.get("out_volume"),
                )
            meta = row.get("meta")
            if not isinstance(meta, dict):
                raise ValueError("项目 Run 元数据格式错误")
            runs.append(Run(
                id=run_id,
                name=str(row.get("name") or run_id),
                source=str(row.get("source") or ""),
                meta=meta,
                curves=curves,
                fractionation=frac,
            ))
        return state, runs
