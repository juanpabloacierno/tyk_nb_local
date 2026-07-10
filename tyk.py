"""
Port of the Colab TyK class for local execution.
Remove Colab-only bits and normalize paths so it works from a local folder.
"""

from __future__ import annotations

import csv
import glob
import heapq
import io
import json
import math
import os
import re
import uuid
import webbrowser
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Evita backends interactivos (MacOSX/Tk) en ejecución batch/CLI.
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt  # noqa: F401  (kept for compatibility)
import networkx as nx  # noqa: F401
import pandas as pd
import plotly.graph_objs as go
import plotly.io as pio
from IPython.display import HTML, clear_output, display  # noqa: F401
from matplotlib import cm, colormaps
from matplotlib import colors as mcolors

try:
    import pycountry  # noqa: F401
except Exception:  # pragma: no cover - optional dependency
    pycountry = None

try:
    from django.utils.translation import gettext as _
except ImportError:
    def _(s):  # type: ignore[misc]
        return s


class TyK:
    def __init__(
        self,
        path_base: str,
        dat_folder: str | None = None,
        json_bcclusters="jsonfiles/BCclusters.json",
        tex_top_clusters=None,
        tex_sub_clusters=None,
        gdf_clusters=None,
        json_cooc="freqs/coocnetworks.json",
    ):
        # Normalize base path to absolute and ensure trailing separator
        base_path = Path(path_base).expanduser().resolve()
        self.path_base = str(base_path) + os.sep

        self.json_bcclusters = self._resolve_path(
            json_bcclusters,
            default_dir="jsonfiles",
            patterns=["*BCclusters*.json"],
            preferred_basename="BCclusters.json",
        )
        self.tex_top_clusters = self._resolve_path(
            tex_top_clusters,
            default_dir="texfiles",
            patterns=["*top_clusters*.tex"],
            preferred_basename="top_clusters.tex",
        )
        self.tex_sub_clusters = self._resolve_path(
            tex_sub_clusters,
            default_dir="texfiles",
            patterns=["*subtop_clusters*.tex"],
            preferred_basename="subtop_clusters.tex",
        )
        self.gdf_clusters = self._resolve_path(
            gdf_clusters,
            default_dir="gdffiles",
            patterns=["*BCclusters*.gdf", "*BCnetwork*.gdf"],
            preferred_basename="BCclusters.gdf",
        )
        self.json_cooc = self._resolve_path(
            json_cooc,
            default_dir="freqs",
            patterns=["*coocnetworks*.json"],
            preferred_basename="coocnetworks.json",
        )

        # Carpeta donde se guardan los HTML interactivos (por defecto, path_base/exports)
        if dat_folder:
            self.dat_folder = os.path.join(self.path_base, dat_folder)
            os.makedirs(self.dat_folder, exist_ok=True)
        else:
            self.dat_folder = None

        # Estructuras en memoria
        # --- TEX labels ---
        self.label_map_top: dict[str, str] = {}  # "1" -> "EMPATHY"
        self.label_map_sub: dict[str, str] = {}  # "1004" -> "PHILOSOPHY"
        self.cluster_name_to_id: dict[str, str] = {}  # "EMPATHY" -> "1"
        self.subcluster_name_to_id: dict[str, str] = {}  # "PHILOSOPHY" -> "1004"
        self.cluster_names: list[str] = []  # nombres TOP
        self.subcluster_names: list[str] = []  # nombres SUB
        self.subclusters_by_top: dict[str, list[str]] = {}  # "1" -> ["1001","1002",...]

        # --- JSON BCclusters ---
        self.bc_clusters: dict[str, Any] = {}
        self.cluster_dict: dict[str, dict[str, Any]] = {}

        # --- JSON cooc ---
        self.cooc_data: dict[str, Any] = {}

        # --- GDF ---
        self.gdf_nodes_top, self.gdf_nodes_sub = [], []
        self.gdf_edges_top, self.gdf_edges_sub = [], []

        # --- Grafos cache ---
        self.G_clusters_top: nx.Graph | None = None
        self.G_sub_by_top: dict[str, nx.Graph] = {}

        self.verbose_notify: bool = True
        self.removed_clusters: set[str] = set()
        self.countries_global_df = None
        self.cluster_summaries: dict[str, str] = {}

        # =========== CARGA INICIAL ==========
        self._load_bcclusters_json()  # carga nodos y rellena label_real; infiere nombres si falta .tex
        self._load_labels()  # parsea .tex si existen (puede quedar vacío)

        self._load_cooc_json()
        self._load_gdf_clusters()
        self._index_subclusters_by_top()
        self._ensure_graph_from_json()
        freq_path = Path(self.path_base) / "freqs" / "freq_countries.dat"
        self.countries_global_df = None
        if freq_path.exists():
            self.countries_global_df = self._read_freq_dat(str(freq_path))
        elif getattr(self, "verbose_notify", False):
            self._notify(
                f"No se encontró <code>{freq_path}</code>; el mapa de países no estará disponible.",
                "warn",
            )
        # Cargar resúmenes solo si no se deshabilita por env (reduce I/O y logs).
        if str(os.environ.get("TYK_SKIP_SUMMARIES", "")).lower() not in {
            "1",
            "true",
            "yes",
        }:
            self.load_cluster_summaries(f"{self.path_base}clusters")

    # ------------------------ CARGA / PARSE ------------------------
    def _read_freq_dat(self, path: str) -> pd.DataFrame:
        with open(path, encoding="utf-8-sig", errors="ignore") as f:
            raw = f.read()

        lines = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("ranking item") or line.lower().startswith(
                "ranking, item"
            ):
                continue
            parts = re.split(r"\s{2,}|\t|,", line)
            parts = [p.strip() for p in parts if p.strip() != ""]
            if len(parts) == 4 and parts[0].isdigit():
                lines.append(parts)
            elif len(parts) == 3 and not parts[0].isdigit():
                lines.append(["", parts[0], parts[1], parts[2]])

        if not lines:
            raise ValueError("No pude parsear el freq_countries.dat")

        tmp = io.StringIO()
        tmp.write("ranking,item,cantidad,frecuencia\n")
        for row in lines:
            r, it, cant, freq = row
            tmp.write(f"{r},{it},{cant},{freq}\n")
        tmp.seek(0)

        df = pd.read_csv(tmp)
        df["item"] = df["item"].astype(str).str.strip()
        df["cantidad"] = (
            pd.to_numeric(df["cantidad"], errors="coerce").fillna(0).astype(int)
        )
        df["frecuencia"] = pd.to_numeric(df["frecuencia"], errors="coerce").fillna(0.0)

        df = df.sort_values(
            ["cantidad", "frecuencia"], ascending=[False, False]
        ).reset_index(drop=True)
        df = df.rename(
            columns={
                "item": "country",
                "cantidad": "articles",
                "frecuencia": "frequency",
            }
        )
        return df[["country", "articles", "frequency"]]

    def _display_label(self, cid: str) -> str:
        cid = str(cid)
        rec = self.cluster_dict.get(cid, {}) or {}
        level = int(rec.get("level", 1) or 1)

        if level == 0:
            lab = self.label_map_top.get(cid)
        else:
            lab = self.label_map_sub.get(cid)

        lab = lab or rec.get("label_real") or rec.get("label") or cid
        return str(lab)

    @staticmethod
    def _base_node_label(label: str) -> str:
        text = str(label or "").strip()
        if not text:
            return ""
        for sep in (" – ", " — "):
            if sep in text:
                head = text.split(sep, 1)[0].strip()
                if head:
                    return head
        return text

    def _collect_top_graph_raw(
        self,
        min_edge_weight: float = 0.0,
        *,
        include_top_subclusters: bool = False,
        top_subcluster_edge_weight: float = 1.0,
        max_subclusters_total: int | None = None,
        max_subclusters_per_top: int | None = None,
    ) -> tuple[list[dict], list[dict]]:
        nodes_raw = list(self.gdf_nodes_top) if self.gdf_nodes_top else []

        expected_top_ids = {
            cid
            for cid, n in self.cluster_dict.items()
            if int(n.get("level", 0)) == 0 and cid not in self.removed_clusters
        }
        have_ids = {str(n.get("id")) for n in nodes_raw if str(n.get("id"))}
        missing = expected_top_ids - have_ids

        for cid in missing:
            n = self.cluster_dict.get(cid, {})
            nodes_raw.append(
                {
                    "id": cid,
                    "label": self._display_label(cid),
                    "size": int(n.get("size", 1) or 1),
                }
            )

        edges_raw = (
            [
                e
                for e in self.gdf_edges_top
                if float(e.get("weight", 0)) >= min_edge_weight
            ]
            if self.gdf_edges_top
            else []
        )

        if not include_top_subclusters:
            return nodes_raw, edges_raw

        try:
            sub_edge_weight = float(top_subcluster_edge_weight)
        except Exception:
            sub_edge_weight = 1.0
        if sub_edge_weight <= 0:
            sub_edge_weight = 1.0

        try:
            total_cap = (
                int(max_subclusters_total)
                if max_subclusters_total is not None
                else 0
            )
        except Exception:
            total_cap = 0
        if total_cap <= 0:
            total_cap = 10**9

        try:
            per_top_cap = (
                int(max_subclusters_per_top)
                if max_subclusters_per_top is not None
                else 0
            )
        except Exception:
            per_top_cap = 0
        if per_top_cap <= 0:
            per_top_cap = 10**9

        def _sid_sort_key(sid: str) -> tuple[int, int, str]:
            node = self.cluster_dict.get(str(sid), {}) or {}
            try:
                size = int(node.get("size", 0) or 0)
            except Exception:
                size = 0
            if str(sid).isdigit():
                return (-size, int(str(sid)), str(sid))
            return (-size, 10**12, str(sid))

        top_ids = [str(n.get("id")) for n in nodes_raw if str(n.get("id"))]
        present_ids = set(top_ids)
        extra_edges: list[dict] = []

        candidates_by_top: dict[str, list[str]] = {}
        for tid in top_ids:
            sub_ids = []
            for raw_sid in list(self.subclusters_by_top.get(str(tid), []) or []):
                sid = str(raw_sid).strip()
                if not sid or sid in self.removed_clusters:
                    continue
                sub_ids.append(sid)
            if not sub_ids:
                continue
            sub_ids = sorted(set(sub_ids), key=_sid_sort_key)
            candidates_by_top[str(tid)] = sub_ids

        selected_pairs: list[tuple[str, str]] = []
        selected_by_top: dict[str, list[str]] = {tid: [] for tid in top_ids}
        rank = 0
        while len(selected_pairs) < total_cap:
            any_added = False
            for tid in top_ids:
                options = candidates_by_top.get(tid, [])
                picked = selected_by_top.get(tid, [])
                if len(picked) >= per_top_cap:
                    continue
                if rank >= len(options):
                    continue
                sid = options[rank]
                if sid in picked:
                    continue
                picked.append(sid)
                selected_by_top[tid] = picked
                selected_pairs.append((tid, sid))
                any_added = True
                if len(selected_pairs) >= total_cap:
                    break
            if not any_added:
                break
            rank += 1

        for tid, sid in selected_pairs:
            if sid not in present_ids:
                node = self.cluster_dict.get(sid, {}) or {}
                try:
                    size = int(node.get("size", 1) or 1)
                except Exception:
                    size = 1
                nodes_raw.append(
                    {
                        "id": sid,
                        "label": self._display_label(sid),
                        "size": max(1, size),
                    }
                )
                present_ids.add(sid)
            if sub_edge_weight >= float(min_edge_weight):
                extra_edges.append(
                    {"source": str(tid), "target": sid, "weight": sub_edge_weight}
                )

        if extra_edges:
            edges_raw = list(edges_raw) + extra_edges

        return nodes_raw, edges_raw

    def _refresh_label_indexes(self) -> None:
        self.cluster_name_to_id = {v: k for k, v in self.label_map_top.items() if v}
        self.subcluster_name_to_id = {v: k for k, v in self.label_map_sub.items() if v}
        self.cluster_names = list(self.cluster_name_to_id.keys())
        self.subcluster_names = list(self.subcluster_name_to_id.keys())

    def _ensure_graph_from_json(self) -> None:
        if not self.cluster_dict:
            return

        if not self.gdf_nodes_top and not self.gdf_nodes_sub:
            for cid, n in self.cluster_dict.items():
                if cid in self.removed_clusters:
                    continue
                cid = str(cid)
                label = n.get("label_real") or n.get("label") or cid
                size = int(n.get("size", 1))
                if int(n.get("level", 0)) == 0:
                    self.gdf_nodes_top.append({"id": cid, "label": label, "size": size})
                else:
                    self.gdf_nodes_sub.append({"id": cid, "label": label, "size": size})
        if (not self.gdf_edges_top and not self.gdf_edges_sub) and self.bc_clusters.get(
            "links"
        ):
            for e in self.bc_clusters["links"]:
                s, t = str(e.get("source")), str(e.get("target"))
                if (
                    not s
                    or not t
                    or s in self.removed_clusters
                    or t in self.removed_clusters
                ):
                    continue
                try:
                    w = float(e.get("weight", e.get("value", 1.0)))
                except Exception:
                    w = 1.0
                ns, nt = self.cluster_dict.get(s, {}), self.cluster_dict.get(t, {})
                ls, lt = int(ns.get("level", 0)), int(nt.get("level", 0))
                if ls == 0 and lt == 0:
                    self.gdf_edges_top.append({"source": s, "target": t, "weight": w})
                elif ls == 1 and lt == 1:
                    sid_top = str(
                        ns.get("id_top")
                        if ns.get("id_top") is not None
                        else (int(s) // 1000 if s.isdigit() else "")
                    )
                    tid_top = str(
                        nt.get("id_top")
                        if nt.get("id_top") is not None
                        else (int(t) // 1000 if t.isdigit() else "")
                    )
                    if sid_top == tid_top and sid_top not in self.removed_clusters:
                        self.gdf_edges_sub.append(
                            {"source": s, "target": t, "weight": w}
                        )

    def _read_text_with_fallback(
        self,
        path: str,
        encodings: list[str] | None = None,
        *,
        errors: str = "strict",
    ) -> str:
        encs = encodings or ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        last_err = None
        for enc in encs:
            try:
                with open(path, encoding=enc, errors=errors) as f:
                    return f.read()
            except UnicodeDecodeError as e:
                last_err = e
                continue
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("latin-1", errors="replace")
        if getattr(self, "verbose_notify", False):
            self._notify(
                f"Advertencia: decodifiqué <code>{path}</code> con fallback latin-1 (caracteres sustituidos).",
                "warn",
            )
        return text

    def _parse_labels(
        self, tex_paths: str | os.PathLike | Sequence[str | os.PathLike]
    ) -> dict[str, str]:
        if not tex_paths:
            return {}

        if isinstance(tex_paths, (str, os.PathLike)):
            tex_paths = [tex_paths]

        labels: dict[str, str] = {}
        for p in tex_paths:
            if not p:
                continue
            p = str(p)
            if not os.path.exists(p):
                if getattr(self, "verbose_notify", False):
                    self._notify(f"No se encontró TEX: <b>{p}</b>", "warn")
                continue

            tex = self._read_text_with_fallback(p)
            labels.update(
                {
                    m[0]: m[1]
                    for m in re.findall(r"Cluster\s+(\d+)\s+\(``(.+?)''\)", tex)
                }
            )

        return labels

    def _load_labels(self) -> None:
        """
        Define los labels finales de clusters y subclusters según la regla oficial:

            Nombre = BaseLabel – SUBJECT1

        donde:
        - BaseLabel usa el nombre histórico (TEX) cuando existe
        - si no existe TEX, cae a stuff["K"] (evitando keywords genéricas como ARTICLE)
        - SUBJECT1 sale de stuff["S"] (o S2 si se quisiera cambiar)
        """

        self.label_map_top = {}
        self.label_map_sub = {}
        debug_labels = str(os.environ.get("TYK_DEBUG_LABELS", "")).lower() in {
            "1",
            "true",
            "yes",
        }
        use_tex_overlay = str(os.environ.get("TYK_LABEL_OVERLAY_TEX", "")).lower() in {
            "1",
            "true",
            "yes",
        }

        tex_top = self._parse_labels(self.tex_top_clusters) if self.tex_top_clusters else {}
        tex_sub = self._parse_labels(self.tex_sub_clusters) if self.tex_sub_clusters else {}

        def pick_first_valid(
            items,
            banned: set[str] | None = None,
            *,
            fallback_to_banned: bool = True,
        ):
            """
            Devuelve el primer término válido de una lista tipo stuff["K"] o stuff["S"].
            """
            banned_norm = {b.upper() for b in (banned or set())}
            first_banned = None
            for it in items:
                term = str(it[0]).strip()
                if term and term != "'":
                    if banned_norm and term.upper() in banned_norm:
                        if first_banned is None:
                            first_banned = term
                        continue
                    return term
            if fallback_to_banned:
                return first_banned
            return None

        generic_keywords = {"ARTICLE"}

        for cid, node in self.cluster_dict.items():
            cid = str(cid)
            lvl = int(node.get("level", 0))
            stuff = node.get("stuff", {}) or {}

            # 1) Keyword (K)
            keyword = pick_first_valid(
                stuff.get("K", []), banned=generic_keywords, fallback_to_banned=False
            )
            keyword_raw = pick_first_valid(stuff.get("K", []))

            # 2) Subject (S)
            subject = pick_first_valid(stuff.get("S", []))

            # 2.5) Base label "como antes" (TEX)
            legacy_label = (tex_top if lvl == 0 else tex_sub).get(cid)
            if legacy_label:
                legacy_label = str(legacy_label).strip()
            if legacy_label == "'":
                legacy_label = None

            if legacy_label:
                base_label = legacy_label
            elif keyword:
                base_label = keyword
            elif keyword_raw:
                base_label = keyword_raw
            elif subject:
                base_label = subject
            else:
                base_label = cid  # último fallback seguro

            # 3) Construcción del label
            if (
                subject
                and base_label
                and subject.casefold() not in str(base_label).casefold()
            ):
                label = f"{base_label} – {subject}"
            else:
                label = str(base_label)
            if debug_labels:
                print(
                    f"[labels] cid={cid} lvl={lvl} legacy={legacy_label!r} keyword={keyword!r} keyword_raw={keyword_raw!r} subject={subject!r} raw_label={label!r}"
                )
            label = self._normalize_label_capital(label)
            if debug_labels:
                print(f"[labels] cid={cid} normalized_label={label!r}")
            node["label_real"] = label

            if lvl == 0:
                self.label_map_top[cid] = label
            else:
                self.label_map_sub[cid] = label

        # =========================
        # Overlay opcional desde TEX
        # (solo si el TEX trae algo usable)
        # =========================
        if use_tex_overlay and tex_top:
            for cid, lbl in tex_top.items():
                if lbl and lbl != "'":
                    lbl = self._normalize_label_capital(lbl)
                    self.label_map_top[str(cid)] = lbl
                    if str(cid) in self.cluster_dict:
                        self.cluster_dict[str(cid)]["label_real"] = lbl

        if use_tex_overlay and tex_sub:
            for cid, lbl in tex_sub.items():
                if lbl and lbl != "'":
                    lbl = self._normalize_label_capital(lbl)
                    self.label_map_sub[str(cid)] = lbl
                    if str(cid) in self.cluster_dict:
                        self.cluster_dict[str(cid)]["label_real"] = lbl

        self._refresh_label_indexes()

    def _load_bcclusters_json(self) -> None:
        """
        Carga BCclusters.json y construye self.cluster_dict.
        NO decide labels.
        """

        self.bc_clusters = {}
        self.cluster_dict = {}

        if not self.json_bcclusters or not os.path.exists(self.json_bcclusters):
            if getattr(self, "verbose_notify", False):
                self._notify(
                    _("<b>BCclusters.json</b> not found. Some functions may not be available."),
                    "warn",
                )
            return

        with open(self.json_bcclusters, encoding="utf-8") as f:
            self.bc_clusters = json.load(f)

        nodes = self.bc_clusters.get("nodes", [])
        for n in nodes:
            cid = str(n.get("name") or n.get("id"))
            n["label_real"] = ""  # se decide después
            self.cluster_dict[cid] = n

    def _load_cooc_json(self) -> bool:
        import gzip

        self.cooc_data = {}
        loaded_ok = False

        if not getattr(self, "json_cooc", None):
            if getattr(self, "verbose_notify", False):
                self._notify(
                    "Sin <b>json_cooc</b> configurado; se omite co-ocurrencia.", "warn"
                )
            return False

        cooc_path = self.json_cooc
        if not os.path.isabs(cooc_path):
            cooc_path = os.path.join(getattr(self, "path_base", "."), cooc_path)

        base_dir = os.path.dirname(cooc_path) or "."

        candidates = []
        if os.path.exists(cooc_path):
            candidates.append(cooc_path)
        candidates += sorted(glob.glob(os.path.join(base_dir, "coocnetworks*.json")))
        candidates += sorted(glob.glob(os.path.join(base_dir, "coocnetworks*.json.gz")))

        if not candidates:
            root = getattr(self, "path_base", ".")
            candidates += sorted(
                glob.glob(
                    os.path.join(root, "**", "coocnetworks*.json"), recursive=True
                )
            )
            candidates += sorted(
                glob.glob(
                    os.path.join(root, "**", "coocnetworks*.json.gz"), recursive=True
                )
            )

        if not candidates:
            if getattr(self, "verbose_notify", False):
                self._notify(
                    f"No se encontró <code>{self.json_cooc}</code> ni variantes "
                    f"<code>coocnetworks*.json(.gz)</code>.",
                    "warn",
                )
            return False

        chosen = candidates[0]

        try:
            if hasattr(self, "_load_json_lenient") and callable(
                self._load_json_lenient
            ):
                data = self._load_json_lenient(chosen)
            else:
                if chosen.endswith(".gz"):
                    with gzip.open(chosen, "rt", encoding="utf-8-sig") as f:
                        data = json.load(f)
                else:
                    with open(chosen, encoding="utf-8-sig") as f:
                        data = json.load(f)
        except Exception as e:
            if getattr(self, "verbose_notify", False):
                self._notify(f"No se pudo leer JSON '{chosen}': {e}", "warn")
            return False

        if not data:
            return False

        nodes = data.get("nodes") or data.get("N") or data.get("items") or []
        links = data.get("links") or data.get("E") or data.get("edges") or []

        norm_nodes, norm_links = [], []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            nid = str(n.get("name") or n.get("id") or n.get("key") or "").strip()
            if not nid:
                continue
            norm_nodes.append(
                {
                    "name": nid,
                    "item": n.get("item", n.get("label", nid)),
                    "type": n.get("type", n.get("kind", "")),
                    "size": int(n.get("size", n.get("count", 1)) or 1),
                }
            )

        for e in links:
            if not isinstance(e, dict):
                continue
            s = str(e.get("source") or e.get("from") or "").strip()
            t = str(e.get("target") or e.get("to") or "").strip()
            if not s or not t:
                continue
            try:
                w = float(e.get("weight", e.get("value", 1.0)))
            except Exception:
                w = 1.0
            norm_links.append({"source": s, "target": t, "weight": w})

        if not norm_nodes or not norm_links:
            if getattr(self, "verbose_notify", False):
                self._notify(
                    f"Co-ocurrencia en <code>{chosen}</code> sin contenido usable "
                    f"(nodes={len(norm_nodes)}, links={len(norm_links)}).",
                    "warn",
                )
            return False

        self.cooc_data = {"nodes": norm_nodes, "links": norm_links}
        if getattr(self, "verbose_notify", False):
            self._notify(
                f"Cargada co-ocurrencia desde <code>{chosen}</code> "
                f"(nodes={len(norm_nodes)}, links={len(norm_links)}).",
                "ok",
            )
        return True

    def _load_gdf_clusters(self) -> None:
        if not self.gdf_clusters or not os.path.exists(self.gdf_clusters):
            return

        text = self._read_text_with_fallback(self.gdf_clusters)
        lines = text.splitlines()
        try:
            node_header_idx = next(
                i for i, l in enumerate(lines) if l.startswith("nodedef>")
            )
            edge_header_idx = next(
                i for i, l in enumerate(lines) if l.startswith("edgedef>")
            )
        except StopIteration:
            self._notify(
                "Formato GDF inválido: faltan encabezados 'nodedef>' o 'edgedef>'.",
                "error",
            )
            return

        node_header = lines[node_header_idx][len("nodedef>") :]
        node_cols = [c.strip().lower() for c in node_header.split(",")]

        def _col_idx(cands):
            for i, name in enumerate(node_cols):
                for c in cands:
                    if name.startswith(c):
                        return i
            return None

        idx_id = _col_idx(["name", "id", "node"]) or 0
        idx_level = _col_idx(["level", "type", "group"])
        idx_size = _col_idx(["size", "weight", "value"])

        self.gdf_nodes_top.clear()
        self.gdf_nodes_sub.clear()
        self.gdf_edges_top.clear()
        self.gdf_edges_sub.clear()

        tops_seen, subs_seen = set(), set()

        reader = csv.reader(
            lines[node_header_idx + 1 : edge_header_idx], delimiter=",", quotechar='"'
        )
        for r in reader:
            if not r:
                continue
            node_id = r[idx_id].strip().strip('"')
            if not node_id:
                continue

            if node_id in self.label_map_top:
                level_tag = "top"
            elif node_id in self.label_map_sub:
                level_tag = "sub"
            else:
                njson = self.cluster_dict.get(node_id)
                if njson is not None:
                    try:
                        level_tag = "sub" if int(njson.get("level", 0)) == 1 else "top"
                    except Exception:
                        level_tag = None
                else:
                    level_tag = None

                if not level_tag:
                    raw_level = (
                        r[idx_level].strip().lower()
                        if idx_level is not None and len(r) > idx_level
                        else ""
                    )
                    if raw_level in ("top", "sub"):
                        level_tag = raw_level
                    elif raw_level in ("0", "1"):
                        level_tag = "sub" if raw_level == "1" else "top"
                    else:
                        level_tag = (
                            "sub"
                            if (node_id.isdigit() and len(node_id) >= 4)
                            else "top"
                        )

            size = 1
            if idx_size is not None and len(r) > idx_size:
                try:
                    size = int(float(r[idx_size]))
                except Exception:
                    size = 1
            if size == 1 and node_id in self.cluster_dict:
                try:
                    size = int(self.cluster_dict[node_id].get("size", 1))
                except Exception:
                    pass

            if level_tag == "top":
                label = self.label_map_top.get(node_id)
            else:
                label = self.label_map_sub.get(node_id)
            if not label and node_id in self.cluster_dict:
                n = self.cluster_dict[node_id]
                label = n.get("label_real") or n.get("label")
            if not label:
                label = node_id

            if level_tag == "top":
                if node_id not in tops_seen:
                    self.gdf_nodes_top.append(
                        {"id": node_id, "label": label, "size": size}
                    )
                    tops_seen.add(node_id)
            else:
                if node_id not in subs_seen:
                    self.gdf_nodes_sub.append(
                        {"id": node_id, "label": label, "size": size}
                    )
                    subs_seen.add(node_id)

        missing_top = set(self.label_map_top.keys()) - tops_seen
        for cid in missing_top:
            n = self.cluster_dict.get(cid, {})
            label = (
                self.label_map_top.get(cid)
                or n.get("label_real")
                or n.get("label")
                or cid
            )
            try:
                size = int(n.get("size", 1))
            except Exception:
                size = 1
            self.gdf_nodes_top.append({"id": cid, "label": label, "size": size})
            tops_seen.add(cid)

        ids_top = tops_seen
        ids_sub = subs_seen
        for line in lines[edge_header_idx + 1 :]:
            if not line.strip():
                continue
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) < 2:
                continue
            s, t = parts[0], parts[1]
            try:
                w = float(parts[2]) if len(parts) > 2 else 1.0
            except Exception:
                w = 1.0
            if s in ids_top and t in ids_top:
                self.gdf_edges_top.append({"source": s, "target": t, "weight": w})
            elif s in ids_sub and t in ids_sub:
                self.gdf_edges_sub.append({"source": s, "target": t, "weight": w})

    def _html_safe(self, s: str) -> str:
        if not s:
            return ""
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return s.replace("\n", "<br>")

    def _shorten(self, text: str, max_chars: int = 300) -> str:
        if not text:
            return ""
        t = text.strip()
        return (t[:max_chars] + "…") if len(t) > max_chars else t

    def add_cluster_summary(self, cluster_id: str, text: str) -> None:
        cid = str(cluster_id)
        self.cluster_summaries[cid] = self._html_safe(text or "")

    def load_cluster_summaries(
        self,
        base_dir: str,
        filename: str = "cluster_overview.txt",
        max_chars_per_file: int = 20000,
    ) -> int:
        import os
        import re

        if not base_dir or not os.path.isdir(base_dir):
            self._notify(f"Directorio no válido: <code>{base_dir}</code>", "error")
            return 0

        count = 0
        for entry in os.listdir(base_dir):
            top_path = os.path.join(base_dir, entry)
            if not os.path.isdir(top_path) or not entry.startswith("top_"):
                continue

            m_top = re.search(r"top_(\d+)", entry)
            if m_top:
                tid = m_top.group(1)
                fpath = os.path.join(top_path, filename)
                if os.path.isfile(fpath):
                    try:
                        txt = open(fpath, encoding="utf-8").read()[:max_chars_per_file]
                        print("LEYENDO: ", fpath)

                        self.cluster_summaries[str(tid)] = self._html_safe(txt)
                        count += 1
                    except Exception:
                        pass

            for sub in os.listdir(top_path):
                sub_dir = os.path.join(top_path, sub)
                if os.path.isdir(sub_dir) and sub.startswith("subcluster_"):
                    m_sub = re.search(r"subcluster_(\d+)", sub)
                    if m_sub:
                        sid = m_sub.group(1)
                        f2 = os.path.join(sub_dir, filename)
                        if os.path.isfile(f2):
                            try:
                                txt2 = open(f2, encoding="utf-8").read()[
                                    :max_chars_per_file
                                ]
                                self.cluster_summaries[str(sid)] = self._html_safe(txt2)
                                print("LEYENDO: ", f2)

                                count += 1
                            except Exception:
                                pass

        self._notify(_("Summaries loaded: <b>{count}</b>").format(count=count), "success")
        return count

    def _is_invalid_label(self, s: str | None) -> bool:
        if s is None:
            return True
        s = str(s).strip()
        if not s:
            return True
        if s in {"'", '"', "''", "“", "”", "’", "`"}:
            return True
        if re.fullmatch(r"[\W_]+", s):
            return True
        if re.match(r"(?i)^foolabel[0-9_]*$", s):
            return True
        return False

    def _normalize_label_capital(self, s: str) -> str:
        s = re.sub(r"\s+", " ", str(s).strip())

        ACR_WHITELIST = {"STEM", "ICT", "ICTS", "IoT"}
        ACR_2_3 = re.compile(r"^[A-Z]{2,3}(?:s|\d+)?$")

        def fix_token(tok: str) -> str:
            parts = tok.split("-")
            fixed = []
            for p in parts:
                if p.upper() in ACR_WHITELIST or ACR_2_3.fullmatch(p):
                    fixed.append(p.upper())
                else:
                    fixed.append(p.capitalize())
            return "-".join(fixed)

        out = s.upper()
        return out

    def _pick_best(
        self, paths: list, preferred_basename: str | None = None
    ) -> str | None:
        if not paths:
            return None
        if preferred_basename:
            exact = [
                p
                for p in paths
                if os.path.basename(p).lower() == preferred_basename.lower()
            ]
            if exact:
                return exact[0]
        return sorted(
            paths, key=lambda p: (len(os.path.basename(p)), os.path.basename(p))
        )[0]

    def _resolve_path(
        self,
        given: str | None = None,
        *,
        default_dir: str,
        patterns: list[str],
        preferred_basename: str | None = None,
    ) -> str | None:
        base = self.path_base
        if given:
            p = given if os.path.isabs(given) else os.path.join(base, given)
            if os.path.exists(p):
                return p

        search_dir = os.path.join(base, default_dir)
        cands: list[str] = []
        for pat in patterns:
            cands.extend(glob.glob(os.path.join(search_dir, pat)))

        best = self._pick_best(cands, preferred_basename=preferred_basename)
        if best and getattr(self, "verbose_notify", False):
            self._notify(
                f"Usando <code>{os.path.relpath(best, base)}</code> (auto-detect).",
                "info",
            )
        return best

    def _load_json_lenient(self, path: str) -> dict:
        raw = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(path, encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue

        if raw is None:
            if getattr(self, "verbose_notify", False):
                self._notify(
                    f"No se pudo decodificar <code>{path}</code> como UTF-8/CP1252/Latin-1.",
                    "error",
                )
            return {}

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        try:
            fixed = self._sanitize_json_text(raw)
            return json.loads(fixed)
        except json.JSONDecodeError as e2:
            if getattr(self, "verbose_notify", False):
                self._notify(
                    f"JSON inválido en <code>{path}</code> (línea {e2.lineno}, col {e2.colno}). "
                    f"No fue posible sanear automáticamente."
                    f"{self._preview_error(raw, getattr(e2, 'pos', None))}",
                    "error",
                )
            return {}

    def _repair_item_strings(self, text: str) -> str:
        t = text
        out = []
        i = 0
        n = len(t)
        while i < n:
            idx = t.find('"item"', i)
            if idx == -1:
                out.append(t[i:])
                break
            out.append(t[i:idx])
            i = idx
            out.append('"item"')
            i += len('"item"')
            while i < n and t[i].isspace():
                out.append(t[i])
                i += 1
            if i < n and t[i] == ":":
                out.append(":")
                i += 1
            while i < n and t[i].isspace():
                out.append(t[i])
                i += 1

            if i < n and t[i] == '"':
                out.append('"')
                i += 1
                buf = []
                while i < n:
                    ch = t[i]
                    if ch in ("\n", "\r"):
                        buf.append(" ")
                        i += 1
                        continue
                    if ch == '"':
                        j = i + 1
                        while j < n and t[j].isspace():
                            j += 1
                        if j < n and (t[j] == "," or t[j] == "}"):
                            out.append("".join(buf))
                            out.append('"')
                            i += 1
                            break
                        else:
                            buf.append("'")
                            i += 1
                            continue
                    if ch == "\\":
                        if i + 1 < n:
                            buf.append("\\")
                            buf.append(t[i + 1])
                            i += 2
                        else:
                            i += 1
                        continue
                    buf.append(ch)
                    i += 1
                else:
                    out.append("".join(buf))
                    out.append('"')
        return "".join(out)

    def _sanitize_json_text(self, text: str) -> str:
        t = text.replace("\r\n", "\n").replace("\ufeff", "")
        t = re.sub(r"//[^\n]*", "", t)
        t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
        t = re.sub(r",(\s*[}\]])", r"\1", t)
        t = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r"\\\\", t)
        t = re.sub(r'(?<=\w)"(?=\w)', "'", t)
        t = self._repair_item_strings(t)

        return t

    def _preview_error(
        self, text: str, pos: int | None = None, window: int = 120
    ) -> str:
        try:
            if pos is None:
                return ""
            start = max(0, pos - window)
            end = min(len(text), pos + window)
            snip = (
                text[start:end]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            return f"<pre style='white-space:pre-wrap;border:1px solid #eee;padding:6px;margin-top:6px'>{snip}</pre>"
        except Exception:
            return ""

    def _index_subclusters_by_top(self) -> None:
        self.subclusters_by_top = {}
        for cid, node in self.cluster_dict.items():
            if int(node.get("level", 0)) != 1 or cid in self.removed_clusters:
                continue
            id_top = node.get("id_top")
            if id_top is None:
                try:
                    id_top = str(int(cid) // 1000)
                except Exception:
                    continue
            tid = str(id_top)
            if tid in self.removed_clusters:
                continue
            self.subclusters_by_top.setdefault(tid, []).append(str(cid))

    def plot_map(
        self,
        *,
        colorscale: str = "Turbo",
        height: int = 650,
        globe: bool = False,
        center_lon: float = -30.0,
        center_lat: float = 0.0,
        title: str = "<b>Countries — Global Publications Distribution</b>",
    ):
        assert (
            self.countries_global_df is not None and not self.countries_global_df.empty
        )

        df = self.countries_global_df.copy()
        df = df.dropna(subset=["country"])
        df["country"] = df["country"].astype(str).str.strip()
        df["articles"] = (
            pd.to_numeric(df["articles"], errors="coerce").fillna(0).astype(int)
        )
        df["frequency"] = pd.to_numeric(df["frequency"], errors="coerce").fillna(0.0)

        df = df.groupby("country", as_index=False).agg(
            articles=("articles", "sum"), frequency=("frequency", "max")
        )

        freq = df["frequency"].astype(float)
        if float(freq.max()) <= 1.0 + 1e-9:
            freq = freq * 100.0
        df["_freq100"] = freq.clip(0, 100)

        z = df["_freq100"].astype(float).to_numpy()
        zmin, zmax = 0.0, 100.0

        hovertext = (
            "<b>"
            + df["country"]
            + "</b><br>"
            + _("Articles: ")
            + df["articles"].map("{:,}".format)
            + "<br>"
            + _("Frequency: ")
            + df["_freq100"].map(lambda x: f"{x:.2f}%")
        )

        fig = go.Figure(
            data=go.Choropleth(
                locations=df["country"],
                locationmode="country names",
                z=z,
                zauto=False,
                zmin=zmin,
                zmax=zmax,
                colorscale=colorscale,
                autocolorscale=False,
                text=hovertext,
                hoverinfo="text",
                marker_line_color="white",
                marker_line_width=0.6,
                showscale=True,
                colorbar=dict(title=_("Frequency (%)")),
            )
        )

        proj = "orthographic" if globe else "natural earth"
        fig.update_geos(
            showframe=False,
            showcoastlines=True,
            coastlinecolor="rgba(90,90,90,0.4)",
            projection_type=proj,
            projection_rotation=dict(lon=center_lon, lat=center_lat) if globe else None,
            showocean=True,
            oceancolor="rgba(173, 216, 230, 0.35)",
            landcolor="rgba(255,255,255,0.0)",
            bgcolor="rgba(0,0,0,0)",
            countrycolor="rgba(80,80,80,0.4)",
        )
        fig.update_layout(
            title=dict(text=title, x=0.5, xanchor="center", font=dict(size=13)),
            font=dict(size=11),
            height=height,
            margin=dict(l=0, r=0, t=50, b=0),
            hoverlabel=dict(bgcolor="white", font_size=11),
        )
        return fig

    def _ensure_naturalearth_countries(self) -> str:
        """
        Asegura que el shapefile de países (Natural Earth 110m) exista localmente.
        Devuelve el path al .shp
        """
        import os
        import urllib.request
        import zipfile

        base_dir = os.path.expanduser("~/.cache/tyk/maps")
        shp_dir = os.path.join(base_dir, "ne_110m_admin_0_countries")
        shp_path = os.path.join(shp_dir, "ne_110m_admin_0_countries.shp")

        if os.path.exists(shp_path):
            return shp_path

        os.makedirs(base_dir, exist_ok=True)

        url = (
            "https://naturalearth.s3.amazonaws.com/110m_cultural/"
            "ne_110m_admin_0_countries.zip"
        )
        zip_path = os.path.join(base_dir, "ne_110m_admin_0_countries.zip")

        print("📥 Descargando Natural Earth (countries 110m)…")

        urllib.request.urlretrieve(url, zip_path)

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(shp_dir)

        if not os.path.exists(shp_path):
            raise RuntimeError("No se pudo preparar el shapefile de Natural Earth")

        return shp_path

    def _plot_countries_static(
        self,
        df,
        *,
        value_col: str,
        title: str,
        save_path: str,
        cmap: str = "viridis",
    ):
        import os

        import geopandas as gpd
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib import colors

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # 🌍 asegurar shapefile
        world_shp = self._ensure_naturalearth_countries()
        world = gpd.read_file(world_shp)

        # merge por ISO3
        gdf = world.merge(
            df,
            how="left",
            left_on="ISO_A3",
            right_on="iso3",
        )

        fig, ax = plt.subplots(figsize=(14, 7))
        vals = gdf[value_col]
        vmin = float(vals.min(skipna=True) if hasattr(vals, "min") else 0.0)
        vmax = float(vals.max(skipna=True) if hasattr(vals, "max") else 0.0)
        if vmax <= vmin:
            vmax = vmin + 1e-6

        cmap_obj = cmap
        if isinstance(cmap, str) and cmap.strip().lower() in {
            "tyk_brand",
            "brand",
            "corporate",
            "tyk",
        }:
            cmap_obj = colors.LinearSegmentedColormap.from_list(
                "tyk_brand_countries",
                ["#1F4E8C", "#4DA6FF", "#8A96A3", "#F2A93B"],
                N=256,
            )

        gdf.plot(
            column=value_col,
            ax=ax,
            cmap=cmap_obj,
            legend=False,
            missing_kwds={
                "color": "lightgrey",
                "label": "No data",
            },
        )

        norm = colors.Normalize(vmin=vmin, vmax=vmax)
        sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap_obj)
        sm.set_array([])
        ticks = list(np.linspace(vmin, vmax, 6))
        cbar = plt.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, ticks=ticks)
        cbar.ax.tick_params(labelsize=8)
        cbar.set_label(_("Frequency (%)"), fontsize=8)

        ax.set_title(title, fontsize=11)
        ax.axis("off")

        plt.tight_layout()
        plt.savefig(save_path, dpi=200)
        plt.close()

    def _iso3_to_numeric(self, iso3: str) -> int | None:
        """ISO 3166-1 numeric code for an alpha-3, for joining with world-atlas topojson `id`s."""
        import pycountry

        if iso3 == "XKX":  # Kosovo has no official ISO 3166-1 numeric code
            return None
        try:
            entry = pycountry.countries.get(alpha_3=iso3)
            return int(entry.numeric) if entry else None
        except Exception:
            return None

    def _d3_sequential_ramp(self, colorscale: str) -> dict:
        """
        Config the client-side D3 choropleth turns into a proper single-hue
        sequential scale (magnitude → light-to-dark, never a rainbow/diverging
        scheme). Recognized d3-scale-chromatic names pass straight through;
        anything else — including the "tyk_brand" default — resolves to a
        validated blue sequential ramp (monotone lightness, light→dark).
        """
        key = (colorscale or "").strip().lower()
        d3_interpolators = {
            "viridis": "interpolateViridis",
            "turbo": "interpolateTurbo",
            "plasma": "interpolatePlasma",
            "cividis": "interpolateCividis",
            "magma": "interpolateMagma",
            "inferno": "interpolateInferno",
            "blues": "interpolateBlues",
            "greens": "interpolateGreens",
            "ylgnbu": "interpolateYlGnBu",
            "ylorrd": "interpolateYlOrRd",
            "warm": "interpolateWarm",
            "cool": "interpolateCool",
        }
        if key in d3_interpolators:
            return {"interpolator": d3_interpolators[key]}
        return {
            "stops": [
                [0.00, "#cde2fb"],
                [0.25, "#9ec5f4"],
                [0.50, "#5598e7"],
                [0.75, "#2a78d6"],
                [1.00, "#0d366b"],
            ]
        }

    def _render_d3_choropleth_html(
        self,
        df,
        *,
        value_col: str = "value",
        articles_col: str = "articles",
        title: str = "",
        height: int = 650,
        colorscale: str = "tyk_brand",
        show_values_as_percent: bool = True,
    ) -> str:
        rows = []
        for _row_idx, r in df.iterrows():
            numeric_id = self._iso3_to_numeric(str(r["iso3"]))
            if numeric_id is None:
                continue
            try:
                value = float(r[value_col])
            except Exception:
                continue
            articles = r.get(articles_col)
            try:
                articles = (
                    int(articles)
                    if articles is not None and not pd.isna(articles)
                    else None
                )
            except Exception:
                articles = None
            rows.append(
                {
                    "id": numeric_id,
                    "country": str(r["country"]),
                    "value": value,
                    "articles": articles,
                }
            )

        div_id = f"tykmap_{uuid.uuid4().hex[:8]}"
        ramp = self._d3_sequential_ramp(colorscale)
        value_label = _("Frequency") if show_values_as_percent else _("Value")
        value_suffix = "%" if show_values_as_percent else ""
        articles_label = _("Articles")
        title_html = (
            f'<div class="tykmap-title">{title}</div>' if title else ""
        )

        template = r"""
<div id="__DIV_ID__" class="tykmap-root">
  __TITLE_HTML__
  <div class="tykmap-canvas"></div>
  <div class="tykmap-legend"></div>
  <div class="tykmap-tooltip" style="display:none;"></div>
</div>
<style>
  #__DIV_ID__ { position: relative; width: 100%; height: __HEIGHT__px; display: flex; flex-direction: column; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; }
  #__DIV_ID__ .tykmap-title { flex: 0 0 auto; font-size: 13px; font-weight: 600; color: #0b0b0b; text-align: center; padding: 4px 0 6px; }
  #__DIV_ID__ .tykmap-canvas { flex: 1 1 auto; min-height: 0; position: relative; background: #f9f9f7; border-radius: 6px; }
  #__DIV_ID__ .tykmap-canvas svg { display: block; width: 100%; height: 100%; }
  #__DIV_ID__ .tykmap-country { stroke: #ffffff; stroke-width: 0.6; vector-effect: non-scaling-stroke; transition: stroke 0.1s; cursor: pointer; }
  #__DIV_ID__ .tykmap-country.is-nodata { fill: #e3e2db; }
  #__DIV_ID__ .tykmap-country:hover { stroke: #0b0b0b; stroke-width: 1.4; }
  #__DIV_ID__ .tykmap-graticule { fill: none; stroke: #d8d7cf; stroke-width: 0.4; vector-effect: non-scaling-stroke; opacity: 0.6; }
  #__DIV_ID__ .tykmap-sphere { fill: none; stroke: #c3c2b7; stroke-width: 0.8; vector-effect: non-scaling-stroke; }
  #__DIV_ID__ .tykmap-zoom-controls { position: absolute; right: 10px; bottom: 10px; display: flex; flex-direction: column; gap: 2px; }
  #__DIV_ID__ .tykmap-zoom-controls button { width: 24px; height: 24px; border: 1px solid #c3c2b7; background: #ffffff; color: #0b0b0b; border-radius: 4px; font-size: 13px; line-height: 1; cursor: pointer; box-shadow: 0 1px 2px rgba(0,0,0,0.12); }
  #__DIV_ID__ .tykmap-zoom-controls button:hover { background: #f0efec; }
  #__DIV_ID__ .tykmap-legend { flex: 0 0 auto; display: flex; align-items: center; gap: 8px; padding: 8px 14px 2px; }
  #__DIV_ID__ .tykmap-legend svg { width: 100%; height: 28px; overflow: visible; }
  #__DIV_ID__ .tykmap-tooltip { position: absolute; pointer-events: none; z-index: 10; background: rgba(11,11,11,0.95); color: #ffffff; font-size: 11px; line-height: 1.5; border-radius: 6px; padding: 6px 9px; box-shadow: 0 2px 8px rgba(0,0,0,0.18); transform: translate(-50%, -100%); white-space: nowrap; }
  #__DIV_ID__ .tykmap-tooltip .tykmap-tt-value { font-weight: 700; }
  #__DIV_ID__ .tykmap-empty { display:flex; align-items:center; justify-content:center; height:100%; color:#898781; font-size:12px; }
</style>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js"></script>
<script>
(function () {
  const root = document.getElementById("__DIV_ID__");
  if (!root) return;
  const canvas = root.querySelector(".tykmap-canvas");
  const legendBox = root.querySelector(".tykmap-legend");
  const tooltip = root.querySelector(".tykmap-tooltip");

  const DATA = __DATA_JSON__;
  const RAMP = __RAMP_JSON__;
  const VALUE_LABEL = __VALUE_LABEL_JSON__;
  const VALUE_SUFFIX = __VALUE_SUFFIX_JSON__;
  const ARTICLES_LABEL = __ARTICLES_LABEL_JSON__;

  const byId = new Map(DATA.map(function (d) { return [d.id, d]; }));
  const maxValue = d3.max(DATA, function (d) { return d.value; }) || 1;

  function buildRamp() {
    if (RAMP.interpolator && d3[RAMP.interpolator]) {
      return d3[RAMP.interpolator];
    }
    const stops = RAMP.stops || [[0, "#cde2fb"], [1, "#0d366b"]];
    return d3.scaleLinear()
      .domain(stops.map(function (s) { return s[0]; }))
      .range(stops.map(function (s) { return s[1]; }))
      .interpolate(d3.interpolateHcl);
  }
  // Sqrt scale: bibliometric country shares are heavily right-skewed (a
  // couple of countries dominate), so a linear map would render nearly
  // every country as the same near-white swatch. Compressing the top end
  // keeps the map visually informative across the whole distribution.
  const color = d3.scaleSequentialSqrt(buildRamp()).domain([0, maxValue]);

  function fmtValue(v) {
    return VALUE_SUFFIX === "%"
      ? (Math.round(v * 100) / 100).toFixed(2) + "%"
      : d3.format(",")(Math.round(v));
  }

  function showTooltip(event, d) {
    tooltip.innerHTML = "";
    const line1 = document.createElement("div");
    const name = document.createElement("b");
    name.textContent = d.country;
    line1.appendChild(name);
    tooltip.appendChild(line1);

    const line2 = document.createElement("div");
    const valSpan = document.createElement("span");
    valSpan.className = "tykmap-tt-value";
    valSpan.textContent = fmtValue(d.value);
    line2.appendChild(document.createTextNode(VALUE_LABEL + ": "));
    line2.appendChild(valSpan);
    tooltip.appendChild(line2);

    if (d.articles != null) {
      const line3 = document.createElement("div");
      line3.textContent = ARTICLES_LABEL + ": " + d3.format(",")(d.articles);
      tooltip.appendChild(line3);
    }

    tooltip.style.display = "block";
    moveTooltip(event);
  }

  function moveTooltip(event) {
    const rect = root.getBoundingClientRect();
    tooltip.style.left = (event.clientX - rect.left) + "px";
    tooltip.style.top = (event.clientY - rect.top - 10) + "px";
  }

  function hideTooltip() {
    tooltip.style.display = "none";
  }

  function draw(topology) {
    if (!document.body.contains(root)) return;
    canvas.innerHTML = "";

    const width = canvas.clientWidth || 600;
    const height = canvas.clientHeight || 360;

    const countries = topojson.feature(topology, topology.objects.countries);
    // Flat (equirectangular) projection: a plain rectangular grid, easier to
    // read at a glance and a natural fit for click-drag pan + scroll zoom.
    const projection = d3.geoEquirectangular().fitSize([width - 8, height - 8], countries);
    const path = d3.geoPath(projection);

    const svg = d3.create("svg")
      .attr("viewBox", [0, 0, width, height])
      .attr("preserveAspectRatio", "xMidYMid meet")
      .style("cursor", "grab");

    const zoomLayer = svg.append("g");

    zoomLayer.append("path")
      .datum({ type: "Sphere" })
      .attr("class", "tykmap-sphere")
      .attr("d", path);

    zoomLayer.append("path")
      .datum(d3.geoGraticule10())
      .attr("class", "tykmap-graticule")
      .attr("d", path);

    zoomLayer.append("g")
      .selectAll("path")
      .data(countries.features)
      .join("path")
      .attr("class", function (f) {
        return byId.has(+f.id) ? "tykmap-country" : "tykmap-country is-nodata";
      })
      .attr("fill", function (f) {
        const d = byId.get(+f.id);
        return d ? color(d.value) : null;
      })
      .attr("d", path)
      .on("mousemove", function (event, f) {
        const d = byId.get(+f.id);
        if (!d) return;
        showTooltip(event, d);
      })
      .on("mouseleave", hideTooltip);

    const zoom = d3.zoom()
      .scaleExtent([1, 8])
      .translateExtent([[0, 0], [width, height]])
      .filter(function (event) {
        // Plain wheel scrolls the surrounding page; ctrl/pinch or the
        // buttons below drive zoom, drag always pans.
        if (event.type === "wheel") return event.ctrlKey || event.metaKey;
        return !event.button;
      })
      .on("start", function () { svg.style("cursor", "grabbing"); })
      .on("end", function () { svg.style("cursor", "grab"); })
      .on("zoom", function (event) { zoomLayer.attr("transform", event.transform); });

    svg.call(zoom).on("dblclick.zoom", function (event) {
      svg.transition().duration(200).call(zoom.scaleBy, 1.6, d3.pointer(event, svg.node()));
    });

    canvas.appendChild(svg.node());
    drawZoomControls(svg, zoom);
    drawLegend();
  }

  function drawZoomControls(svg, zoom) {
    canvas.querySelectorAll(".tykmap-zoom-controls").forEach(function (n) { n.remove(); });

    const controls = document.createElement("div");
    controls.className = "tykmap-zoom-controls";

    const makeBtn = function (label, title, onClick) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      btn.title = title;
      btn.addEventListener("click", onClick);
      return btn;
    };

    controls.appendChild(makeBtn("+", "Zoom in", function () {
      svg.transition().duration(200).call(zoom.scaleBy, 1.5);
    }));
    controls.appendChild(makeBtn("−", "Zoom out", function () {
      svg.transition().duration(200).call(zoom.scaleBy, 1 / 1.5);
    }));
    controls.appendChild(makeBtn("↻", "Reset view", function () {
      svg.transition().duration(200).call(zoom.transform, d3.zoomIdentity);
    }));

    canvas.appendChild(controls);
  }

  function drawLegend() {
    legendBox.innerHTML = "";
    if (!maxValue) return;

    const barW = Math.max(legendBox.clientWidth - 90, 120);
    const barH = 10;
    const steps = 40;

    const svg = d3.create("svg").attr("width", "100%").attr("height", 28)
      .attr("viewBox", [0, 0, barW + 90, 28]);

    const gradId = "__DIV_ID__-grad";
    const defs = svg.append("defs");
    const grad = defs.append("linearGradient").attr("id", gradId)
      .attr("x1", "0%").attr("x2", "100%");
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      grad.append("stop").attr("offset", (t * 100) + "%").attr("stop-color", color(t * maxValue));
    }

    svg.append("text").attr("x", 0).attr("y", 20).attr("font-size", 10).attr("fill", "#898781").text("0" + VALUE_SUFFIX);
    svg.append("rect").attr("x", 26).attr("y", 8).attr("width", barW).attr("height", barH)
      .attr("rx", 3).attr("fill", "url(#" + gradId + ")");
    svg.append("text").attr("x", barW + 32).attr("y", 20).attr("font-size", 10).attr("fill", "#898781")
      .text((VALUE_SUFFIX === "%" ? maxValue.toFixed(1) : d3.format(",.0f")(maxValue)) + VALUE_SUFFIX);

    legendBox.appendChild(svg.node());
  }

  let topologyCache = null;
  fetch("https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json")
    .then(function (r) { return r.json(); })
    .then(function (topology) {
      topologyCache = topology;
      draw(topology);
    })
    .catch(function () {
      canvas.innerHTML = '<div class="tykmap-empty">Unable to load map data.</div>';
    });

  let resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (topologyCache) draw(topologyCache);
    }, 150);
  });
})();
</script>
"""
        html = (
            template.replace("__DIV_ID__", div_id)
            .replace("__HEIGHT__", str(height))
            .replace("__TITLE_HTML__", title_html)
            .replace("__DATA_JSON__", json.dumps(rows))
            .replace("__RAMP_JSON__", json.dumps(ramp))
            .replace("__VALUE_LABEL_JSON__", json.dumps(str(value_label)))
            .replace("__VALUE_SUFFIX_JSON__", json.dumps(value_suffix))
            .replace("__ARTICLES_LABEL_JSON__", json.dumps(str(articles_label)))
        )
        return html

    def plot_countries_map_global(
        self,
        *,
        engine: str = "plotly",
        height: int = 650,
        colorscale: str = "tyk_brand",
        show_values_as_percent: bool = True,
        exporting: bool = False,
        save_path: str | None = None,
        method: str = "modern",
    ):

        if self.countries_global_df is None or self.countries_global_df.empty:
            self._notify(
                _("No global country data available. Run tyk.refresh_aggregates()."),
                "warn",
            )
            return

        df = self.countries_global_df.copy()
        df = df.dropna(subset=["country"])
        df = df.rename(columns={"frequency": "value"})
        df["value"] = df["value"].fillna(0)

        # ---------- ISO3 ----------
        import pycountry

        # Build a comprehensive exact-match lookup — no fuzzy search (too slow on large files)
        _iso3_lookup: dict[str, str] = {}
        for _c in pycountry.countries:
            iso3 = _c.alpha_3
            _iso3_lookup[_c.name] = iso3
            _iso3_lookup[_c.alpha_2] = iso3
            _iso3_lookup[_c.alpha_3] = iso3
            if hasattr(_c, "common_name"):
                _iso3_lookup[_c.common_name] = iso3
            if hasattr(_c, "official_name"):
                _iso3_lookup[_c.official_name] = iso3

        # Bibliometric / WoS / Scopus name variants not covered by pycountry
        _iso3_lookup.update({
            "USA": "USA",
            "UK": "GBR",
            "England": "GBR",
            "Scotland": "GBR",
            "Wales": "GBR",
            "Northern Ireland": "GBR",
            "Russia": "RUS",
            "Iran": "IRN",
            "South Korea": "KOR",
            "North Korea": "PRK",
            "Czech Republic": "CZE",
            "Taiwan": "TWN",
            "Viet Nam": "VNM",
            "Hong Kong": "HKG",
            "Peoples R China": "CHN",
            "Democratic Republic of the Congo": "COD",
            "Ivory Coast": "CIV",
            "Syria": "SYR",
            "Bolivia": "BOL",
            "Venezuela": "VEN",
            "Tanzania": "TZA",
            "Macedonia": "MKD",
            "Moldova": "MDA",
            "Kosovo": "XKX",
            "Palestine": "PSE",
            "Laos": "LAO",
        })

        df["iso3"] = df["country"].map(lambda n: _iso3_lookup.get(str(n).strip()))
        df = df.dropna(subset=["iso3"])

        if df.empty:
            self._notify(_("Could not map countries to ISO3 codes."), "error")
            return

        title = _("Countries — Global distribution of publications")

        # =========================================================
        # EXPORTACIÓN PDF → MAPA ESTÁTICO
        # =========================================================
        if exporting:
            if not save_path:
                raise ValueError("exporting=True requiere save_path")

            self._plot_countries_static(
                df=df,
                value_col="value",
                title=title,
                save_path=save_path,
                cmap=colorscale,
            )
            return

        # =========================================================
        # NOTEBOOK → D3.js (interactive, modern default)
        # =========================================================
        if method not in ("plotly", "classic", "legacy"):
            html = self._render_d3_choropleth_html(
                df,
                value_col="value",
                articles_col="articles",
                title=title,
                height=height,
                colorscale=colorscale,
                show_values_as_percent=show_values_as_percent,
            )
            display(HTML(html))
            return

        # =========================================================
        # NOTEBOOK → PLOTLY (legacy fallback, method="plotly")
        # =========================================================
        import plotly.graph_objects as go

        arts_col = df.get("articles", 0).fillna(0).astype(int)
        freq_label = _("Frequency: ") if show_values_as_percent else _("Value: ")
        val_fmt = df["value"].apply(lambda v: f"{v:.2f}%" if show_values_as_percent else f"{v:,}")
        df["hover"] = (
            "<b>" + df["country"] + "</b><br>"
            + freq_label + val_fmt + "<br>"
            + _("Articles: ") + arts_col.astype(str)
        )

        choropleth_colorscale = colorscale
        if isinstance(colorscale, str) and colorscale.strip().lower() in {
            "tyk_brand",
            "brand",
            "corporate",
            "tyk",
        }:
            choropleth_colorscale = [
                [0.00, "#1F4E8C"],
                [0.45, "#4DA6FF"],
                [0.78, "#8A96A3"],
                [1.00, "#F2A93B"],
            ]

        fig = go.Figure(
            data=go.Choropleth(
                locations=df["iso3"],
                z=df["value"],
                text=df["hover"],
                hoverinfo="text",
                colorscale=choropleth_colorscale,
                colorbar_title=_("Frequency (%)")
                if show_values_as_percent
                else _("Amount"),
                marker_line_color="white",
                marker_line_width=0.6,
            )
        )

        fig.update_layout(
            title=dict(
                text=f"<b>{title}</b>",
                x=0.5,
                xanchor="center",
                yanchor="top",
                font=dict(size=13, color="#222"),
            ),
            font=dict(size=11),
            geo=dict(
                showframe=False,
                showcoastlines=True,
                projection_type="natural earth",
            ),
            height=height,
            margin=dict(l=0, r=0, t=50, b=0),
        )

        self._show_figure(fig)

    def plot_countries_map_cluster(
        self,
        cluster_id: str,
        *,
        height: int = 650,
        colorscale: str = "tyk_brand",
        show_values_as_percent: bool = True,
        exporting: bool = False,
        save_path: str | None = None,
    ):
        """
        Mapa por países para un clúster específico usando su distribución C.
        Mantiene el mismo formato que plot_countries_map_global.
        """
        cluster = self.get_cluster(cluster_id)
        data = (cluster.get("stuff", {}) or {}).get("C", [])
        size = int(cluster.get("size", 0) or 0)

        if not data:
            self._notify(
                _("No country distribution (C) for cluster {id}.").format(id=cluster_id),
                "warn",
            )
            return

        rows = []
        for entry in data:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            country = entry[0]
            try:
                freq = float(entry[1])
            except Exception:
                continue
            articles = round(size * freq / 100.0) if size else None
            rows.append({"country": country, "value": freq, "articles": articles})

        if not rows:
            self._notify(
                _("Could not build country table for cluster {id}.").format(id=cluster_id),
                "warn",
            )
            return

        import pandas as pd

        df = pd.DataFrame(rows)
        df = df.dropna(subset=["country"])

        def _country_to_iso3(name: str):
            import pycountry

            aliases = {
                "United States": "USA",
                "United States of America": "USA",
                "UK": "GBR",
                "England": "GBR",
                "Russia": "RUS",
                "Iran": "IRN",
                "South Korea": "KOR",
                "North Korea": "PRK",
                "Czech Republic": "CZE",
                "Taiwan": "TWN",
                "Viet Nam": "VNM",
                "Hong Kong": "HKG",
                "Democratic Republic of the Congo": "COD",
                "Ivory Coast": "CIV",
            }
            name = str(name).strip()
            if name in aliases:
                return aliases[name]
            try:
                return pycountry.countries.search_fuzzy(name)[0].alpha_3
            except Exception:
                return None

        df["iso3"] = df["country"].apply(_country_to_iso3)
        df = df.dropna(subset=["iso3"])

        if df.empty:
            self._notify(
                _("Could not map countries to ISO3 for cluster {id}.").format(id=cluster_id),
                "error",
            )
            return

        title = _("Countries — Cluster {id}").format(id=cluster_id)

        if exporting:
            if not save_path:
                raise ValueError("exporting=True requiere save_path")
            self._plot_countries_static(
                df=df,
                value_col="value",
                title=title,
                save_path=save_path,
                cmap=colorscale,
            )
            return

        import plotly.graph_objects as go

        hover_text = []
        for _row_idx, r in df.iterrows():
            val = r["value"]
            arts = r.get("articles", 0) or 0
            val_str = f"{val:.2f}%" if show_values_as_percent else f"{val:,}"
            hover_text.append(
                f"<b>{r['country']}</b><br>"
                f"{_('Frequency: ')}{val_str}<br>"
                f"{_('Articles: ')}{int(arts)}"
            )
        df["hover"] = hover_text

        choropleth_colorscale = colorscale
        if isinstance(colorscale, str) and colorscale.strip().lower() in {
            "tyk_brand",
            "brand",
            "corporate",
            "tyk",
        }:
            choropleth_colorscale = [
                [0.00, "#1F4E8C"],
                [0.45, "#4DA6FF"],
                [0.78, "#8A96A3"],
                [1.00, "#F2A93B"],
            ]

        fig = go.Figure(
            data=go.Choropleth(
                locations=df["iso3"],
                z=df["value"],
                text=df["hover"],
                hoverinfo="text",
                colorscale=choropleth_colorscale,
                colorbar_title=_("Frequency (%)")
                if show_values_as_percent
                else _("Amount"),
                marker_line_color="white",
                marker_line_width=0.6,
            )
        )

        fig.update_layout(
            title=dict(
                text=f"<b>{title}</b>",
                x=0.5,
                xanchor="center",
                yanchor="top",
                font=dict(size=13, color="#222"),
            ),
            font=dict(size=11),
            geo=dict(
                showframe=False,
                showcoastlines=True,
                projection_type="natural earth",
            ),
            height=height,
            margin=dict(l=0, r=0, t=50, b=0),
        )

        self._show_figure(fig)

    def list_clusters(self, top: bool = True, show: bool = True):
        keyer = lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x))
        removed = getattr(self, "removed_clusters", set())

        if top:
            ids = [cid for cid in self.label_map_top if cid not in removed]
            pairs = [
                (cid, self._normalize_label_capital(self.label_map_top[cid]))
                for cid in sorted(ids, key=keyer)
            ]
            if show:
                return self._render_clusters_table(pairs, level="TOP")

            return pairs

        ids = [cid for cid in self.label_map_sub if cid not in removed]
        pairs = [
            (cid, self._normalize_label_capital(self.label_map_sub[cid]))
            for cid in sorted(ids, key=keyer)
        ]
        if show:
            return self._render_clusters_table(pairs, level="SUB")

        return pairs

    def list_subclusters(self, top_id: str, show: bool = True):
        tid = str(top_id)
        keyer = lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x))
        removed = getattr(self, "removed_clusters", set())
        subs = [
            sid for sid in self.subclusters_by_top.get(tid, []) if sid not in removed
        ]
        subs = sorted(subs, key=keyer)

        pairs = []
        for sid in subs:
            name = self._normalize_label_capital(
                self.label_map_sub.get(sid)
                or self.cluster_dict.get(sid, {}).get("label_real", sid)
            )
            pairs.append((sid, name))
        if show:
            return self._render_clusters_table(pairs, level="SUB", top_id=tid)
        return pairs

    def _render_clusters_table(self, pairs: list, level: str, top_id: str = None):
        from IPython.display import HTML, display

        if not pairs:
            if level == "TOP":
                self._notify(_("No TOP clusters available."), "warn")
            else:
                if top_id:
                    self._notify(
                        _("TOP <b>{top}</b> has no subclusters.").format(
                            top=self.label_map_top.get(top_id, top_id)
                        ),
                        "warn",
                    )
                else:
                    self._notify(_("No subclusters to display."), "warn")
            return

        show_top_col = level == "SUB" and not top_id
        _th_id = "ID"
        _th_name = _("Name")
        _th_articles = _("Articles")
        _th_subclusters = _("Subclusters")
        _th_style_l = "padding:5px 8px; text-align:left; font-size:11px;"
        _th_style_r = "padding:5px 8px; text-align:right; font-size:11px;"
        if level == "TOP":
            thead = (
                f"<th style='{_th_style_l}'>{_th_id}</th>"
                f"<th style='{_th_style_l}'>{_th_name}</th>"
                f"<th style='{_th_style_r}'>{_th_articles}</th>"
                f"<th style='{_th_style_r}'>{_th_subclusters}</th>"
            )
        else:
            thead = (
                f"<th style='{_th_style_l}'>{_th_id}</th>"
                f"<th style='{_th_style_l}'>{_th_name}</th>"
                f"<th style='{_th_style_r}'>{_th_articles}</th>"
                + (
                    f"<th style='{_th_style_l}'>TOP</th>"
                    if show_top_col
                    else ""
                )
            )

        _td_l = "padding:4px 8px; font-size:11px;"
        _td_r = "padding:4px 8px; font-size:11px; text-align:right;"
        rows_html = []
        for cid, name in pairs:
            c = self.cluster_dict.get(cid, {})
            size = int(c.get("size", 0))
            if level == "TOP":
                nsubs = len(self.subclusters_by_top.get(cid, []))
                extra_cells = f"<td style='{_td_r}'>{nsubs}</td>"
            else:
                top_name = ""
                if show_top_col:
                    tid = (
                        str(c.get("id_top"))
                        if c.get("id_top") is not None
                        else str(int(cid) // 1000 if str(cid).isdigit() else "")
                    )
                    top_name = self.label_map_top.get(tid, tid)
                extra_cells = (
                    f"<td style='{_td_l}'>{top_name}</td>"
                    if show_top_col
                    else ""
                )

            rows_html.append(
                "<tr>"
                f"<td style='{_td_l}'><code>{cid}</code></td>"
                f"<td style='{_td_l}'>{name}</td>"
                f"<td style='{_td_r}'>{size}</td>"
                f"{extra_cells}"
                "</tr>"
            )
        body = "".join(rows_html)

        title = (
            _("Available <b>TOP</b> Clusters (total: {total})").format(total=len(pairs))
            if level == "TOP"
            else (
                _("Subclusters of <b>{top}</b> (ID {id}) (total: {total})").format(
                    top=self.label_map_top.get(top_id, top_id), id=top_id, total=len(pairs)
                )
                if top_id
                else _("Available Subclusters (total: {total})").format(total=len(pairs))
            )
        )

        html = f"""
        <details open style="margin:8px 0">
          <summary style="cursor:pointer; font-family:sans-serif; font-size:12px;">{title}</summary>
          <div style="margin-top:6px; max-width:800px;">
            <table style="width:100%; border-collapse:collapse; font-family:sans-serif; font-size:11px;
                          background:#ffffff; color:#222; border:1px solid #d7dbe2;">
              <thead style="background:#eef2f7; color:#222; border-bottom:1px solid #d7dbe2;">
                <tr>{thead}</tr>
              </thead>
              <tbody>
                {body}
              </tbody>
            </table>
          </div>
        </details>
        <style>
          details table tbody tr:nth-child(odd)  {{ background:#fafbfe; }}
          details table tbody tr:nth-child(even) {{ background:#ffffff; }}
          details table code {{ color:#374151; background:#f3f4f6; padding:1px 4px; border-radius:3px; font-size:10px; }}
        </style>
        """

        # hint = (
        #     "Elegí un <b>TOP</b> por <b>ID</b> o por <b>Nombre</b> donde corresponda."
        #     if level == "TOP"
        #     else (
        #         "Elegí un <b>SUB</b> por <b>ID</b> o <b>Nombre</b> para visualizar."
        #         if top_id
        #         else "Indicá primero un <b>TOP</b> para filtrar sus subclusters."
        #     )
        # )
        # self._notify(hint, "info")
        display(HTML(html))

    def get_cluster(self, cluster_id: str) -> dict[str, Any]:
        c = self.cluster_dict.get(str(cluster_id))
        if not c:
            raise ValueError(f"Cluster {cluster_id} no encontrado en BCclusters.json")
        return c

    def _build_pdf_map(self) -> dict[str, str]:
        """Scan clusters directory and return {cluster_id: '/pdf/relative/path'} for TOP and subcluster PDFs."""
        clusters_dir = os.path.join(self.path_base, "clusters")
        pdf_map: dict[str, str] = {}
        if not os.path.isdir(clusters_dir):
            return pdf_map
        for top_entry in os.scandir(clusters_dir):
            if not top_entry.is_dir():
                continue
            for fname in os.listdir(top_entry.path):
                if fname.startswith("cluster_") and fname.endswith("_report.pdf"):
                    cid = fname[len("cluster_"):-len("_report.pdf")]
                    rel = os.path.relpath(
                        os.path.join(top_entry.path, fname)
                    ).replace(os.sep, "/")
                    pdf_map[cid] = f"/pdf/{rel}"
            for sub_entry in os.scandir(top_entry.path):
                if not sub_entry.is_dir() or not sub_entry.name.startswith("subcluster_"):
                    continue
                for fname in os.listdir(sub_entry.path):
                    if fname.startswith("cluster_") and fname.endswith("_report.pdf"):
                        cid = fname[len("cluster_"):-len("_report.pdf")]
                        rel = os.path.relpath(
                            os.path.join(sub_entry.path, fname)
                        ).replace(os.sep, "/")
                        pdf_map[cid] = f"/pdf/{rel}"
        return pdf_map

    def _load_subcluster_detail_map(self, tid: str, max_chars: int = 20000) -> dict[str, str]:
        """Return {sub_id: html_text} from text_blocks/subclusters_detail_{sub_id}.txt for one TOP."""
        import re
        clusters_dir = os.path.join(self.path_base, "clusters")
        result: dict[str, str] = {}
        if not os.path.isdir(clusters_dir):
            return result
        top_dir = next(
            (e.path for e in os.scandir(clusters_dir)
             if e.is_dir() and e.name.startswith(f"top_{tid}_")),
            None,
        )
        if not top_dir:
            return result
        for entry in os.scandir(top_dir):
            if not entry.is_dir() or not entry.name.startswith("subcluster_"):
                continue
            m = re.search(r"subcluster_(\d+)", entry.name)
            if not m:
                continue
            sid = m.group(1)
            fpath = os.path.join(entry.path, "text_blocks", f"cluster_desc_{sid}.txt")
            if os.path.isfile(fpath):
                try:
                    txt = open(fpath, encoding="utf-8").read()[:max_chars]
                    result[sid] = self._html_safe(txt)
                except Exception:
                    pass
        return result

    def _render_vis_network(
        self,
        nodes: list,
        edges: list,
        title: str = "Red interactiva",
        *,
        palette: str = "YlGnBu",
        show_colorbar: bool = True,
        edge_weight_threshold: float | None = None,
        scaling_min: int = 8,
        scaling_max: int = 36,
        height_px: int = 680,
        width_px: int | None = None,
        mode: str = "auto",
        outfile: str | None = None,
        open_in_browser: bool = True,
        show_summary_panel: bool = False,
        summaries_map: dict[str, str] | None = None,
        pdf_map: dict[str, str] | None = None,
    ) -> str | None:
        vals = [float(n.get("raw", n.get("value", 1))) for n in nodes] or [1.0]

        vmin, vmax = (min(vals), max(vals))
        try:
            cmap = colormaps.get_cmap(palette)
        except Exception:
            cmap = colormaps.get_cmap("YlGnBu")

        gradient_css = (
            "linear-gradient(to top, "
            + ", ".join(mcolors.to_hex(cmap(i / 255.0)) for i in range(256))
            + ")"
        )

        if summaries_map:
            for n in nodes:
                nid = str(n.get("id"))
                if nid in summaries_map and not n.get("title"):
                    snippet = self._shorten(summaries_map[nid], 280)
                    n["title"] = (
                        f"<b>{n.get('label', '')}</b><br><div style='max-width:360px'>{snippet}</div>"
                    )

        div_id = f"vis_{uuid.uuid4().hex}"
        panel_id = f"panel_{uuid.uuid4().hex}"

        options_json = f"""
            {{
              "physics": {{
                "enabled": true,
                "solver": "barnesHut",
                "barnesHut": {{
                  "gravitationalConstant": -25000,
                  "springLength": 180,
                  "springConstant": 0.03,
                  "damping": 0.85,
                  "avoidOverlap": 0.3
                }},
                "minVelocity": 0.75,
                "stabilization": {{ "iterations": 200 }}
              }},
              "interaction": {{ "hover": true, "dragNodes": true, "dragView": true, "zoomView": true }},
              "edges": {{
                "smooth": false,
                "color": {{ "color": "rgba(120,120,120,0.28)", "highlight": "rgba(100,100,100,0.50)" }}
              }},
              "nodes": {{
                "shape": "dot",
                "scaling": {{ "min": {scaling_min}, "max": {scaling_max} }},
                "font": {{ "face": "Inter, Arial, sans-serif", "size": 11, "color": "#233" }},
                "borderWidth": 1
              }},
              "layout": {{ "improvedLayout": true, "randomSeed": 7 }}
            }}
            """.strip()

        def _slug(s: str) -> str:
            s = re.sub(r"\s+", "_", s.strip())
            s = re.sub(r"[^\w\-.]+", "", s)
            return s[:80] or "graph"

        def _env_is_vscode():
            return "VSCODE_PID" in os.environ

        _lbl_size = _("Size")
        _lbl_edge_threshold = _("Edge threshold")
        colorbar_html = ""
        if show_colorbar:
            threshold_html = (
                f"<div style='margin-top:6px;font-size:10px;color:#333;'>{_lbl_edge_threshold} ≥ {edge_weight_threshold:g}</div>"
                if edge_weight_threshold is not None
                else ""
            )
            colorbar_html = f"""
            <div style="position:absolute; top:16px; right:16px; background:white; border:1px solid #e1e5ea;
                        border-radius:6px; padding:6px 10px; font-family:sans-serif; font-size:11px; color:#222; text-align:center;">
              <div style="font-weight:600; margin-bottom:4px;">{_lbl_size}</div>
              <div style="margin-bottom:3px;">{int(vmax)}</div>
              <div style="width:16px; height:120px; background:{gradient_css}; border:1px solid #ccc; margin:0 auto;"></div>
              <div style="margin-top:3px;">{int(vmin)}</div>
              {threshold_html}
            </div>
            """
        elif edge_weight_threshold is not None:
            colorbar_html = f"""
            <div style="position:absolute; top:16px; right:16px; background:white; border:1px solid #e1e5ea;
                        border-radius:6px; padding:6px 10px; font-family:sans-serif; font-size:11px; color:#222; text-align:center;">
              <div style="font-weight:600;">{_lbl_edge_threshold}</div>
              <div style="margin-top:3px;">≥ {edge_weight_threshold:g}</div>
            </div>
            """

        _js_cluster = _("Cluster")
        _js_no_summary = _("No summary available.")
        _js_view_report = _("View full report")
        _js_click_prompt = _("Click a node to read its summary")
        nodes_json = json.dumps(nodes, ensure_ascii=False)
        edges_json = json.dumps(edges, ensure_ascii=False)
        summaries_json = json.dumps(summaries_map or {}, ensure_ascii=False)
        pdf_map_js = json.dumps(pdf_map or {}, ensure_ascii=False)

        tooltip_html = f"""
        <div id="{div_id}_tip"
            style="position:absolute; display:none; pointer-events:none;
                    background:white; border:1px solid #ddd; border-radius:6px;
                    padding:8px 10px; box-shadow:0 2px 10px rgba(0,0,0,.12);
                    max-width:320px; z-index:3; color:#111; font-family:sans-serif; font-size:13px;">
        </div>
        """

        root_width = f"{int(width_px)}px" if width_px else "100%"

        if show_summary_panel:
            sidebar_html = f"""
            <div id="{panel_id}" style="flex:0 0 300px; height:{height_px}px; overflow-y:auto;
                border:1px solid #d8e4ff; border-radius:8px; background:#f6f9ff;
                font-family:sans-serif; font-size:12px; color:#123; box-sizing:border-box;">
              <div id="{panel_id}_placeholder" style="height:100%; display:flex; align-items:center;
                  justify-content:center; padding:24px; text-align:center; color:#8899bb; font-style:italic; line-height:1.5;">
                {_js_click_prompt}
              </div>
              <div id="{panel_id}_content" style="display:none; padding:14px 16px;">
                <div id="{panel_id}_title" style="font-weight:600; font-size:13px; color:#112; margin-bottom:10px; line-height:1.3;"></div>
                <div id="{panel_id}_body" style="line-height:1.6; color:#234;"></div>
              </div>
            </div>
            """
            graph_area = f"""
          <div style="display:flex; gap:14px; align-items:flex-start;">
            <div style="flex:1 1 0; min-width:0; position:relative;">
              <div id="{div_id}" style="width:100%; height:{height_px}px; border:1px solid #e1e5ea; border-radius:8px; background-color:white;"></div>
              {colorbar_html}
              {tooltip_html}
            </div>
            {sidebar_html}
          </div>"""
        else:
            graph_area = f"""
          <div style="position:relative;">
            <div id="{div_id}" style="width:100%; height:{height_px}px; border:1px solid #e1e5ea; border-radius:8px; background-color:white;"></div>
            {colorbar_html}
            {tooltip_html}
          </div>"""

        html = f"""
        <div data-tyk-root="1" style="width:{root_width}; max-width:{root_width};">
          <div style="font-family:sans-serif;margin:6px 0 10px 0;font-weight:600">{title}</div>
          {graph_area}
        </div>

        <script type="text/javascript">
        (function(){{
          window.__TYK_NETWORK_READY = false;
          function ensureVis(callback) {{
            if (window.vis && window.vis.Network) {{ callback(); return; }}
            var s = document.createElement('script');
            s.src = "https://unpkg.com/vis-network@9.1.6/dist/vis-network.min.js";
            s.onload = callback;
            document.head.appendChild(s);
            var l = document.createElement('link');
            l.rel = "stylesheet";
            l.href = "https://unpkg.com/vis-network@9.1.6/dist/vis-network.min.css";
            document.head.appendChild(l);
          }}

          ensureVis(function() {{
            var container = document.getElementById("{div_id}");
            var tip       = document.getElementById("{div_id}_tip");

            var data = {{
              nodes: new vis.DataSet({nodes_json}),
              edges: new vis.DataSet({edges_json})
            }};
            var options   = {options_json};
            var network   = new vis.Network(container, data, options);
            window.__TYK_NETWORK = network;
            var SUMMARIES = {summaries_json};
            var PDF_MAP   = {pdf_map_js};
            var panel     = document.getElementById("{panel_id}");

            network.on("click", function(params){{
              if (!panel) return;
              if (params.nodes && params.nodes.length) {{
                var nid    = String(params.nodes[0]);
                var node   = data.nodes.get(nid);
                var lbl    = (node && node.label) ? node.label : "{_js_cluster}";
                var txt    = SUMMARIES[nid] || "<i>{_js_no_summary}</i>";
                var pdfUrl = PDF_MAP[nid];
                var pdfLink = pdfUrl
                  ? "<a href='" + pdfUrl + "' target='_blank' style='font-weight:600;color:#2563eb;text-decoration:none;font-size:11px;'>" +
                      "{_js_view_report}</a>"
                  : "";
                document.getElementById("{panel_id}_placeholder").style.display = "none";
                var content = document.getElementById("{panel_id}_content");
                content.style.display = "block";
                document.getElementById("{panel_id}_title").innerHTML =
                  lbl + (pdfLink ? "<div style='margin-top:4px;'>" + pdfLink + "</div>" : "");
                document.getElementById("{panel_id}_body").innerHTML = txt;
                panel.scrollTop = 0;
              }}
            }});

            function moveTip(evt) {{
              if (!evt) return;
              var rect = container.getBoundingClientRect();
              var x = (evt.clientX - rect.left) + 14;
              var y = (evt.clientY - rect.top)  + 14;
              tip.style.left = x + "px";
              tip.style.top  = y + "px";
            }}

            network.on("hoverNode", function(params){{
              var n = data.nodes.get(params.node);
              if (n && n.title) {{
                tip.innerHTML = n.title;
                tip.style.display = "block";
              }}
            }});

            network.on("blurNode", function(){{
              tip.style.display = "none";
            }});

            network.on("dragging", function(p) {{
              if (tip.style.display === "block" && p.event && p.event.srcEvent) {{
                moveTip(p.event.srcEvent);
              }}
            }});

            network.on("pointerMove", function(p) {{
              if (tip.style.display === "block" && p.event && p.event.srcEvent) {{
                moveTip(p.event.srcEvent);
              }}
            }});

            network.once("stabilizationIterationsDone", function(){{
              network.fit({{ animation: {{ duration: 500, easing: 'easeInOutQuad' }} }});
              window.__TYK_NETWORK_READY = true;
            }});

            // Fallback por si no dispara el evento
            setTimeout(function(){{ window.__TYK_NETWORK_READY = true; }}, 4000);
          }});
        }})();
        </script>
        """

        def _save_html(_html: str, *, open_browser: bool) -> str:
            if outfile:
                outpath = Path(outfile).expanduser()
                if outpath.is_absolute() or outpath.parent != Path("."):
                    base_dir = outpath.parent
                    name = outpath.name
                    os.makedirs(base_dir, exist_ok=True)
                    outpath = base_dir / name
                else:
                    base_dir = Path(self.dat_folder or self.path_base or ".")
                    os.makedirs(base_dir, exist_ok=True)
                    outpath = base_dir / outpath.name
            else:
                base_dir = Path(self.dat_folder or self.path_base or ".")
                os.makedirs(base_dir, exist_ok=True)
                outpath = base_dir / f"{_slug(title)}.html"

            with open(outpath, "w", encoding="utf-8") as f:
                full_html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <style>
      body {{
        margin: 0;
        padding: 16px;
        background: #ffffff;
        font-family: sans-serif;
      }}
    </style>
  </head>
  <body>
    {_html}
  </body>
</html>"""
                f.write(full_html)
            if getattr(self, "verbose_notify", False):
                self._notify(f"Grafo guardado en <code>{outpath}</code>.", "info")
            if open_browser:
                try:
                    webbrowser.open("file://" + os.path.abspath(outpath))
                except Exception:
                    pass
            return str(outpath)

        try_inline = (mode == "inline") or (mode == "auto" and not _env_is_vscode())
        if try_inline:
            saved_path = None
            if outfile:
                saved_path = _save_html(html, open_browser=False)
            try:
                display(HTML(html))
                return saved_path
            except Exception:
                return _save_html(html, open_browser=open_in_browser)

        return _save_html(html, open_browser=open_in_browser)

    def _build_top_clusters_vis_graph(
        self,
        min_edge_weight: float = 0.0,
        *,
        include_top_subclusters: bool = False,
        top_subcluster_edge_weight: float = 1.0,
        max_subclusters_total: int | None = None,
        max_subclusters_per_top: int | None = None,
        label_base_only: bool = False,
        label_ids_only: bool = False,
    ) -> tuple[list, list]:
        nodes_raw, edges_raw = self._collect_top_graph_raw(
            min_edge_weight=min_edge_weight,
            include_top_subclusters=include_top_subclusters,
            top_subcluster_edge_weight=top_subcluster_edge_weight,
            max_subclusters_total=max_subclusters_total,
            max_subclusters_per_top=max_subclusters_per_top,
        )

        if not nodes_raw:
            return [], []

        cmap = colormaps.get_cmap("YlGnBu")
        sizes = [int(n.get("size", 1)) for n in nodes_raw] or [1]
        norm = mcolors.Normalize(vmin=min(sizes), vmax=max(sizes))

        nodes = []
        for n in nodes_raw:
            nid = str(n.get("id"))
            label_value = str(nid) if label_ids_only else str(n.get("label", nid) or nid)
            if not label_ids_only and nid in self.label_map_top:
                label_value = str(self.label_map_top.get(nid) or label_value)
            if label_base_only and not label_ids_only:
                label_value = self._base_node_label(label_value)

            articles = int(
                self.cluster_dict.get(nid, {}).get("size", n.get("size", 0) or 0)
            )
            val = articles if articles else int(n.get("size", 1))
            col = mcolors.to_hex(cmap(norm(max(val, 1))))

            title_html = (
                f"<div style='font-size:13px'>"
                f"<b>{label_value}</b><br>"
                f"ID: <code>{nid}</code><br>"
                f"{_('Articles: ')}<b>{articles}</b>"
                f"</div>"
            )

            nodes.append(
                {
                    "id": nid,
                    "label": label_value,
                    "title": title_html,
                    "value": val,
                    "color": {
                        "background": col,
                        "border": "#334",
                        "highlight": {"background": col, "border": "#222"},
                    },
                }
            )

        edges = []
        for e in edges_raw:
            w = float(e.get("weight", 1.0))
            edges.append(
                {"from": e["source"], "to": e["target"], "value": w, "width": 1.0}
            )

        if edges:
            weights = [float(e.get("value", 1.0)) for e in edges]
            wmin, wmax = min(weights), max(weights)
            wspan = wmax - wmin or 1.0
            for e in edges:
                w = float(e.get("value", 1.0))
                e["width"] = 0.6 + 3.4 * (w - wmin) / wspan

        return nodes, edges

    def _build_subclusters_vis_graph(
        self, top_id: str, min_edge_weight: float = 0.0
    ) -> tuple[list, list, str]:
        top_label = self._display_label(top_id)
        subs = self.subclusters_by_top.get(top_id, [])
        if not subs:
            return [], [], top_label

        sizes = []
        for sid in subs:
            n = self.cluster_dict.get(sid, {})
            sizes.append(int(n.get("size", 1) or 1))

        cmap = colormaps.get_cmap("YlGnBu")
        norm = mcolors.Normalize(vmin=min(sizes), vmax=max(sizes))

        nodes = []
        for sid in subs:
            n = self.cluster_dict.get(sid, {})
            val = int(n.get("size", 1) or 1)
            col = mcolors.to_hex(cmap(norm(max(val, 1))))
            label = self._display_label(sid)

            nodes.append(
                {
                    "id": sid,
                    "label": label,
                    "title": f"{label} · {_('size: ')}{val}",
                    "value": val,
                    "color": {
                        "background": col,
                        "border": "#334",
                        "highlight": {"background": col, "border": "#222"},
                    },
                }
            )

        edges = []
        if self.gdf_edges_sub and self.gdf_nodes_sub:
            sub_set = set(subs)

            def _top_of(sub_id: str) -> str:
                n = self.cluster_dict.get(sub_id, {})
                return str(
                    n.get("id_top")
                    if n.get("id_top") is not None
                    else int(sub_id) // 1000
                )

            for e in self.gdf_edges_sub:
                s, t = e["source"], e["target"]
                if (
                    s in sub_set
                    and t in sub_set
                    and _top_of(s) == top_id
                    and _top_of(t) == top_id
                ):
                    w = float(e.get("weight", 1.0))
                    if w >= min_edge_weight:
                        edges.append({"from": s, "to": t, "value": w, "width": 1.0})
        if edges:
            weights = [float(e.get("value", 1.0)) for e in edges]
            wmin, wmax = min(weights), max(weights)
            wspan = wmax - wmin or 1.0
            for e in edges:
                w = float(e.get("value", 1.0))
                e["width"] = 0.6 + 3.4 * (w - wmin) / wspan

        if not edges:
            center_id = f"TOP-{top_id}"
            avg = max(20, int(sum(n["value"] for n in nodes) / len(nodes)))
            nodes.append(
                {
                    "id": center_id,
                    "label": top_label,
                    "title": top_label,
                    "value": avg,
                    "color": {"background": "#e9eef8", "border": "#334"},
                }
            )
            for n in nodes:
                if n["id"] != center_id:
                    edges.append(
                        {
                            "from": center_id,
                            "to": n["id"],
                            "value": n["value"],
                            "width": max(1.0, n["value"] / 2.0),
                        }
                    )

        return nodes, edges, top_label

    def _snapshot_html_to_png(
        self,
        html_path: str,
        png_path: str,
        *,
        selector: str = "[data-tyk-root]",
        width_px: int = 1400,
        height_px: int = 900,
        wait_ms: int = 7000,
    ) -> bool:
        """
        Captura un screenshot PNG de un HTML local usando Playwright.
        Devuelve True si tuvo éxito, False si Playwright no está disponible o falla.
        """
        try:
            pass  # type: ignore
        except Exception:
            return False

    def _can_snapshot_html(self) -> bool:
        try:
            from playwright.sync_api import (
                sync_playwright,  # type: ignore  # noqa: F401
            )
        except Exception:
            return False
        return True

        try:
            html_url = Path(html_path).expanduser().resolve().as_uri()
        except Exception:
            html_url = f"file://{os.path.abspath(html_path)}"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": int(width_px), "height": int(height_px)}
                )
                page.goto(html_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_function(
                        "window.__TYK_NETWORK_READY === true", timeout=wait_ms
                    )
                except Exception:
                    page.wait_for_timeout(min(wait_ms, 2000))
                element = page.query_selector(selector)
                if element:
                    element.screenshot(path=png_path)
                else:
                    page.screenshot(path=png_path, full_page=True)
                browser.close()
            return True
        except Exception:
            return False

    def plot_clusters_graph_interactive(
        self,
        min_edge_weight: float = 0.0,
        title: str | None = None,
        mode: str = "auto",
    ) -> None:
        if title is None:
            title = _("Cluster Graph (TOP)")
        nodes, edges = self._build_top_clusters_vis_graph(
            min_edge_weight=min_edge_weight
        )
        self._render_vis_network(
            nodes,
            edges,
            title=title,
            mode=mode,
            show_summary_panel=True,
            summaries_map=self.cluster_summaries,
            pdf_map=self._build_pdf_map(),
            edge_weight_threshold=min_edge_weight,
        )

    def _rebalance_disconnected_components(
        self,
        G: nx.Graph,
        pos: dict[str, tuple[float, float]],
        *,
        spread: float = 0.95,
    ) -> dict[str, tuple[float, float]]:
        """
        Reubica componentes desconectados para evitar que un aislado arrastre
        todo el grafo hacia una esquina. Se usa solo si hay >1 componente.
        """
        if not pos or G.number_of_nodes() <= 1:
            return pos

        try:
            components = []
            for comp in nx.connected_components(G):
                nodes = [n for n in comp if n in pos]
                if nodes:
                    components.append(nodes)
        except Exception:
            return pos

        if len(components) <= 1:
            return pos

        def _comp_rank(nodes: list[str]) -> tuple[int, int, str]:
            total_size = 0
            for n in nodes:
                try:
                    total_size += int(G.nodes[n].get("size", 1) or 1)
                except Exception:
                    total_size += 1
            head = min((str(n) for n in nodes), default="")
            return (len(nodes), total_size, head)

        components.sort(key=_comp_rank, reverse=True)

        def _normalize_component(
            nodes: list[str], target_radius: float
        ) -> dict[str, tuple[float, float]]:
            xs = [float(pos[n][0]) for n in nodes]
            ys = [float(pos[n][1]) for n in nodes]
            cx = sum(xs) / max(1, len(xs))
            cy = sum(ys) / max(1, len(ys))
            centered: dict[str, tuple[float, float]] = {}
            max_r = 0.0
            for n in nodes:
                dx = float(pos[n][0]) - cx
                dy = float(pos[n][1]) - cy
                centered[n] = (dx, dy)
                max_r = max(max_r, math.hypot(dx, dy))
            if max_r <= 1e-10:
                max_r = 1.0
            scale = float(target_radius) / max_r
            return {n: (dx * scale, dy * scale) for n, (dx, dy) in centered.items()}

        balanced: dict[str, tuple[float, float]] = {}
        side_count = len(components) - 1
        main_radius = spread * (0.62 if side_count <= 1 else 0.56)
        main_layout = _normalize_component(components[0], target_radius=main_radius)
        balanced.update(main_layout)

        if side_count > 0:
            ring_radius = spread * (0.78 if side_count <= 3 else 0.72)
            if side_count == 1:
                angles = [-math.pi / 2.0]
            else:
                angles = [
                    (2.0 * math.pi * idx / side_count) - (math.pi / 2.0)
                    for idx in range(side_count)
                ]
            for idx, nodes in enumerate(components[1:]):
                theta = angles[idx]
                cx = ring_radius * math.cos(theta)
                cy = ring_radius * math.sin(theta)
                comp_radius = spread * min(
                    0.22, 0.08 + 0.05 * math.sqrt(max(1, len(nodes)))
                )
                comp_layout = _normalize_component(nodes, target_radius=comp_radius)
                for n, (dx, dy) in comp_layout.items():
                    balanced[n] = (cx + dx, cy + dy)

        limit = spread * 0.985
        return {
            n: (
                max(-limit, min(limit, float(x))),
                max(-limit, min(limit, float(y))),
            )
            for n, (x, y) in balanced.items()
        }

    def plot_clusters_graph_png(
        self,
        min_edge_weight: float = 0.0,
        title: str | None = None,
        outfile: str | None = None,
        *,
        dpi: int = 200,
        figsize: tuple[float, float] = (12.0, 9.0),
        label_mode: str = "auto",
        max_labels: int = 40,
        seed: int = 7,
        render_mode: str = "auto",
        vis_height_px: int | None = None,
        vis_width_px: int | None = None,
        vis_show_summary_panel: bool = True,
        vis_wait_ms: int = 7000,
        vis_keep_html: bool = False,
        max_nodes: int | None = None,
        node_size_range: tuple[float, float] = (120.0, 900.0),
        layout_k: float | None = None,
        layout_iterations: int = 280,
        layout_use_edge_weights: bool = True,
        edge_alpha: float = 0.28,
        include_top_subclusters: bool = False,
        top_subcluster_edge_weight: float = 1.0,
        max_subclusters_total: int | None = None,
        max_subclusters_per_top: int | None = None,
        label_base_only: bool = False,
        label_ids_only: bool = False,
        label_font_size: int = 7,
        label_wrap_chars: int | None = None,
    ) -> str:
        if title is None:
            title = _("Cluster Graph (TOP)")

        def _slug(s: str) -> str:
            s = re.sub(r"\s+", "_", s.strip())
            s = re.sub(r"[^\w\-.]+", "", s)
            return s[:80] or "graph"

        if outfile:
            outpath = Path(outfile).expanduser().resolve()
        else:
            base_dir = self.dat_folder or self.path_base or "."
            outpath = Path(base_dir) / f"{_slug(title)}.png"
        outpath.parent.mkdir(parents=True, exist_ok=True)

        mode = (render_mode or "auto").strip().lower()
        can_snap = self._can_snapshot_html()
        if mode in {"auto", "vis", "interactive", "html"} and (
            mode != "auto" or can_snap
        ):
            nodes, edges = self._build_top_clusters_vis_graph(
                min_edge_weight=min_edge_weight,
                include_top_subclusters=include_top_subclusters,
                top_subcluster_edge_weight=top_subcluster_edge_weight,
                max_subclusters_total=max_subclusters_total,
                max_subclusters_per_top=max_subclusters_per_top,
                label_base_only=label_base_only,
                label_ids_only=label_ids_only,
            )
            if nodes:
                vis_height = int(vis_height_px or max(360, int(figsize[1] * dpi)))
                vis_width = int(vis_width_px or max(480, int(figsize[0] * dpi)))
                html_path = outpath.with_suffix(".html")
                html_saved = self._render_vis_network(
                    nodes,
                    edges,
                    title=title,
                    mode="file",
                    outfile=str(html_path),
                    open_in_browser=False,
                    show_summary_panel=vis_show_summary_panel,
                    summaries_map=self.cluster_summaries
                    if vis_show_summary_panel
                    else None,
                    edge_weight_threshold=min_edge_weight,
                    height_px=vis_height,
                    width_px=vis_width,
                )
                if html_saved:
                    extra_h = 180 if vis_show_summary_panel else 120
                    ok = self._snapshot_html_to_png(
                        html_saved,
                        str(outpath),
                        width_px=vis_width,
                        height_px=vis_height + extra_h,
                        wait_ms=vis_wait_ms,
                    )
                    if ok:
                        if not vis_keep_html:
                            try:
                                os.remove(html_saved)
                            except Exception:
                                pass
                        if getattr(self, "verbose_notify", False):
                            self._notify(
                                f"Grafo PNG guardado en <code>{outpath}</code>.", "info"
                            )
                        return str(outpath)
                if mode == "vis":
                    if getattr(self, "verbose_notify", False):
                        self._notify("No se pudo exportar PNG desde HTML.", "warn")
                    return ""
        elif (
            mode in {"vis", "interactive", "html"}
            and not can_snap
            and getattr(self, "verbose_notify", False)
        ):
            self._notify(
                "Playwright no está disponible; no se pudo exportar PNG desde HTML.",
                "warn",
            )
        elif mode in {"vis", "interactive", "html"} and not can_snap:
            return ""

        nodes_raw, edges_raw = self._collect_top_graph_raw(
            min_edge_weight=min_edge_weight,
            include_top_subclusters=include_top_subclusters,
            top_subcluster_edge_weight=top_subcluster_edge_weight,
            max_subclusters_total=max_subclusters_total,
            max_subclusters_per_top=max_subclusters_per_top,
        )

        if not nodes_raw:
            if getattr(self, "verbose_notify", False):
                self._notify("No hay nodos TOP para graficar.", "warn")
            return ""

        G = nx.Graph()
        for n in nodes_raw:
            nid = str(n["id"])
            label = str(nid) if label_ids_only else str(n.get("label", nid) or nid)
            if not label_ids_only and nid in self.label_map_top:
                label = str(self.label_map_top.get(nid) or label)
            if label_base_only and not label_ids_only:
                label = self._base_node_label(label)
            size = int(
                self.cluster_dict.get(nid, {}).get("size", n.get("size", 1) or 1)
            )
            G.add_node(nid, label=label, size=size)

        for e in edges_raw:
            s = str(e.get("source"))
            t = str(e.get("target"))
            if not s or not t:
                continue
            w = float(e.get("weight", 1.0))
            G.add_edge(s, t, weight=w)

        try:
            max_nodes_int = int(max_nodes) if max_nodes is not None else 0
        except Exception:
            max_nodes_int = 0
        if max_nodes_int > 0 and G.number_of_nodes() > max_nodes_int:
            ranked_nodes = sorted(
                G.nodes,
                key=lambda n: (
                    int(G.nodes[n].get("size", 1) or 1),
                    str(G.nodes[n].get("label", n)),
                ),
                reverse=True,
            )
            keep_nodes = set(ranked_nodes[:max_nodes_int])
            G = G.subgraph(keep_nodes).copy()

        if G.number_of_nodes() == 0:
            if getattr(self, "verbose_notify", False):
                self._notify("No hay nodos TOP para graficar.", "warn")
            return ""

        sizes = [max(1, int(G.nodes[n].get("size", 1))) for n in G.nodes]
        sqrt_sizes = [math.sqrt(s) for s in sizes]
        smin, smax = min(sqrt_sizes), max(sqrt_sizes)
        sspan = smax - smin or 1.0
        node_size_min, node_size_max = node_size_range
        try:
            node_size_min = float(node_size_min)
            node_size_max = float(node_size_max)
        except Exception:
            node_size_min, node_size_max = 120.0, 900.0
        if node_size_max < node_size_min:
            node_size_min, node_size_max = node_size_max, node_size_min
        if abs(node_size_max - node_size_min) < 1e-6:
            node_size_max = node_size_min + 1.0
        node_sizes = [
            node_size_min + (node_size_max - node_size_min) * (s - smin) / sspan
            for s in sqrt_sizes
        ]

        cmap = colormaps.get_cmap("YlGnBu")
        norm = mcolors.Normalize(vmin=min(sizes), vmax=max(sizes))
        node_colors = [mcolors.to_hex(cmap(norm(s))) for s in sizes]

        edge_list = list(G.edges())
        edge_weights = [float(G.edges[e].get("weight", 1.0)) for e in edge_list]
        if edge_weights:
            wmin, wmax = min(edge_weights), max(edge_weights)
            wspan = wmax - wmin or 1.0
            edge_widths = [0.6 + 3.6 * (w - wmin) / wspan for w in edge_weights]
        else:
            edge_widths = []

        n_nodes = max(1, G.number_of_nodes())
        auto_k = max(0.55, 2.0 / math.sqrt(n_nodes))
        k_value = float(layout_k) if (layout_k is not None and layout_k > 0) else auto_k
        iters = max(50, int(layout_iterations or 0))

        weight_key = "weight" if bool(layout_use_edge_weights) else None
        try:
            pos = nx.spring_layout(
                G,
                seed=seed,
                weight=weight_key,
                k=k_value,
                scale=0.85,
                iterations=iters,
            )
        except Exception:
            pos = nx.spring_layout(
                G,
                seed=seed,
                k=k_value,
                scale=0.85,
                iterations=iters,
            )

        # Normaliza coordenadas para que el grafo use mejor el espacio útil.
        if pos:
            spread = 0.95
            xs = [float(v[0]) for v in pos.values()]
            ys = [float(v[1]) for v in pos.values()]
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)

            def _percentile(values: list[float], q: float) -> float:
                if not values:
                    return 0.0
                arr = sorted(values)
                if len(arr) == 1:
                    return float(arr[0])
                q = min(100.0, max(0.0, float(q)))
                rank = (len(arr) - 1) * (q / 100.0)
                low = int(math.floor(rank))
                high = int(math.ceil(rank))
                if low == high:
                    return float(arr[low])
                frac = rank - low
                return float(arr[low] * (1.0 - frac) + arr[high] * frac)

            # Evita que outliers extremos colapsen el núcleo del grafo.
            if len(xs) >= 8:
                rxmin = _percentile(xs, 4.0)
                rxmax = _percentile(xs, 96.0)
                rymin = _percentile(ys, 4.0)
                rymax = _percentile(ys, 96.0)
                full_xspan = xmax - xmin
                full_yspan = ymax - ymin
                if (
                    (rxmax - rxmin) > max(0.25, 0.3 * full_xspan)
                    and (rymax - rymin) > max(0.25, 0.3 * full_yspan)
                ):
                    xmin, xmax = rxmin, rxmax
                    ymin, ymax = rymin, rymax

            xspan = xmax - xmin or 1.0
            yspan = ymax - ymin or 1.0
            pos = {
                n: (
                    (
                        (
                            (
                                min(max(float(v[0]), xmin), xmax) - xmin
                            )
                            / xspan
                        )
                        * 2.0
                        - 1.0
                    )
                    * spread,
                    (
                        (
                            (
                                min(max(float(v[1]), ymin), ymax) - ymin
                            )
                            / yspan
                        )
                        * 2.0
                        - 1.0
                    )
                    * spread,
                )
                for n, v in pos.items()
            }

            # Empuje adicional entre nodos para reducir áreas saturadas.
            nodes_seq = list(G.nodes)
            size_min = min(node_sizes) if node_sizes else 0.0
            size_span = (max(node_sizes) - size_min) if node_sizes else 1.0
            if size_span <= 0:
                size_span = 1.0
            node_size_map_local = {n: node_sizes[i] for i, n in enumerate(nodes_seq)}
            local_pos = {
                n: [float(pos[n][0]), float(pos[n][1])]
                for n in nodes_seq
                if n in pos
            }
            for _ in range(120):
                moved = False
                for i in range(len(nodes_seq)):
                    ni = nodes_seq[i]
                    if ni not in local_pos:
                        continue
                    xi, yi = local_pos[ni]
                    rel_i = (float(node_size_map_local.get(ni, size_min)) - size_min) / size_span
                    for j in range(i + 1, len(nodes_seq)):
                        nj = nodes_seq[j]
                        if nj not in local_pos:
                            continue
                        xj, yj = local_pos[nj]
                        rel_j = (float(node_size_map_local.get(nj, size_min)) - size_min) / size_span
                        dx = xj - xi
                        dy = yj - yi
                        dist2 = dx * dx + dy * dy
                        min_dist = 0.082 + 0.060 * max(rel_i, rel_j)
                        if dist2 <= 1e-10:
                            sign = 1.0 if ((i + j) % 2 == 0) else -1.0
                            dx = 0.0015 * sign
                            dy = 0.0015 * (-sign)
                            dist2 = dx * dx + dy * dy
                        dist = math.sqrt(dist2)
                        if dist < min_dist:
                            push = (min_dist - dist) * 0.5 + 0.0015
                            ux, uy = dx / dist, dy / dist
                            xi -= ux * push
                            yi -= uy * push
                            xj += ux * push
                            yj += uy * push
                            moved = True
                            local_pos[ni] = [xi, yi]
                            local_pos[nj] = [xj, yj]
                for n in local_pos:
                    local_pos[n][0] = max(-spread, min(spread, local_pos[n][0]))
                    local_pos[n][1] = max(-spread, min(spread, local_pos[n][1]))
                if not moved:
                    break
            pos = {n: (local_pos[n][0], local_pos[n][1]) for n in local_pos}
            pos = self._rebalance_disconnected_components(G, pos, spread=spread)

        mode = (label_mode or "auto").strip().lower()
        label_nodes: list[str] = []
        if mode == "all":
            label_nodes = list(G.nodes)
        elif mode == "none":
            label_nodes = []
        else:
            if len(G.nodes) <= max_labels:
                label_nodes = list(G.nodes)
            else:
                ranked = sorted(
                    ((n, G.nodes[n].get("size", 1)) for n in G.nodes),
                    key=lambda x: x[1],
                    reverse=True,
                )
                label_nodes = [n for n, _ in ranked[:max_labels]]
        def _wrap_label(raw_label: Any) -> str:
            text = str(raw_label if raw_label is not None else "")
            try:
                max_chars = int(label_wrap_chars) if label_wrap_chars is not None else 0
            except Exception:
                max_chars = 0
            if max_chars <= 0 or len(text) <= max_chars:
                return text
            words = text.split()
            if len(words) <= 1:
                return text[: max(4, max_chars - 3)] + "..."
            lines: list[str] = []
            current = ""
            used_words = 0
            for w in words:
                candidate = w if not current else f"{current} {w}"
                if len(candidate) <= max_chars or not current:
                    current = candidate
                    used_words += 1
                    continue
                lines.append(current)
                current = w
                used_words += 1
                if len(lines) >= 2:
                    break
            if len(lines) < 2 and current:
                lines.append(current)
            if used_words < len(words):
                lines[-1] = lines[-1][: max(4, max_chars - 3)] + "..."
            return "\n".join(lines[:2])

        labels = {n: _wrap_label(G.nodes[n].get("label", n)) for n in label_nodes}

        fig, ax = plt.subplots(figsize=figsize)
        ax.set_title(title)
        ax.axis("off")
        if edge_list:
            nx.draw_networkx_edges(
                G,
                pos,
                ax=ax,
                edgelist=edge_list,
                width=edge_widths,
                edge_color="#888",
                alpha=min(1.0, max(0.05, float(edge_alpha))),
            )
        nx.draw_networkx_nodes(
            G,
            pos,
            ax=ax,
            node_size=node_sizes,
            node_color=node_colors,
            linewidths=0.7,
            edgecolors="#223",
        )
        if labels:
            def _label_box_dims(text: str) -> tuple[float, float]:
                lines = str(text or "").split("\n")
                n_lines = max(1, len(lines))
                max_chars = max((len(line) for line in lines), default=1)
                # Aproximación en coordenadas del layout normalizado [-1, 1].
                width = 0.0105 * float(max_chars) + 0.038
                height = 0.030 * float(n_lines) + 0.020
                return width, height

            size_min = min(node_sizes) if node_sizes else 0.0
            size_span = (max(node_sizes) - size_min) if node_sizes else 1.0
            if size_span <= 0:
                size_span = 1.0
            node_size_map = {n: node_sizes[i] for i, n in enumerate(G.nodes)}
            label_items = []
            for n, label_txt in labels.items():
                x, y = pos.get(n, (0.0, 0.0))
                rel = (float(node_size_map.get(n, size_min)) - size_min) / size_span
                # Base: texto debajo del nodo.
                base_dy = 0.098 + (0.074 * rel)
                lx, ly = float(x), float(y) - base_dy
                w, h = _label_box_dims(str(label_txt))
                label_items.append(
                    {
                        "node": n,
                        "label": str(label_txt),
                        "x": lx,
                        "y": ly,
                        "w": w,
                        "h": h,
                    }
                )

            # Relaja solapamientos entre labels y contra nodos.
            for _ in range(240):
                moved = False

                for i in range(len(label_items)):
                    a = label_items[i]
                    for j in range(i + 1, len(label_items)):
                        b = label_items[j]
                        dx = b["x"] - a["x"]
                        dy_lbl = b["y"] - a["y"]
                        min_dx = (a["w"] + b["w"]) * 0.5 + 0.030
                        min_dy = (a["h"] + b["h"]) * 0.5 + 0.026
                        if abs(dx) < min_dx and abs(dy_lbl) < min_dy:
                            push_x = (min_dx - abs(dx)) * 0.5 + 0.006
                            push_y = (min_dy - abs(dy_lbl)) * 0.5 + 0.004
                            sign_x = -1.0 if dx >= 0 else 1.0
                            a["x"] += sign_x * push_x
                            b["x"] -= sign_x * push_x
                            # Mantener etiquetas por debajo: empuje leve hacia abajo.
                            a["y"] -= push_y * 0.35
                            b["y"] -= push_y * 0.35
                            moved = True

                for item in label_items:
                    for n, (node_x, node_y) in pos.items():
                        rel_n = (float(node_size_map.get(n, size_min)) - size_min) / size_span
                        node_r = 0.022 + 0.042 * rel_n
                        dx = item["x"] - float(node_x)
                        dy_node = item["y"] - float(node_y)
                        min_dx = (item["w"] * 0.5) + node_r + 0.018
                        min_dy = (item["h"] * 0.5) + node_r + 0.020
                        if abs(dx) < min_dx and abs(dy_node) < min_dy:
                            # Prioriza despegar texto hacia abajo del nodo.
                            item["y"] = min(
                                item["y"],
                                float(node_y) - (item["h"] * 0.5 + node_r + 0.032),
                            )
                            if abs(dx) < min_dx * 0.65:
                                item["x"] += -0.008 if dx <= 0 else 0.008
                            moved = True

                for item in label_items:
                    item["x"] = max(-1.22, min(1.22, float(item["x"])))
                    item["y"] = max(-1.24, min(1.12, float(item["y"])))

                if not moved:
                    break

            for item in label_items:
                ax.text(
                    item["x"],
                    item["y"],
                    item["label"],
                    fontsize=max(6, int(label_font_size)),
                    color="#111",
                    fontweight="bold",
                    ha="center",
                    va="top",
                    bbox=dict(
                        facecolor="white",
                        edgecolor="none",
                        alpha=0.86,
                        boxstyle="round,pad=0.12",
                    ),
                )
        ax.margins(x=0.18, y=0.30)
        try:
            if len(set(sizes)) > 1:
                sm = cm.ScalarMappable(norm=norm, cmap=cmap)
                sm.set_array([])
                cbar = fig.colorbar(sm, ax=ax, fraction=0.035, pad=0.02)
                cbar.ax.tick_params(labelsize=8)
                cbar.set_label(_("Size (articles)"), fontsize=9)
        except Exception:
            pass
        ax.text(
            0.02,
            0.02,
            _("Edge threshold: ≥ {threshold}").format(threshold=f"{min_edge_weight:g}"),
            transform=ax.transAxes,
            fontsize=9,
            bbox=dict(facecolor="white", edgecolor="#ccc", alpha=0.8, boxstyle="round"),
        )
        fig.tight_layout()
        fig.savefig(str(outpath), dpi=dpi, bbox_inches="tight")
        plt.close(fig)

        if getattr(self, "verbose_notify", False):
            self._notify(f"Grafo PNG guardado en <code>{outpath}</code>.", "info")

        return str(outpath)

    def plot_subclusters_graph_interactive(
        self,
        top_val: str,
        min_edge_weight: float = 0.0,
        title: str | None = None,
        mode: str = "auto",
    ) -> None:
        tid = self._resolve_top_id(top_val)
        if not tid:
            self._notify(
                _("TOP <b>{top}</b> not found (use ID or exact name).").format(top=top_val), "error"
            )
            return

        nodes, edges, top_label = self._build_subclusters_vis_graph(
            tid, min_edge_weight=min_edge_weight
        )
        if not nodes:
            self._notify(
                _("TOP <b>{top}</b> (ID {id}) has no subclusters.").format(
                    top=self.label_map_top.get(tid, tid), id=tid
                ),
                "warn",
            )
            return

        if title is None:
            title = _("Subclusters of {label}").format(label=top_label)

        self._render_vis_network(
            nodes,
            edges,
            title=title,
            mode=mode,
            show_summary_panel=True,
            summaries_map=self._load_subcluster_detail_map(tid),
            pdf_map=self._build_pdf_map(),
            edge_weight_threshold=min_edge_weight,
        )

    def plot_subclusters_graph_png(
        self,
        top_val: str,
        min_edge_weight: float = 0.0,
        title: str | None = None,
        outfile: str | None = None,
        *,
        dpi: int = 200,
        figsize: tuple[float, float] = (12.0, 9.0),
        label_mode: str = "auto",
        max_labels: int = 40,
        seed: int = 7,
        render_mode: str = "auto",
        vis_height_px: int | None = None,
        vis_width_px: int | None = None,
        vis_show_summary_panel: bool = True,
        vis_wait_ms: int = 7000,
        vis_keep_html: bool = False,
        max_nodes: int | None = None,
        node_size_range: tuple[float, float] = (120.0, 900.0),
        layout_k: float | None = None,
        layout_iterations: int = 280,
        layout_use_edge_weights: bool = True,
        edge_alpha: float = 0.35,
        label_font_size: int = 9,
        label_wrap_chars: int | None = None,
    ) -> str:
        def _slug(s: str) -> str:
            s = re.sub(r"\s+", "_", s.strip())
            s = re.sub(r"[^\w\-.]+", "", s)
            return s[:80] or "graph"

        tid = self._resolve_top_id(top_val)
        if not tid:
            self._notify(
                _("TOP <b>{top}</b> not found (use ID or exact name).").format(top=top_val), "error"
            )
            return ""

        nodes_vis, edges_vis, top_label = self._build_subclusters_vis_graph(
            tid, min_edge_weight=min_edge_weight
        )
        if not nodes_vis:
            self._notify(
                _("TOP <b>{top}</b> (ID {id}) has no subclusters.").format(
                    top=self.label_map_top.get(tid, tid), id=tid
                ),
                "warn",
            )
            return ""

        if title is None:
            title = _("Subclusters of {label}").format(label=top_label)

        if outfile:
            outpath = Path(outfile).expanduser().resolve()
        else:
            base_dir = self.dat_folder or self.path_base or "."
            outpath = Path(base_dir) / f"{_slug(title)}.png"
        outpath.parent.mkdir(parents=True, exist_ok=True)

        mode = (render_mode or "auto").strip().lower()
        can_snap = self._can_snapshot_html()
        if mode in {"auto", "vis", "interactive", "html"} and (
            mode != "auto" or can_snap
        ):
            vis_height = int(vis_height_px or max(360, int(figsize[1] * dpi)))
            vis_width = int(vis_width_px or max(480, int(figsize[0] * dpi)))
            html_path = outpath.with_suffix(".html")
            html_saved = self._render_vis_network(
                nodes_vis,
                edges_vis,
                title=title,
                mode="file",
                outfile=str(html_path),
                open_in_browser=False,
                show_summary_panel=vis_show_summary_panel,
                summaries_map=self.cluster_summaries
                if vis_show_summary_panel
                else None,
                edge_weight_threshold=min_edge_weight,
                height_px=vis_height,
                width_px=vis_width,
            )
            if html_saved:
                extra_h = 180 if vis_show_summary_panel else 120
                ok = self._snapshot_html_to_png(
                    html_saved,
                    str(outpath),
                    width_px=vis_width,
                    height_px=vis_height + extra_h,
                    wait_ms=vis_wait_ms,
                )
                if ok:
                    if not vis_keep_html:
                        try:
                            os.remove(html_saved)
                        except Exception:
                            pass
                    if getattr(self, "verbose_notify", False):
                        self._notify(
                            f"Grafo PNG guardado en <code>{outpath}</code>.", "info"
                        )
                    return str(outpath)
            if mode == "vis":
                if getattr(self, "verbose_notify", False):
                    self._notify("No se pudo exportar PNG desde HTML.", "warn")
                return ""
        elif (
            mode in {"vis", "interactive", "html"}
            and not can_snap
            and getattr(self, "verbose_notify", False)
        ):
            self._notify(
                "Playwright no está disponible; no se pudo exportar PNG desde HTML.",
                "warn",
            )
        elif mode in {"vis", "interactive", "html"} and not can_snap:
            return ""

        # Fallback estático (sin Playwright)
        G = nx.Graph()
        for n in nodes_vis:
            nid = str(n.get("id"))
            label = n.get("label", nid)
            size = int(n.get("value", n.get("raw", 1) or 1))
            color = None
            if isinstance(n.get("color"), dict):
                color = n["color"].get("background")
            G.add_node(nid, label=label, size=size, color=color)

        for e in edges_vis:
            s = str(e.get("from") or e.get("source") or "")
            t = str(e.get("to") or e.get("target") or "")
            if not s or not t:
                continue
            w = float(e.get("value", e.get("weight", 1.0)) or 1.0)
            G.add_edge(s, t, weight=w)

        try:
            max_nodes_int = int(max_nodes) if max_nodes is not None else 0
        except Exception:
            max_nodes_int = 0
        if max_nodes_int > 0 and G.number_of_nodes() > max_nodes_int:
            ranked_nodes = sorted(
                G.nodes,
                key=lambda n: (
                    int(G.nodes[n].get("size", 1) or 1),
                    str(G.nodes[n].get("label", n)),
                ),
                reverse=True,
            )
            keep_nodes = set(ranked_nodes[:max_nodes_int])
            G = G.subgraph(keep_nodes).copy()

        if G.number_of_nodes() == 0:
            if getattr(self, "verbose_notify", False):
                self._notify("No hay nodos SUB para graficar.", "warn")
            return ""

        sizes = [max(1, int(G.nodes[n].get("size", 1))) for n in G.nodes]
        sqrt_sizes = [math.sqrt(s) for s in sizes]
        smin, smax = min(sqrt_sizes), max(sqrt_sizes)
        sspan = smax - smin or 1.0
        node_size_min, node_size_max = node_size_range
        try:
            node_size_min = float(node_size_min)
            node_size_max = float(node_size_max)
        except Exception:
            node_size_min, node_size_max = 120.0, 900.0
        if node_size_max < node_size_min:
            node_size_min, node_size_max = node_size_max, node_size_min
        if abs(node_size_max - node_size_min) < 1e-6:
            node_size_max = node_size_min + 1.0
        node_sizes = [
            node_size_min + (node_size_max - node_size_min) * (s - smin) / sspan
            for s in sqrt_sizes
        ]

        cmap = colormaps.get_cmap("YlGnBu")
        norm = mcolors.Normalize(vmin=min(sizes), vmax=max(sizes))
        node_colors = []
        for n in G.nodes:
            col = G.nodes[n].get("color")
            if not col:
                col = mcolors.to_hex(cmap(norm(G.nodes[n].get("size", 1))))
            node_colors.append(col)

        edge_list = list(G.edges())
        edge_weights = [float(G.edges[e].get("weight", 1.0)) for e in edge_list]
        if edge_weights:
            wmin, wmax = min(edge_weights), max(edge_weights)
            wspan = wmax - wmin or 1.0
            edge_widths = [0.6 + 3.6 * (w - wmin) / wspan for w in edge_weights]
        else:
            edge_widths = []

        n_nodes = max(1, G.number_of_nodes())
        auto_k = max(0.55, 2.0 / math.sqrt(n_nodes))
        k_value = float(layout_k) if (layout_k is not None and layout_k > 0) else auto_k
        iters = max(50, int(layout_iterations or 0))
        weight_key = "weight" if bool(layout_use_edge_weights) else None
        try:
            pos = nx.spring_layout(
                G,
                seed=seed,
                weight=weight_key,
                k=k_value,
                scale=0.85,
                iterations=iters,
            )
        except Exception:
            pos = nx.spring_layout(
                G,
                seed=seed,
                k=k_value,
                scale=0.85,
                iterations=iters,
            )

        # Normaliza coordenadas para que el grafo use mejor el espacio útil.
        if pos:
            spread = 0.95
            xs = [float(v[0]) for v in pos.values()]
            ys = [float(v[1]) for v in pos.values()]
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)

            def _percentile(values: list[float], q: float) -> float:
                if not values:
                    return 0.0
                arr = sorted(values)
                if len(arr) == 1:
                    return float(arr[0])
                q = min(100.0, max(0.0, float(q)))
                rank = (len(arr) - 1) * (q / 100.0)
                low = int(math.floor(rank))
                high = int(math.ceil(rank))
                if low == high:
                    return float(arr[low])
                frac = rank - low
                return float(arr[low] * (1.0 - frac) + arr[high] * frac)

            if len(xs) >= 8:
                rxmin = _percentile(xs, 4.0)
                rxmax = _percentile(xs, 96.0)
                rymin = _percentile(ys, 4.0)
                rymax = _percentile(ys, 96.0)
                full_xspan = xmax - xmin
                full_yspan = ymax - ymin
                if (
                    (rxmax - rxmin) > max(0.25, 0.3 * full_xspan)
                    and (rymax - rymin) > max(0.25, 0.3 * full_yspan)
                ):
                    xmin, xmax = rxmin, rxmax
                    ymin, ymax = rymin, rymax

            xspan = xmax - xmin or 1.0
            yspan = ymax - ymin or 1.0
            pos = {
                n: (
                    (
                        (
                            (
                                min(max(float(v[0]), xmin), xmax) - xmin
                            )
                            / xspan
                        )
                        * 2.0
                        - 1.0
                    )
                    * spread,
                    (
                        (
                            (
                                min(max(float(v[1]), ymin), ymax) - ymin
                            )
                            / yspan
                        )
                        * 2.0
                        - 1.0
                    )
                    * spread,
                )
                for n, v in pos.items()
            }

            # Empuje adicional entre nodos para reducir zonas saturadas.
            nodes_seq = list(G.nodes)
            size_min = min(node_sizes) if node_sizes else 0.0
            size_span = (max(node_sizes) - size_min) if node_sizes else 1.0
            if size_span <= 0:
                size_span = 1.0
            node_size_map_local = {n: node_sizes[i] for i, n in enumerate(nodes_seq)}
            local_pos = {
                n: [float(pos[n][0]), float(pos[n][1])]
                for n in nodes_seq
                if n in pos
            }
            for _ in range(120):
                moved = False
                for i in range(len(nodes_seq)):
                    ni = nodes_seq[i]
                    if ni not in local_pos:
                        continue
                    xi, yi = local_pos[ni]
                    rel_i = (float(node_size_map_local.get(ni, size_min)) - size_min) / size_span
                    for j in range(i + 1, len(nodes_seq)):
                        nj = nodes_seq[j]
                        if nj not in local_pos:
                            continue
                        xj, yj = local_pos[nj]
                        rel_j = (float(node_size_map_local.get(nj, size_min)) - size_min) / size_span
                        dx = xj - xi
                        dy = yj - yi
                        dist2 = dx * dx + dy * dy
                        min_dist = 0.082 + 0.060 * max(rel_i, rel_j)
                        if dist2 <= 1e-10:
                            sign = 1.0 if ((i + j) % 2 == 0) else -1.0
                            dx = 0.0015 * sign
                            dy = 0.0015 * (-sign)
                            dist2 = dx * dx + dy * dy
                        dist = math.sqrt(dist2)
                        if dist < min_dist:
                            push = (min_dist - dist) * 0.5 + 0.0015
                            ux, uy = dx / dist, dy / dist
                            xi -= ux * push
                            yi -= uy * push
                            xj += ux * push
                            yj += uy * push
                            moved = True
                            local_pos[ni] = [xi, yi]
                            local_pos[nj] = [xj, yj]
                for n in local_pos:
                    local_pos[n][0] = max(-spread, min(spread, local_pos[n][0]))
                    local_pos[n][1] = max(-spread, min(spread, local_pos[n][1]))
                if not moved:
                    break
            pos = {n: (local_pos[n][0], local_pos[n][1]) for n in local_pos}
            pos = self._rebalance_disconnected_components(G, pos, spread=spread)

        mode = (label_mode or "auto").strip().lower()
        label_nodes: list[str] = []
        if mode == "all":
            label_nodes = list(G.nodes)
        elif mode == "none":
            label_nodes = []
        else:
            if len(G.nodes) <= max_labels:
                label_nodes = list(G.nodes)
            else:
                ranked = sorted(
                    ((n, G.nodes[n].get("size", 1)) for n in G.nodes),
                    key=lambda x: x[1],
                    reverse=True,
                )
                label_nodes = [n for n, _ in ranked[:max_labels]]
        if mode != "none":
            for n in G.nodes:
                if str(n).startswith("TOP-") and n not in label_nodes:
                    label_nodes.append(n)

        def _wrap_label(raw_label: Any) -> str:
            text = str(raw_label if raw_label is not None else "")
            try:
                max_chars = int(label_wrap_chars) if label_wrap_chars is not None else 0
            except Exception:
                max_chars = 0
            if max_chars <= 0 or len(text) <= max_chars:
                return text
            words = text.split()
            if len(words) <= 1:
                return text[: max(4, max_chars - 3)] + "..."
            lines: list[str] = []
            current = ""
            used_words = 0
            for w in words:
                candidate = w if not current else f"{current} {w}"
                if len(candidate) <= max_chars or not current:
                    current = candidate
                    used_words += 1
                    continue
                lines.append(current)
                current = w
                used_words += 1
                if len(lines) >= 2:
                    break
            if len(lines) < 2 and current:
                lines.append(current)
            if used_words < len(words):
                lines[-1] = lines[-1][: max(4, max_chars - 3)] + "..."
            return "\n".join(lines[:2])

        labels = {n: _wrap_label(G.nodes[n].get("label", n)) for n in label_nodes}

        fig, ax = plt.subplots(figsize=figsize)
        ax.set_title(title)
        ax.axis("off")
        if edge_list:
            nx.draw_networkx_edges(
                G,
                pos,
                ax=ax,
                edgelist=edge_list,
                width=edge_widths,
                edge_color="#888",
                alpha=min(1.0, max(0.05, float(edge_alpha))),
            )
        nx.draw_networkx_nodes(
            G,
            pos,
            ax=ax,
            node_size=node_sizes,
            node_color=node_colors,
            linewidths=0.7,
            edgecolors="#223",
        )
        if labels:
            def _label_box_dims(text: str) -> tuple[float, float]:
                lines = str(text or "").split("\n")
                n_lines = max(1, len(lines))
                max_chars = max((len(line) for line in lines), default=1)
                width = 0.0105 * float(max_chars) + 0.038
                height = 0.030 * float(n_lines) + 0.020
                return width, height

            size_min = min(node_sizes) if node_sizes else 0.0
            size_span = (max(node_sizes) - size_min) if node_sizes else 1.0
            if size_span <= 0:
                size_span = 1.0
            node_size_map = {n: node_sizes[i] for i, n in enumerate(G.nodes)}
            label_items = []
            for n, label_txt in labels.items():
                x, y = pos.get(n, (0.0, 0.0))
                rel = (float(node_size_map.get(n, size_min)) - size_min) / size_span
                base_dy = 0.098 + (0.074 * rel)
                lx, ly = float(x), float(y) - base_dy
                w, h = _label_box_dims(str(label_txt))
                label_items.append(
                    {
                        "label": str(label_txt),
                        "x": lx,
                        "y": ly,
                        "w": w,
                        "h": h,
                    }
                )

            for _ in range(240):
                moved = False
                for i in range(len(label_items)):
                    a = label_items[i]
                    for j in range(i + 1, len(label_items)):
                        b = label_items[j]
                        dx = b["x"] - a["x"]
                        dy_lbl = b["y"] - a["y"]
                        min_dx = (a["w"] + b["w"]) * 0.5 + 0.030
                        min_dy = (a["h"] + b["h"]) * 0.5 + 0.026
                        if abs(dx) < min_dx and abs(dy_lbl) < min_dy:
                            push_x = (min_dx - abs(dx)) * 0.5 + 0.006
                            push_y = (min_dy - abs(dy_lbl)) * 0.5 + 0.004
                            sign_x = -1.0 if dx >= 0 else 1.0
                            a["x"] += sign_x * push_x
                            b["x"] -= sign_x * push_x
                            a["y"] -= push_y * 0.35
                            b["y"] -= push_y * 0.35
                            moved = True

                for item in label_items:
                    for n, (node_x, node_y) in pos.items():
                        rel_n = (float(node_size_map.get(n, size_min)) - size_min) / size_span
                        node_r = 0.022 + 0.042 * rel_n
                        dx = item["x"] - float(node_x)
                        dy_node = item["y"] - float(node_y)
                        min_dx = (item["w"] * 0.5) + node_r + 0.018
                        min_dy = (item["h"] * 0.5) + node_r + 0.020
                        if abs(dx) < min_dx and abs(dy_node) < min_dy:
                            item["y"] = min(
                                item["y"],
                                float(node_y) - (item["h"] * 0.5 + node_r + 0.032),
                            )
                            if abs(dx) < min_dx * 0.65:
                                item["x"] += -0.008 if dx <= 0 else 0.008
                            moved = True

                for item in label_items:
                    item["x"] = max(-1.22, min(1.22, float(item["x"])))
                    item["y"] = max(-1.24, min(1.12, float(item["y"])))

                if not moved:
                    break

            for item in label_items:
                ax.text(
                    item["x"],
                    item["y"],
                    item["label"],
                    fontsize=max(6, int(label_font_size)),
                    color="#111",
                    fontweight="bold",
                    ha="center",
                    va="top",
                    bbox=dict(
                        facecolor="white",
                        edgecolor="none",
                        alpha=0.86,
                        boxstyle="round,pad=0.12",
                    ),
                )
        ax.margins(x=0.18, y=0.30)
        try:
            if len(set(sizes)) > 1:
                sm = cm.ScalarMappable(norm=norm, cmap=cmap)
                sm.set_array([])
                cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.015)
                cbar.ax.tick_params(labelsize=8)
                cbar.set_label(_("Size (articles)"), fontsize=9)
        except Exception:
            pass
        ax.text(
            0.02,
            0.02,
            _("Edge threshold: ≥ {threshold}").format(threshold=f"{min_edge_weight:g}"),
            transform=ax.transAxes,
            fontsize=9,
            bbox=dict(facecolor="white", edgecolor="#ccc", alpha=0.8, boxstyle="round"),
        )
        fig.tight_layout()
        fig.savefig(str(outpath), dpi=dpi, bbox_inches="tight")
        plt.close(fig)

        if getattr(self, "verbose_notify", False):
            self._notify(f"Grafo PNG guardado en <code>{outpath}</code>.", "info")

        return str(outpath)

    def plot_cooc_network_interactive(
        self,
        node_type: str = "K",
        min_node_size: int = 5,
        min_edge_weight: float = 0.0,
        title: str | None = None,
        palette: str = "YlGnBu",
        max_nodes: int = 250,
        topk_per_node: int = 5,
        node_size_range: tuple = (18, 60),
        height_px: int = 720,
        mode: str = "auto",
    ) -> None:
        if title is None:
            title = _("Co-occurrence network")
        if not self.cooc_data:
            self._notify(
                _("No co-occurrence data loaded. Cannot plot network."),
                "warn",
            )
            return

        nodes_raw = [
            n for n in self.cooc_data.get("nodes", []) if n.get("type") == node_type
        ]
        if not nodes_raw:
            self._notify(
                _("No nodes of type <b>{type}</b> found.").format(type=node_type), "warn"
            )
            return

        nodes_raw.sort(key=lambda n: int(n.get("size", 1)), reverse=True)
        nodes_raw = nodes_raw[: max(1, int(max_nodes))]
        node_ids = {str(n.get("name")) for n in nodes_raw}
        node_by_id = {str(n.get("name")): n for n in nodes_raw}

        edges_dict = defaultdict(list)
        for e in self.cooc_data.get("links", []):
            s, t = str(e.get("source")), str(e.get("target"))
            if s in node_ids and t in node_ids:
                w = float(e.get("weight", 1.0))
                if w >= float(min_edge_weight):
                    edges_dict[s].append((w, t))
                    edges_dict[t].append((w, s))

        kept_edges = set()
        for u, lst in edges_dict.items():
            for w, v in heapq.nlargest(int(topk_per_node), lst, key=lambda x: x[0]):
                a, b = (u, v) if u < v else (v, u)
                kept_edges.add((a, b, w))

        try:
            cmap = colormaps.get_cmap(palette)
        except Exception:
            cmap = colormaps.get_cmap("YlGnBu")

        sizes_raw = [int(node_by_id[nid].get("size", 1)) for nid in node_ids] or [1]
        vmin, vmax = min(sizes_raw), max(sizes_raw)
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

        def _lin(v, a0, a1, b0, b1):
            if a1 <= a0:
                return (b0 + b1) / 2.0
            x = (v - a0) / (a1 - a0)
            return b0 + x * (b1 - b0)

        vmin_px, vmax_px = node_size_range
        nodes = []
        for nid in node_ids:
            n = node_by_id[nid]
            label = str(n.get("item", nid))
            raw_size = int(n.get("size", 1))

            vis_size = _lin(raw_size, vmin, vmax, vmin_px, vmax_px)
            vis_size = max(vmin_px, min(vmax_px, vis_size))

            color = mcolors.to_hex(cmap(norm(raw_size)))
            nodes.append(
                {
                    "id": nid,
                    "label": label,
                    "title": f"{label} · {_('size: ')}{raw_size}",
                    "value": vis_size,
                    "raw": raw_size,
                    "color": {
                        "background": color,
                        "border": "#334",
                        "highlight": {"background": color, "border": "#222"},
                    },
                }
            )

        edges = [
            {"from": a, "to": b, "value": w, "width": max(1.0, w / 2.5)}
            for a, b, w in kept_edges
        ]

        pretty_type = self.stuff_titles.get(node_type, node_type)
        final_title = f"{title} — {pretty_type} (n={len(nodes)})"

        self._render_vis_network(
            nodes,
            edges,
            title=final_title,
            palette=palette,
            show_colorbar=True,
            scaling_min=int(vmin_px * 0.8),
            scaling_max=int(vmax_px),
            height_px=height_px,
            mode=mode,
        )

    def describe_cluster_params(
        self,
        level: str,  # "TOP" | "SUB"  (en Colab: @param ["TOP","SUB"])
        stuff_type: str,  # (en Colab: @param ["K","TK","S","S2","J","C","I","R","RJ","A","MCAU","MCP","MRP","Y"])
        cluster_top: str = "",  # ID o nombre TOP
        cluster_sub: str = "",  # ID o nombre SUB (dentro del TOP elegido)
        listar_max: int = 20,
        save_path: str | None = None,
        return_fig: bool = False,
        force_chart: str | None = None,  # 👈 NUEVO
    ) -> None:
        """
        Modo @param minimalista para notebooks.
        * Si level=TOP y no pasás cluster_top → lista TOPs.
        * Si level=SUB, pide primero cluster_top; si no hay cluster_sub → lista los SUB de ese TOP.
        """
        lvl = (level or "TOP").upper()
        if lvl not in ("TOP", "SUB"):
            self._notify(
                _("Invalid level: <b>{level}</b>. Use <b>TOP</b> or <b>SUB</b>.").format(level=level),
                "error",
            )
            return

        pairs = [
            (cid, self.label_map_top[cid])
            for cid in sorted(self.label_map_top, key=int)
        ]
        # self._render_candidates_table("Clusters TOP disponibles", pairs, limit=listar_max)

        if lvl == "TOP":
            # Si no hay TOP elegido, listamos opciones y salimos
            if not cluster_top.strip():
                # pairs = [(cid, self.label_map_top[cid]) for cid in sorted(self.label_map_top, key=int)]
                self._render_candidates_table(
                    _("Available TOP Clusters"), pairs, limit=listar_max
                )
                display(
                    HTML(
                        f"<div style='margin-top:6px;color:#666'>{_('Specify <b>cluster_top</b> (ID or name) to visualize.')}</div>"
                    )
                )
                return
            # pairs = [(cid, self.label_map_top[cid]) for cid in sorted(self.label_map_top, key=int)]
            self._render_candidates_table(
                _("Available TOP Clusters"), pairs, limit=listar_max, open=False
            )

            tid = self._resolve_top_id(cluster_top.strip())
            if not tid:
                display(
                    HTML(
                        f"<div style='color:#c00'>{_('TOP <b>{top}</b> not found.').format(top=cluster_top)}</div>"
                    )
                )
                return
            top_name = self.label_map_top.get(tid, tid)
            cluster = self.get_cluster(tid)

            display(
                HTML(
                    f"<div style='font-family:sans-serif;margin:6px 0 10px 0;'>"
                    f"{_('Level: ')}<b>TOP</b> &nbsp;|&nbsp; {_('Cluster: ')}<b>{top_name}</b> (ID: {tid}) "
                    f"&nbsp;|&nbsp; {_('Type: ')}<b>{self.stuff_titles.get(stuff_type, stuff_type)}</b></div>"
                )
            )
            fig = self._build_figure(
                cluster,
                stuff_type,
                exporting=save_path is not None,
                save_path=save_path,
                force_chart=force_chart,
            )
            if fig is not None and save_path is None:
                self._show_figure(fig)

            return

        # === SUB ===
        if (
            not cluster_top.strip()
        ):  # Para SUB obligamos a elegir primero un TOP (y le mostramos sus opciones)
            pairs = [
                (cid, self.label_map_top[cid])
                for cid in sorted(self.label_map_top, key=int)
            ]
            self._render_candidates_table(
                _("Available TOP Clusters"), pairs, limit=listar_max
            )
            self._notify(
                _("Specify <b>cluster_top</b> (ID or name) to visualize."), "info"
            )
            return

        tid = self._resolve_top_id(cluster_top.strip())
        if not tid:
            self._notify(
                _("TOP <b>{top}</b> not found.").format(top=cluster_top), "error"
            )
            return

        sub_ids = self.subclusters_by_top.get(tid, [])
        sub_pairs = [
            (sid, self.label_map_sub.get(sid, sid)) for sid in sorted(sub_ids, key=int)
        ]
        self._render_candidates_table(
            _("Available TOP Clusters"), pairs, limit=listar_max, open=False
        )

        if (
            not cluster_sub.strip()
        ):  # Si todavía no se eligió SUB, listamos los de ese TOP y salimos
            pairs = [
                (cid, self.label_map_top[cid])
                for cid in sorted(self.label_map_top, key=int)
            ]
            self._render_candidates_table(
                _("Subclusters of TOP {name} (ID {id})").format(
                    name=self.label_map_top.get(tid, tid), id=tid
                ),
                sub_pairs,
                limit=listar_max,
            )
            self._notify(
                _("Specify <b>cluster_sub</b> (ID or name) to visualize."), "info"
            )
            return

        sid = self._resolve_sub_in_top(tid, cluster_sub.strip())
        if not sid:
            self._notify(
                _("SUB <b>{sub}</b> does not exist in TOP <b>{top}</b> (ID {id}).").format(
                    sub=cluster_sub, top=self.label_map_top.get(tid, tid), id=tid
                ),
                "error",
            )
            return

        sub_name = self.label_map_sub.get(sid, sid)
        top_name = self.label_map_top.get(tid, tid)
        cluster = self.get_cluster(sid)
        display(
            HTML(
                f"<div style='font-family:sans-serif;margin:6px 0 10px 0;'>"
                f"{_('Level: ')}<b>SUB</b> &nbsp;|&nbsp; {_('Cluster: ')}<b>{sub_name}</b> (ID: {sid}) "
                f"&nbsp;|&nbsp; TOP: <b>{top_name}</b> (ID: {tid}) "
                f"&nbsp;|&nbsp; {_('Type: ')}<b>{self.stuff_titles.get(stuff_type, stuff_type)}</b></div>"
            )
        )
        fig = self._build_figure(
            cluster,
            stuff_type,
            exporting=save_path is not None,
            save_path=save_path,
            force_chart=force_chart,
        )
        if fig is not None and save_path is None:
            self._show_figure(fig)

        return None

    def _display_cluster_table(
        self,
        title: str,
        headers: list[str],
        rows: list[list[Any]],
        link_column: int | None = None,
        link_prefix: str | None = None,
    ) -> None:
        """Arma una tabla HTML con fondo blanco y texto negro (legible en tema oscuro), con links a Scholar."""
        html = f"""
        <h3 style='text-align: left; font-family: sans-serif;'>{title}</h3>
        <div style='max-width: 1000px; margin: left; overflow-y: auto; max-height: 600px; background-color: white; border: 1px solid #ccc;'>
        <table style='width: 100%; border-collapse: collapse; font-family: sans-serif; background-color: white; color: black !important;'>
            <thead style='background-color: #e6e6e6; color: black !important;'>
                <tr>
                    {"".join(f"<th style='padding: 10px; text-align: justify; border-bottom: 1px solid #ccc; color: black !important;'>{col}</th>" for col in headers)}
                </tr>
            </thead>
            <tbody>
        """
        for row in rows:
            html += "<tr>"
            for i, col in enumerate(row):
                if link_column is not None and i == link_column:
                    query = str(col).replace(" ", "+")
                    link = f"{link_prefix}{query}"
                    html += f"<td style='padding: 8px; text-align: justify; border-bottom: 1px solid #eee; color: black !important;'><a style='color: #0645AD !important;' href='{link}' target='_blank'>{col}</a></td>"
                else:
                    html += f"<td style='padding: 8px; text-align: justify; border-bottom: 1px solid #eee; color: black !important;'>{col}</td>"
            html += "</tr>"
        html += "</tbody></table></div>"
        display(HTML(html))

    def _show_figure(self, fig: go.Figure) -> None:
        html = pio.to_html(fig, include_plotlyjs="cdn", full_html=False)
        display(HTML(html))

    def _render_static_matplotlib(
        self,
        *,
        stuff_type: str,
        title: str,
        save_path: str,
        # barras
        labels: list | None = None,
        values: list | None = None,
        orientation: str = "v",  # "v" o "h"
        x_label: str = "",
        y_label: str = "",
        annotate: bool = False,
        bar_colors: list | None = None,
        bar_legend: list | None = None,
        # pie
        pie_labels: list | None = None,
        pie_values: list | None = None,
        # tabla
        table_headers: list | None = None,
        table_rows: list | None = None,
    ):
        import os

        import matplotlib.pyplot as plt

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        plt.figure(figsize=(12, 5))
        plt.title(title)

        # --- TABLA ---
        if table_headers is not None and table_rows is not None:
            plt.axis("off")
            # limitar filas para que no explote el PDF
            rows = table_rows[:20]
            tbl = plt.table(
                cellText=rows,
                colLabels=table_headers,
                loc="center",
                cellLoc="left",
            )
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(8)
            tbl.scale(1, 1.3)
            plt.tight_layout()
            plt.savefig(save_path, dpi=200, bbox_inches="tight")
            plt.close()
            return

        # --- PIE ---
        if pie_labels is not None and pie_values is not None:
            plt.pie(pie_values, labels=pie_labels, autopct="%1.1f%%")
            plt.tight_layout()
            plt.savefig(save_path, dpi=200, bbox_inches="tight")
            plt.close()
            return

        # --- BARRAS ---
        if labels is None or values is None:
            raise ValueError("Para barras se requieren labels y values")

        if orientation == "h":
            plt.barh(labels, values, color=bar_colors)
            plt.xlabel(x_label)
            plt.ylabel(y_label)
            if annotate:
                for i, v in enumerate(values):
                    plt.text(
                        v,
                        i,
                        f"{v:.2f}" if isinstance(v, float) else str(v),
                        va="center",
                    )
        else:
            plt.bar(labels, values, color=bar_colors)
            plt.xlabel(x_label)
            plt.ylabel(y_label)
            # ejes enteros si son años
            try:
                ax = plt.gca()
                ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
            except Exception:
                pass
            if annotate:
                for x, v in zip(labels, values):
                    plt.text(x, v, str(v), ha="center", va="bottom", fontsize=9)

        if bar_legend:
            try:
                from matplotlib.patches import Patch

                handles = [Patch(color=c, label=lbl) for lbl, c in bar_legend]
                plt.legend(handles=handles, loc="upper left", fontsize=8, frameon=False)
            except Exception:
                pass

        plt.tight_layout()
        plt.savefig(save_path, dpi=200, bbox_inches="tight")
        plt.close()

    def _build_figure(
        self,
        cluster_data: dict[str, Any],
        stuff_type: str,
        *,
        exporting: bool = False,
        save_path: str | None = None,
        force_chart=None,
    ) -> go.Figure | None:
        cid = str(cluster_data.get("name"))
        cluster_name = cluster_data.get("label_real", cluster_data.get("label", cid))
        size_val = int(cluster_data.get("size", 0))
        stuff = (cluster_data.get("stuff", {}) or {}).get(stuff_type, [])

        titles = {
            "Y": _("Publications by year"),
            "MCP": _("Most Cited Articles"),
            "MRP": _("Most Representative Articles"),
            "MCAU": _("Most Cited Authors"),
        }

        # Sin datos
        if not stuff:
            if getattr(self, "verbose_notify", False):
                self._notify(
                    _("{name}: no data for <b>{type}</b>.").format(
                        name=cluster_name, type=self.stuff_titles.get(stuff_type, stuff_type)
                    ),
                    "warn",
                )
            # En exporting: no guardamos nada (no hay data)
            return None

        # =========================================================
        # 1) CASOS TABLA (MCP / MRP / MCAU): notebook=HTML, PDF=PNG
        # =========================================================
        if stuff_type in ("MCP", "MRP"):
            headers = [
                "Title",
                "Author(s)",
                "Journal (Year)",
                "In-degree",
                "Times Cited",
            ]
            rows = []
            for (
                item
            ) in stuff:  # (title, author, journal, year, cited, indegree, doc_type)
                title = item[0] if len(item) > 0 else ""
                author = item[1] if len(item) > 1 else ""
                journal = item[2] if len(item) > 2 else ""
                year = item[3] if len(item) > 3 else ""
                cited = item[4] if len(item) > 4 else 0
                indegree = item[5] if len(item) > 5 else 0
                rows.append([title, author, f"{journal} ({year})", indegree, cited])

            pretty = (
                "Most Representative Papers"
                if stuff_type == "MRP"
                else "Most Cited Papers"
            )
            title = f"{cluster_name} — {pretty} ({len(rows)})"

            if exporting:
                if not save_path:
                    raise ValueError("exporting=True requiere save_path")
                self._render_static_matplotlib(
                    stuff_type=stuff_type,
                    title=title,
                    save_path=save_path,
                    table_headers=headers,
                    table_rows=rows,
                )
                return None

            # comportamiento original (notebook)
            self._display_cluster_table(
                title=title,
                headers=headers,
                rows=rows,
                link_column=0,
                link_prefix="https://scholar.google.com/scholar?q=",
            )
            return None

        if stuff_type == "MCAU":
            headers = ["Author", "Papers", "Citations"]

            def _to_int(x):
                try:
                    return int(float(x))
                except Exception:
                    return 0

            rows = []
            for item in stuff:
                author = item[0] if len(item) > 0 else ""
                citations = _to_int(item[1] if len(item) > 1 else 0)
                papers = _to_int(item[2] if len(item) > 2 else 0)
                rows.append([author, papers, citations])

            title = f"{cluster_name} — Most Cited Authors ({len(rows)})"

            if exporting:
                if not save_path:
                    raise ValueError("exporting=True requiere save_path")
                self._render_static_matplotlib(
                    stuff_type=stuff_type,
                    title=title,
                    save_path=save_path,
                    table_headers=headers,
                    table_rows=rows,
                )
                return None

            # comportamiento original (notebook)
            self._display_cluster_table(
                title=title,
                headers=headers,
                rows=rows,
                link_column=0,
                link_prefix="https://scholar.google.com/scholar?q=",
            )
            return None

        # ===========================================
        # 2) CASO Y (Publicaciones por año): bar chart
        # ===========================================
        if stuff_type == "Y":

            def _to_float(val):
                try:
                    return float(val)
                except Exception:
                    return None

            stuff_sorted = sorted(stuff, key=lambda s: int(s[0]))
            labels = [int(round(float(s[0]))) for s in stuff_sorted]
            # En BCclusters, Y[1] llega como porcentaje del clúster (0-100).
            # Convertimos a conteos estimados para mantener consistencia con
            # reports.get_timeline_info y evitar discrepancias en el reporte.
            values = []
            for s in stuff_sorted:
                p = _to_float(s[1])
                if p is None:
                    values.append(0)
                elif size_val > 0:
                    values.append(int(round(size_val * p / 100.0)))
                else:
                    values.append(int(round(p)))
            weights = [_to_float(s[2]) if len(s) > 2 else None for s in stuff_sorted]
            title = f"{cluster_name} — {titles.get('Y', _('Year'))}"

            def _weights_to_colors(weights_list):
                try:
                    from matplotlib import colors as mcolors
                except Exception:
                    return None
                vals = [abs(w) for w in weights_list if w is not None]
                if not vals:
                    return None
                max_abs = max(vals) or 1.0
                base = mcolors.to_rgb("#1f77b4")

                def _mix(base, t):
                    t = max(0.0, min(1.0, t))
                    return tuple((1.0 - t) * 1.0 + t * base[i] for i in range(3))

                colors = []
                for w in weights_list:
                    if w is None:
                        colors.append("#cfd8dc")
                        continue
                    intensity = 0.25 + 0.75 * (abs(w) / max_abs)
                    rgb = _mix(base, intensity)
                    colors.append(mcolors.to_hex(rgb))
                return colors

            def _legend_colors(weights_list):
                try:
                    from matplotlib import colors as mcolors
                except Exception:
                    return None
                if not weights_list:
                    return None
                vals = [abs(w) for w in weights_list if w is not None]
                if not vals:
                    return None
                min_abs = min(vals)
                max_abs = max(vals) or 1.0
                base = mcolors.to_rgb("#1f77b4")

                def _mix(base, t):
                    t = max(0.0, min(1.0, t))
                    return tuple((1.0 - t) * 1.0 + t * base[i] for i in range(3))

                t_min = 0.25 + 0.75 * (min_abs / max_abs) if max_abs else 0.25
                t_max = 0.25 + 0.75 * (max_abs / max_abs) if max_abs else 1.0
                legend = [
                    (_("Lower weight"), mcolors.to_hex(_mix(base, t_min))),
                    (_("Higher weight"), mcolors.to_hex(_mix(base, t_max))),
                ]
                return legend

            if exporting:
                if not save_path:
                    raise ValueError("exporting=True requiere save_path")
                bar_colors = _weights_to_colors(weights)
                bar_legend = _legend_colors(weights)
                self._render_static_matplotlib(
                    stuff_type=stuff_type,
                    title=title,
                    save_path=save_path,
                    labels=labels,
                    values=values,
                    orientation="v",
                    x_label=_("Year"),
                    y_label=_("No. articles"),
                    annotate=True,
                    bar_colors=bar_colors,
                    bar_legend=bar_legend,
                )
                return None

            # comportamiento original (plotly)
            bar_colors = _weights_to_colors(weights)
            bar_kwargs = {"marker": dict(color=bar_colors)} if bar_colors else {}
            fig = go.Figure(
                go.Bar(
                    x=labels,
                    y=values,
                    text=[f"{v}" for v in values],
                    textposition="auto",
                    **bar_kwargs,
                )
            )
            # leyenda manual (positivo/negativo) cuando hay ponderación
            try:
                vals = [abs(w) for w in weights if w is not None]
                if vals:
                    max_abs = max(vals) or 1.0
                    min_abs = min(vals)

                    def _mix_hex(t):
                        t = max(0.0, min(1.0, t))
                        return f"rgba({int((1.0 - t) * 255 + t * 31)},{int((1.0 - t) * 255 + t * 119)},{int((1.0 - t) * 255 + t * 180)},1)"

                    t_min = 0.25 + 0.75 * (min_abs / max_abs) if max_abs else 0.25
                    t_max = 0.25 + 0.75 * (max_abs / max_abs) if max_abs else 1.0
                    fig.add_trace(
                        go.Bar(
                            x=[],
                            y=[],
                            name=_("Lower weight"),
                            marker_color=_mix_hex(t_min),
                            showlegend=True,
                        )
                    )
                    fig.add_trace(
                        go.Bar(
                            x=[],
                            y=[],
                            name=_("Higher weight"),
                            marker_color=_mix_hex(t_max),
                            showlegend=True,
                        )
                    )
                    fig.update_layout(
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="left",
                            x=0,
                            font=dict(size=10),
                        )
                    )
            except Exception:
                pass
            fig.update_layout(
                title=dict(text=title, font=dict(size=13)),
                font=dict(size=11),
                xaxis_title=_("Year"),
                yaxis_title=_("No. articles"),
                height=max(360, 28 * len(labels)),
                margin=dict(l=60, r=20, t=40, b=40),
            )
            return fig

        # =========================================================
        # 3) FRECUENCIAS (barras o pie chart): como lo original
        # =========================================================

        if isinstance(stuff[0], (list, tuple)) and len(stuff[0]) >= 2:
            labels = [str(s[0]) for s in stuff]
            values = [float(s[1]) for s in stuff]
            top = sorted(zip(labels, values), key=lambda x: x[1])[-20:]
            labels, values = (
                (list(zip(*top))[0], list(zip(*top))[1]) if top else ([], [])
            )
            labels = list(labels)
            values = list(values)

            title = f"{cluster_name} ({size_val} {_('articles')}) — {self.stuff_titles.get(stuff_type, stuff_type)}"
            if force_chart in ("pie", "bar"):
                chart_type = force_chart
            elif len(labels) <= 6:
                chart_type = "pie"
            else:
                chart_type = "bar"
            # Exportación PDF
            if exporting:
                if not save_path:
                    raise ValueError("exporting=True requiere save_path")

                if chart_type == "pie":
                    self._render_static_matplotlib(
                        stuff_type=stuff_type,
                        title=title,
                        save_path=save_path,
                        pie_labels=labels,
                        pie_values=values,
                    )
                else:  # bar
                    self._render_static_matplotlib(
                        stuff_type=stuff_type,
                        title=title,
                        save_path=save_path,
                        labels=labels,
                        values=values,
                        orientation="h",
                        x_label=_("Frequency"),
                        y_label="",
                        annotate=True,
                    )
                return None

            # Notebook (Plotly)
            if chart_type == "pie":
                fig = go.Figure(
                    go.Pie(
                        labels=labels,
                        values=values,
                        textinfo="label+percent",
                        hole=0.3,
                    )
                )
                fig.update_layout(
                    title=dict(text=title, font=dict(size=13)),
                    font=dict(size=11),
                    legend=dict(font=dict(size=10)),
                )
            else:
                fig = go.Figure(
                    go.Bar(
                        x=values,
                        y=labels,
                        orientation="h",
                        text=[f"{v:.2f}" for v in values],
                        textposition="auto",
                    )
                )
                fig.update_layout(
                    title=dict(text=title, font=dict(size=13)),
                    font=dict(size=11),
                    height=max(520, len(labels) * 28),
                    margin=dict(l=110, r=20, t=40, b=40),
                    xaxis_title=_("Frequency"),
                )

            return fig

        # Default
        if exporting and save_path:
            # Si no sabemos cómo renderizarlo estático, mejor avisar explícito
            raise ValueError(f"No hay renderer estático para stuff_type={stuff_type}")

        return go.Figure().update_layout(
            title=f"{cluster_name} — {stuff_type} (formato no reconocido)"
        )

    # ------------------------ HELPERS ------------------------
    def _render_candidates_table(
        self,
        title: str,
        pairs: list[tuple[str, str]],
        limit: int = 15,
        open: bool = True,
    ) -> None:
        """Tabla HTML para listar candidatos (TOPs o SUBs) para ayudar al usuario a seleccionar en describe_cluster_params"""
        if not pairs:
            return
        rows = "".join(
            f"<tr><td style='padding:4px 8px'>{name}</td>"
            f"<td style='padding:4px 8px'>{cid}</td></tr>"
            for cid, name in pairs[:limit]
        )
        if open:
            detail_txt = (
                "<details open style='margin:6px 0'><summary style='cursor:pointer'>"
            )
        else:
            detail_txt = (
                "<details style='margin:6px 0'><summary style='cursor:pointer'>"
            )
        display(
            HTML(
                f"{detail_txt}"
                f"{title} (top {min(limit, len(pairs))}/{len(pairs)})</summary>"
                "<table style='border-collapse:collapse;margin-top:6px'>"
                f"<thead><tr><th style='text-align:left;padding:4px 8px'>{_('Name')}</th>"
                "<th style='text-align:left;padding:4px 8px'>ID</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></details>"
            )
        )

    def _resolve_top_id(self, val) -> str | None:
        """Devuelve el ID de un TOP a partir de un ID o un nombre."""
        if val is None:
            return None
        s = str(val).strip()

        # 1) Si es un ID de TOP existente en el JSON, devolvelo directo.
        n = self.cluster_dict.get(s)
        if n and int(n.get("level", 0)) == 0:
            return s

        # 2) Intentar por nombre en mapas (exacto y normalizado/case-insensitive).
        v_norm = self._normalize_label_capital(s)
        # a) nombre → id directo
        if v_norm in self.cluster_name_to_id:
            return self.cluster_name_to_id[v_norm]
        # b) recorrer label_map_top y comparar case-insensitive
        for cid, name in self.label_map_top.items():
            if name and (
                name == s
                or name.lower() == s.lower()
                or self._normalize_label_capital(name) == v_norm
            ):
                return cid

        # 3) Fallback: recorrer JSON (label_real / label) para TOPs
        for cid, node in self.cluster_dict.items():
            if int(node.get("level", 0)) != 0:
                continue
            for cand in (node.get("label_real"), node.get("label")):
                if not cand:
                    continue
                if (
                    str(cand) == s
                    or str(cand).lower() == s.lower()
                    or self._normalize_label_capital(str(cand)) == v_norm
                ):
                    return str(cid)

        return None

    def _resolve_sub_in_top(self, top_id: str, val) -> str | None:
        """Devuelve el ID de un SUB (dentro del TOP dado) a partir de un ID o nombre."""
        if not top_id or val is None:
            return None
        tid = str(top_id)
        s = str(val).strip()

        subs = set(self.subclusters_by_top.get(tid, []))
        if not subs:
            return None

        # 1) Si ya es un ID y pertenece a ese TOP, devolverlo
        if s in subs:
            return s

        # 2) Intentar por nombre en mapas (exacto y normalizado/case-insensitive)
        s_norm = self._normalize_label_capital(s)
        for sid in subs:
            name = self.label_map_sub.get(sid)
            if name and (
                name == s
                or name.lower() == s.lower()
                or self._normalize_label_capital(name) == s_norm
            ):
                return sid

        # 3) Fallback: recorrer JSON (label_real / label)
        for sid in subs:
            node = self.cluster_dict.get(sid, {})
            for cand in (node.get("label_real"), node.get("label")):
                if not cand:
                    continue
                if (
                    str(cand) == s
                    or str(cand).lower() == s.lower()
                    or self._normalize_label_capital(str(cand)) == s_norm
                ):
                    return sid

        return None

    @property
    def stuff_titles(self) -> dict[str, str]:
        return {
            "K": _("Keywords"),
            "TK": _("Title Words"),
            "S": _("Subject Categories"),
            "S2": _("Subject Sub-Categories"),
            "J": _("Journal Sources"),
            "C": _("Countries"),
            "I": _("Institutions"),
            "R": _("References"),
            "RJ": _("Reference Sources"),
            "A": _("Authors (Freq)"),
            "MCAU": _("Most Cited Authors"),
            "MCP": _("Most Cited Papers"),
            "MRP": _("Most Representative Papers"),
            "Y": _("Publications by year"),
        }

    def _notify(self, msg: str, kind: str = "info") -> None:
        """Muestra mensajes como HTML (más amigable que errores de consola)."""
        colors = {
            "info": ("#0b5", "#e8f9f0"),  # verde
            "warn": ("#b80", "#fff6e5"),  # amarillo
            "error": ("#c00", "#ffeaea"),  # rojo
            "success": ("#0a7", "#e9fbf4"),  # verde éxito
        }
        fg, bg = colors.get(kind, colors["info"])
        display(
            HTML(
                f"<div style='font-family:sans-serif; padding:10px 12px; border:1px solid {fg}; "
                f"border-radius:6px; background:{bg}; color:#111; line-height:1.4'>{msg}</div>"
            )
        )

    def sync_notebook_params(self, param_name: str = "top_cluster") -> None:
        """
        Update dropdown options for `param_name` in every notebook cell that uses
        this instance's path_base, pulling the current TOP cluster IDs from memory.

        Call this once after `tyk = TyK(path_base=PATH)` in a notebook cell so the
        dropdown always reflects what is actually loaded. Options are persisted in the
        Django DB and can also be edited manually in the admin.
        """
        top_ids = sorted(
            self.label_map_top.keys(),
            key=lambda x: int(x) if x.isdigit() else x,
        )
        if not top_ids:
            self._notify(
                "sync_notebook_params: no TOP clusters loaded — nothing to sync.", "warn"
            )
            return

        try:
            from tyk_notebook_app.models import Cell, Parameter
        except Exception as exc:
            self._notify(
                f"sync_notebook_params: cannot import Django models ({exc}).", "error"
            )
            return

        path_str = self.path_base.replace("\\", "/").rstrip("/")

        # Find all notebooks that have a cell referencing this path_base
        notebook_ids = set(
            Cell.objects.filter(source_code__icontains=path_str).values_list(
                "notebook_id", flat=True
            )
        )
        if not notebook_ids:
            self._notify(
                f"sync_notebook_params: no notebooks found with path <code>{path_str}</code>.",
                "warn",
            )
            return

        params = Parameter.objects.filter(
            name=param_name, cell__notebook_id__in=notebook_ids
        )
        updated = 0
        for param in params:
            param.param_type = "dropdown"
            param.options = top_ids
            if str(param.default_value) not in top_ids:
                param.default_value = top_ids[0]
            param.save()
            updated += 1

        self._notify(
            f"sync_notebook_params: updated <b>{updated}</b> <code>{param_name}</code> "
            f"parameter(s) with <b>{len(top_ids)}</b> TOP clusters: {', '.join(top_ids)}.",
            "success",
        )

    def rename_cluster(
        self,
        level: str,  # "TOP" | "SUB"
        cluster: str,  # ID o nombre del cluster a renombrar
        new_name: str,  # nuevo nombre
        top_id: str | None = None,  # opcional: para SUB si pasás nombre ambiguo
    ) -> None:

        level = (level or "").strip().upper()
        if level not in ("TOP", "SUB"):
            self._notify(_("The parameter <b>level</b> must be 'TOP' or 'SUB'."), "error")
            return

        if not cluster or not cluster.strip():
            self._notify(
                _("Specify a <b>cluster</b> (ID or name) to rename."), "error"
            )
            return

        if not new_name or not new_name.strip():
            self._notify(
                _("Specify the <b>new name</b> (new_name) to rename."), "error"
            )
            return

        new_name = new_name.strip()

        # Helper: aplica el cambio y sincroniza estructuras
        def _apply_rename(
            id_str: str, map_label: dict, map_rev: dict, gdf_nodes: list, lvl_text: str
        ) -> None:
            old = map_label[id_str]
            if old in map_rev:
                del map_rev[old]
            map_label[id_str] = new_name
            map_rev[new_name] = id_str
            # cluster_dict
            if id_str in self.cluster_dict:
                self.cluster_dict[id_str]["label_real"] = new_name
            # GDF
            for n in gdf_nodes:
                if n.get("id") == id_str:
                    n["label"] = new_name
                    break
            self._notify(
                _("<b>Renamed successfully</b> — Level: <b>{level}</b> · ID: <code>{id}</code> · <i>{old}</i> → <b>{new}</b>").format(
                    level=lvl_text, id=id_str, old=old, new=new_name
                ),
                "success",
            )

        if level == "TOP":
            tid = self._resolve_top_id(cluster)
            if not tid:
                self._notify(
                    _("TOP <b>{top}</b> not found (use ID or exact name).").format(top=cluster),
                    "error",
                )
                return
            _apply_rename(
                tid,
                self.label_map_top,
                self.cluster_name_to_id,
                self.gdf_nodes_top,
                "TOP",
            )
            return

        # SUB
        resolved_top = self._resolve_top_id(top_id) if top_id else None

        # Si 'cluster' es ID de SUB
        if cluster in self.label_map_sub:
            sid = cluster
            if resolved_top:
                subs = set(self.subclusters_by_top.get(resolved_top, []))
                if sid not in subs:
                    top_name = self.label_map_top.get(resolved_top, resolved_top)
                    self._notify(
                        _("SUB <code>{sid}</code> does not belong to the specified TOP (<b>{top}</b>, ID <code>{id}</code>).").format(
                            sid=sid, top=top_name, id=resolved_top
                        ),
                        "error",
                    )
                    return
            _apply_rename(
                sid,
                self.label_map_sub,
                self.subcluster_name_to_id,
                self.gdf_nodes_sub,
                "SUB",
            )
            return

        # Si 'cluster' es NOMBRE de SUB: buscar ID (limitando por TOP si lo dieron)
        if resolved_top:
            candidates = [
                sid
                for sid in self.subclusters_by_top.get(resolved_top, [])
                if self.label_map_sub.get(sid) == cluster
            ]
        else:
            candidates = [
                sid for sid, name in self.label_map_sub.items() if name == cluster
            ]

        if not candidates:
            hint = ""
            if not resolved_top:
                hint = " " + _("If the name exists in more than one TOP, also specify <b>top_id</b> (ID or name of the TOP).")
            self._notify(
                _("SUB <b>{sub}</b> not found.").format(sub=cluster) + hint, "error"
            )
            return

        if len(candidates) > 1:
            # listado de coincidencias para ayudar
            items = []
            for sid in candidates:
                owner_top = None
                for tid, subs in self.subclusters_by_top.items():
                    if sid in subs:
                        owner_top = tid
                        break
                items.append(
                    f"<li>SUB ID <code>{sid}</code> in TOP <code>{owner_top}</code> "
                    f"(<b>{self.label_map_top.get(owner_top, owner_top)}</b>)</li>"
                )
            self._notify(
                _("The specified name matches multiple SUBs in different TOPs. Specify <b>top_id</b> to disambiguate:")
                + "<ul>" + "".join(items) + "</ul>",
                "warn",
            )
            return

        sid = candidates[0]
        _apply_rename(
            sid, self.label_map_sub, self.subcluster_name_to_id, self.gdf_nodes_sub, "SUB"
        )
