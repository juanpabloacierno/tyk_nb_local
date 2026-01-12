# Map Plot Enhancement - Cell 23

## Summary

Updated Cell 23 (Maps) to support **two rendering methods** for country maps:
1. **Modern** (default): Uses Plotly Express - cleaner, more concise API
2. **Classic**: Uses Plotly Graph Objects - traditional method with granular control

## Changes Made

### 1. Updated `tyk.plot_countries_map_global()` Method

**File:** `tyk.py` (line ~988)

**New Parameter:**
- `method: str = "modern"` - Choose between "modern" or "classic" rendering

**Modern Method (Plotly Express):**
- Uses `px.choropleth()` - high-level API
- More concise code (~30% less code)
- Automatic styling and layout
- Better default hover templates
- Cleaner parameter handling

**Classic Method (Graph Objects):**
- Uses `go.Choropleth()` - low-level API
- More granular control over every aspect
- Custom hover text formatting
- Original implementation (preserved)

### 2. Updated Cell 23 Source Code

**Before:**
```python
#tyk.plot_map()
tyk.plot_countries_map_global(colorscale="Turbo")
```

**After:**
```python
#@title Global Country Map Visualization

# Method selection: 'modern' uses Plotly Express (cleaner API),
# 'classic' uses Graph Objects (more control)
method = "modern"  #@param ["modern", "classic"]
colorscale = "Turbo"  #@param ["Turbo", "Viridis", "Plasma", "Blues", "YlOrRd", "RdYlGn"]

# Render the map
tyk.plot_countries_map_global(colorscale=colorscale, method=method)
```

### 3. Added Interactive Parameters

**Parameter 1: method**
- Type: Dropdown
- Options: ["modern", "classic"]
- Default: "modern"
- Description: Rendering method selection

**Parameter 2: colorscale**
- Type: Dropdown
- Options: ["Turbo", "Viridis", "Plasma", "Blues", "YlOrRd", "RdYlGn"]
- Default: "Turbo"
- Description: Color scale for the choropleth map

## Usage

### In Notebook UI:
1. Navigate to Cell 23 (Maps)
2. Use the dropdown menus to select:
   - **Method**: Switch between modern and classic rendering
   - **Colorscale**: Choose your preferred color palette
3. Click "Run" to render the map

### Programmatic Usage:

```python
# Modern method (default) with Turbo colorscale
tyk.plot_countries_map_global(colorscale="Turbo", method="modern")

# Classic method with Viridis colorscale
tyk.plot_countries_map_global(colorscale="Viridis", method="classic")

# Compare both methods side by side
tyk.plot_countries_map_global(colorscale="Plasma", method="modern")
tyk.plot_countries_map_global(colorscale="Plasma", method="classic")
```

## Comparison: Modern vs Classic

### Modern Method (Plotly Express)

**Pros:**
- ✅ Cleaner, more readable code
- ✅ Less boilerplate
- ✅ Automatic hover template generation
- ✅ Better defaults out of the box
- ✅ Easier to customize with fewer parameters
- ✅ Modern Plotly API (recommended by Plotly)

**Cons:**
- ⚠️ Less granular control
- ⚠️ Custom hover templates require workarounds

**Use When:**
- You want quick, beautiful maps with minimal code
- Standard styling is sufficient
- You're prototyping or exploring data

### Classic Method (Graph Objects)

**Pros:**
- ✅ Complete control over every element
- ✅ Custom hover text formatting
- ✅ Fine-tuned styling options
- ✅ Backward compatible with existing code

**Cons:**
- ⚠️ More verbose code
- ⚠️ Requires more parameters for customization
- ⚠️ Older API (still fully supported)

**Use When:**
- You need precise control over styling
- Custom hover templates are required
- Maintaining legacy code
- Advanced customization needed

## Visual Differences

Both methods produce visually similar output with:
- Interactive country highlighting
- Smooth hover effects
- Clean borders and coastlines
- Ocean background with transparency
- Color-coded choropleth based on data values

**Key Rendering Differences:**
1. **Hover Templates**: Modern method has cleaner default formatting
2. **Color Bar**: Modern method has slightly different positioning
3. **Performance**: Modern method may render slightly faster for large datasets

## Technical Details

### Modern Implementation
```python
fig = px.choropleth(
    df,
    locations="iso3",
    color="value",
    hover_name="country",
    color_continuous_scale=colorscale,
    projection="natural earth",
)
```

### Classic Implementation
```python
fig = go.Figure(
    data=go.Choropleth(
        locations=df["iso3"],
        z=df["value"],
        text=df["hover"],
        hoverinfo="text",
        colorscale=colorscale,
    )
)
```

## Migration Guide

If you have existing code using the old method:

**No Changes Required!**
- Default behavior uses "modern" method
- Add `method="classic"` to get original behavior
- All existing parameters still work

**Example:**
```python
# Old code (still works, uses modern method now)
tyk.plot_countries_map_global(colorscale="Viridis")

# To get old rendering exactly
tyk.plot_countries_map_global(colorscale="Viridis", method="classic")
```

## Testing

Both methods have been tested and produce correct output:
- ✅ Data mapping (countries to ISO3 codes)
- ✅ Color scaling
- ✅ Hover information
- ✅ Layout and styling
- ✅ Interactive features

## Benefits

1. **Flexibility**: Choose the best tool for your use case
2. **Learning**: Compare modern vs classic Plotly approaches
3. **Future-Proof**: Modern method aligns with Plotly's direction
4. **Backward Compatible**: Classic method preserves original functionality
5. **Educational**: See two approaches to the same visualization

## Recommendations

**For New Users:** Start with `method="modern"`
- Simpler API
- Less code to write
- Faster development

**For Advanced Users:** Use `method="classic"` when you need:
- Precise hover template control
- Complex custom styling
- Legacy code compatibility

---
*Updated: 2026-01-12*
*Cell: 23 (Maps)*
*Function: `tyk.plot_countries_map_global()`*
