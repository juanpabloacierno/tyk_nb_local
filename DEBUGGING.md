# Debugging Guide for TyK Notebook

## Overview

TyK Notebook now includes comprehensive debugging capabilities for cell code execution:
- **Interactive web-based debugger** (web-pdb) for breakpoints and stepping
- **Helper functions** for quick variable inspection and execution tracing

## Installation

The debugging tools are already installed if you followed the standard setup:

```bash
uv add web-pdb  # Already done
```

## Interactive Debugging with web-pdb

### Usage

Add a breakpoint in any cell:

```python
x = calculate_something()
set_trace()  # Execution pauses here
y = process(x)
```

### When Breakpoint Hits

1. **Cell output displays**:
   ```
   🔍 DEBUGGER ACTIVE
   ============================================================
   Open this URL in a new browser tab:
       http://localhost:5555
   ============================================================
   ```

2. **Click "Open Debugger" button** - A blue button appears automatically

3. **Use standard pdb commands** in the web interface:
   - `n` (next) - Execute next line
   - `s` (step) - Step into function
   - `c` (continue) - Continue execution
   - `p variable` - Print variable value
   - `l` - List source code around current line
   - `pp variable` - Pretty-print variable
   - `h` - Help with commands
   - `q` - Quit debugger

### Port Management

- Default port: 5555
- Auto-increments if port is busy (5555, 5556, 5557, etc.)
- Displayed port shown in notification message

## Quick Debugging Helpers

These functions are always available in every cell, no installation needed beyond web-pdb.

### debug() - Variable Inspection

Display variables with names, types, and values in rich HTML format:

```python
x = 42
y = [1, 2, 3, 4, 5]
df = pd.DataFrame({'a': [1, 2, 3]})

debug(x, y, df, title="My Variables")
```

**Optional parameters:**
- `title`: Custom title for output (default: "Debug Output")
- `max_len`: Maximum length for value strings (default: 1000)

**Output includes:**
- Variable names (auto-detected from calling context)
- Type information
- Formatted values

### inspect_obj() - Object Details

Detailed inspection of any Python object:

```python
import pandas as pd
df = pd.DataFrame({'col1': [1, 2, 3], 'col2': ['a', 'b', 'c']})
inspect_obj(df)
```

**Shows:**
- Object type
- String representation
- Length (if applicable)
- All attributes (non-private)
- All methods with type indicators (🔧 for methods, 📊 for data)

### vars_dump() - Namespace Overview

Display all variables in current namespace as a formatted table:

```python
x = 100
y = "hello"
z = [1, 2, 3]

vars_dump()  # Show all
vars_dump(filter_prefix='x')  # Only vars starting with 'x'
vars_dump(exclude_modules=False)  # Include imported modules
```

**Optional parameters:**
- `filter_prefix`: Show only variables starting with this prefix
- `exclude_modules`: Exclude imported modules (default: True)

**Output:**
- Table with columns: Name, Type, Value
- Sorted alphabetically
- Shows total count

### trace() - Execution Flow Tracking

Add timestamped messages to track execution flow:

```python
trace("Starting data load")
data = load_large_dataset()
trace("Data loaded, rows:", len(data))

process_data(data)
trace("Processing complete")

# View all traces
trace_log()
```

**Features:**
- Millisecond-precision timestamps
- Messages stored across cell execution
- Color-coded display (green)

### trace_log() - View Trace History

Display all trace messages collected during the session:

```python
trace_log()
```

Shows complete timeline of all `trace()` calls with timestamps.

## Examples

### Example 1: Debug Data Processing

```python
#@title Process Cluster Data
cluster_file = "clusters.json"  #@param {type:"string"}

trace("Loading cluster data")
data = load_data(cluster_file)
debug(data, title="Loaded Data")

trace("Processing clusters")
result = process_clusters(data)
inspect_obj(result)

trace("Complete")
trace_log()
```

### Example 2: Interactive Debugging Session

```python
#@title Analyze Network
cluster_id = "C1"  #@param {type:"string"}

# Build graph
G = build_network_graph(cluster_id)
trace(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

# Pause for interactive inspection
set_trace()  # <-- Debugger opens here

# Continue with analysis
metrics = calculate_metrics(G)
debug(metrics, title="Network Metrics")
```

### Example 3: Quick Variable Check

```python
#@title Data Analysis

# Load and process
df = pd.read_csv('data.csv')
debug(df.shape, df.columns, title="DataFrame Info")

# Transform
df_filtered = df[df['value'] > 100]
debug(len(df_filtered), title="Filtered Count")

# View all variables
vars_dump(filter_prefix='df')
```

## Tips & Best Practices

### Interactive Debugging
- Keep debugging sessions under 5 minutes to avoid timeouts
- Only one breakpoint per session recommended
- Use `c` (continue) to resume execution
- Close debugger tab when done

### Helper Functions
- Use `debug()` for quick variable checks during development
- Use `inspect_obj()` to explore unfamiliar objects
- Use `vars_dump()` to verify namespace state
- Use `trace()` for performance tracking and flow visualization

### Performance
- Helper functions have minimal overhead (<1ms)
- Interactive debugger only runs when `set_trace()` is called
- No performance impact on normal cell execution

## Troubleshooting

### "web-pdb not installed" message

If you see this warning when calling `set_trace()`:

```bash
uv add web-pdb
```

Then restart your notebook session (click "Reset Session" button).

### Debugger port conflicts

If port 5555 is busy, the system automatically finds the next available port (5556, 5557, etc.). The actual port is shown in the debugger notification.

### Helper functions not showing output

Make sure you've initialized the notebook (click "Initialize Notebook" button). Helper functions require the IPython display system to be set up.

### Variable names not detected in debug()

This is expected for complex expressions. The system tries to detect variable names but may fall back to `arg0`, `arg1`, etc. for complex cases. This doesn't affect the values displayed.

## Architecture Notes

### How It Works

1. **Namespace injection**: All debugging functions are automatically added to each cell's execution namespace during initialization
2. **HTML output capture**: Helper functions use the IPython display mock system to output rich HTML
3. **Port management**: web-pdb wrapper automatically finds available ports and notifies user
4. **Frontend integration**: JavaScript detects debugger activation and creates clickable buttons

### Files Modified

- `tyk_notebook_app/executor.py`: Core debugging implementation
- `tyk_notebook_app/templates/notebook/detail.html`: Frontend integration
- `requirements.txt`: Added web-pdb dependency
- `tyk.py`: Fixed broken pdb usage

## Comparison: pdb vs web-pdb vs Helpers

| Feature | pdb | web-pdb | Helper Functions |
|---------|-----|---------|------------------|
| Breakpoints | ❌ No | ✅ Yes | ❌ No |
| Stepping | ❌ No | ✅ Yes | ❌ No |
| Variable inspection | ❌ No | ✅ Yes | ✅ Yes |
| Terminal required | ✅ Yes | ❌ No | ❌ No |
| Works in web UI | ❌ No | ✅ Yes | ✅ Yes |
| Installation | Built-in | Required | Built-in |
| Setup time | N/A | Seconds | None |
| Use case | - | Complex debugging | Quick checks |

## Summary

TyK Notebook now supports modern debugging workflows:
- Use **set_trace()** when you need to pause execution and inspect state interactively
- Use **helper functions** (debug, inspect_obj, vars_dump, trace) for quick, non-blocking inspection
- Both approaches work seamlessly in the web UI without terminal access

Happy debugging! 🔍
