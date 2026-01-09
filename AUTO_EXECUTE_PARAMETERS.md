# Auto-Execute Parameters Feature

## Overview

All parameter types now support auto-execution when changed, but only for cells marked with `auto_run=True`.

## Changes Made

### File: `tyk_notebook_app/templates/notebook/detail.html`

**Added debounce helper function** for text inputs:
```javascript
const debounceTimers = {};
function debounceRunCell(cellId, delay = 800) {
    if (debounceTimers[cellId]) {
        clearTimeout(debounceTimers[cellId]);
    }
    debounceTimers[cellId] = setTimeout(() => {
        runCell(cellId);
    }, delay);
}
```

**Updated parameter inputs:**

1. **Dropdown** (line 120):
   - Before: Always executed on change
   - After: `{% if item.cell.auto_run %}onchange="runCell(...)"{% endif %}`

2. **Number** (line 138):
   - Before: No auto-execution
   - After: `{% if item.cell.auto_run %}onchange="runCell(...)"{% endif %}`
   - Triggers on blur or Enter key

3. **Boolean** (line 146):
   - Already had: `{% if item.cell.auto_run %}onchange="runCell(...)"{% endif %}`
   - No change needed

4. **Slider** (line 160):
   - Before: Only updated display value
   - After: `{% if item.cell.auto_run %}onchange="runCell(...)"{% endif %}`
   - Triggers when user releases slider

5. **Text/String** (line 170):
   - Before: No auto-execution
   - After: `{% if item.cell.auto_run %}oninput="debounceRunCell(...)"{% endif %}`
   - Triggers 800ms after user stops typing

## Behavior

### When `auto_run=True`:

| Parameter Type | Trigger Event | Timing | Notes |
|----------------|---------------|--------|-------|
| Dropdown | `onchange` | Immediate | When selection changes |
| Number | `onchange` | On blur/Enter | When user finishes editing |
| Boolean | `onchange` | Immediate | When checkbox toggled |
| Slider | `onchange` | On release | When user releases slider |
| Text/String | `oninput` | 800ms delay | Debounced while typing |

### When `auto_run=False`:

All parameter changes are captured but don't trigger execution. User must click "Run" button manually.

## Why Debouncing for Text?

Text inputs use `oninput` with debouncing (800ms delay) because:
- Prevents execution on every keystroke
- Waits until user finishes typing
- Reduces server load and API calls
- Better user experience (doesn't interrupt typing)

Other parameter types use `onchange` because:
- User explicitly selects a value (dropdown, checkbox)
- Change is deliberate (number input blur, slider release)
- No intermediate states while editing

## Example Cells

### Cell with Auto-Run Enabled:

```python
#@title Interactive Visualization
node_type = "K"  #@param ["K","TK","S","S2","I","R","RJ"]
max_nodes = 250  #@param {type:"string"}
min_size = 5     #@param {type:"number"}

tyk.plot_cooc_network_interactive(
    node_type=node_type,
    max_nodes=max_nodes,
    min_node_size=min_size
)
```

When this cell has `auto_run=True`:
- ✅ Changing dropdown → runs immediately
- ✅ Typing in text → runs 800ms after stopping
- ✅ Changing number → runs on blur/Enter
- ✅ Graph updates automatically

### Cell with Auto-Run Disabled:

When cell has `auto_run=False`:
- ❌ Parameter changes don't trigger execution
- ✅ User must click "Run" button
- ✅ Good for expensive computations
- ✅ Good for multi-parameter adjustment

## Setting Auto-Run Flag

The `auto_run` flag is set in the database Cell model:

```python
# In Django shell or migration
cell = Cell.objects.get(id=526)  # Cell 55
cell.auto_run = True
cell.save()
```

Or when creating cells from notebooks:

```python
cell = Cell.objects.create(
    notebook=notebook,
    order=55,
    title="cooc1",
    cell_type="code",
    is_executable=True,
    auto_run=True,  # Enable auto-execution
    source_code="..."
)
```

## Testing

### Test Auto-Execute for Each Type:

1. **Dropdown:**
   - Change `node_type` parameter
   - Cell should execute immediately
   - Graph updates with new node type

2. **Text Input:**
   - Type in `max_nodes` field
   - Wait 800ms after stopping
   - Cell executes automatically
   - Graph updates with new node count

3. **Number Input:**
   - Change `min_size` value
   - Press Enter or click outside
   - Cell executes
   - Graph updates

4. **Boolean:**
   - Toggle a checkbox parameter
   - Cell executes immediately

5. **Slider:**
   - Drag slider to new position
   - Release mouse button
   - Cell executes

### Test Debouncing:

1. Type quickly in text input: `"100"`
2. Cell should only execute once (800ms after last keystroke)
3. Not three times for each digit

### Test Auto-Run Disabled:

1. Find cell with `auto_run=False`
2. Change any parameter
3. Cell should NOT execute
4. Click "Run" button to execute manually

## Benefits

1. **Interactive Visualizations:** Real-time updates as parameters change
2. **Better UX:** No need to click "Run" after every change
3. **Efficient:** Debouncing prevents excessive executions
4. **Flexible:** Can be enabled/disabled per cell
5. **Consistent:** All parameter types work the same way

## Performance Considerations

- Debouncing reduces API calls (text inputs)
- Only cells with `auto_run=True` are affected
- Execution is async (doesn't block UI)
- Server can handle concurrent requests
- Consider longer debounce for expensive cells

## Potential Improvements

### Future Enhancements:

1. **Configurable debounce delay:**
   ```python
   cell.auto_run_delay = 1000  # milliseconds
   ```

2. **Smart execution:**
   - Skip if already running
   - Queue if multiple changes
   - Cancel pending if new change

3. **Visual feedback:**
   - Show "Auto-run in X seconds..."
   - Highlight changed parameters
   - Cancel button for pending execution

4. **Per-parameter control:**
   ```python
   max_nodes = 250  #@param {type:"string", auto_run:false}
   ```

## Troubleshooting

### Cell executes too often:
- Increase debounce delay in `debounceRunCell(cellId, 1500)`
- Set `auto_run=False` for that cell
- Use number input instead of text (only executes on blur)

### Cell doesn't execute on change:
- Check that cell has `auto_run=True` in database
- Check browser console for JavaScript errors
- Verify parameter has correct `data-cell-id` attribute

### Typing is interrupted:
- Increase debounce delay (current: 800ms)
- Consider disabling auto-run for text-heavy cells
- Use "Run" button instead

## Summary

✅ All parameter types now support auto-execution
✅ Controlled by `auto_run` flag per cell
✅ Text inputs use smart debouncing
✅ Consistent behavior across all types
✅ Better interactive notebook experience
