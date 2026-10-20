#!/usr/bin/env python3
"""Extract the designed-protein sequence from SnapGene (.dna) plasmids and
compute the extinction coefficient (Pace 1995, reduced state).

The expression cassette is a 6xHis-TEV fusion:  HHHHHHSSGENLYFQGS + <design>.
  * fusion = full insert ORF translation
  * design = fusion[17:]  (after the TEV linker, matches the 'no-tag' sequence)
Outputs a CSV:  design, fusion_seq, design_seq, len, mw, eps280_fusion, eps280_design
"""
from __future__ import annotations
import argparse, csv, glob, os
import snapgene_reader
from Bio.Seq import Seq

from akta import Curve  # noqa: F401  (keep the project import path working)
import analysis

TEV_PREFIX = "HHHHHHSSGENLYFQGS"   # 17 aa, shared by all constructs


def extract_dna(path: str):
    rec = snapgene_reader.snapgene_file_to_seqrecord(path)
    seq = str(rec.seq)
    his_starts = []
    for feat in rec.features:
        if feat.type != "CDS" or int(feat.location.strand) != 1:
            continue
        st = int(feat.location.start)
        aa = str(Seq(seq[st:st + 60]).translate())
        if aa.startswith("HHHHHH"):
            his_starts.append(st)
    if not his_starts:
        return None
    start = min(his_starts)
    fusion = str(Seq(seq[start:]).translate()).split("*")[0]
    return {"fusion": fusion, "design": fusion[len(TEV_PREFIX):] if fusion.startswith(TEV_PREFIX) else fusion}


def _seq_stats(seq: str) -> dict:
    r = analysis.analyze_sequence(seq)
    return {"len": r["length"], "mw_kda": r["mw_avg"] / 1000.0,
            "eps280": r["eps280"], "a280_0_1pct": r["a280_0_1pct"], "pI": r["pI"]}


def load_ev5_xlsx():
    import openpyxl
    f = "/data/codex/webui/sec/data/plasmid/20_ev5/ev5_order_reference_20260915.xlsx"
    if not os.path.exists(f):
        return {}
    wb = openpyxl.load_workbook(f, data_only=True)
    ws = wb["design_protein_sequences"]
    out = {}
    for row in ws.iter_rows(values_only=True):
        if not row or not str(row[0] or "").strip().lower().startswith("e"):
            continue
        name = str(row[0]).strip()
        seq = str(row[5] or "").strip().upper()
        if seq:
            out[name] = {"design": seq}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plasmid_root", nargs="?", default="/data/codex/webui/sec/data/plasmid")
    ap.add_argument("--out", default="/data/codex/webui/sec/data/plasmid/design_sequences.csv")
    args = ap.parse_args()

    rows = []
    for d in sorted(glob.glob(os.path.join(args.plasmid_root, "*"))):
        for f in sorted(glob.glob(os.path.join(d, "*.dna"))):
            design = os.path.basename(f).split(" in ")[0].split(".dna")[0]
            rec = extract_dna(f)
            if not rec:
                print("!! no insert found:", f)
                continue
            fs = _seq_stats(rec["fusion"])
            ds = _seq_stats(rec["design"])
            rows.append({"design": design, "fusion": rec["fusion"], "design_seq": rec["design"],
                         "len_fusion": fs["len"], "mw_fusion_kda": fs["mw_kda"],
                         "eps280_fusion": fs["eps280"], "a280_0_1pct_fusion": fs["a280_0_1pct"],
                         "len_design": ds["len"], "mw_design_kda": ds["mw_kda"],
                         "eps280_design": ds["eps280"], "a280_0_1pct_design": ds["a280_0_1pct"],
                         "pI_design": ds["pI"]})

    # cross-check ev5 against the official xlsx
    xlsx = load_ev5_xlsx()
    mismatch = 0
    for r in rows:
        ref = xlsx.get(r["design"])
        if ref and ref["design"] != r["design_seq"]:
            mismatch += 1
            print(f"!! {r['design']}: .dna vs xlsx differ")
    print(f"extracted {len(rows)} designs; xlsx cross-check mismatches: {mismatch}")

    cols = ["design", "len_design", "eps280_design", "a280_0_1pct_design", "mw_design_kda", "pI_design",
            "len_fusion", "eps280_fusion", "a280_0_1pct_fusion", "mw_fusion_kda",
            "design_seq", "fusion"]
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])
    print("wrote", args.out)

    # quick summary: epsilon range
    eps = [r["eps280_design"] for r in rows]
    print("eps280_design: min=%d max=%d n=%d" % (min(eps), max(eps), len(eps)))
    for r in sorted(rows, key=lambda x: x["design"]):
        print("  %-6s len=%3d eps280=%6d mw=%6.1fkDa" % (r["design"], r["len_design"], r["eps280_design"], r["mw_design_kda"]))
    return rows


if __name__ == "__main__":
    main()
