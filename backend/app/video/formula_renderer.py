import io
import matplotlib
matplotlib.use('Agg')  # Headless mode
import matplotlib.pyplot as plt
from PIL import Image

def render_latex_to_image(formula_str: str, font_size: int = 36, color: str = 'white') -> Image.Image:
    """
    Converts a LaTeX mathematical equation/formula into a PIL Image with transparent background.
    """
    # Enclose formula in single dollar signs for Matplotlib's MathText rendering
    if not formula_str.startswith('$'):
        formula_str = f"${formula_str}$"
        
    # Create figure with high DPI for clarity
    fig = plt.figure(figsize=(10, 3), dpi=300)
    fig.patch.set_alpha(0.0)  # Make figure background transparent
    
    # Renders the formula text centered on the figure canvas
    fig.text(0.5, 0.5, formula_str, fontsize=font_size, color=color,
             ha='center', va='center')
             
    # Save the rendered figure directly into an in-memory byte buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1, dpi=300, transparent=True)
    plt.close(fig)
    buf.seek(0)
    
    # Load byte buffer as PIL image and force conversion to RGBA (for transparency)
    img = Image.open(buf).convert("RGBA")
    return img
