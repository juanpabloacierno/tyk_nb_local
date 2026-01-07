# -*- coding: utf-8 -*-


import os
!pip install pyvis
import networkx as nx
import plotly.graph_objs as go
from pyvis.network import Network
import os, re, json, csv, uuid, glob, io
from pathlib import Path
import tempfile
from IPython.display import display, HTML, clear_output

import matplotlib.pyplot as plt
import plotly.io as pio

from typing import Any, Dict, List, Optional, Tuple, Iterable,Union, Sequence, Set
import heapq
from collections import defaultdict
from matplotlib import cm, colormaps, colors as mcolors
import webbrowser
!pip install pycountry
import pandas as pd

from tyk import TyK


PATH= "data/HVOA/"

tyk = TyK(
    path_base=PATH, #ESTO ES LO UNICO QUE HAY QUE MODIFICAR
)

# contar cuántos items hay por stuff en cada TOP
for cid, name in tyk.list_clusters(top=True, show=None):
    c = tyk.get_cluster(cid)
    stuff = (c.get("stuff") or {})
    counts = {k: len(v or []) for k, v in stuff.items()}
    print(f"{cid} — {name}:", counts)

import pandas as pd

stuff_types = ["MCP","MRP","MCAU","K","TK","S","S2","J","C","I","R","RJ","A","Y"]
rows = []

for cid, name in tyk.list_clusters(top=True, show=None):   # top=False para SUB

    c = tyk.get_cluster(cid)
    s = (c.get("stuff") or {})
    row = {"id": cid, "name": name, "size": int(c.get("size", 0))}
    for t in stuff_types:
        row[t] = len(s.get(t, []) or [])
    rows.append(row)

df = pd.DataFrame(rows).set_index(["id","name"]).sort_values("MCP", ascending=False)
df

# @title
tyk.plot_map()

tyk.plot_countries_map_global(colorscale="Turbo")

